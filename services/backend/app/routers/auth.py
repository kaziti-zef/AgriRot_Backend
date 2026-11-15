"""T41 - Authentification (§4)."""
import datetime as dt
import logging
import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db.models import Member, RefreshToken, ResetToken, User, maintenant
from app.db.session import get_db
from app.errors import ApiError, champ, validation
from app.security import (
    current_user,
    effacer_echecs,
    hacher,
    jeton_acces,
    normaliser_identifiant,
    noter_echec,
    reponse_jetons,
    verifier,
    verifier_limite,
)

router = APIRouter(tags=["auth"])
log = logging.getLogger("agrorot")


class Inscription(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    identifier: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    invitation_token: str | None = None


class Connexion(BaseModel):
    identifier: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=128)


class Renouvellement(BaseModel):
    refresh_token: str


class Oubli(BaseModel):
    identifier: str


class Reinit(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/register", status_code=201)
def register(body: Inscription, request: Request, db: Session = Depends(get_db)):
    verifier_limite(request, body.identifier)
    ident = normaliser_identifiant(body.identifier)
    if "@" not in ident and not ident.startswith("+"):
        noter_echec(request, body.identifier)
        raise validation(champ("identifier", "invalid_format", "Adresse e-mail ou numéro de téléphone attendu."))
    if db.scalar(select(User).where(User.identifier == ident)):
        noter_echec(request, body.identifier)
        raise ApiError("ACCOUNT_ALREADY_EXISTS", 409, "Un compte existe déjà avec cet identifiant.")
    user = User(full_name=body.full_name.strip(), identifier=ident, password_hash=hacher(body.password))
    db.add(user)
    db.flush()
    # Invitations en attente : par jeton explicite, ou par identifiant (CU1-A3)
    q = select(Member).where(Member.status == "pending", Member.identifier == ident)
    if body.invitation_token:
        q = select(Member).where(Member.status == "pending", Member.invitation_token == body.invitation_token)
    for m in db.scalars(q):
        if m.invitation_expires_at and m.invitation_expires_at < maintenant():
            continue
        m.user_id, m.status, m.invitation_token = user.id, "active", None
    return reponse_jetons(db, user)


@router.post("/auth/login")
def login(body: Connexion, request: Request, db: Session = Depends(get_db)):
    verifier_limite(request, body.identifier)
    user = db.scalar(select(User).where(User.identifier == normaliser_identifiant(body.identifier)))
    if user is None or not verifier(body.password, user.password_hash):
        noter_echec(request, body.identifier)
        raise ApiError("INVALID_CREDENTIALS", 401, "Identifiant ou mot de passe incorrect.")
    effacer_echecs(request, body.identifier)
    return reponse_jetons(db, user)


@router.post("/auth/refresh")
def refresh(body: Renouvellement, db: Session = Depends(get_db)):
    rt = db.get(RefreshToken, body.refresh_token)
    if rt is None or rt.revoked:
        raise ApiError("TOKEN_INVALID", 401, "Jeton d'accès absent ou invalide.")
    if rt.expires_at < maintenant():
        raise ApiError("TOKEN_EXPIRED", 401, "Votre session a expiré. Veuillez vous reconnecter.")
    return {"access_token": jeton_acces(rt.user_id), "token_type": "bearer",
            "expires_in": config.ACCESS_TOKEN_MINUTES * 60}


@router.post("/auth/logout", status_code=204)
def logout(body: Renouvellement, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rt = db.get(RefreshToken, body.refresh_token)
    if rt and rt.user_id == user.id:
        rt.revoked = True
    return Response(status_code=204)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "full_name": user.full_name, "identifier": user.identifier, "language": user.language}


@router.post("/auth/forgot-password", status_code=204)
def forgot(body: Oubli, request: Request, db: Session = Depends(get_db)):
    """Priorité C : sans service d'envoi, le lien est écrit dans les journaux du serveur."""
    verifier_limite(request, body.identifier)
    user = db.scalar(select(User).where(User.identifier == normaliser_identifiant(body.identifier)))
    if user:
        tok = "rst_" + secrets.token_urlsafe(24)
        db.add(ResetToken(token=tok, user_id=user.id, expires_at=maintenant() + dt.timedelta(hours=1)))
        log.info("Lien de réinitialisation pour %s : %s/reset?token=%s", user.identifier, config.PUBLIC_URL, tok)
    else:
        noter_echec(request, body.identifier)
    return Response(status_code=204)          # même réponse que le compte existe ou non


@router.post("/auth/reset-password", status_code=204)
def reset(body: Reinit, db: Session = Depends(get_db)):
    t = db.get(ResetToken, body.token)
    if t is None or t.used or t.expires_at < maintenant():
        raise ApiError("TOKEN_INVALID", 401, "Jeton d'accès absent ou invalide.")
    user = db.get(User, t.user_id)
    user.password_hash = hacher(body.new_password)
    t.used = True
    for rt in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)):
        rt.revoked = True
    return Response(status_code=204)
