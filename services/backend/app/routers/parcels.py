"""T44 - Parcelles (§7)."""
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import data
from app.db.models import Parcel, ParcelData, SavedStrategy, User
from app.db.session import get_db
from app.domain import geometrie as G
from app.errors import ApiError
from app.i18n import avertissements, langue
from app.security import (
    EXPLOITANTS,
    current_user,
    exiger,
    membre,
    parcelle,
    verifier_version,
)

router = APIRouter(tags=["parcels"])


class NouvelleParcelle(BaseModel):
    farm_id: str
    name: str = Field(min_length=1, max_length=120)
    geometry: dict


class ModifParcelle(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    geometry: dict | None = None


def completude(db: Session, p: Parcel) -> dict:
    kinds = {d.kind for d in db.scalars(select(ParcelData).where(ParcelData.parcel_id == p.id))}
    return {"local_inputs": "local_inputs" in kinds, "history": "history" in kinds, "preferences": "preferences" in kinds}


def vue(db: Session, p: Parcel, warnings=None) -> dict:
    return {"id": p.id, "farm_id": p.farm_id, "name": p.name, "area_ha": p.area_ha,
            "centroid": {"lat": p.lat, "lon": p.lon},
            "srtm": {"elevation_m": p.elevation_m, "slope_deg": p.slope_deg},
            "geometry": p.geometry, "data_completeness": completude(db, p), "version": p.version,
            "warnings": warnings or []}


def _terrain(lat, lon) -> tuple[float | None, float | None, list]:
    try:
        t = data.terrain(lat, lon)
        return t.get("elevation_m"), t.get("slope_deg"), t.get("warnings", [])
    except ApiError:
        return None, None, [{"code": "SRTM_UNAVAILABLE",
                             "message": "Altitude et pente indisponibles ; renseignez la pente à la main."}]


def _controles(db: Session, farm_id: str, name: str, proj, centre, sauf: str | None = None):
    autres = db.scalars(select(Parcel).where(Parcel.farm_id == farm_id, Parcel.id != (sauf or ""))).all()
    if any(o.name.strip().lower() == name.strip().lower() for o in autres):
        raise ApiError("PARCEL_NAME_TAKEN", 409, "Une parcelle porte déjà ce nom dans la ferme.")
    if proj is not None and G.chevauche(proj, [o.geometry for o in autres], centre):
        raise ApiError("PARCEL_OVERLAP", 409, "Cette parcelle chevauche une parcelle existante de la ferme.")


@router.post("/parcels", status_code=201)
def creer(body: NouvelleParcelle, taches: BackgroundTasks, request: Request, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    exiger(membre(db, body.farm_id, user), *EXPLOITANTS)
    geo, _, proj, ha, (lat, lon) = G.valider(body.geometry)
    _controles(db, body.farm_id, body.name, proj, (lat, lon))
    alt, pente, warnings = _terrain(lat, lon)
    p = Parcel(farm_id=body.farm_id, name=body.name.strip(), geometry=geo, area_ha=ha, lat=lat, lon=lon,
               elevation_m=alt, slope_deg=pente)
    db.add(p)
    db.commit()            # valider AVANT le préchargement : sinon la parcelle reste invisible jusqu'à sa fin
    taches.add_task(data.prefetch, lat, lon)          # 30 ans de POWER mis en cache en arrière-plan
    return vue(db, p, avertissements(warnings, langue(request)))


@router.get("/farms/{farm_id}/parcels")
def lister(farm_id: str, limit: int = Query(20, ge=1, le=100), cursor: str | None = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    membre(db, farm_id, user)
    ps = db.scalars(select(Parcel).where(Parcel.farm_id == farm_id).order_by(Parcel.created_at, Parcel.id)).all()
    debut = int(cursor) if cursor and cursor.isdigit() else 0
    page = ps[debut:debut + limit]
    out = []
    for p in page:
        s = db.scalars(select(SavedStrategy).where(SavedStrategy.parcel_id == p.id)
                       .order_by(SavedStrategy.saved_at.desc())).first()
        out.append({"id": p.id, "name": p.name, "area_ha": p.area_ha, "centroid": {"lat": p.lat, "lon": p.lon},
                    "geometry": p.geometry, "data_completeness": completude(db, p),
                    "last_saved_strategy": None if s is None else {
                        "saved_id": s.id, "type": s.strategy_id, "score": s.snapshot.get("score"),
                        "saved_at": s.saved_at.strftime("%Y-%m-%dT%H:%M:%SZ")}})
    suivant = str(debut + limit) if debut + limit < len(ps) else None
    return {"parcels": out, "next_cursor": suivant}


@router.get("/parcels/{parcel_id}")
def lire(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    return vue(db, p)


@router.patch("/parcels/{parcel_id}")
def modifier(parcel_id: str, body: ModifParcelle, request: Request, if_match: str | None = Header(None),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, *EXPLOITANTS)
    verifier_version(p.version, if_match)
    warnings = []
    nom = body.name.strip() if body.name else p.name
    if body.geometry:
        geo, _, proj, ha, centre = G.valider(body.geometry)
        _controles(db, p.farm_id, nom, proj, centre, sauf=p.id)
        if G.distance_km((p.lat, p.lon), centre) > 5:
            warnings.append({"code": "CENTROID_MOVED", "message": "Le centre de la parcelle s'est déplacé de plus "
                             "de 5 km : vérifiez le diagnostic climatique."})
        alt, pente, w = _terrain(*centre)
        warnings += w
        p.geometry, p.area_ha, (p.lat, p.lon) = geo, ha, centre
        p.elevation_m, p.slope_deg = alt, pente
        p.geometry_version += 1                     # les stratégies sauvegardées deviennent « outdated »
    elif body.name:
        _controles(db, p.farm_id, nom, None, None, sauf=p.id)
    p.name = nom
    p.version += 1
    return vue(db, p, avertissements(warnings, langue(request)))


@router.delete("/parcels/{parcel_id}", status_code=204)
def supprimer(parcel_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user, "owner")
    db.delete(p)
    return Response(status_code=204)
