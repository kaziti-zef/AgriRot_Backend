"""T34 (1/2) - Des traces de calcul aux cinq rubriques du contrat. Aucun texte libre : uniquement
des gabarits (ici et dans les critères) remplis avec des valeurs calculées."""
from app.engine import contraintes as K
from app.engine.evaluation import CRITERES, Evaluation
from app.schemas import Explication

NOMS = {"S1": "Climat", "S2": "Eau", "S3": "Fertilité du sol", "S4": "Érosion", "S5": "Maladies et ravageurs",
        "S6": "Vos priorités et débouchés"}
MAX = {"why": 5, "proofs": 3, "benefits": 4, "information_gaps": 4, "local_risks_to_check": 5}
INDISPONIBLE = "Information indisponible"


def _uniques(textes):
    return list(dict.fromkeys(textes))


def _rubrique(ev: Evaluation, nom: str) -> list[str]:
    ts = sorted((t for t in ev.traces if t.rubrique == nom), key=lambda t: -t.poids)
    return _uniques(t.texte for t in ts)


def construire(ev: Evaluation, type_: str, reference: Evaluation | None, diff_reco: float | None = None) -> Explication:
    why, risques = [], _rubrique(ev, "local_risks_to_check")
    if type_ == "existing":
        dures = [v for v in ev.violations if v.code in K.DURES or v.code == "C0"]
        why += [f"Règle {v.code} : {v.message}." for v in dures]
        why += _rubrique(ev, "why")
        if not why:
            why.append("Aucune règle agronomique enfreinte : la rotation actuelle est cohérente.")
    else:
        if reference is not None:
            ecarts = sorted(((ev.scores[k] - reference.scores[k], k) for k in CRITERES), reverse=True)
            for d, k in ecarts[:3]:
                if d >= 3:
                    why.append(f"{NOMS[k]} ({k}) : {ev.scores[k]:.0f} contre {reference.scores[k]:.0f} pour votre "
                               f"rotation actuelle.")
            if ev.G > reference.G:
                why.append(f"Note globale {ev.G:.0f} contre {reference.G:.0f}, avec vos priorités.")
        if diff_reco is not None:
            why.append(f"Différente de la stratégie recommandée sur {round(100 * diff_reco)} % des saisons, "
                       f"pour vous laisser un vrai choix.")
        risques = [f"Point faible : {t}" for t in _rubrique(ev, "why")] + risques
    risques += [f"Règle {v.code} : {v.message}." for v in ev.violations if v.code in ("C5", "C7")]

    out = {"why": why, "proofs": _rubrique(ev, "proofs"), "benefits": _rubrique(ev, "benefits"),
           "information_gaps": _rubrique(ev, "information_gaps"), "local_risks_to_check": _uniques(risques)}
    return Explication(**{k: (v[:MAX[k]] or [INDISPONIBLE]) for k, v in out.items()})
