"""T15 + T17 - Routes climatiques."""
import numpy as np
from fastapi import APIRouter, Query

from app import climat as C
from app.processing import climatologie
from app.sources import en_ligne
from app.sources import nasa_power as power
from app.sources import pre_agreges as pre

router = APIRouter(tags=["climat"])
LAT = Query(..., ge=-90, le=90)
LON = Query(..., ge=-180, le=180)
MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
        "Novembre", "Décembre"]
GLOSSAIRE = {
    "evapotranspiration": "Eau perdue par le sol et les plantes.",
    "ndvi": "Indice de la vigueur de la végétation vue du ciel.",
    "soil_moisture_anomaly": "Écart entre l'humidité actuelle et la normale.",
    "water_balance": "Pluie plus irrigation, moins le besoin de la culture.",
    "frost_risk": "Probabilité de gel (quasi nulle à Yaoundé, utile ailleurs).",
}


def _entete(c: C.Climat) -> dict:
    return {"data_source_status": c.statut, "cached_at": c.cached_at, "synthetique": c.synthetique}


@router.get("/climate/series")
def series(lat: float = LAT, lon: float = LON, start_year: int | None = None, end_year: int | None = None):
    """Entrée du moteur : `site_climat` se transmet tel quel à agrorot-core (Contexte.climat)."""
    c = C.calculer(lat, lon, start_year, end_year)
    m = c.mensuel
    return {**_entete(c), "altitude_m": c.altitude_m, "site_climat": C.site_climat(c),
            "qualite": {"methode_et0": c.methode_et0,
                        "mois_interpoles": int((m["qualite"] == "interpolated").sum()),
                        "mois_indisponibles": int((m["qualite"] == "unavailable").sum()),
                        "annees": [int(m.index.get_level_values(0).min()), int(m.index.get_level_values(0).max())]}}


@router.post("/climate/prefetch")
def prefetch(lat: float = LAT, lon: float = LON):
    """À appeler à l'enregistrement d'une parcelle : télécharge 30 ans de POWER avec un délai long
    (DELAI_LONG) et remplit le cache ; les appels suivants répondent en moins d'une seconde."""
    c = C.calculer(lat, lon, delai=power.DELAI_LONG)
    # Sources en ligne (sans fichiers pré-agrégés) : humidité du sol et NDVI de la dernière année complète.
    en_ligne.humidite_sol(lat, lon)
    en_ligne.precharger_ndvi(lat, lon)
    return {**_entete(c), "jours": len(c.jours)}


def _periodes(mois: list[int], type_: str) -> list[dict]:
    """Regroupe des mois (1-12) en périodes consécutives, y compris à cheval sur décembre-janvier."""
    if not mois:
        return []
    s = sorted(set(mois))
    groupes, cour = [], [s[0]]
    for m in s[1:]:
        if m == cour[-1] + 1:
            cour.append(m)
        else:
            groupes.append(cour)
            cour = [m]
    groupes.append(cour)
    if len(groupes) > 1 and groupes[0][0] == 1 and groupes[-1][-1] == 12:
        groupes[0] = groupes.pop() + groupes[0]
    return [{"type": type_, "from_month": g[0], "to_month": g[-1]} for g in groupes]


@router.get("/climate/diagnostic")
def diagnostic(lat: float = LAT, lon: float = LON, year: int | None = None):
    """Contrat §8 : 12 mois de l'année demandée (défaut : dernière année complète) face aux normales."""
    c = C.calculer(lat, lon)
    m, j = c.mensuel, c.jours
    norm = climatologie.normales(m)
    annees = sorted(set(m.index.get_level_values(0)))
    annee = year if year in annees else annees[-1]
    # Fichiers pré-agrégés (SMAP, MODIS) s'ils existent, sinon sources NASA en ligne (en_ligne.py).
    smap = pre.serie_mensuelle("smap_monthly.nc", lat, lon)
    sm = pre.anomalies(smap if smap is not None else en_ligne.humidite_sol(lat, lon))
    ndvi = pre.serie_mensuelle("ndvi_monthly.nc", lat, lon)
    if ndvi is None:
        ndvi = en_ligne.ndvi_mensuel(lat, lon, annee)
    gel = j.groupby(j.index.month)["t_min"].apply(lambda x: float((x < 0).mean()))
    serie, manquants = [], set()
    for mo in range(1, 13):
        r = m.loc[(annee, mo)] if (annee, mo) in m.index else None
        n = norm.loc[mo] if mo in norm.index else None
        sm_v = _valeur(sm, annee, mo)
        nd_v = _valeur(ndvi, annee, mo)
        if sm_v is None:
            manquants.add("soil_moisture_anomaly")
        if nd_v is None:
            manquants.add("ndvi")
        ok = r is not None and r["qualite"] != "unavailable"
        pluie, et = (float(r.pluie_mm), float(r.et0_mm)) if ok else (None, None)
        bilan = round(pluie - et, 1) if ok else None
        alertes = []
        if n is not None and 0.8 * n.pluie_mm < 0.75 * n.et0_mm:
            alertes.append("dry_season")
        if ok and (bilan < -50 and pluie < 0.6 * n.pluie_mm or (sm_v is not None and sm_v <= -1)):
            alertes.append("water_stress")
        if ok and r.pluie_intense_mm > max(30, 1.5 * n.pluie_intense_mm):
            alertes.append("heavy_rain")
        if ok and r.c34 >= 3:
            alertes.append("heat_stress")
        if gel.get(mo, 0) > 0.05:
            alertes.append("frost_risk")
        if nd_v is not None and nd_v < 0.2 and "dry_season" not in alertes:
            alertes.append("bare_soil_risk")
        serie.append({
            "month": mo, "label": MOIS[mo - 1],
            "temp_avg_c": round(float(r.t_moy_c), 1) if ok else None,
            "temp_normal_c": round(float(n.t_moy_c), 1) if n is not None else None,
            "rain_mm": round(pluie, 1) if ok else None,
            "rain_normal_mm": round(float(n.pluie_mm), 1) if n is not None else None,
            "soil_moisture_anomaly": None if sm_v is None else round(sm_v, 2),
            "ndvi": None if nd_v is None else round(nd_v, 2),
            "evapotranspiration_mm": round(et, 1) if ok else None,
            "water_balance_mm": bilan,
            "frost_risk": round(float(gel.get(mo, 0.0)), 2),
            "quality": r["qualite"] if r is not None else "unavailable",
            "alerts": alertes,
        })
    # Périodes vulnérables : climatologie (bilan normal très négatif) et NDVI bas en saison des pluies
    stress = [mo for mo in norm.index if 0.8 * norm.loc[mo].pluie_mm - norm.loc[mo].et0_mm < -40]
    nu = [x["month"] for x in serie if "bare_soil_risk" in x["alerts"]]
    intense = norm["pluie_intense_mm"] / max(1e-9, norm["pluie_intense_mm"].sum())
    fortes = [int(mo) for mo, v in intense.items() if v >= 0.15]
    periodes = _periodes(stress, "water_stress") + _periodes(nu, "bare_soil") + _periodes(fortes, "heavy_rain")
    return {"parcel_point": {"lat": lat, "lon": lon}, "year": int(annee), **_entete(c),
            "grid_resolution_note": "NASA POWER (cellule de 0,5° x 0,625°, environ 55 x 70 km), humidité du sol SMAP (9 km) "
                                    "ou NASA POWER GWETROOT, MODIS NDVI (250 m).",
            "monthly_series": serie, "vulnerable_periods": periodes,
            "missing_indicators": sorted(manquants), "glossary": GLOSSAIRE}


def _valeur(serie, annee, mois):
    if serie is None:
        return None
    sel = serie[(serie.index.year == annee) & (serie.index.month == mois)]
    return None if sel.empty or np.isnan(sel.iloc[0]) else float(sel.iloc[0])
