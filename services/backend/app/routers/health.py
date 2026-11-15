"""T52 - Santé (§12) : état de la base, du moteur, de NASA POWER (vu par le data-service) et du cache."""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients import core, data
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        base = "ok"
    except Exception:
        base = "error"
    service, power = data.sante()
    comps = {"database": base, "engine": core.sante(), "nasa_power": power if service == "ok" else "unknown",
             "cache": service}
    status = "ok" if all(v == "ok" for v in comps.values()) else "degraded"
    return {"status": status, "components": comps,
            "time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
