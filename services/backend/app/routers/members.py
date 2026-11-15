"""T43 - Membres et invitations (§6)."""
import datetime as dt
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db.models import Member, User, maintenant
from app.db.session import get_db
from app.errors import ApiError, champ, validation
from app.security import current_user, exiger, membre, normaliser_identifiant

router = APIRouter(tags=["members"])


class Ajout(BaseModel):
    identifier: str
    role: Literal["co_farmer", "advisor"]


class Modif(BaseModel):
    role: Literal["co_farmer", "advisor"] | None = None
    resend_invitation: bool = False


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def _vue(db: Session, m: Member) -> dict:
    u = db.get(User, m.user_id) if m.user_id else None
    out = {"member_id": m.id, "full_name": u.full_name if u else None, "identifier": m.identifier,
           "role": m.role, "status": m.status}
    if m.status == "pending":
        out["invitation_expires_at"] = _iso(m.invitation_expires_at)
    return out


def _inviter(m: Member):
    m.invitation_token = "inv_" + secrets.token_urlsafe(16)
    m.invitation_expires_at = maintenant() + dt.timedelta(days=config.INVITATION_DAYS)


@router.get("/farms/{farm_id}/members")
def lister(farm_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membre(db, farm_id, user)
    ms = db.scalars(select(Member).where(Member.farm_id == farm_id)).all()
    return {"members": [_vue(db, m) for m in ms]}


@router.post("/farms/{farm_id}/members", status_code=201)
def ajouter(farm_id: str, body: Ajout, user: User = Depends(current_user), db: Session = Depends(get_db)):
    exiger(membre(db, farm_id, user), "owner")
    ident = normaliser_identifiant(body.identifier)
    if ident == user.identifier:
        raise validation(champ("identifier", "invalid_choice", "Vous êtes déjà membre de cette ferme."))
    if db.scalar(select(Member).where(Member.farm_id == farm_id, Member.identifier == ident)):
        raise ApiError("MEMBER_ALREADY_EXISTS", 409, "Cette personne est déjà membre de la ferme.")
    cible = db.scalar(select(User).where(User.identifier == ident))
    m = Member(farm_id=farm_id, identifier=ident, role=body.role,
               user_id=cible.id if cible else None, status="active" if cible else "pending")
    if not cible:
        _inviter(m)
    db.add(m)
    db.flush()
    out = {**_vue(db, m), "farm_id": farm_id}
    if m.status == "pending":
        out["invitation"] = {"link": f"{config.PUBLIC_URL}/invite/{m.invitation_token}",
                             "expires_at": _iso(m.invitation_expires_at)}
    return out


@router.patch("/farms/{farm_id}/members/{member_id}")
def modifier(farm_id: str, member_id: str, body: Modif, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    exiger(membre(db, farm_id, user), "owner")
    m = db.get(Member, member_id)
    if m is None or m.farm_id != farm_id:
        raise ApiError("MEMBER_NOT_FOUND", 404, "Membre introuvable.")
    if m.role == "owner":
        raise ApiError("LAST_OWNER", 409, "Le propriétaire ne peut pas être retiré. Transférez d'abord la propriété.")
    if body.role:
        m.role = body.role
    out = _vue(db, m)
    if body.resend_invitation and m.status == "pending":
        _inviter(m)
        out["invitation"] = {"link": f"{config.PUBLIC_URL}/invite/{m.invitation_token}",
                             "expires_at": _iso(m.invitation_expires_at)}
    return out


@router.delete("/farms/{farm_id}/members/{member_id}", status_code=204)
def retirer(farm_id: str, member_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    moi = membre(db, farm_id, user)
    if member_id == "me":
        m = moi
    else:
        exiger(moi, "owner")
        m = db.get(Member, member_id)
        if m is None or m.farm_id != farm_id:
            raise ApiError("MEMBER_NOT_FOUND", 404, "Membre introuvable.")
    if m.role == "owner":
        raise ApiError("LAST_OWNER", 409, "Le propriétaire ne peut pas être retiré. Transférez d'abord la propriété.")
    db.delete(m)
    return Response(status_code=204)
