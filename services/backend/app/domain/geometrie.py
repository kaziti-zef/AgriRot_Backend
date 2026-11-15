"""T44 - Géométrie des parcelles : validation (Shapely), surface en projection UTM, centroïde,
chevauchement. Le frontend envoie un polygone construit à partir des points posés sur la carte ;
un anneau non fermé est refermé automatiquement."""
import math

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, shape

from app.errors import ApiError

SURFACE_MIN_HA, SURFACE_MAX_HA = 0.01, 1000.0


def _invalide(raison: str) -> ApiError:
    return ApiError("INVALID_POLYGON", 400, "Le polygone tracé présente une auto-intersection, moins de 3 sommets "
                    "ou une surface nulle ou hors limites.", {"reason": raison})


def _utm(lon: float, lat: float) -> Transformer:
    zone = int((lon + 180) // 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)


def _projeter(geom, tr: Transformer):
    return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def valider(geometry: dict) -> tuple[dict, Polygon, Polygon, float, tuple[float, float]]:
    """-> (GeoJSON normalisé, polygone WGS84, polygone projeté, surface ha, (lat, lon) du centroïde)."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon" or not geometry.get("coordinates"):
        raise _invalide("type")
    anneau = [tuple(map(float, p[:2])) for p in geometry["coordinates"][0]]
    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in anneau):
        raise _invalide("hors_limites")
    if anneau and anneau[0] != anneau[-1]:
        anneau.append(anneau[0])
    if len(set(anneau)) < 3:
        raise _invalide("moins_de_3_sommets")
    poly = Polygon(anneau)
    if not poly.is_valid:
        raise _invalide("auto_intersection")
    c = poly.centroid
    proj = _projeter(poly, _utm(c.x, c.y))
    ha = proj.area / 10_000
    if not SURFACE_MIN_HA <= ha <= SURFACE_MAX_HA:
        raise _invalide("surface")
    norm = {"type": "Polygon", "coordinates": [[list(p) for p in anneau]]}
    return norm, poly, proj, round(ha, 2), (round(c.y, 6), round(c.x, 6))


def chevauche(proj: Polygon, autres: list[dict], centre: tuple[float, float]) -> bool:
    tr = _utm(centre[1], centre[0])
    for g in autres:
        o = _projeter(shape(g), tr)
        if o.is_valid and proj.intersection(o).area > 0.005 * min(proj.area, o.area):
            return True
    return False


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))
