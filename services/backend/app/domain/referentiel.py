"""T46 - Référentiel (régions, cultures, bioagresseurs) lu dans agrorot-core, gardé 10 minutes en mémoire."""
import time

from app.clients import core

_CACHE: dict = {}
DUREE_S = 600
SPECIAUX = {"jachere", "autre"}


def _lire(cle, fonction):
    v = _CACHE.get(cle)
    if v and time.time() - v[0] < DUREE_S:
        return v[1]
    r = fonction()
    _CACHE[cle] = (time.time(), r)
    return r


def regions() -> dict:
    return _lire("regions", core.regions)


def crops(region: str) -> dict:
    return _lire(("crops", region), lambda: core.crops(region))


def ids_cultures(region: str) -> set[str]:
    return {c["id"] for c in crops(region)["crops"]}


def ids_bioagresseurs() -> set[str]:
    return {p["id"] for p in _lire("pests", lambda: core._envoyer("GET", "/v1/pests"))["pests"]}


def vider():
    _CACHE.clear()
