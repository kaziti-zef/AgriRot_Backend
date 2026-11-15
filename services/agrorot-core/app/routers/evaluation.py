from fastapi import APIRouter

from app.engine.pipeline import evaluer_sequence
from app.schemas import ReponseEvaluation, RequeteEvaluation

router = APIRouter(tags=["évaluation"])


@router.post("/evaluate", response_model=ReponseEvaluation)
def evaluate(req: RequeteEvaluation):
    """Note UNE séquence donnée (rotation actuelle ou modifiée à la main), sans en proposer d'autres."""
    return evaluer_sequence(req)
