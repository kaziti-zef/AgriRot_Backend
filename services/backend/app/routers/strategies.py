"""T49 - Stratégies et simulation (§10) : l'endpoint central.

Flux : contexte (base + data-service) -> agrorot-core /v1/strategies -> mise au format du contrat
-> mémorisation 24 h sous computation_id. Rien n'est enregistré comme « retenu » ici."""
import datetime as dt

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import config
from app.clients import core
from app.db.models import Computation, User, maintenant
from app.db.session import get_db
from app.domain import contexte
from app.errors import ApiError
from app.i18n import DISCLAIMER_EN, avertissements, langue
from app.security import TOUS, current_user, parcelle

router = APIRouter(tags=["strategies"])


class ScenarioClimat(BaseModel):
    rain_delta_pct: float = 0
    temp_delta_c: float = 0
    horizon_years: int = 0


class RequeteStrategies(BaseModel):
    horizon_seasons: int = Field(6, ge=2, le=12)
    priorities: dict[str, float] | None = None
    constraints: dict | None = None
    climate_scenario: ScenarioClimat = ScenarioClimat()
    manual_overrides: dict[str, dict[str, str]] = {}


def _verifier_scenario(s: ScenarioClimat):
    if not (-30 <= s.rain_delta_pct <= 30 and 0 <= s.temp_delta_c <= 3 and s.horizon_years in (0, 5, 10)):
        raise ApiError("INVALID_SCENARIO", 422, "Valeurs de simulation hors des bornes autorisées.",
                       {"rain_delta_pct": [-30, 30], "temp_delta_c": [0, 3], "horizon_years": [0, 5, 10]})


def _iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def mise_en_forme(res: dict, parcel_id: str, comp: Computation, entete: dict, scenario: dict, warnings: list,
                  lang: str = "fr") -> dict:
    strategies = []
    for s in res["strategies"]:
        strategies.append({
            "id": s["id"], "type": s["type"], "name": s["name"], "score": s["score"],
            "resilience_index": s["resilience_index"], "confidence": s["confidence"],
            "sequence": s["sequence"], "explanation": s["explanation"], "non_viable": s["non_viable"],
            # ajouts au contrat v2 (décision du plan)
            "scores": s["scores"], "delta_vs_existing": s["delta_vs_existing"], "violations": s["violations"],
            "off_rotation_advice": s["off_rotation_advice"],
        })
    return {"parcel_id": parcel_id, "computation_id": comp.id, "computed_at": _iso(comp.created_at),
            **entete, "disclaimer": DISCLAIMER_EN if lang == "en" else config.DISCLAIMER, "applied_scenario": scenario,
            "warnings": avertissements(warnings + res.get("warnings", []), lang), "strategies": strategies}


@router.post("/parcels/{parcel_id}/strategies")
def calculer(parcel_id: str, body: RequeteStrategies, request: Request, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *TOUS)
    _verifier_scenario(body.climate_scenario)
    for cle in body.manual_overrides:
        if cle not in ("existing", "recommended", "alternative"):
            raise ApiError("VALIDATION_ERROR", 422, "Certaines valeurs sont invalides.",
                           {"fields": [{"path": f"manual_overrides.{cle}", "reason": "invalid_choice",
                                        "message": "Stratégie inconnue."}]})
    ctx, entete, warnings = contexte.construire(db, p, body.priorities, body.constraints)
    scenario = body.climate_scenario.model_dump()
    res = core.strategies({"contexte": ctx, "horizon_seasons": body.horizon_seasons, "scenario": scenario,
                           "manual_overrides": body.manual_overrides}, request.state.request_id)
    # Mémorisation 24 h ; purge des calculs expirés
    limite = maintenant() - dt.timedelta(hours=config.COMPUTATION_TTL_HOURS)
    db.execute(delete(Computation).where(Computation.created_at < limite))
    comp = Computation(parcel_id=p.id, result={}, request=body.model_dump(), geometry_version=p.geometry_version)
    db.add(comp)
    db.flush()
    sortie = mise_en_forme(res, p.id, comp, entete, scenario, warnings, langue(request))
    comp.result = sortie
    return sortie


@router.get("/parcels/{parcel_id}/strategies/computed/{computation_id}")
def relire(parcel_id: str, computation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """AJOUT au contrat : relit un calcul non sauvegardé (mémorisé 24 h), pour afficher le détail d'une
    stratégie (/strategies/{existing|recommended|alternative}) sans relancer le moteur."""
    p, _ = parcelle(db, parcel_id, user, *TOUS)
    c = db.get(Computation, computation_id)
    limite = maintenant() - dt.timedelta(hours=config.COMPUTATION_TTL_HOURS)
    if c is None or c.parcel_id != p.id or c.created_at < limite:
        raise ApiError("STRATEGY_NOT_FOUND", 404, "Stratégie introuvable ou périmée. Relancez le calcul.")
    return c.result
