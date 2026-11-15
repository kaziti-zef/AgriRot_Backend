"""T65 - Météo récente et prévisions quotidiennes pour la surveillance d'une rotation choisie.

Une seule forme de sortie, quelle que soit la source : une ligne par jour avec
  date, t_max, t_min (°C), pluie_mm, et0_mm (ET0 FAO-56, mm/j), observe (True = jour passé).

Sources, dans l'ordre :
  1. Meteomatics, si METEOMATICS_USER et METEOMATICS_PASSWORD sont définis (partenaire du défi) ;
     paramètres t_max_2m_24h:C, t_min_2m_24h:C, precip_24h:mm, evapotranspiration_24h:mm
     (cumuls « des 24 h précédentes » : la valeur datée J 00:00 UTC décrit le jour J-1) ;
  2. Open-Meteo (gratuit, sans clé, usage non commercial) : /v1/forecast avec past_days et forecast_days ;
  3. PREVISION_SIMULEE=normal|sec|pluie_forte|chaleur : série déterministe pour les tests et la démo hors ligne.
Si aucune ne répond : statut "unavailable" (la surveillance ne génère alors aucune alerte).
"""
import datetime as dt
import math
import os
import time

import httpx

DELAI = float(os.getenv("FORECAST_TIMEOUT_S", 10))
CACHE_S = 3 * 3600
_cache: dict[tuple, tuple[float, dict]] = {}

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
METEOMATICS = "https://api.meteomatics.com"
MM_PARAMS = ["t_max_2m_24h:C", "t_min_2m_24h:C", "precip_24h:mm", "evapotranspiration_24h:mm"]
MM_COLONNES = dict(zip(MM_PARAMS, ["t_max", "t_min", "pluie_mm", "et0_mm"]))


class PrevisionIndisponible(Exception):
    pass


def _aujourdhui() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _ligne(date: dt.date, t_max, t_min, pluie, et0) -> dict:
    r = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 1)  # noqa: E731
    return {"date": date.isoformat(), "t_max": r(t_max), "t_min": r(t_min), "pluie_mm": r(pluie), "et0_mm": r(et0),
            "observe": date < _aujourdhui()}


# ------------------------------------------------------------------------------------------- Meteomatics
def meteomatics(lat: float, lon: float, passe: int, jours: int, client: httpx.Client | None = None) -> list[dict]:
    user, mdp = os.getenv("METEOMATICS_USER"), os.getenv("METEOMATICS_PASSWORD")
    if not (user and mdp):
        raise PrevisionIndisponible("identifiants Meteomatics absents")
    j0 = _aujourdhui()
    debut, fin = j0 - dt.timedelta(days=passe - 1), j0 + dt.timedelta(days=jours)
    url = (f"{METEOMATICS}/{debut.isoformat()}T00:00:00Z--{fin.isoformat()}T00:00:00Z:P1D/"
           f"{','.join(MM_PARAMS)}/{lat:.4f},{lon:.4f}/json")
    c = client or httpx.Client(timeout=DELAI)
    try:
        r = c.get(url, auth=(user, mdp))
        r.raise_for_status()
        return analyser_meteomatics(r.json())
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise PrevisionIndisponible(f"Meteomatics : {e}") from e


def analyser_meteomatics(payload: dict) -> list[dict]:
    jours: dict[dt.date, dict] = {}
    for bloc in payload["data"]:
        col = MM_COLONNES.get(bloc["parameter"])
        for d in bloc["coordinates"][0]["dates"]:
            date = dt.date.fromisoformat(d["date"][:10]) - dt.timedelta(days=1)   # cumul des 24 h précédentes
            v = d.get("value")
            jours.setdefault(date, {})[col] = None if v is None or v <= -999 else v
    return [_ligne(k, v.get("t_max"), v.get("t_min"), v.get("pluie_mm"), v.get("et0_mm")) for k, v in sorted(jours.items())]


# ------------------------------------------------------------------------------------------- Open-Meteo
def open_meteo(lat: float, lon: float, passe: int, jours: int, client: httpx.Client | None = None) -> list[dict]:
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "auto",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration",
              "past_days": min(passe, 92), "forecast_days": min(jours, 16)}
    c = client or httpx.Client(timeout=DELAI)
    try:
        r = c.get(OPEN_METEO, params=params)
        r.raise_for_status()
        return analyser_open_meteo(r.json())
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise PrevisionIndisponible(f"Open-Meteo : {e}") from e


def analyser_open_meteo(payload: dict) -> list[dict]:
    d = payload["daily"]
    return [_ligne(dt.date.fromisoformat(t), d["temperature_2m_max"][i], d["temperature_2m_min"][i],
                   d["precipitation_sum"][i], d["et0_fao_evapotranspiration"][i]) for i, t in enumerate(d["time"])]


# ------------------------------------------------------------------------------------------- simulation
def simulee(scenario: str, passe: int, jours: int) -> list[dict]:
    """Série déterministe inspirée du climat de Yaoundé (≈ 4 mm/j, 30/20 °C, ET0 3,8 mm/j)."""
    j0 = _aujourdhui()
    out = []
    for k in range(-passe, jours):
        d = j0 + dt.timedelta(days=k)
        futur = k >= 0
        pluie = [0, 12, 0, 3, 0, 8, 0][d.toordinal() % 7] * 1.0            # ≈ 3,3 mm/j
        tmax, tmin, et0 = 29.5, 20.0, 3.8
        if scenario == "sec":
            pluie = 0.0 if k >= -20 else pluie * 0.3                            # 20 jours sans pluie, et la suite sèche
            tmax, et0 = 31.5, 4.6
        elif scenario == "pluie_forte" and futur and k in (2, 3):
            pluie = 85.0 if k == 2 else 40.0
        elif scenario == "chaleur" and futur and 1 <= k <= 5:
            tmax, et0 = 36.5, 5.0
        out.append(_ligne(d, tmax, tmin, pluie, et0))
    return out


# ------------------------------------------------------------------------------------------- façade
def obtenir(lat: float, lon: float, passe: int = 30, jours: int = 10) -> dict:
    sim = os.getenv("PREVISION_SIMULEE")
    cle = (round(lat, 2), round(lon, 2), passe, jours, sim)
    if cle in _cache and time.time() - _cache[cle][0] < CACHE_S:
        return _cache[cle][1]
    erreurs = []
    res = None
    if sim:
        res = {"source": f"simulation:{sim}", "status": "simulated", "days": simulee(sim, passe, jours)}
    else:
        for nom, f in (("meteomatics", meteomatics), ("open-meteo", open_meteo)):
            try:
                res = {"source": nom, "status": "live", "days": f(lat, lon, passe, jours)}
                break
            except PrevisionIndisponible as e:
                erreurs.append(str(e))
    if res is None:
        return {"source": None, "status": "unavailable", "days": [], "errors": erreurs,
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    res["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _cache[cle] = (time.time(), res)
    return res
