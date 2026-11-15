"""T16 - Terrain : altitude et pente (SRTM local), sinon altitude de la cellule POWER sans pente."""
from fastapi import APIRouter, Query

from app import cache
from app.sources import pre_agreges as pre

router = APIRouter(tags=["terrain"])


def dans_zone_pilote(lat: float, lon: float) -> bool:
    return any(la0 <= lat <= la1 and lo0 <= lon <= lo1 for _, la0, la1, lo0, lo1 in cache.ZONES_SECOURS)


@router.get("/terrain")
def terrain(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    warnings = []
    alt, pente = pre.srtm(lat, lon)
    source = "SRTM 30 m"
    if alt is None:
        source = None
        warnings.append({"code": "SRTM_UNAVAILABLE",
                         "message": "Altitude et pente indisponibles ; renseignez la pente à la main."})
    if not dans_zone_pilote(lat, lon):
        warnings.append({"code": "OUTSIDE_COVERED_REGION",
                         "message": "Parcelle hors de la zone pilote : SMAP, NDVI et SRTM locaux non disponibles."})
    return {"lat": lat, "lon": lon, "elevation_m": None if alt is None else round(alt),
            "slope_deg": None if pente is None else round(pente, 1), "source": source,
            "soil": {"ph": None, "texture": None, "source": None}, "warnings": warnings}
