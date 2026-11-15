"""T33 (2/2) + T34 - Orchestration : existante, recommandée, alternative ; modifications manuelles ;
avertissements ; mise au format de sortie."""
from app.engine import scenario as sc
from app.engine import explications as X
from app.engine.evaluation import CRITERES, Evaluation, confiance, evaluer, poids_criteres, resilience
from app.engine.generateur import choisir_alternative, difference, normaliser, rechercher
from app.engine.precalcul import Precalcul, construire
from app.engine.temps import calendrier_contexte, mois_calendaire
from app.errors import ApiError
from app.params import P
from app.referentiel.loader import JACHERE, REF
from app.schemas import (Avertissement, Confiance, Contexte, EtapeNotee, EtapeRotation, ReponseEvaluation,
                         ReponseStrategies, RequeteEvaluation, RequeteStrategies, Strategie)

LIBELLES = {"S2": "économie d'eau", "S3": "sol et azote", "S4": "lutte contre l'érosion", "S5": "santé des cultures",
            "S6": "revenu", "S1": "climat"}


# ------------------------------------------------------------------ préparation
def _preparer(ctx: Contexte, scenario) -> tuple[sc.Climat, Precalcul]:
    if not REF.region_connue(ctx.region):
        raise ApiError("REGION_NOT_SUPPORTED", 404, "Cette région n'est pas encore prise en charge.")
    base = sc.depuis_site(ctx.climat)
    cl = sc.appliquer(base, scenario)
    return cl, construire(ctx, cl, calendrier_contexte(ctx))


def _verifier_culture(crop: str, ctx: Contexte, champ: str):
    if crop != JACHERE and (crop not in REF.cultures or ctx.region not in REF.cultures[crop].regions):
        raise ApiError("CROP_NOT_FOUND", 422, "Culture inconnue pour cette région.", {"path": champ, "crop_id": crop})


def _existante(ctx: Contexte, n: int, pc: Precalcul) -> tuple[list[EtapeRotation], str]:
    """Rotation prévue, sinon historique répété, sinon monoculture témoin (CU8-A1)."""
    if ctx.planned_rotation:
        prevue = sorted(ctx.planned_rotation, key=lambda e: e.season)
        crops = [e.crop_id for e in prevue]
        nom = "Rotation prévue (référence)"
    elif ctx.historique:
        crops = [h.crop_id if h.crop_id in REF.cultures else JACHERE
                 for h in sorted(ctx.historique, key=lambda h: h.season_index)]
        nom = "Rotation actuelle (référence)"
    else:
        crops = [P()["generateur"]["culture_temoin"]]
        nom = "Monoculture témoin (aucun historique saisi)"
    for i, c in enumerate(crops):
        _verifier_culture(c, ctx, f"existing[{i}]")
    seq = [EtapeRotation(season=s, crop_id=crops[(s - 1) % len(crops)]) for s in range(1, n + 1)]
    return normaliser(seq, pc), nom


def _appliquer_overrides(etapes, overrides: dict, ctx: Contexte, pc: Precalcul, n: int, cle: str):
    if not overrides:
        return etapes
    par_s = {e.season: e for e in etapes}
    exclues = set(ctx.contraintes.excluded_crops)
    for s_txt, crop in overrides.items():
        try:
            s = int(s_txt)
        except ValueError:
            s = -1
        if not 1 <= s <= n:
            raise ApiError("VALIDATION_ERROR", 422, "Certaines valeurs sont invalides.",
                           {"fields": [{"path": f"manual_overrides.{cle}.{s_txt}", "reason": "out_of_range",
                                        "message": f"La saison doit être comprise entre 1 et {n}."}]})
        _verifier_culture(crop, ctx, f"manual_overrides.{cle}.{s_txt}")
        if crop in exclues:
            raise ApiError("EXCLUDED_CROP", 422, "Cette culture est exclue pour cette parcelle.",
                           {"crop_id": crop, "season": s})
        par_s[s] = EtapeRotation(season=s, crop_id=crop, modified_by_user=True)
    return normaliser(list(par_s.values()), pc)


# ------------------------------------------------------------------ mise en forme
def _strategie(id_: str, nom: str, ev: Evaluation, ref: Evaluation | None, ctx, cl, pc,
               diff_reco: float | None = None) -> Strategie:
    score_c, niveau, _ = confiance(ev, ctx, pc)
    seq = []
    modifs = {e.season for e in ev.etapes if e.modified_by_user}
    for s in range(1, ev.rot.n + 1):
        o = ev.rot.par_saison.get(s)
        crop = o.crop if o else JACHERE
        seq.append(EtapeNotee(season=s, label=pc.cal.label(s), crop_id=crop, crop_name=REF.nom(crop),
                              sowing_month=mois_calendaire(o.semis_am) if o else None,
                              harvest_month=mois_calendaire(o.recolte_am) if o else None,
                              continuation=bool(ev.rot.continuation.get(s)),
                              season_score=ev.par_saison.get(s, 50.0), modified_by_user=s in modifs))
    cultures = {o.crop for o in ev.rot.occupations}
    effondrees = {c for c in cultures if pc.aptitude.get(c, 1.0) == 0}
    return Strategie(
        id=id_, type=id_, name=nom, score=ev.G, scores=ev.scores,
        delta_vs_existing={k: round(ev.scores[k] - ref.scores[k], 1) for k in CRITERES} if ref else {},
        resilience_index=resilience(ev, ctx, cl, pc), confidence=Confiance(score=score_c, level=niveau),
        sequence=seq, violations=ev.violations, explanation=X.construire(ev, id_, ref, diff_reco),
        off_rotation_advice=ev.conseils[:4], non_viable=bool(cultures) and effondrees == cultures)


def _nom_reco(ev: Evaluation, ctx: Contexte) -> str:
    w = poids_criteres(ctx)
    k = max(("S2", "S3", "S4", "S5", "S6"), key=lambda c: w[c])
    return f"Stratégie recommandée ({LIBELLES[k]} d'abord)"


def _nom_alt(alt: Evaluation, reco: Evaluation) -> str:
    k = max(CRITERES, key=lambda c: alt.scores[c] - reco.scores[c])
    if alt.scores[k] - reco.scores[k] >= 3:
        return f"Alternative ({LIBELLES[k]})"
    return "Alternative diversifiée"


def _avertissements(ctx, pc, evs: list[Evaluation], relache: str | None) -> list[Avertissement]:
    out = []
    if relache:
        out.append(Avertissement(code="CONSTRAINTS_RELAXED", message="Aucune rotation ne respectait toutes les règles : "
                                 "des règles secondaires ont été relâchées.", details={"blocking_constraint": relache}))
    exclues = set(ctx.contraintes.excluded_crops)
    hist = [h.crop_id for h in ctx.historique if h.crop_id in exclues]
    if hist:
        out.append(Avertissement(code="EXCLUDED_CROP_IN_HISTORY", message="Une culture exclue figure dans l'historique.",
                                 details={"crop_ids": sorted(set(hist))}))
    vus = set()
    for ev in evs:
        for o in ev.rot.occupations:
            if pc.aptitude.get(o.crop, 1.0) == 0 and o.crop not in vus:
                vus.add(o.crop)
                out.append(Avertissement(code="CROP_COLLAPSE", message=f"{REF.nom(o.crop)} n'est plus adaptée au "
                                         f"climat simulé.", details={"crop_id": o.crop}))
    s, niveau, defauts = confiance(evs[1] if len(evs) > 1 else evs[0], ctx, pc)
    if niveau == "faible":
        out.append(Avertissement(code="LOW_CONFIDENCE", message="Confiance faible : plusieurs valeurs par défaut "
                                 "ont été utilisées.", details={"defaults": defauts, "score": s}))
    if pc.climat.synthetique:
        out.append(Avertissement(code="SYNTHETIC_CLIMATE", message="Série climatique synthétique (jeu de test) : "
                                 "les résultats ne valent pas pour une vraie parcelle."))
    return out


# ------------------------------------------------------------------ points d'entrée
def evaluer_sequence(req: RequeteEvaluation) -> ReponseEvaluation:
    ctx = req.contexte
    cl, pc = _preparer(ctx, req.scenario)
    for e in req.sequence:
        _verifier_culture(e.crop_id, ctx, f"sequence[{e.season}]")
    ev = evaluer(normaliser(req.sequence, pc), pc, ctx)
    strat = _strategie("existing", "Rotation évaluée", ev, None, ctx, cl, pc)
    return ReponseEvaluation(strategy=strat, warnings=_avertissements(ctx, pc, [ev], None))


def proposer(req: RequeteStrategies) -> ReponseStrategies:
    ctx, n = req.contexte, req.horizon_seasons
    cl, pc = _preparer(ctx, req.scenario)
    if len(pc.candidates) < 2 and not ctx.eau.has_irrigation:
        raise ApiError("NO_SUITABLE_CROP", 422, "Aucune culture assez adaptée aux conditions de la parcelle.",
                       {"candidates": pc.candidates})

    seq_ex, nom_ex = _existante(ctx, n, pc)
    seq_ex = _appliquer_overrides(seq_ex, req.manual_overrides.get("existing", {}), ctx, pc, n, "existing")
    ex = evaluer(seq_ex, pc, ctx)

    relache = None
    pool = rechercher(pc, ctx, n, strict=True)
    if not pool:
        relache = "C4/C5 (délai de retour, succession de familles)"
        pool = rechercher(pc, ctx, n, strict=False)
    if not pool:
        raise ApiError("NO_SUITABLE_CROP", 422, "Aucune culture assez adaptée aux conditions de la parcelle.")

    reco = pool[0]
    seuil = P()["generateur"]["difference_min_alternative"]
    alt = choisir_alternative(pool, reco, seuil)
    d_alt = difference(alt.cle, reco.cle)

    for cle, ev in (("recommended", reco), ("alternative", alt)):
        ov = req.manual_overrides.get(cle, {})
        if ov:
            nouv = _appliquer_overrides(list(ev.etapes), ov, ctx, pc, n, cle)
            if cle == "recommended":
                reco = evaluer(nouv, pc, ctx)
            else:
                alt = evaluer(nouv, pc, ctx)

    strategies = [
        _strategie("existing", nom_ex, ex, None, ctx, cl, pc),
        _strategie("recommended", _nom_reco(reco, ctx), reco, ex, ctx, cl, pc),
        _strategie("alternative", _nom_alt(alt, reco), alt, ex, ctx, cl, pc, diff_reco=d_alt),
    ]
    return ReponseStrategies(applied_scenario=req.scenario, warnings=_avertissements(ctx, pc, [ex, reco, alt], relache),
                             strategies=strategies)
