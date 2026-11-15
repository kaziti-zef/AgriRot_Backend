"""T16 - Lecture des fichiers pré-agrégés produits par scripts/pretelecharger.py.

data/preaggregated/ : smap_monthly.nc, ndvi_monthly.nc, srtm_30m.tif, imerg_daily.csv.
Chaque lecteur renvoie None si le fichier ou la bibliothèque manque : l'appelant signale alors
l'indicateur dans `missing_indicators` ou un avertissement, sans échouer.
"""
import math
from functools import lru_cache
from pathlib import Path

DOSSIER = Path(__file__).resolve().parents[2] / "data" / "preaggregated"


@lru_cache
def _ouvrir_nc(nom: str):
    f = DOSSIER / nom
    if not f.exists():
        return None
    try:
        import xarray as xr
        ds = xr.open_dataset(f)
        return ds[list(ds.data_vars)[0]]
    except Exception:
        return None


def serie_mensuelle(nom: str, lat: float, lon: float):
    """Série mensuelle (pandas) à la cellule la plus proche, ou None."""
    da = _ouvrir_nc(nom)
    if da is None:
        return None
    try:
        dims = {d.lower(): d for d in da.dims}
        la, lo = dims.get("lat") or dims.get("latitude"), dims.get("lon") or dims.get("longitude")
        return da.sel({la: lat, lo: lon}, method="nearest").to_series().dropna()
    except Exception:
        return None


def anomalies(serie):
    """z = (x - moyenne du mois) / écart-type du mois."""
    if serie is None or serie.empty:
        return None
    g = serie.groupby(serie.index.month)
    return (serie - g.transform("mean")) / g.transform("std").replace(0, float("nan"))


def srtm(lat: float, lon: float) -> tuple[float | None, float | None]:
    """(altitude m, pente °) au point, depuis le MNT local ; (None, None) si indisponible."""
    f = DOSSIER / "srtm_30m.tif"
    if not f.exists():
        return None, None
    try:
        import numpy as np
        import rasterio
        with rasterio.open(f) as ds:
            r, c = ds.index(lon, lat)
            if not (1 <= r < ds.height - 1 and 1 <= c < ds.width - 1):
                return None, None
            win = ds.read(1, window=((r - 1, r + 2), (c - 1, c + 2))).astype(float)
            dy = abs(ds.transform.e) * 111_320
            dx = abs(ds.transform.a) * 111_320 * math.cos(math.radians(lat))
            gx = ((win[0, 2] + 2 * win[1, 2] + win[2, 2]) - (win[0, 0] + 2 * win[1, 0] + win[2, 0])) / (8 * dx)
            gy = ((win[2, 0] + 2 * win[2, 1] + win[2, 2]) - (win[0, 0] + 2 * win[0, 1] + win[0, 2])) / (8 * dy)
            return float(win[1, 1]), float(np.degrees(np.arctan(np.hypot(gx, gy))))
    except Exception:
        return None, None
