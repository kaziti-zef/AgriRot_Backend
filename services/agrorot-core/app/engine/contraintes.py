"""T25 - Contraintes éliminatoires C1 à C6 (C7 est calculée avec S5).

Chaque fonction renvoie une liste de `Violation` détaillées (code, saison, culture, valeurs).
C5 est souple : elle est signalée ici et pénalisée dans S5.
"""
from app.engine.aptitude import cycle_court
from app.engine.precalcul import Precalcul
from app.engine.temps import Rotation, mois_calendaire
from app.referentiel.loader import REF
from app.schemas import Contexte, Violation

DURES = {"C1", "C2", "C3", "C4", "C6"}


def fr(x: float) -> str:
    """Nombre à la française : 0,4 ; 1,6 ; 2."""
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def c1_climat(crop: str, code: str, pc: Precalcul, ctx: Contexte) -> list[Violation]:
    c, f = REF.cultures[crop], pc.fiche(crop, code)
    out = []
    mois = f.mois if f else []
    froid = [m for m in mois if c.t_abs[0] is not None and pc.t10_min[m - 1] < c.t_abs[0]]
    chaud = [m for m in mois if c.t_abs[1] is not None and pc.t90_max[m - 1] > c.t_abs[1]]
    if froid:
        out.append(Violation(code="C1", crop_id=crop, message=f"{c.nom} : nuits trop froides en mois {froid[0]}",
                             details={"mois": froid, "t_abs_min": c.t_abs[0]}))
    if chaud:
        out.append(Violation(code="C1", crop_id=crop, message=f"{c.nom} : chaleur au-delà de sa limite en mois {chaud[0]}",
                             details={"mois": chaud, "t_abs_max": c.t_abs[1]}))
    p = pc.climat.pluie_annuelle
    if not ctx.eau.has_irrigation and c.pluie_abs[0] is not None and p < c.pluie_abs[0]:
        out.append(Violation(code="C1", crop_id=crop, message=f"{c.nom} : pluie annuelle insuffisante ({p:.0f} mm)",
                             details={"pluie_annuelle": round(p), "minimum": c.pluie_abs[0]}))
    if c.pluie_abs[1] is not None and p > c.pluie_abs[1] and not cycle_court(c):
        out.append(Violation(code="C1", crop_id=crop, message=f"{c.nom} : pluie annuelle excessive ({p:.0f} mm)",
                             details={"pluie_annuelle": round(p), "maximum": c.pluie_abs[1]}))
    return out


def c2_saison(crop: str, code: str, pc: Precalcul, ctx: Contexte) -> list[Violation]:
    """Une culture courte tient dans sa saison ; une culture longue ne traverse la saison sèche
    que si elle tolère la sécheresse (exception décidée pour manioc, igname, macabo)."""
    if ctx.eau.has_irrigation:
        return []
    c = REF.cultures[crop]
    cal = pc.cal
    semis = cal.semis[code]
    mois = [mois_calendaire(semis + k) for k in range(c.cycle_mois)]
    if c.longue:
        secs = [m for m in mois if m not in cal.mois_humides()]
        if secs and c.secheresse == "forte":
            return [Violation(code="C2", crop_id=crop, message=f"{c.nom} traverse la saison sèche (mois {secs[0]}) "
                              f"alors qu'elle y est sensible", details={"mois_secs": secs})]
        return []
    hors = [m for m in mois if m not in cal.fenetre(code)]
    if hors:
        return [Violation(code="C2", crop_id=crop, message=f"{c.nom} semé en {code} dépasse la saison des pluies "
                          f"(mois {hors[0]})", details={"mois_hors_saison": hors})]
    return []


def c6_sol(crop: str, ctx: Contexte) -> list[Violation]:
    c, out = REF.cultures[crop], []
    ph = ctx.sol.ph
    if ph is not None and c.ph_opt[0] is not None and not (c.ph_opt[0] - 0.5 <= ph <= c.ph_opt[1] + 0.5):
        out.append(Violation(code="C6", crop_id=crop, message=f"{c.nom} : pH {fr(ph)} hors de sa plage ({fr(c.ph_opt[0])}–{fr(c.ph_opt[1])})",
                             details={"ph": ph, "ph_opt": list(c.ph_opt)}))
    if ctx.sol.drainage == "faible" and c.drainage_mal_tolere:
        out.append(Violation(code="C6", crop_id=crop, message=f"{c.nom} supporte mal un sol mal drainé"))
    return out


def statiques(crop: str, code: str, pc: Precalcul, ctx: Contexte) -> list[Violation]:
    """Violations qui ne dépendent que de la culture et de sa saison (cache-friendly)."""
    return c1_climat(crop, code, pc, ctx) + c2_saison(crop, code, pc, ctx) + c6_sol(crop, ctx)


def sequence(rot: Rotation) -> list[Violation]:
    """C3 (chevauchement), C4 (délai de retour), C5 (même famille à la suite), historique compris."""
    out = [Violation(code="C3", season=s, crop_id=voulu,
                     message=f"Saison {s} encore occupée par {REF.nom(en_place)} : {REF.nom(voulu)} ne peut pas être semé",
                     details={"en_place": en_place}) for s, voulu, en_place in rot.conflits]
    toutes = rot.historique + rot.occupations
    dernier: dict[str, int] = {}
    for o in toutes:
        c = REF.cultures[o.crop]
        if o.crop in dernier and o.s0 >= 1:
            ecart = (o.semis_am - dernier[o.crop]) / 12
            if ecart + 1e-9 < c.delai_retour_ans:
                out.append(Violation(code="C4", season=o.s0, crop_id=o.crop,
                                     message=f"{c.nom} revient après {fr(ecart)} an au lieu de {fr(c.delai_retour_ans)}",
                                     details={"ecart_ans": round(ecart, 2), "delai_retour_ans": c.delai_retour_ans}))
        dernier[o.crop] = o.semis_am
    for a, b in zip(toutes, toutes[1:]):
        if b.s0 >= 1 and REF.cultures[a.crop].famille == REF.cultures[b.crop].famille:
            out.append(Violation(code="C5", season=b.s0, crop_id=b.crop,
                                 message=f"{REF.nom(b.crop)} suit {REF.nom(a.crop)} : même famille ({REF.cultures[b.crop].famille})",
                                 details={"famille": REF.cultures[b.crop].famille, "precedent": a.crop}))
    return out


def toutes(rot: Rotation, pc: Precalcul, ctx: Contexte) -> list[Violation]:
    out = sequence(rot)
    exclues = set(ctx.contraintes.excluded_crops)
    for o in rot.occupations:
        for v in statiques(o.crop, o.code, pc, ctx):
            out.append(v.model_copy(update={"season": o.s0}))
        if o.crop in exclues:
            out.append(Violation(code="C0", season=o.s0, crop_id=o.crop, message=f"{REF.nom(o.crop)} est exclue par l'agriculteur"))
    return out


def admissible(violations: list[Violation]) -> bool:
    return not any(v.code in DURES or v.code == "C0" for v in violations)
