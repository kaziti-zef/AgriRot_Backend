from fastapi import APIRouter

from app.engine.pipeline import proposer
from app.schemas import ReponseStrategies, RequeteStrategies

router = APIRouter(tags=["stratégies"])


@router.post("/strategies", response_model=ReponseStrategies)
def strategies(req: RequeteStrategies):
    """Existante + recommandée + alternative (contrat §10), avec modifications manuelles et scénario."""
    return proposer(req)
