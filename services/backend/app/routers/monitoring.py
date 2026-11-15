"""T65 - Surveillance de la rotation choisie et notifications (ajout au contrat v2)."""
import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.clients import core, data
from app.db import session as base
from app.db.models import Member, Notification, Parcel, SavedStrategy, User, maintenant
from app.db.session import get_db
from app.domain import contexte, referentiel
from app.domain import surveillance as S
from app.errors import ApiError
from app.security import EXPLOITANTS, TOUS, current_user, parcelle

router = APIRouter(tags=["monitoring"])
log = logging.getLogger("agrorot.surveillance")
ANTI_DOUBLON_JOURS = 7


def _iso(d: dt.datetime | None) -> str | None:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


# ------------------------------------------------------------------------------------------- moteur
def _reevaluer(db: Session, p: Parcel, s: SavedStrategy, scen: dict, pos: dict) -> dict | None:
    """Note de la rotation sauvegardée avec le climat normal, puis « si la saison continue ainsi »."""
    seq = s.snapshot["sequence"]
    try:
        ctx, _, _ = contexte.construire(db, p, None, None)
        annee, code = str(seq[0]["label"]).split("-")
        ctx["premiere_annee"], ctx["premiere_saison"] = int(annee), code
        etapes = [{"season": e["season"], "crop_id": e["crop_id"]} for e in seq]
        base_ = core.evaluate({"contexte": ctx, "sequence": etapes})["strategy"]
        sim = core.evaluate({"contexte": ctx, "sequence": etapes, "scenario": scen})["strategy"]
    except ApiError as e:
        log.warning("réévaluation impossible pour %s : %s", s.id, e.code)
        return None
    cible = pos["current"] or pos["sowing"] or pos["next"]
    note_cible = next((e["season_score"] for e in sim["sequence"] if cible and e["season"] == cible["season"]), None)
    return {"scenario": scen, "score_normal": base_["score"], "score_if_season_continues": sim["score"],
            "drop": round(base_["score"] - sim["score"], 1), "target_season": cible and cible["season"],
            "target_season_score": note_cible}


# ------------------------------------------------------------------------------------------- exécution
def executer(db: Session, s: SavedStrategy, jour: dt.date | None = None) -> dict:
    """Une vérification : calcule l'état, l'enregistre et crée les notifications nouvelles."""
    simule = jour is not None
    jour = jour or dt.date.today()
    p = db.get(Parcel, s.parcel_id)
    region = contexte_region(db, p)
    cultures = {c["id"]: c for c in referentiel.crops(region)["crops"]}
    etapes = S.calendrier(s.snapshot["sequence"])
    pos = S.position(etapes, jour)
    prev = data.previsions(p.lat, p.lon)
    if simule:
        prev = S.recaler(prev, jour)
    ind = S.indicateurs(prev, jour)
    alertes: list[S.Alerte] = []
    evaluation = None
    if ind is not None and pos["phase"] != "finished":
        loc = contexte.lire_donnees(db, p.id, "local_inputs")
        irrigue = bool(loc and loc.data.get("water", {}).get("has_irrigation"))
        pente = (loc.data.get("soil", {}).get("slope_deg") if loc else None) or p.slope_deg
        alertes = S.regles(pos, ind, cultures, irrigue, pente, s.id, jour)
        scen = S.scenario_observe(ind)
        if scen and pos["phase"] in ("in_crop", "sowing_window", "between_crops"):
            evaluation = _reevaluer(db, p, s, scen, pos)
            sec = scen["rain_delta_pct"] < 0
            if evaluation:
                mauvais = evaluation["drop"] >= S.BAISSE_CRITIQUE or (
                    evaluation["target_season_score"] is not None and evaluation["target_season_score"] < S.NOTE_CRITIQUE)
                txt = (f"Pluie des 30 derniers jours : {S.fr(ind['rain_last_30d_mm'])} mm pour {S.fr(ind['rain_normal_30d_mm'])} mm "
                       f"en temps normal. Si la saison continue ainsi, la note de votre rotation passe de "
                       f"{S.fr(evaluation['score_normal'])} à {S.fr(evaluation['score_if_season_continues'])}.")
                if mauvais:
                    alertes.append(S.Alerte("ROTATION_MISMATCH", "critical", "Votre rotation n'est plus bien adaptée", txt,
                                            ["Relancer le calcul des stratégies avec le scénario proposé.",
                                             "Comparer avec l'alternative avant de semer."],
                                            {"suggested_scenario": scen, **evaluation},
                                            f"{s.id}:ROTATION_MISMATCH:{jour.isocalendar()[0]}W{jour.isocalendar()[1]:02d}"))
                else:
                    alertes.append(S.Alerte("SEASON_ANOMALY", "info",
                                            "Saison plus sèche que la normale" if sec else "Saison plus humide que la normale",
                                            txt + " La rotation reste adaptée.", [], {"suggested_scenario": scen, **evaluation},
                                            f"{s.id}:SEASON_ANOMALY:{jour.isocalendar()[0]}W{jour.isocalendar()[1]:02d}"))
    etat = {
        "checked_at": _iso(maintenant()), "reference_date": jour.isoformat(), "simulated_date": simule,
        "weather": {"source": prev.get("source"), "status": prev.get("status"), "generated_at": prev.get("generated_at"),
                    **({k: v for k, v in ind.items() if not k.startswith("_")} if ind else {})},
        "position": {k: v for k, v in pos.items() if not k.startswith("_")},
        "alerts": [a.vue() for a in alertes], "evaluation": evaluation,
    }
    s.monitoring_state = etat
    _notifier(db, p, s, alertes, simule)
    return etat


def contexte_region(db: Session, p: Parcel) -> str:
    from app.db.models import Farm
    return db.get(Farm, p.farm_id).region


def _notifier(db: Session, p: Parcel, s: SavedStrategy, alertes: list[S.Alerte], simule: bool):
    if not alertes:
        return
    membres = db.scalars(select(Member).where(Member.farm_id == p.farm_id, Member.status == "active",
                                              Member.user_id.is_not(None))).all()
    depuis = maintenant() - dt.timedelta(days=ANTI_DOUBLON_JOURS)
    for a in alertes:
        for m in membres:
            deja = db.scalar(select(Notification.id).where(Notification.user_id == m.user_id,
                                                           Notification.dedup_key == a.cle,
                                                           Notification.created_at >= depuis))
            if deja:
                continue
            db.add(Notification(user_id=m.user_id, farm_id=p.farm_id, parcel_id=p.id, saved_id=s.id, code=a.code,
                                severity=a.severity, title=a.title, message=a.message,
                                data={**a.data, "advice": a.advice, "parcel_name": p.name, "simulated_date": simule},
                                dedup_key=a.cle))


def tout_surveiller() -> int:
    """Tâche périodique : toutes les rotations actives. Une erreur sur une parcelle n'arrête pas les autres."""
    if base.SessionLocal is None:
        base.init()
    n = 0
    with base.SessionLocal() as db:
        ids = db.scalars(select(SavedStrategy.id).where(SavedStrategy.monitoring_active.is_(True))).all()
    for sid in ids:
        with base.SessionLocal() as db:
            try:
                executer(db, db.get(SavedStrategy, sid))
                db.commit()
                n += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("surveillance de %s en échec", sid)
    return n


def premiere_verification(saved_id: str):
    """Après une sauvegarde : premier état sans attendre la prochaine tournée (tâche de fond)."""
    if base.SessionLocal is None:
        base.init()
    with base.SessionLocal() as db:
        try:
            s = db.get(SavedStrategy, saved_id)
            if s is not None and s.monitoring_active:
                executer(db, s)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("première vérification de %s en échec", saved_id)


def activer(db: Session, s: SavedStrategy, actif: bool):
    if actif:
        db.execute(update(SavedStrategy).where(SavedStrategy.parcel_id == s.parcel_id, SavedStrategy.id != s.id)
                   .values(monitoring_active=False))
    s.monitoring_active = actif


# ------------------------------------------------------------------------------------------- routes
class Activation(BaseModel):
    active: bool


def _vue_etat(s: SavedStrategy | None) -> dict:
    if s is None:
        return {"saved_id": None, "active": False, "strategy_name": None, "state": None}
    return {"saved_id": s.id, "active": s.monitoring_active, "strategy_name": s.snapshot.get("name"),
            "state": s.monitoring_state}


def _active(db: Session, parcel_id: str) -> SavedStrategy | None:
    return db.scalar(select(SavedStrategy).where(SavedStrategy.parcel_id == parcel_id,
                                                 SavedStrategy.monitoring_active.is_(True)))


@router.put("/parcels/{parcel_id}/strategies/saved/{saved_id}/monitoring")
def basculer(parcel_id: str, saved_id: str, body: Activation, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    """Choisit la rotation surveillée (une seule par parcelle) ou arrête la surveillance."""
    p, _ = parcelle(db, parcel_id, user, *EXPLOITANTS)
    s = db.get(SavedStrategy, saved_id)
    if s is None or s.parcel_id != p.id:
        raise ApiError("STRATEGY_NOT_FOUND", 404, "Stratégie introuvable ou périmée. Relancez le calcul.")
    activer(db, s, body.active)
    return _vue_etat(s)


@router.get("/parcels/{parcel_id}/monitoring")
def etat(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *TOUS)
    return _vue_etat(_active(db, p.id))


@router.post("/parcels/{parcel_id}/monitoring/run")
def verifier(parcel_id: str, date: dt.date | None = Query(None, description="Date simulée (démo)"),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Vérifie maintenant (sans attendre la tournée quotidienne). `date` permet de simuler un autre jour."""
    p, _ = parcelle(db, parcel_id, user, *TOUS)
    s = _active(db, p.id)
    if s is None:
        raise ApiError("PRECONDITION_FAILED", 412, "Aucune rotation choisie pour cette parcelle : sauvegardez une stratégie.",
                       {"missing": ["monitored_strategy"]})
    executer(db, s, date)
    return _vue_etat(s)


def _vue_notif(n: Notification) -> dict:
    return {"id": n.id, "code": n.code, "severity": n.severity, "title": n.title, "message": n.message,
            "farm_id": n.farm_id, "parcel_id": n.parcel_id, "saved_id": n.saved_id, "data": n.data,
            "created_at": _iso(n.created_at), "read": n.read_at is not None}


@router.get("/notifications")
def lister(unread_only: bool = False, limit: int = Query(20, ge=1, le=100), cursor: str | None = None,
           severity: Literal["info", "warning", "critical"] | None = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    if severity:
        q = q.where(Notification.severity == severity)
    if cursor:
        c = db.get(Notification, cursor)
        if c is not None:
            q = q.where((Notification.created_at < c.created_at) |
                        ((Notification.created_at == c.created_at) & (Notification.id < c.id)))
    rows = db.scalars(q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)).all()
    return {"notifications": [_vue_notif(n) for n in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
            "unread_count": _non_lues(db, user)}


def _non_lues(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(Notification)
                     .where(Notification.user_id == user.id, Notification.read_at.is_(None)))


@router.get("/notifications/unread-count")
def compte(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"unread_count": _non_lues(db, user)}


@router.post("/notifications/{notification_id}/read", status_code=204)
def lue(notification_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise ApiError("NOT_FOUND", 404, "Ressource introuvable.")
    n.read_at = n.read_at or maintenant()
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204)
def toutes_lues(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
               .values(read_at=maintenant()))
    return Response(status_code=204)
