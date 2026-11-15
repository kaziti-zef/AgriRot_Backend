"""Format d'erreur standard (contrat v2, section 3.1)."""
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, http: int, message: str, details: dict | None = None):
        self.code, self.http, self.message, self.details = code, http, message, details or {}


def _body(code, message, details, request_id):
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
        return JSONResponse(_body(exc.code, exc.message, exc.details, request.state.request_id), status_code=exc.http)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [{"path": ".".join(str(p) for p in e["loc"][1:]), "reason": e["type"], "message": e["msg"]}
                  for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Certaines valeurs sont invalides.", {"fields": fields},
                                  request.state.request_id), status_code=422)

    @app.exception_handler(Exception)
    async def internal(request: Request, exc: Exception):
        return JSONResponse(_body("INTERNAL_ERROR", "Une erreur est survenue. Communiquez le code de requête "
                                  "si le problème persiste.", {}, getattr(request.state, "request_id", "req_?")),
                            status_code=500)


def not_implemented(what: str) -> ApiError:
    return ApiError("NOT_IMPLEMENTED", 501, f"{what} : à implémenter.")
