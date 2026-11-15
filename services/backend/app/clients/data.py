"""T47 - Client HTTP vers data-service. Panne -> 503 CLIMATE_DATA_UNAVAILABLE.
Lectures : jusqu'à 2 nouvelles tentatives (1 s puis 3 s), comme le prévoit le contrat §3.8."""
import time

import httpx

from app import config
from app.errors import ApiError

TIMEOUT = httpx.Timeout(20.0, connect=3.0)
_transport = None
_attentes = (1.0, 3.0)


def _client(timeout=TIMEOUT) -> httpx.Client:
    return httpx.Client(base_url=config.DATA_SERVICE_URL, timeout=timeout, transport=_transport)


def _indispo():
    return ApiError("CLIMATE_DATA_UNAVAILABLE", 503, "Les données climatiques sont momentanément indisponibles.",
                    {"retry_after_seconds": 30})


def _get(path: str, **params) -> dict:
    for i in range(len(_attentes) + 1):
        try:
            with _client() as c:
                r = c.get(path, params=params)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code < 500:
            break
        if i < len(_attentes):
            time.sleep(_attentes[i])
    if r is None or r.status_code >= 500:
        raise _indispo()
    if r.status_code >= 400:
        err = r.json().get("error", {})
        raise ApiError(err.get("code", "INVALID_REQUEST"), r.status_code, err.get("message", ""), err.get("details"))
    return r.json()


def series(lat: float, lon: float) -> dict:
    return _get("/v1/climate/series", lat=lat, lon=lon)


def diagnostic(lat: float, lon: float, year: int | None = None) -> dict:
    return _get("/v1/climate/diagnostic", lat=lat, lon=lon, **({"year": year} if year else {}))


def terrain(lat: float, lon: float) -> dict:
    return _get("/v1/terrain", lat=lat, lon=lon)


def prefetch(lat: float, lon: float):
    """Préchargement en tâche de fond à la création d'une parcelle ; les erreurs sont ignorées."""
    try:
        with _client(timeout=httpx.Timeout(180.0, connect=3.0)) as c:
            c.post("/v1/climate/prefetch", params={"lat": lat, "lon": lon})
    except httpx.HTTPError:
        pass


def sante() -> tuple[str, str]:
    """(état du data-service, état de NASA POWER vu par lui)."""
    try:
        with _client(timeout=4.0) as c:
            r = c.get("/health")
        if r.status_code != 200:
            return "error", "unknown"
        return "ok", r.json().get("nasa_power", "unknown")
    except httpx.HTTPError:
        return "timeout", "unknown"


def previsions(lat: float, lon: float, past_days: int = 30, days: int = 10) -> dict:
    """T65 : météo récente + prévision. Jamais bloquant : en cas de panne, statut "unavailable"."""
    try:
        return _get("/v1/forecast/daily", lat=lat, lon=lon, past_days=past_days, days=days)
    except ApiError:
        return {"status": "unavailable", "source": None, "days": [], "normals": None}
