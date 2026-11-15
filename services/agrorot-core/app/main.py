"""agrorot-core : moteur d'évaluation et de proposition de rotations. Service interne, SANS ÉTAT.
Il ne connaît ni utilisateurs ni fermes : il reçoit un contexte complet et rend des stratégies."""
from fastapi import FastAPI
from app.errors import install_error_handlers
from app.routers import referentiel, evaluation, strategies

app = FastAPI(title="agrorot-core", version="0.1.0")
install_error_handlers(app)
app.include_router(referentiel.router, prefix="/v1")
app.include_router(evaluation.router, prefix="/v1")
app.include_router(strategies.router, prefix="/v1")


@app.get("/health")
def health():
    from app.referentiel.loader import REF
    return {"status": "ok", "crops": len(REF.cultures), "pests": len(REF.bioagresseurs)}
