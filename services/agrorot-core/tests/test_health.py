from fastapi.testclient import TestClient
from app.main import app


def test_health_et_referentiel():
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/v1/crops", params={"region": "cm_yaounde"}).json()
    assert any(x["id"] == "niebe" for x in r["crops"])
    assert c.get("/v1/crops", params={"region": "xx"}).json()["error"]["code"] == "REGION_NOT_SUPPORTED"
