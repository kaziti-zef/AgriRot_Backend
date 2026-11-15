import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import scenario as sc
from app.engine.precalcul import construire
from app.engine.temps import calendrier_contexte
from app.main import app
from app.schemas import Contexte, EtapeRotation

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def ctx_dict() -> dict:
    return json.loads((FIX / "contexte_demo.json").read_text())


@pytest.fixture
def ctx(ctx_dict) -> Contexte:
    return Contexte(**ctx_dict)


@pytest.fixture
def pc(ctx):
    cl = sc.depuis_site(ctx.climat)
    return construire(ctx, cl, calendrier_contexte(ctx))


@pytest.fixture
def client():
    return TestClient(app)


def seq(*crops):
    return [EtapeRotation(season=i, crop_id=c) for i, c in enumerate(crops, start=1)]
