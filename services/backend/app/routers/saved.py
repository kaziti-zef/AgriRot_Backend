"""T51 + T52 - Sauvegarde, historique, notes et export PDF (§11)."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db.models import Computation, Note, SavedStrategy, User, maintenant
from app.db.session import get_db
from app.domain import pdf
from app.errors import ApiError
from app.security import EXPLOITANTS, current_user, exiger, parcelle

router = APIRouter(tags=["saved"])


class Sauvegarde(BaseModel):
    computation_id: str
    strategy_id: Literal["existing", "recommended", "alternative"]
    note: str | None = Field(None, max_length=1000)
    monitor: bool = True                   # ajout T65 : surveiller cette rotation (désactive les autres)


class NouvelleNote(BaseModel):
    kind: Literal["observation", "validation"]
    text: str = Field(min_length=1, max_length=1000)


def _iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _introuvable():
    return ApiError("STRATEGY_NOT_FOUND", 404, "Stratégie introuvable ou périmée. Relancez le calcul.")


def _vue_note(db: Session, n: Note) -> dict:
    u = db.get(User, n.author_id)
    return {"note_id": n.id, "kind": n.kind, "text": n.text,
            "author": {"id": u.id, "full_name": u.full_name, "role": n.author_role}, "created_at": _iso(n.created_at)}


def _saved(db: Session, parcel_id: str, saved_id: str) -> SavedStrategy:
    s = db.get(SavedStrategy, saved_id)
    if s is None or s.parcel_id != parcel_id:
        raise _introuvable()
    return s


@router.post("/parcels/{parcel_id}/strategies/save", status_code=201)
def retenir(parcel_id: str, body: Sauvegarde, taches: BackgroundTasks, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    p, m = parcelle(db, parcel_id, user, *EXPLOITANTS)
    c = db.get(Computation, body.computation_id)
    limite = maintenant() - dt.timedelta(hours=config.COMPUTATION_TTL_HOURS)
    if c is None or c.parcel_id != p.id or c.created_at < limite:
        raise _introuvable()
    strat = next((s for s in c.result["strategies"] if s["id"] == body.strategy_id), None)
    if strat is None:
        raise _introuvable()
    instant = {**strat, "computation_id": c.id, "computed_at": c.result["computed_at"],
               "applied_scenario": c.result["applied_scenario"], "manual_overrides": c.request.get("manual_overrides", {}),
               "data_source_status": c.result["data_source_status"], "disclaimer": c.result["disclaimer"],
               "saved_by": user.full_name}
    s = SavedStrategy(parcel_id=p.id, strategy_id=body.strategy_id, snapshot=instant, saved_by=user.id,
                      saved_role=m.role, geometry_version=c.geometry_version)
    db.add(s)
    db.flush()
    s.snapshot = {**instant, "saved_at": _iso(s.saved_at)}
    if body.note:
        db.add(Note(saved_id=s.id, author_id=user.id, author_role=m.role, kind="observation", text=body.note))
    if body.monitor:                       # T65 : la rotation choisie devient la rotation surveillée
        from app.routers.monitoring import activer, premiere_verification
        activer(db, s, True)
        db.commit()
        taches.add_task(premiere_verification, s.id)
    return {"saved_id": s.id, "parcel_id": p.id, "strategy_id": s.strategy_id, "saved_at": _iso(s.saved_at),
            "saved_by": {"id": user.id, "full_name": user.full_name, "role": m.role},
            "pdf_export_url": f"/api/v1/parcels/{p.id}/strategies/saved/{s.id}/export.pdf",
            "monitoring_active": s.monitoring_active}


@router.get("/parcels/{parcel_id}/strategies/saved")
def historique(parcel_id: str, limit: int = Query(20, ge=1, le=100), cursor: str | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    tout = db.scalars(select(SavedStrategy).where(SavedStrategy.parcel_id == p.id)
                      .order_by(SavedStrategy.saved_at.desc(), SavedStrategy.id)).all()
    debut = int(cursor) if cursor and cursor.isdigit() else 0
    out = []
    for s in tout[debut:debut + limit]:
        n = db.scalar(select(func.count()).select_from(Note).where(Note.saved_id == s.id))
        out.append({"saved_id": s.id, "strategy_id": s.strategy_id, "name": s.snapshot["name"],
                    "score": s.snapshot["score"], "saved_at": _iso(s.saved_at), "saved_by": s.snapshot["saved_by"],
                    "notes_count": n, "outdated_geometry": s.geometry_version != p.geometry_version})
    return {"saved": out, "next_cursor": str(debut + limit) if debut + limit < len(tout) else None}


@router.get("/parcels/{parcel_id}/strategies/saved/{saved_id}")
def detail(parcel_id: str, saved_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    s = _saved(db, p.id, saved_id)
    notes = db.scalars(select(Note).where(Note.saved_id == s.id).order_by(Note.created_at)).all()
    return {"saved_id": s.id, "parcel_id": p.id, **s.snapshot,
            "outdated_geometry": s.geometry_version != p.geometry_version,
            "notes": [_vue_note(db, n) for n in notes]}


@router.post("/parcels/{parcel_id}/strategies/saved/{saved_id}/notes", status_code=201)
def noter(parcel_id: str, saved_id: str, body: NouvelleNote, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    p, m = parcelle(db, parcel_id, user)
    s = _saved(db, p.id, saved_id)
    exiger(m, *(EXPLOITANTS if body.kind == "observation" else ("advisor",)))
    n = Note(saved_id=s.id, author_id=user.id, author_role=m.role, kind=body.kind, text=body.text.strip())
    db.add(n)
    db.flush()
    return _vue_note(db, n)


@router.delete("/parcels/{parcel_id}/strategies/saved/{saved_id}/notes/{note_id}", status_code=204)
def effacer_note(parcel_id: str, saved_id: str, note_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    p, m = parcelle(db, parcel_id, user)
    _saved(db, p.id, saved_id)
    n = db.get(Note, note_id)
    if n is None or n.saved_id != saved_id:
        raise _introuvable()
    if n.author_id != user.id and m.role != "owner":
        raise ApiError("FORBIDDEN_ROLE", 403, "Votre rôle ne permet pas cette action.",
                       {"required_roles": ["owner"], "your_role": m.role})
    db.delete(n)
    return Response(status_code=204)


@router.get("/parcels/{parcel_id}/strategies/saved/{saved_id}/export.pdf")
def export_pdf(parcel_id: str, saved_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    s = _saved(db, p.id, saved_id)
    notes = [_vue_note(db, n) for n in db.scalars(select(Note).where(Note.saved_id == s.id).order_by(Note.created_at))]
    contenu = pdf.generer(s.snapshot, {"name": p.name, "area_ha": p.area_ha}, notes)
    return Response(contenu, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="agrorot_{p.id}_{s.id}.pdf"'})
