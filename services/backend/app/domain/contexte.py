"""T48 - Assemblage du Contexte envoyé à agrorot-core : point de jonction entre le contrat public
(base de données, saisies) et le contrat interne du moteur (schemas.py du moteur)."""
import copy
import datetime as dt

from sqlalchemy.orm import Session

from app.clients import data
from app.db.models import Farm, Parcel
from app.routers.inputs import (
    Contraintes,
    DonneesLocales,
    Preferences,
    confiance_saisies,
    lire_donnees,
    resoudre_preferences,
)


def premiere_saison(aujourd_hui: dt.date | None = None) -> tuple[int, str]:
    """Prochaine saison à semer : avant mars -> S1 de l'année ; avant août -> S2 ; sinon S1 de l'an prochain."""
    d = aujourd_hui or dt.date.today()
    if d.month < 3:
        return d.year, "S1"
    if d.month < 8:
        return d.year, "S2"
    return d.year + 1, "S1"


def appliquer_corrections(site: dict, corrections: list[dict]) -> dict:
    """Corrections de l'agriculteur (§9 nasa_overrides) : pluie en %, température en °C, par mois."""
    if not corrections:
        return site
    site = copy.deepcopy(site)
    for m in site["serie_mensuelle"]:
        for c in corrections:
            if c["month"] != m["mois"]:
                continue
            if c["field"] == "rain_mm":
                f = 1 + c["value"] / 100
                m["pluie_mm"] = round(m["pluie_mm"] * f, 1)
                m["pluie_intense_mm"] = round(m.get("pluie_intense_mm", 0) * f, 1)
            elif c["field"] == "temp_avg_c":
                for k in ("t_moy_c", "t_min_c", "t_max_c"):
                    m[k] = round(m[k] + c["value"], 2)
    return site


def construire(db: Session, p: Parcel, priorities: dict | None, constraints: dict | None) -> tuple[dict, dict, list]:
    """-> (Contexte pour le moteur, en-tête données {data_source_status, cached_at}, avertissements)."""
    region = db.get(Farm, p.farm_id).region
    d_loc = lire_donnees(db, p.id, "local_inputs")
    loc = d_loc.data if d_loc else DonneesLocales().model_dump()
    d_hist = lire_donnees(db, p.id, "history")
    hist = d_hist.data["seasons"] if d_hist else []
    d_pref = lire_donnees(db, p.id, "preferences")
    pref = d_pref.data if d_pref else None
    warnings = []
    if priorities is not None or constraints is not None:
        base = pref or {"weights": None, "constraints": Contraintes().model_dump()}
        body = Preferences(weights=priorities if priorities is not None else base.get("weights"),
                           constraints=Contraintes(**(constraints if constraints is not None else base["constraints"])))
        pref, warnings = resoudre_preferences(body, region)
    if pref is None:
        pref = {"weights": {}, "constraints": Contraintes().model_dump()}

    serie = data.series(p.lat, p.lon)
    site = appliquer_corrections(serie["site_climat"], loc.get("nasa_overrides", []))
    sol = loc.get("soil", {})
    conf, _, _ = confiance_saisies(p, loc)
    annee, saison = premiere_saison()
    ctx = {
        "region": region, "premiere_annee": annee, "premiere_saison": saison, "climat": site,
        "sol": {"texture": sol.get("texture"), "ph": sol.get("ph"), "drainage": sol.get("drainage"),
                "organic_matter": sol.get("organic_matter"),
                "slope_deg": sol.get("slope_deg") if sol.get("slope_deg") is not None else p.slope_deg,
                "elevation_m": p.elevation_m, "confidences": conf},
        "eau": loc.get("water", {}),
        "pratiques": loc.get("practices", {}),
        "historique": [{"season_index": s["season_index"], "crop_id": s["crop_id"],
                        "botanical_family": s.get("botanical_family")} for s in hist],
        "planned_rotation": [{"season": e["season"], "crop_id": e["crop_id"]} for e in loc.get("planned_rotation", [])],
        "pest_history": loc.get("pest_history", []),
        "poids": pref.get("weights") or {},
        "contraintes": pref["constraints"],
    }
    entete = {"data_source_status": serie.get("data_source_status", "live"), "cached_at": serie.get("cached_at")}
    exclues = set(pref["constraints"].get("excluded_crops", []))
    if any(s["crop_id"] in exclues for s in hist):
        warnings.append({"code": "EXCLUDED_CROP_IN_HISTORY", "message": "Une culture exclue figure dans l'historique."})
    return ctx, entete, warnings
