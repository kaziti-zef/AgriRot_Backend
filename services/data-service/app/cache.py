"""T11 - Cache disque et Plan B (contrat §3.6).

Ordre : cache récent (< CACHE_FRAIS_JOURS) -> POWER en direct -> dernier cache, même ancien
(fallback_cache) -> jeu régional de secours (fallback_local) -> 503 CLIMATE_DATA_UNAVAILABLE.
Clé : coordonnées arrondies à 0,5° (taille d'une cellule POWER) + période.
"""
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.errors import ApiError
from app.sources import nasa_power as power

CACHE_DIR = Path(os.getenv("CACHE_DIR", Path(__file__).resolve().parents[1] / ".cache"))   # modifiable (tests)
FALLBACK_DIR = Path(__file__).resolve().parents[1] / "data" / "fallback"
CACHE_FRAIS_JOURS = 7
# Zones couvertes par un jeu de secours : (code, lat min, lat max, lon min, lon max)
ZONES_SECOURS = [("cm_yaounde", 3.4, 4.3, 11.0, 12.0)]


@dataclass
class Resultat:
    serie: power.SerieJournaliere
    statut: str                 # live | fallback_cache | fallback_local
    cached_at: str | None
    synthetique: bool = False


def _cle(lat, lon, debut, fin) -> str:
    return f"power_{round(lat * 2) / 2:+.1f}_{round(lon * 2) / 2:+.1f}_{debut}_{fin}"


def _ecrire(cle: str, s: power.SerieJournaliere):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    s.jours.to_csv(CACHE_DIR / f"{cle}.csv.gz")
    (CACHE_DIR / f"{cle}.json").write_text(json.dumps({"altitude_m": s.altitude_m, "lat": s.lat, "lon": s.lon,
                                                        "saved_at": time.time()}))


def _lire(cle: str) -> tuple[power.SerieJournaliere, float] | None:
    f, m = CACHE_DIR / f"{cle}.csv.gz", CACHE_DIR / f"{cle}.json"
    if not (f.exists() and m.exists()):
        return None
    meta = json.loads(m.read_text())
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    return power.SerieJournaliere(df, meta["altitude_m"], meta["lat"], meta["lon"]), meta["saved_at"]


def _secours(lat, lon) -> tuple[power.SerieJournaliere, bool] | None:
    for code, la0, la1, lo0, lo1 in ZONES_SECOURS:
        f = FALLBACK_DIR / f"{code}_daily.csv.gz"
        if la0 <= lat <= la1 and lo0 <= lon <= lo1 and f.exists():
            meta_f = FALLBACK_DIR / f"{code}_daily.json"
            meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            return power.SerieJournaliere(df, meta.get("altitude_m"), lat, lon), bool(meta.get("synthetique", True))
    return None


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def obtenir(lat: float, lon: float, debut: int, fin: int, delai: float = power.DELAI_COURT) -> Resultat:
    cle = _cle(lat, lon, debut, fin)
    en_cache = _lire(cle)
    if en_cache and time.time() - en_cache[1] < CACHE_FRAIS_JOURS * 86400:
        return Resultat(en_cache[0], "live", _iso(en_cache[1]))
    try:
        s = power.telecharger(lat, lon, debut, fin, delai)
        _ecrire(cle, s)
        return Resultat(s, "live", None)
    except power.PowerIndisponible:
        pass
    if en_cache:
        return Resultat(en_cache[0], "fallback_cache", _iso(en_cache[1]))
    sec = _secours(lat, lon)
    if sec:
        return Resultat(sec[0], "fallback_local", None, synthetique=sec[1])
    raise ApiError("CLIMATE_DATA_UNAVAILABLE", 503, "Les données climatiques sont momentanément indisponibles.",
                   {"retry_after_seconds": 30})
