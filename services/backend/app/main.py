"""Backend public AgroRot : implémente le contrat d'API v2 (/api/v1).
Gère utilisateurs, fermes, parcelles, saisies et sauvegardes ; délègue les données à data-service
et le calcul à agrorot-core."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.db import session
from app.errors import install_error_handlers
from app.routers import (
    auth,
    climate,
    farms,
    health,
    inputs,
    members,
    monitoring,
    parcels,
    referentiel,
    saved,
    strategies,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def cycle_de_vie(_app):
    probleme = config.verifier_secret()
    if probleme:
        raise RuntimeError(probleme)          # refuse de démarrer en production avec un secret faible
    if config.JWT_SECRET in config.SECRETS_FAIBLES:
        logging.getLogger("agrorot").warning("JWT_SECRET de développement : à changer avant la mise en ligne.")
    session.init()
    tache = asyncio.create_task(_tournee()) if config.MONITORING_INTERVAL_HOURS > 0 else None
    yield
    if tache:
        tache.cancel()


async def _tournee():
    """T65 : vérifie toutes les rotations choisies, au démarrage (+1 min) puis toutes les N heures."""
    await asyncio.sleep(60)
    while True:
        try:
            n = await asyncio.to_thread(monitoring.tout_surveiller)
            logging.getLogger("agrorot.surveillance").info("tournée de surveillance : %d rotation(s)", n)
        except Exception:  # noqa: BLE001
            logging.getLogger("agrorot.surveillance").exception("tournée de surveillance en échec")
        await asyncio.sleep(config.MONITORING_INTERVAL_HOURS * 3600)


app = FastAPI(title="AgroRot API", version="2.0.0", lifespan=cycle_de_vie)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID", "Retry-After"])
install_error_handlers(app)
for r in (auth, referentiel, farms, members, parcels, climate, inputs, strategies, saved, monitoring, health):
    app.include_router(r.router, prefix="/api/v1")

