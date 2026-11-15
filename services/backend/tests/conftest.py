"""Tests de bout en bout du backend : agrorot-core et data-service tournent pour de vrai (uvicorn),
NASA POWER est simulé (POWER_SIMULE=1). La base est une SQLite temporaire."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

SERVICES = Path(__file__).resolve().parents[2]
_tmp = tempfile.mkdtemp(prefix="agrorot_test_")


def _port_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT_CORE, PORT_DATA = _port_libre(), _port_libre()
os.environ.update({"DATABASE_URL": f"sqlite:///{_tmp}/test.db", "CORE_SERVICE_URL": f"http://127.0.0.1:{PORT_CORE}",
                   "DATA_SERVICE_URL": f"http://127.0.0.1:{PORT_DATA}", "JWT_SECRET": "test-secret-de-32-caracteres-min",
                   "MONITORING_INTERVAL_HOURS": "0"})


def _lancer(dossier: str, port: int, env: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
                            cwd=SERVICES / dossier, env={**os.environ, **env},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="session", autouse=True)
def services():
    procs = [_lancer("agrorot-core", PORT_CORE, {}),
             _lancer("data-service", PORT_DATA, {"POWER_SIMULE": "1", "CACHE_DIR": f"{_tmp}/cache",
                                                 "PREVISION_SIMULEE": "sec"})]
    for port in (PORT_CORE, PORT_DATA):
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError(f"service sur le port {port} injoignable")
    yield
    for p in procs:
        p.terminate()


@pytest.fixture(scope="session")
def client(services):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
