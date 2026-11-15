"""T20 - Chargement du référentiel et conversion des colonnes en valeurs exploitables.

Les CSV sont lus une fois au démarrage. Les catégories texte (« forte », « moyen »…) et les
intervalles (« 40–100 ») sont convertis ici, pour que le reste du moteur ne manipule que des nombres.
"""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.params import P

DATA = Path(__file__).resolve().parents[2] / "data"
JACHERE = "jachere"


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _moyenne(v, defaut: float) -> float:
    a, b = _intervalle(v)
    return defaut if a is None else (a + (b or a)) / 2


def _intervalle(v) -> tuple[float | None, float | None]:
    """'40–100' -> (40, 100) ; '> 2' -> (2, None) ; vide -> (None, None)."""
    if not isinstance(v, str) or not v.strip():
        return None, None
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", v)]
    if not nums:
        return None, None
    return (nums[0], None) if v.strip().startswith(">") else (nums[0], nums[-1])


def _niveau(v: str | float | None) -> str | None:
    """Ramène 'faible au départ, moyenne ensuite' ou 'moyenne à forte' à une classe unique."""
    if not isinstance(v, str):
        return None
    mots = re.findall(r"faible|moyenne|moyen|forte|fort", v.lower())
    return mots[-1] if mots else None      # « faible au départ, moyenne ensuite » -> moyenne


def _usages(v) -> set[str]:
    v = (v or "").lower() if isinstance(v, str) else ""
    out = set()
    if any(k in v for k in ("vente", "export", "huile")):
        out.add("vente")
    if "alimentation" in v:
        out.add("alimentation")
    if any(k in v for k in ("fourrag", "fanes")):
        out.add("fourrage")
    return out


@dataclass
class Culture:
    id: str
    nom: str
    famille: str
    en_rotation: bool
    regions: set[str]
    cycle_jours: float | None
    stades: tuple[float, float, float, float] | None     # initial, développement, mi-saison, fin (jours)
    kc: tuple[float, float, float]                        # ini, mid, fin
    t_opt: tuple[float, float]
    t_abs: tuple[float, float]
    pluie_opt: tuple[float, float]
    pluie_abs: tuple[float, float]
    altitude_max: float | None
    ph_opt: tuple[float | None, float | None]
    drainage_mal_tolere: bool                            # True si la culture exige un sol bien drainé
    tolere_engorgement: bool
    secheresse: str                                       # faible / moyenne / forte
    fixe_azote: bool
    azote_fixe: tuple[float | None, float | None]
    besoin_azote: str                                     # faible / moyen / fort
    residus: str                                          # faible / moyen / fort
    couverture: str                                       # faible / moyenne / forte
    delai_retour_ans: float
    usages: set[str]
    a_verifier: str
    ravageurs: str
    zone: str
    service: bool = False                                 # plante de service (couverture, engrais vert)
    racines_m: float = 0.8                                # profondeur racinaire moyenne (m), réserve en eau du sol
    extra: dict = field(default_factory=dict)

    @property
    def cycle_mois(self) -> int:
        return max(1, math.ceil((self.cycle_jours or 90) / 30))

    @property
    def longue(self) -> bool:
        """Culture longue (>= 200 j) : couvre plusieurs saisons ; C2 la juge sur les mois secs traversés."""
        return (self.cycle_jours or 0) >= 200


def _culture(r) -> Culture:
    st = tuple(_num(r[c]) for c in ("stade_initial_j", "stade_developpement_j", "stade_mi_saison_j", "stade_fin_j"))
    stades = st if all(x is not None for x in st) else None
    cycle = _num(r["duree_cycle_jours"])
    if stades and cycle:
        stades = tuple(x * cycle / sum(stades) for x in stades)   # recale les stades sur la durée du cycle
    drainage = str(r["drainage"]) if isinstance(r["drainage"], str) else ""
    secheresse = _niveau(r["sensibilite_secheresse"]) or "moyenne"
    return Culture(
        id=r["id"], nom=r["culture"], famille=r["famille"],
        en_rotation=str(r["entre_en_rotation"]).startswith("Oui"),
        regions={x.strip() for x in str(r.get("regions") or "").split(";") if x.strip() and x != "nan"},
        cycle_jours=cycle, stades=stades,
        kc=(_num(r["kc_ini"]) or 0.5, _num(r["kc_mid"]) or 1.0, _num(r["kc_fin"]) or 0.8),
        t_opt=(_num(r["t_opt_min_c"]), _num(r["t_opt_max_c"])),
        t_abs=(_num(r["t_abs_min_c"]), _num(r["t_abs_max_c"])),
        pluie_opt=(_num(r["pluie_opt_min_mm"]), _num(r["pluie_opt_max_mm"])),
        pluie_abs=(_num(r["pluie_abs_min_mm"]), _num(r["pluie_abs_max_mm"])),
        altitude_max=_num(r["altitude_max_m"]),
        ph_opt=(_num(r["ph_opt_min"]), _num(r["ph_opt_max"])),
        drainage_mal_tolere="mal drainé" not in drainage,
        tolere_engorgement="mal drainé" in drainage,
        secheresse={"fort": "forte", "moyen": "moyenne"}.get(secheresse, secheresse),
        fixe_azote=r["fixe_azote"] == "Oui",
        azote_fixe=_intervalle(r["azote_fixe_kg_ha"]),
        besoin_azote={"forte": "fort", "moyenne": "moyen"}.get(_niveau(r["besoin_azote"]) or "moyen", _niveau(r["besoin_azote"]) or "moyen"),
        residus={"forte": "fort", "moyenne": "moyen"}.get(_niveau(r["residus"]) or "moyen", _niveau(r["residus"]) or "moyen"),
        couverture={"fort": "forte", "moyen": "moyenne"}.get(_niveau(r["couverture_sol"]) or "moyenne", _niveau(r["couverture_sol"]) or "moyenne"),
        delai_retour_ans=_num(r["delai_retour_ans"]) or 0.0,
        usages=_usages(r["usages"]),
        a_verifier=r["a_verifier"] if isinstance(r["a_verifier"], str) else "",
        ravageurs=r["ravageurs_maladies_majeurs"] if isinstance(r["ravageurs_maladies_majeurs"], str) else "",
        zone=r["zone_typique_cameroun"] if isinstance(r["zone_typique_cameroun"], str) else "",
        service=str(r["categorie"]).startswith("Plante de service"),
        racines_m=_moyenne(r["profondeur_racines_m"], 0.8),
    )


@dataclass
class Bioagresseur:
    id: str
    nom: str
    type: str
    note: bool                       # entre dans S5
    delta: float                     # persistance d'une saison sur l'autre
    gravite: int
    hotes: dict[str, float]          # culture -> h (1 ou 0,5)
    assainissantes: set[str]
    conseil: str
    zones: str
    a_verifier: str


class Referentiel:
    def __init__(self):
        p = P()
        df = pd.read_csv(DATA / "crops_cm.csv", encoding="utf-8-sig")
        self.cultures: dict[str, Culture] = {r["id"]: _culture(r) for _, r in df.iterrows()}
        bio = pd.read_csv(DATA / "bioagresseurs.csv", encoding="utf-8-sig")
        liens = pd.read_csv(DATA / "bioagresseurs_cultures.csv", encoding="utf-8-sig")
        self.bioagresseurs: dict[str, Bioagresseur] = {}
        for _, r in bio.iterrows():
            lb = liens[liens.bioagresseur_id == r["id"]]
            self.bioagresseurs[r["id"]] = Bioagresseur(
                id=r["id"], nom=r["nom"], type=r["type"], note=str(r["pris_en_compte_score"]).startswith("Oui"),
                delta=p["s5"]["delta"][r["survie_sans_hote"]], gravite=p["s5"]["gravite"][r["gravite"]],
                hotes={x.culture_id: p["s5"]["h"][x.role] for x in lb.itertuples() if x.role in p["s5"]["h"]},
                assainissantes=set(lb[lb.role == "assainissante_ou_piege"].culture_id),
                conseil=r["mesures_hors_rotation"] if isinstance(r["mesures_hors_rotation"], str) else "",
                zones=r["zones_cameroun"] if isinstance(r["zones_cameroun"], str) else "",
                a_verifier=r["a_verifier"] if isinstance(r["a_verifier"], str) else "",
            )
        self.regions = pd.read_csv(DATA / "regions.csv", encoding="utf-8-sig").to_dict("records")
        inconnus = {c for b in self.bioagresseurs.values() for c in (*b.hotes, *b.assainissantes)} - set(self.cultures)
        if inconnus:
            raise ValueError(f"Cultures de la matrice des hôtes absentes du catalogue : {sorted(inconnus)}")

    # ---- vues publiques
    def region_connue(self, region: str) -> bool:
        return region in {r["code"] for r in self.regions}

    def cultures_region(self, region: str) -> list[Culture]:
        return [c for c in self.cultures.values() if region in c.regions]

    def nom(self, crop_id: str) -> str:
        return "Jachère" if crop_id == JACHERE else self.cultures[crop_id].nom

    def crops_public(self, region: str) -> list[dict]:
        """Vue exposée par GET /crops (contrat §5)."""
        out = []
        for c in self.cultures_region(region):
            if not c.en_rotation:
                continue
            besoin = c.kc[1] * (c.cycle_jours or 0)
            out.append({"id": c.id, "name": c.nom, "botanical_family": c.famille,
                        "cycle_days": int(c.cycle_jours) if c.cycle_jours else None,
                        "nitrogen_fixing": c.fixe_azote,
                        "water_need": "faible" if besoin < 90 else "moyen" if besoin < 150 else "élevé",
                        # ajouts pour la surveillance de la rotation (backend) :
                        "kc": list(c.kc), "t_opt_max_c": c.t_opt[1], "drought_sensitivity": c.secheresse,
                        "waterlogging_tolerant": c.tolere_engorgement, "service_plant": c.service})
        return out

    def bioagresseurs_public(self) -> list[dict]:
        return [{"id": b.id, "name": b.nom, "type": b.type, "scored": b.note} for b in self.bioagresseurs.values()]


REF = Referentiel()
