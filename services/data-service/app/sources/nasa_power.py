"""T10 - Client NASA POWER, point journalier (communauté AG).

Requête : GET https://power.larc.nasa.gov/api/temporal/daily/point
          ?parameters=...&community=AG&longitude=..&latitude=..&start=AAAAMMJJ&end=AAAAMMJJ&format=JSON
Réponse : GeoJSON ; valeurs dans properties.parameter[PARAM][AAAAMMJJ] ; valeur manquante = -999
          (header.fill_value) ; altitude de la cellule dans geometry.coordinates[2].
Unités (communauté AG) : °C, mm/jour, %, m/s, MJ/m²/jour.
"""
import os
from dataclasses import dataclass

import httpx
import numpy as np
import pandas as pd

BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"
# WS2M (vent à 2 m) est indispensable à l'ET0 Penman-Monteith.
PARAMETRES = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]
COLONNES = {"T2M": "t_moy", "T2M_MAX": "t_max", "T2M_MIN": "t_min", "PRECTOTCORR": "pluie", "RH2M": "hr",
            "WS2M": "vent", "ALLSKY_SFC_SW_DWN": "rayonnement"}
DELAI_COURT = float(os.getenv("NASA_POWER_TIMEOUT_S", 5))     # contrat §3.6 : affichage
DELAI_LONG = float(os.getenv("NASA_POWER_PREFETCH_TIMEOUT_S", 120))   # préchargement de 30 ans


class PowerIndisponible(Exception):
    """POWER n'a pas répondu à temps ou a renvoyé une erreur."""


@dataclass
class SerieJournaliere:
    jours: pd.DataFrame          # index = dates ; colonnes t_moy, t_max, t_min, pluie, hr, vent, rayonnement
    altitude_m: float | None
    lat: float
    lon: float


def url(lat: float, lon: float, debut: int, fin: int) -> tuple[str, dict]:
    return BASE, {"parameters": ",".join(PARAMETRES), "community": "AG", "longitude": round(lon, 4),
                  "latitude": round(lat, 4), "start": f"{debut}0101", "end": f"{fin}1231", "format": "JSON"}


def analyser(payload: dict, lat: float, lon: float) -> SerieJournaliere:
    """Réponse JSON POWER -> tableau journalier. Les -999 deviennent des valeurs manquantes."""
    try:
        params = payload["properties"]["parameter"]
    except (KeyError, TypeError) as e:
        raise PowerIndisponible(f"réponse POWER inattendue : {e}") from e
    fill = payload.get("header", {}).get("fill_value", -999)
    df = pd.DataFrame({COLONNES[p]: pd.Series(params[p], dtype=float) for p in PARAMETRES if p in params})
    manquants = [p for p in PARAMETRES if p not in params]
    if "pluie" not in df or "t_max" not in df or "t_min" not in df:
        raise PowerIndisponible(f"paramètres essentiels absents : {manquants}")
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.sort_index().replace(fill, np.nan).mask(df <= -998)
    coords = payload.get("geometry", {}).get("coordinates", [])
    alt = float(coords[2]) if len(coords) > 2 and coords[2] not in (None, fill) else None
    return SerieJournaliere(df, alt, lat, lon)


def telecharger(lat: float, lon: float, debut: int, fin: int, delai: float = DELAI_COURT,
                client: httpx.Client | None = None) -> SerieJournaliere:
    if os.getenv("POWER_SIMULE") == "1":          # tests de bout en bout et démo hors ligne uniquement
        from tests.power_simule import payload
        return analyser(payload(lat, lon, debut, fin), lat, lon)
    base, q = url(lat, lon, debut, fin)
    try:
        c = client or httpx.Client()
        r = c.get(base, params=q, timeout=delai)
        r.raise_for_status()
        return analyser(r.json(), lat, lon)
    except (httpx.HTTPError, ValueError) as e:
        raise PowerIndisponible(str(e)) from e
    finally:
        if client is None:
            c.close()


def ping(delai: float = 3.0) -> str:
    try:
        httpx.get("https://power.larc.nasa.gov/api/temporal/daily/openapi.json", timeout=delai).raise_for_status()
        return "ok"
    except httpx.TimeoutException:
        return "timeout"
    except httpx.HTTPError:
        return "error"
