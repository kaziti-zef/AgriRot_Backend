"""Format d'erreur standard (contrat v2, §3.1 à §3.4) et identifiant de requête."""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("agrorot")

RAISONS = {"missing": "required", "string_too_short": "too_short", "string_too_long": "too_long",
           "too_short": "too_short", "too_long": "too_long", "greater_than": "out_of_range",
           "greater_than_equal": "out_of_range", "less_than": "out_of_range", "less_than_equal": "out_of_range",
           "literal_error": "invalid_choice", "enum": "invalid_choice"}


class ApiError(Exception):
    def __init__(self, code: str, http: int, message: str, details: dict | None = None, headers: dict | None = None):
        self.code, self.http, self.message, self.details, self.headers = code, http, message, details or {}, headers


def champ(path: str, reason: str, message: str, **extra) -> dict:
    return {"path": path, "reason": reason, "message": message, **extra}


def validation(*fields: dict) -> ApiError:
    return ApiError("VALIDATION_ERROR", 422, "Certaines valeurs sont invalides.", {"fields": list(fields)})


def _body(code, message, details, request_id, request=None):
    from app.i18n import langue
    from app.i18n import message as traduire
    message = traduire(code, message, langue(request))
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id}}


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:8]}"
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details, request.state.request_id, request),
                            status_code=exc.http, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errs = exc.errors()
        if any(e["type"] == "json_invalid" for e in errs):
            return JSONResponse(_body("INVALID_REQUEST", "La requête est mal formée.", {}, request.state.request_id, request), 400)
        fields = []
        for e in errs:
            loc = [str(p) for p in e["loc"] if p not in ("body", "query", "path", "header")]
            ctx = e.get("ctx") or {}
            extra = {k: v for k, v in ctx.items() if k in ("min_length", "max_length", "ge", "le", "gt", "lt")}
            fields.append(champ(".".join(loc), RAISONS.get(e["type"], "invalid_format"), e["msg"], **extra))
        return JSONResponse(_body("VALIDATION_ERROR", "Certaines valeurs sont invalides.", {"fields": fields},
                                  request.state.request_id, request), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "INVALID_REQUEST"}.get(exc.status_code, "INVALID_REQUEST")
        return JSONResponse(_body(code, "Ressource introuvable." if exc.status_code == 404 else "La requête est mal formée.",
                                  {}, getattr(request.state, "request_id", "req_?"), request), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def internal(request: Request, exc: Exception):
        log.exception("Erreur interne %s", getattr(request.state, "request_id", "?"))
        return JSONResponse(_body("INTERNAL_ERROR", "Une erreur est survenue. Communiquez le code de requête "
                                  "si le problème persiste.", {}, getattr(request.state, "request_id", "req_?"), request),
                            status_code=500)
