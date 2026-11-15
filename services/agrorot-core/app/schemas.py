"""Contrat INTERNE backend -> agrorot-core (T03).

Le backend construit un `Contexte` complet (données climatiques déjà récupérées par
data-service + saisies de l'agriculteur) ; le moteur ne fait aucun appel réseau.
Tout changement de ce fichier passe par une PR annoncée à l'équipe.
"""
from typing import Literal

from pydantic import BaseModel, Field

PriorityKey = Literal["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"]
StrategyId = Literal["existing", "recommended", "alternative"]
SEUILS_CHALEUR = (30, 32, 34, 36, 38)


# ---------------------------------------------------------------- Entrées : climat
class MoisClimat(BaseModel):
    annee: int
    mois: int = Field(ge=1, le=12)
    pluie_mm: float
    t_moy_c: float
    t_min_c: float
    t_max_c: float
    et0_mm: float
    pluie_intense_mm: float = 0.0          # pluie tombée les jours > 95e centile journalier
    jours_pluie_intense: int = 0
    jours_chaleur: dict[str, int] = {}      # {"30": n, "32": n, ...} jours où Tmax dépasse le seuil


class Saison(BaseModel):
    annee: int
    code: Literal["S1", "S2"]
    debut_mois: int = Field(ge=1, le=12)
    fin_mois: int = Field(ge=1, le=12)


class SiteClimat(BaseModel):
    serie_mensuelle: list[MoisClimat]       # 20 à 40 années complètes
    saisons: list[Saison] = []               # vide : calendrier régional
    source_status: Literal["live", "fallback_cache", "fallback_local"] = "live"
    synthetique: bool = False                # vrai pour les jeux de test générés


# ---------------------------------------------------------------- Entrées : parcelle et agriculteur
class Sol(BaseModel):
    texture: Literal["sableux", "limoneux", "argileux", "argilo-limoneux", "sablo-limoneux"] | None = None
    ph: float | None = Field(None, ge=3, le=10)
    drainage: Literal["faible", "moyen", "bon"] | None = None
    organic_matter: Literal["faible", "moyenne", "élevée"] | None = None
    slope_deg: float | None = Field(None, ge=0, le=90)
    elevation_m: float | None = None
    confidences: dict[str, float] = {}       # 1.0 saisi, 0.7 donnée NASA, 0.4 défaut régional


class Eau(BaseModel):
    has_irrigation: bool = False
    dry_season_availability: Literal["nulle", "faible", "moyenne", "bonne"] = "nulle"


class Pratiques(BaseModel):
    """Extension du contrat v2 (T03) : pratiques qui changent la fertilité."""
    fertilizer_use: Literal["aucun", "organique", "mineral", "mixte"] | None = None
    residue_return: float | None = Field(None, ge=0, le=1)   # part des résidus laissée au champ


class SaisonHistorique(BaseModel):
    season_index: int = Field(ge=-3, le=-1)
    crop_id: str                             # id culture, "jachere" ou "autre"
    botanical_family: str | None = None


class Contraintes(BaseModel):
    equipment: list[str] = []
    labor: Literal["familiale", "salariée", "mixte"] | None = None
    excluded_crops: list[str] = []
    market_available_crops: list[str] = []


class ScenarioClimat(BaseModel):
    rain_delta_pct: float = Field(0, ge=-30, le=30)
    temp_delta_c: float = Field(0, ge=0, le=3)
    horizon_years: Literal[0, 5, 10] = 0


class EtapeRotation(BaseModel):
    season: int = Field(ge=1)                # 1..horizon_seasons
    crop_id: str                             # id culture ou "jachere"
    modified_by_user: bool = False


class Contexte(BaseModel):
    region: str
    premiere_annee: int                      # année de la saison 1 (ex. 2027)
    premiere_saison: Literal["S1", "S2"] = "S1"
    climat: SiteClimat
    sol: Sol = Sol()
    eau: Eau = Eau()
    pratiques: Pratiques = Pratiques()
    historique: list[SaisonHistorique] = []
    planned_rotation: list[EtapeRotation] = []   # extension : rotation prévue par l'agriculteur
    pest_history: list[str] = []                 # extension : bioagresseurs déjà observés
    poids: dict[PriorityKey, float] = {}         # somme = 1 ; vide = pondération équilibrée
    contraintes: Contraintes = Contraintes()


class RequeteEvaluation(BaseModel):
    contexte: Contexte
    sequence: list[EtapeRotation]
    scenario: ScenarioClimat = ScenarioClimat()


class RequeteStrategies(BaseModel):
    contexte: Contexte
    horizon_seasons: int = Field(6, ge=2, le=12)
    scenario: ScenarioClimat = ScenarioClimat()
    manual_overrides: dict[StrategyId, dict[str, str]] = {}   # {"recommended": {"2": "niebe"}}


# ---------------------------------------------------------------- Sorties
class Explication(BaseModel):
    why: list[str] = []
    proofs: list[str] = []
    benefits: list[str] = []
    information_gaps: list[str] = []
    local_risks_to_check: list[str] = []


class EtapeNotee(BaseModel):
    season: int
    label: str                               # "2027-S1"
    crop_id: str
    crop_name: str
    sowing_month: int | None = None
    harvest_month: int | None = None
    continuation: bool = False               # culture longue semée à une saison précédente
    season_score: float
    modified_by_user: bool = False


class Confiance(BaseModel):
    score: float
    level: Literal["élevée", "moyenne", "faible"]


class Violation(BaseModel):
    code: str                                # C1..C7
    message: str
    season: int | None = None
    crop_id: str | None = None
    details: dict = {}


class Strategie(BaseModel):
    id: StrategyId
    type: StrategyId
    name: str
    score: float
    scores: dict[str, float]                 # S1..S6 (ajout au contrat)
    delta_vs_existing: dict[str, float] = {}  # ajout au contrat
    resilience_index: float
    confidence: Confiance
    sequence: list[EtapeNotee]
    violations: list[Violation] = []          # ajout au contrat
    explanation: Explication
    off_rotation_advice: list[str] = []      # conseils hors rotation (bioagresseurs non notés)
    non_viable: bool = False


class Avertissement(BaseModel):
    code: str
    message: str
    details: dict = {}


class ReponseStrategies(BaseModel):
    applied_scenario: ScenarioClimat
    warnings: list[Avertissement] = []
    strategies: list[Strategie]


class ReponseEvaluation(BaseModel):
    strategy: Strategie
    warnings: list[Avertissement] = []
