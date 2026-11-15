"""T50 - Diagnostic NASA (§8) : relais du data-service, corrections de l'agriculteur appliquées."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.clients import data
from app.db.models import User
from app.db.session import get_db
from app.routers.inputs import lire_donnees
from app.security import current_user, parcelle

router = APIRouter(tags=["climate"])


@router.get("/parcels/{parcel_id}/climate")
def diagnostic(parcel_id: str, year: int | None = None, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    p, _ = parcelle(db, parcel_id, user)
    d = data.diagnostic(p.lat, p.lon, year)
    loc = lire_donnees(db, p.id, "local_inputs")
    for c in (loc.data.get("nasa_overrides", []) if loc else []):
        for m in d["monthly_series"]:
            if m["month"] != c["month"]:
                continue
            if c["field"] == "rain_mm" and m["rain_mm"] is not None:
                m["rain_mm"] = round(m["rain_mm"] * (1 + c["value"] / 100), 1)
                if m["evapotranspiration_mm"] is not None:
                    m["water_balance_mm"] = round(m["rain_mm"] - m["evapotranspiration_mm"], 1)
            elif c["field"] == "temp_avg_c" and m["temp_avg_c"] is not None:
                m["temp_avg_c"] = round(m["temp_avg_c"] + c["value"], 1)
            m["corrected_by_user"] = True
    d.pop("parcel_point", None)
    return {"parcel_id": p.id, **d}
