"""data-service : récupère, met en cache et prépare les données externes (NASA POWER, SRTM, SMAP,
NDVI, Meteomatics). Gère le Plan B du contrat : live -> fallback_cache -> fallback_local."""
from fastapi import FastAPI

from app.errors import install_error_handlers
from app.routers import climate, forecast, terrain

app = FastAPI(title="data-service", version="0.2.0")
install_error_handlers(app)
app.include_router(climate.router, prefix="/v1")
app.include_router(terrain.router, prefix="/v1")
app.include_router(forecast.router, prefix="/v1")


@app.get("/health")
def health():
    from app.sources import nasa_power
    return {"status": "ok", "nasa_power": nasa_power.ping()}
