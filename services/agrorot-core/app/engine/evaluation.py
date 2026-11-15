"""T32 - Évaluation complète d'une rotation : contraintes, S1 à S6, note globale, résilience, confiance."""
from dataclasses import dataclass, field

import numpy as np

from app.engine import contraintes as K
from app.engine import scenario as sc
from app.engine.criteres import Trace, s1_climat, s2_eau, s3_fertilite, s4_erosion, s5_phyto, s6_priorites
from app.engine.precalcul import Precalcul, construire
from app.engine.temps import Rotation, interpreter
from app.params import P
from app.referentiel.loader import REF
from app.schemas import Contexte, EtapeRotation, ScenarioClimat, Violation

CRITERES = ("S1", "S2", "S3", "S4", "S5", "S6")


@dataclass
class Evaluation:
    etapes: list[EtapeRotation]
    rot: Rotation
    scores: dict[str, float]
    G: float
    par_saison: dict[int, float]
    traces: list[Trace]
    violations: list[Violation]
    conseils: list[str] = field(default_factory=list)
    resilience: float | None = None
    confiance: float | None = None

    @property
    def admissible(self) -> bool:
        return K.admissible(self.violations)

    @property
    def cle(self) -> tuple:
        return tuple(e.crop_id for e in self.etapes)


def poids_criteres(ctx: Contexte) -> dict[str, float]:
    """Priorités du contrat -> poids des critères. S1 et S5 gardent un plancher fixe (décision du plan)."""
    p = P()["agregation"]
    w = ctx.poids or p["poids_equilibres"]
    brut = {"S1": 0.0, "S2": w.get("water_saving", 0), "S3": w.get("nitrogen", 0) + 0.5 * w.get("soil_health", 0),
            "S4": w.get("erosion_control", 0), "S5": 0.5 * w.get("soil_health", 0),
            "S6": w.get("income", 0) + w.get("fodder", 0)}
    total = sum(brut.values()) or 1.0
    planchers = p["poids_planchers"]
    reste = 1 - sum(planchers.values())
    return {k: reste * brut[k] / total + planchers.get(k, 0.0) for k in CRITERES}


def evaluer(etapes: list[EtapeRotation], pc: Precalcul, ctx: Contexte) -> Evaluation:
    rot = interpreter(etapes, pc.cal, ctx.historique)
    w_ctx = ctx.poids or P()["agregation"]["poids_equilibres"]
    r = {"S1": s1_climat.noter(rot, pc, ctx), "S2": s2_eau.noter(rot, pc, ctx), "S3": s3_fertilite.noter(rot, pc, ctx),
         "S4": s4_erosion.noter(rot, pc, ctx), "S5": s5_phyto.noter(rot, pc, ctx),
         "S6": s6_priorites.noter(rot, pc, ctx, w_ctx)}
    scores = {k: round(v.note, 1) for k, v in r.items()}
    w = poids_criteres(ctx)
    G = sum(w[k] * scores[k] for k in CRITERES)
    par_saison = {}
    for s in range(1, rot.n + 1):
        parts = [r[k].par_saison[s] for k in ("S1", "S2", "S5") if s in r[k].par_saison]
        par_saison[s] = round(float(np.mean(parts)), 1) if parts else 50.0     # jachère : neutre
    violations = K.toutes(rot, pc, ctx) + r["S5"].extra["violations"]
    # Pénalité de non-admissibilité : la rotation existante est notée même si elle viole une règle dure
    pa = P()["agregation"]
    dures = {(v.code, v.crop_id) for v in violations if v.code in K.DURES or v.code == "C0"}
    G = round(G * (1 - min(pa["penalite_violation_max"], pa["penalite_violation_dure"] * len(dures))), 1)
    traces = [t for v in r.values() for t in v.traces]
    return Evaluation(etapes, rot, scores, G, par_saison, traces, violations, r["S5"].extra.get("conseils", []))


def resilience(ev: Evaluation, ctx: Contexte, cl: sc.Climat, pc: Precalcul) -> float:
    """G dans le pire scénario de stress / G de base, plafonné à 1 (décision du plan)."""
    if ev.G <= 0:
        return 0.0
    pires = []
    for s in P()["resilience"]["scenarios"]:
        pc2 = _stress(ctx, cl, pc, s)
        pires.append(evaluer(ev.etapes, pc2, ctx).G)
    return round(min(1.0, min(pires) / ev.G), 2)


_CACHE_STRESS: dict = {}


def _stress(ctx, cl, pc, s) -> Precalcul:
    cle = (id(pc), s["rain_delta_pct"], s["temp_delta_c"])
    if cle not in _CACHE_STRESS:
        if len(_CACHE_STRESS) > 64:
            _CACHE_STRESS.clear()
        cl2 = sc.appliquer(cl, ScenarioClimat(rain_delta_pct=s["rain_delta_pct"], temp_delta_c=s["temp_delta_c"]))
        _CACHE_STRESS[cle] = construire(ctx, cl2, pc.cal)
    return _CACHE_STRESS[cle]


def confiance(ev: Evaluation, ctx: Contexte, pc: Precalcul) -> tuple[float, str, list[str]]:
    """Score 0-1, niveau, et paramètres par défaut utilisés (pour LOW_CONFIDENCE)."""
    p = P()["confiance"]
    champs = ("ph", "texture", "organic_matter", "drainage", "slope_deg")
    vals, defauts = [], []
    for c in champs:
        v = ctx.sol.confidences.get(c)
        if v is None:
            v = p["base_defaut"] if getattr(ctx.sol, c) is None else 0.7
        if v <= p["base_defaut"]:
            defauts.append(c)
        vals.append(v)
    score = 0.4 + 0.6 * float(np.mean(vals))
    a_verif = {o.crop for o in ev.rot.occupations if REF.cultures[o.crop].a_verifier}
    score -= min(p["penalite_a_verifier_max"], p["penalite_a_verifier"] * len(a_verif))
    score -= p["penalite_source"].get(pc.climat.source_status, 0)
    if pc.climat.synthetique:
        score -= p["penalite_synthetique"]
    if ctx.pratiques.fertilizer_use is None or ctx.pratiques.residue_return is None:
        score -= p["penalite_pratiques_inconnues"]
        defauts.append("pratiques")
    score = round(max(0.0, min(1.0, score)), 2)
    niveau = "élevée" if score >= p["seuils"]["elevee"] else "moyenne" if score >= p["seuils"]["moyenne"] else "faible"
    return score, niveau, defauts
