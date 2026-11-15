"""T65 - Prévisions : météo des 30 derniers jours + 10 prochains jours, avec les normales du lieu."""
from fastapi import APIRouter, Query

from app.errors import not_implemented
from app.sources import previsions

router = APIRouter(tags=["prévision"])


def _normales(lat: float, lon: float) -> dict | None:
    """Pluie et ET0 normales par mois (mm/jour), depuis la série NASA POWER en cache. None si indisponible."""
    try:
        from app import climat as C
        from app.processing import climatologie
        c = C.calculer(lat, lon)
        n = climatologie.normales(c.mensuel)
        jours_mois = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        return {"source": "NASA POWER", "synthetique": c.synthetique,
                "par_mois": {int(m): {"pluie_mm_j": round(float(r["pluie_mm"]) / jours_mois[int(m) - 1], 2),
                                      "et0_mm_j": round(float(r["et0_mm"]) / jours_mois[int(m) - 1], 2),
                                      "t_max_c": round(float(r["t_max_c"]), 1)} for m, r in n.iterrows()}}
    except Exception:  # noqa: BLE001 - les normales sont un complément, jamais bloquantes
        return None


@router.get("/forecast/daily")
def quotidien(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
              past_days: int = Query(30, ge=0, le=92), days: int = Query(10, ge=1, le=16)):
    """Une ligne par jour (passé observé/analysé puis prévision). Sert à la surveillance des rotations."""
    p = previsions.obtenir(lat, lon, past_days, days)
    return {**p, "normals": _normales(lat, lon)}


@router.get("/forecast/seasonal")
def seasonal(lat: float, lon: float):
    """Meteomatics : prévision saisonnière en ensemble - non implémenté."""
    raise not_implemented("forecast/seasonal")
