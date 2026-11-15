"""T47 - Client HTTP vers agrorot-core. Panne -> 503 ENGINE_UNAVAILABLE ; erreurs métier propagées."""
import httpx

from app import config
from app.errors import ApiError

TIMEOUT = httpx.Timeout(30.0, connect=3.0)
_transport = None          # injectable dans les tests


def _client(request_id: str | None = None) -> httpx.Client:
    h = {"X-Request-ID": request_id} if request_id else {}
    return httpx.Client(base_url=config.CORE_SERVICE_URL, timeout=TIMEOUT, transport=_transport, headers=h)


def _envoyer(methode: str, path: str, request_id=None, **kw) -> dict:
    try:
        with _client(request_id) as c:
            r = c.request(methode, path, **kw)
    except httpx.HTTPError:
        raise ApiError("ENGINE_UNAVAILABLE", 503, "Le calcul des stratégies est momentanément indisponible.")
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        if r.status_code >= 500 or not err.get("code"):
            raise ApiError("ENGINE_UNAVAILABLE", 503, "Le calcul des stratégies est momentanément indisponible.")
        raise ApiError(err["code"], r.status_code, err.get("message", ""), err.get("details"))
    return r.json()


def strategies(payload: dict, request_id=None) -> dict:
    return _envoyer("POST", "/v1/strategies", request_id, json=payload)


def evaluate(payload: dict, request_id=None) -> dict:
    return _envoyer("POST", "/v1/evaluate", request_id, json=payload)


def regions() -> dict:
    return _envoyer("GET", "/v1/regions")


def crops(region: str) -> dict:
    return _envoyer("GET", "/v1/crops", params={"region": region})


def sante() -> str:
    try:
        with _client() as c:
            return "ok" if c.get("/health", timeout=2.0).status_code == 200 else "error"
    except httpx.HTTPError:
        return "timeout"
