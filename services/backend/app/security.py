"""T41 + T42 - Jetons, mots de passe, limitation des tentatives, droits par rôle (matrice §2)."""
import datetime as dt
import re
import secrets
import time
from collections import defaultdict, deque

import bcrypt
import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db.models import Farm, Member, Parcel, RefreshToken, User, maintenant
from app.db.session import get_db
from app.errors import ApiError

ALGO = "HS256"


# ------------------------------------------------------------------ identifiants et mots de passe
def normaliser_identifiant(v: str) -> str:
    """E-mail en minuscules ; téléphone camerounais ramené à +237XXXXXXXXX."""
    v = v.strip()
    if "@" in v:
        return v.lower()
    chiffres = re.sub(r"\D", "", v)
    if len(chiffres) == 9 and chiffres[0] in "62":
        return "+237" + chiffres
    if chiffres.startswith("237") and len(chiffres) == 12:
        return "+" + chiffres
    if chiffres.startswith("00237"):
        return "+" + chiffres[2:]
    return v


def hacher(mdp: str) -> str:
    return bcrypt.hashpw(mdp.encode(), bcrypt.gensalt()).decode()


def verifier(mdp: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(mdp.encode(), h.encode())
    except ValueError:
        return False


# ------------------------------------------------------------------ jetons
def jeton_acces(user_id: str) -> str:
    exp = int(time.time()) + config.ACCESS_TOKEN_MINUTES * 60
    return jwt.encode({"sub": user_id, "exp": exp, "typ": "access"}, config.JWT_SECRET, algorithm=ALGO)


def jeton_renouvellement(db: Session, user_id: str) -> str:
    tok = "rt_" + secrets.token_urlsafe(32)
    db.add(RefreshToken(token=tok, user_id=user_id,
                        expires_at=maintenant() + dt.timedelta(days=config.REFRESH_TOKEN_DAYS)))
    return tok


def reponse_jetons(db: Session, user: User) -> dict:
    return {"access_token": jeton_acces(user.id), "refresh_token": jeton_renouvellement(db, user.id),
            "token_type": "bearer", "expires_in": config.ACCESS_TOKEN_MINUTES * 60,
            "user": {"id": user.id, "full_name": user.full_name, "identifier": user.identifier}}


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError("TOKEN_INVALID", 401, "Jeton d'accès absent ou invalide.")
    try:
        data = jwt.decode(authorization.split(" ", 1)[1], config.JWT_SECRET, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise ApiError("TOKEN_EXPIRED", 401, "Votre session a expiré. Veuillez vous reconnecter.")
    except jwt.InvalidTokenError:
        raise ApiError("TOKEN_INVALID", 401, "Jeton d'accès absent ou invalide.")
    user = db.get(User, data.get("sub"))
    if user is None or data.get("typ") != "access":
        raise ApiError("TOKEN_INVALID", 401, "Jeton d'accès absent ou invalide.")
    return user


# ------------------------------------------------------------------ limitation (§1 : 5 échecs en 15 min)
_ECHECS: dict[str, deque] = defaultdict(deque)
FENETRE_S, MAX_ECHECS = 15 * 60, 5


def _cle_limite(request: Request, identifiant: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"{normaliser_identifiant(identifiant)}|{ip}"


def verifier_limite(request: Request, identifiant: str):
    q = _ECHECS[_cle_limite(request, identifiant)]
    now = time.time()
    while q and now - q[0] > FENETRE_S:
        q.popleft()
    if len(q) >= MAX_ECHECS:
        attente = int(FENETRE_S - (now - q[0])) + 1
        raise ApiError("TOO_MANY_REQUESTS", 429, "Trop de tentatives. Réessayez dans quelques minutes.",
                       {"retry_after_seconds": attente}, headers={"Retry-After": str(attente)})


def noter_echec(request: Request, identifiant: str):
    _ECHECS[_cle_limite(request, identifiant)].append(time.time())


def effacer_echecs(request: Request, identifiant: str):
    _ECHECS.pop(_cle_limite(request, identifiant), None)


# ------------------------------------------------------------------ droits (§2)
def membre(db: Session, farm_id: str, user: User) -> Member:
    if db.get(Farm, farm_id) is None:
        raise ApiError("FARM_NOT_FOUND", 404, "Ferme introuvable.")
    m = db.scalar(select(Member).where(Member.farm_id == farm_id, Member.user_id == user.id,
                                       Member.status == "active"))
    if m is None:
        raise ApiError("NOT_FARM_MEMBER", 403, "Vous n'avez pas accès à cette ferme.")
    return m


def exiger(m: Member, *roles: str) -> Member:
    if m.role not in roles:
        raise ApiError("FORBIDDEN_ROLE", 403, "Votre rôle ne permet pas cette action.",
                       {"required_roles": list(roles), "your_role": m.role})
    return m


def parcelle(db: Session, parcel_id: str, user: User, *roles: str) -> tuple[Parcel, Member]:
    p = db.get(Parcel, parcel_id)
    if p is None:
        raise ApiError("PARCEL_NOT_FOUND", 404, "Parcelle introuvable.")
    m = membre(db, p.farm_id, user)
    if roles:
        exiger(m, *roles)
    return p, m


TOUS = ("owner", "co_farmer", "advisor")
EXPLOITANTS = ("owner", "co_farmer")


# ------------------------------------------------------------------ contrôle de version (§1)
def verifier_version(version_courante: int, if_match: str | None):
    if if_match is None:
        return
    try:
        v = int(if_match.strip('"W/ '))
    except ValueError:
        raise ApiError("INVALID_REQUEST", 400, "La requête est mal formée.", {"header": "If-Match"})
    if v != version_courante:
        raise ApiError("VERSION_CONFLICT", 409, "Cette donnée a été modifiée par une autre personne. "
                       "Rechargez avant de modifier.", {"current_version": version_courante, "your_version": v})
