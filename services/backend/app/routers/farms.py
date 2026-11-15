"""T43 - Fermes (§6)."""
from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients import core
from app.db.models import Farm, Member, Parcel, User
from app.db.session import get_db
from app.errors import ApiError, champ, validation
from app.security import current_user, exiger, membre, verifier_version

router = APIRouter(tags=["farms"])


class NouvelleFerme(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    region: str


class ModifFerme(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    region: str | None = None


class Confirmation(BaseModel):
    confirm_name: str


class Transfert(BaseModel):
    member_id: str


def verifier_region(region: str):
    codes = {r["code"] for r in core.regions()["regions"]}
    if region not in codes:
        raise ApiError("REGION_NOT_SUPPORTED", 404, "Cette région n'est pas encore prise en charge.")


def vue(db: Session, f: Farm, role: str) -> dict:
    return {"id": f.id, "name": f.name, "region": f.region, "user_role": role,
            "parcels_count": db.scalar(select(func.count()).select_from(Parcel).where(Parcel.farm_id == f.id)),
            "members_count": db.scalar(select(func.count()).select_from(Member).where(Member.farm_id == f.id)),
            "version": f.version}


@router.post("/farms", status_code=201)
def creer(body: NouvelleFerme, user: User = Depends(current_user), db: Session = Depends(get_db)):
    verifier_region(body.region)
    f = Farm(name=body.name.strip(), region=body.region)
    db.add(f)
    db.flush()
    db.add(Member(farm_id=f.id, user_id=user.id, identifier=user.identifier, role="owner", status="active"))
    db.flush()
    return vue(db, f, "owner")


@router.get("/farms")
def lister(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ms = db.scalars(select(Member).where(Member.user_id == user.id, Member.status == "active")).all()
    return {"farms": [vue(db, db.get(Farm, m.farm_id), m.role) for m in ms]}


@router.get("/farms/{farm_id}")
def lire(farm_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = membre(db, farm_id, user)
    return vue(db, db.get(Farm, farm_id), m.role)


@router.patch("/farms/{farm_id}")
def modifier(farm_id: str, body: ModifFerme, if_match: str | None = Header(None),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = exiger(membre(db, farm_id, user), "owner")
    f = db.get(Farm, farm_id)
    verifier_version(f.version, if_match)
    if body.region and body.region != f.region:
        verifier_region(body.region)
        f.region = body.region
    if body.name:
        f.name = body.name.strip()
    f.version += 1
    return vue(db, f, m.role)


@router.delete("/farms/{farm_id}", status_code=204)
def supprimer(farm_id: str, body: Confirmation, user: User = Depends(current_user), db: Session = Depends(get_db)):
    exiger(membre(db, farm_id, user), "owner")
    f = db.get(Farm, farm_id)
    if body.confirm_name.strip() != f.name:
        raise validation(champ("confirm_name", "invalid_choice", "Le nom saisi ne correspond pas au nom de la ferme."))
    db.delete(f)
    return Response(status_code=204)


@router.post("/farms/{farm_id}/transfer-ownership")
def transferer(farm_id: str, body: Transfert, user: User = Depends(current_user), db: Session = Depends(get_db)):
    moi = exiger(membre(db, farm_id, user), "owner")
    cible = db.get(Member, body.member_id)
    if cible is None or cible.farm_id != farm_id:
        raise ApiError("MEMBER_NOT_FOUND", 404, "Membre introuvable.")
    if cible.role != "co_farmer" or cible.status != "active":
        raise validation(champ("member_id", "invalid_choice", "La propriété ne peut être transférée qu'à un "
                               "co-exploitant actif."))
    cible.role, moi.role = "owner", "co_farmer"
    f = db.get(Farm, farm_id)
    f.version += 1
    return vue(db, f, "co_farmer")

