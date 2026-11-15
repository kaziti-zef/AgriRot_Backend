"""Les six critères S1 à S6. Chaque critère renvoie un `Resultat` : note 0-100, notes partielles
par saison (quand elles ont un sens) et traces. Une trace = une phrase issue d'un gabarit,
rangée dans une rubrique de l'explication du contrat (why, proofs, benefits, information_gaps,
local_risks_to_check). Aucun texte libre n'est généré ailleurs.
"""
from dataclasses import dataclass, field

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


@dataclass
class Trace:
    critere: str
    rubrique: str          # why | proofs | benefits | information_gaps | local_risks_to_check
    texte: str
    regle: str | None = None
    saison: int | None = None
    poids: float = 0.0     # importance, pour trier les phrases


@dataclass
class Resultat:
    note: float
    par_saison: dict[int, float] = field(default_factory=dict)
    traces: list[Trace] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def source_climat(pc) -> str:
    a0, a1 = int(pc.climat.annees.min()), int(pc.climat.annees.max())
    nom = "série synthétique de test" if pc.climat.synthetique else "NASA POWER"
    return f"{nom}, {a0}–{a1}"


def pct(x: float) -> str:
    return f"{round(100 * x)} %"
