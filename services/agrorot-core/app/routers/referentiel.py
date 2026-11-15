from fastapi import APIRouter

from app.errors import ApiError
from app.referentiel.loader import REF

router = APIRouter(tags=["référentiel"])


@router.get("/regions")
def regions():
    return {"regions": REF.regions}


@router.get("/crops")
def crops(region: str):
    if not REF.region_connue(region):
        raise ApiError("REGION_NOT_SUPPORTED", 404, "Cette région n'est pas encore prise en charge.")
    return {"region": region, "crops": REF.crops_public(region)}


@router.get("/pests")
def pests():
    return {"pests": REF.bioagresseurs_public()}


@router.get("/rules")
def rules():
    """Catalogue des règles (C1…C7, R1…R8) citées dans les explications."""
    from app.engine.regles import CATALOGUE
    return {"rules": CATALOGUE}
