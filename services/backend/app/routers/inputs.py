"""T45 - Données locales, historique et préférences (§9), avec les extensions décidées au plan :
practices (fertilizer_use, residue_return), pest_history, planned_rotation."""
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.models import Farm, Parcel, ParcelData, User
from app.db.session import get_db
from app.domain import preferences as PR
from app.domain import referentiel as REF
from app.errors import ApiError, champ, validation
from app.i18n import avertissements, langue
from app.security import EXPLOITANTS, current_user, parcelle, verifier_version

router = APIRouter(tags=["inputs"])
CONF_SAISI, CONF_NASA, CONF_DEFAUT = 1.0, 0.7, 0.4


# ------------------------------------------------------------------ modèles
class Sol(BaseModel):
    texture: Literal["sableux", "limoneux", "argileux", "argilo-limoneux", "sablo-limoneux"] | None = None
    ph: float | None = Field(None, ge=3.0, le=10.0)
    drainage: Literal["faible", "moyen", "bon"] | None = None
    organic_matter: Literal["faible", "moyenne", "élevée"] | None = None
    slope_deg: float | None = Field(None, ge=0, le=90)
    slope_confirmed: bool = False


class Eau(BaseModel):
    has_irrigation: bool = False
    dry_season_availability: Literal["nulle", "faible", "moyenne", "bonne"] = "nulle"


class Correction(BaseModel):
    field: Literal["rain_mm", "temp_avg_c"]
    month: int = Field(ge=1, le=12)
    mode: Literal["adjustment"] = "adjustment"
    value: float

    @model_validator(mode="after")
    def bornes(self):
        lim = 100 if self.field == "rain_mm" else 5
        if not -lim <= self.value <= lim:
            raise ValueError(f"value doit être entre -{lim} et {lim}")
        return self


class Pratiques(BaseModel):
    fertilizer_use: Literal["aucun", "organique", "mineral", "mixte"] | None = None
    residue_return: float | None = Field(None, ge=0, le=1)


class Etape(BaseModel):
    season: int = Field(ge=1, le=12)
    crop_id: str


class DonneesLocales(BaseModel):
    soil: Sol = Sol()
    water: Eau = Eau()
    nasa_overrides: list[Correction] = []
    practices: Pratiques = Pratiques()
    pest_history: list[str] = []
    planned_rotation: list[Etape] = []


class SaisonHist(BaseModel):
    season_index: int = Field(ge=-3, le=-1)
    label: str | None = None
    crop_id: str
    botanical_family: str | None = None


class Historique(BaseModel):
    seasons: list[SaisonHist] = Field(default_factory=list, max_length=3)


class Contraintes(BaseModel):
    equipment: list[str] = []
    labor: Literal["familiale", "salariée", "mixte"] | None = None
    excluded_crops: list[str] = []
    market_available_crops: list[str] = []


class Preferences(BaseModel):
    ranking: list[Literal["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"]] | None = None
    weights: dict[str, float] | None = None
    constraints: Contraintes = Contraintes()


# ------------------------------------------------------------------ stockage
def lire_donnees(db: Session, parcel_id: str, kind: str) -> ParcelData | None:
    return db.get(ParcelData, (parcel_id, kind))


def _ecrire(db: Session, p: Parcel, kind: str, data: dict, if_match: str | None) -> ParcelData:
    d = lire_donnees(db, p.id, kind)
    if d is None:
        verifier_version(0, if_match)
        d = ParcelData(parcel_id=p.id, kind=kind, data=data, version=1)
        db.add(d)
    else:
        verifier_version(d.version, if_match)
        d.data, d.version = data, d.version + 1
    db.flush()
    return d


def _region(db: Session, p: Parcel) -> str:
    return db.get(Farm, p.farm_id).region


def _verifier_cultures(ids, region: str, chemin: str, speciaux=False):
    connus = REF.ids_cultures(region) | (REF.SPECIAUX if speciaux else set())
    inconnus = [c for c in ids if c not in connus]
    if inconnus:
        raise ApiError("CROP_NOT_FOUND", 422, "Culture inconnue pour cette région.",
                       {"fields": [champ(chemin, "not_found", f"Culture inconnue : {', '.join(inconnus)}")]})


# ------------------------------------------------------------------ données locales
def confiance_saisies(p: Parcel, data: dict) -> tuple[dict, dict, list]:
    sol, conf, defauts = data.get("soil", {}), {}, []
    for k in ("ph", "texture", "organic_matter", "drainage"):
        conf[k] = CONF_SAISI if sol.get(k) is not None else CONF_DEFAUT
        if sol.get(k) is None:
            defauts.append(k)
    if sol.get("slope_deg") is not None:
        conf["slope_deg"] = CONF_SAISI if sol.get("slope_confirmed") else CONF_NASA
    elif p.slope_deg is not None:
        conf["slope_deg"] = CONF_NASA
    else:
        conf["slope_deg"] = CONF_DEFAUT
        defauts.append("slope_deg")
    corr = {c["field"] for c in data.get("nasa_overrides", [])}
    conf["rain_mm"] = CONF_SAISI if "rain_mm" in corr else CONF_NASA
    conf["ndvi"] = 0.6
    score = round(sum(conf.values()) / len(conf), 2)
    niveau = "élevée" if score >= 0.8 else "moyenne" if score >= 0.6 else "faible"
    return conf, {"score": score, "level": niveau}, defauts


def _vue_locales(p: Parcel, d: ParcelData | None) -> dict:
    data = d.data if d else DonneesLocales().model_dump()
    conf, parcelle_conf, defauts = confiance_saisies(p, data)
    return {"parcel_id": p.id, **data, "input_confidence": conf, "parcel_confidence": parcelle_conf,
            "defaults_used": defauts, "version": d.version if d else 0}


@router.get("/parcels/{parcel_id}/local-inputs")
def lire_locales(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    return _vue_locales(p, lire_donnees(db, p.id, "local_inputs"))


@router.put("/parcels/{parcel_id}/local-inputs")
def ecrire_locales(parcel_id: str, body: DonneesLocales, if_match: str | None = Header(None),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *EXPLOITANTS)
    region = _region(db, p)
    if body.planned_rotation:
        _verifier_cultures([e.crop_id for e in body.planned_rotation], region, "planned_rotation", speciaux=True)
    inconnus = [x for x in body.pest_history if x not in REF.ids_bioagresseurs()]
    if inconnus:
        raise validation(champ("pest_history", "not_found", f"Bioagresseur inconnu : {', '.join(inconnus)}"))
    d = _ecrire(db, p, "local_inputs", body.model_dump(), if_match)
    return _vue_locales(p, d)


# ------------------------------------------------------------------ historique
@router.get("/parcels/{parcel_id}/history")
def lire_hist(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    d = lire_donnees(db, p.id, "history")
    return {"parcel_id": p.id, "seasons": d.data["seasons"] if d else [], "version": d.version if d else 0}


@router.put("/parcels/{parcel_id}/history")
def ecrire_hist(parcel_id: str, body: Historique, if_match: str | None = Header(None),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *EXPLOITANTS)
    idx = [s.season_index for s in body.seasons]
    if len(set(idx)) != len(idx):
        raise validation(champ("seasons", "duplicate", "Chaque saison ne peut apparaître qu'une fois."))
    _verifier_cultures([s.crop_id for s in body.seasons], _region(db, p), "seasons", speciaux=True)
    for i, s in enumerate(body.seasons):
        if s.crop_id == "autre" and not s.botanical_family:
            raise validation(champ(f"seasons.{i}.botanical_family", "required",
                                   "Indiquez la famille botanique d'une culture hors catalogue."))
    data = {"seasons": [s.model_dump() for s in sorted(body.seasons, key=lambda s: s.season_index)]}
    d = _ecrire(db, p, "history", data, if_match)
    return {"parcel_id": p.id, **d.data, "version": d.version}


# ------------------------------------------------------------------ préférences
def _vue_pref(p: Parcel, d: ParcelData | None, warnings=None) -> dict:
    if d is None:
        return {"weights": dict(PR.DEFAULT), "source": "default", "constraints": Contraintes().model_dump(),
                "warnings": [], "version": 0}
    return {**d.data, "warnings": warnings or [], "version": d.version}


@router.get("/parcels/{parcel_id}/preferences")
def lire_pref(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    return _vue_pref(p, lire_donnees(db, p.id, "preferences"))


def resoudre_preferences(body: Preferences, region: str) -> tuple[dict, list]:
    """Valide et convertit ; renvoie (données stockées, avertissements). Sert aussi au calcul (§10)."""
    if body.ranking is not None and body.weights is not None:
        raise validation(champ("ranking", "invalid_choice", "Envoyez soit un classement, soit des poids."))
    if body.ranking is not None:
        if len(set(body.ranking)) != len(body.ranking):
            raise validation(champ("ranking", "duplicate", "Chaque priorité ne peut être classée qu'une fois."))
        poids, source = PR.ranking_to_weights(body.ranking), "ranking"
    elif body.weights is not None:
        inconnues = set(body.weights) - set(PR.KEYS)
        if inconnues:
            raise validation(champ("weights", "invalid_choice", f"Priorités inconnues : {', '.join(inconnues)}"))
        if any(v < 0 for v in body.weights.values()):
            raise validation(champ("weights", "out_of_range", "Les poids doivent être positifs.", min=0))
        poids, source = PR.normaliser(body.weights), "weights"
    else:
        poids, source = dict(PR.DEFAULT), "default"
    c = body.constraints
    _verifier_cultures(c.excluded_crops, region, "constraints.excluded_crops")
    _verifier_cultures(c.market_available_crops, region, "constraints.market_available_crops")
    catalogue = REF.ids_cultures(region)
    restantes = catalogue - set(c.excluded_crops)
    if len(restantes) < 2:
        raise ApiError("NO_CROP_AVAILABLE", 422, "Trop de cultures exclues : il en faut au moins deux de disponibles.",
                       {"available": sorted(restantes)})
    warnings = []
    if len(c.excluded_crops) >= 0.7 * len(catalogue):
        warnings.append({"code": "EXCLUSION_TOO_RESTRICTIVE", "message": "Presque toutes les cultures sont exclues ; "
                         "les règles de rotation risquent d'être compromises."})
    if not c.market_available_crops:
        warnings.append({"code": "MARKETS_NOT_PROVIDED", "message": "Aucun débouché renseigné : le critère revenu "
                         "est estimé sans connaître vos marchés."})
    return {"weights": poids, "source": source, "constraints": c.model_dump()}, warnings


@router.put("/parcels/{parcel_id}/preferences")
def ecrire_pref(parcel_id: str, body: Preferences, request: Request, if_match: str | None = Header(None),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *EXPLOITANTS)
    data, warnings = resoudre_preferences(body, _region(db, p))
    d = _ecrire(db, p, "preferences", data, if_match)
    return _vue_pref(p, d, avertissements(warnings, langue(request)))
