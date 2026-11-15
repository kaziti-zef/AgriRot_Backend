"""T46 - Régions et cultures (§5) : publics, relayés depuis agrorot-core (cache 10 min)."""
from fastapi import APIRouter

from app.domain import referentiel as REF

router = APIRouter(tags=["referentiel"])


@router.get("/regions")
def regions():
    return REF.regions()


@router.get("/crops")
def crops(region: str):
    return REF.crops(region)
