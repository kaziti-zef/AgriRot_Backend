"""Paramètres du scoring, correspondances et calendriers régionaux (chargés une fois)."""
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def P() -> dict:
    return yaml.safe_load((ROOT / "config" / "parametres.yaml").read_text(encoding="utf-8"))


@lru_cache
def correspondances() -> dict:
    return yaml.safe_load((ROOT / "data" / "correspondances.yaml").read_text(encoding="utf-8"))


@lru_cache
def calendrier(region: str) -> dict:
    f = ROOT / "data" / f"calendrier_{region}.yaml"
    if not f.exists():
        from app.errors import ApiError
        raise ApiError("REGION_NOT_SUPPORTED", 404, "Cette région n'est pas encore prise en charge.")
    return yaml.safe_load(f.read_text(encoding="utf-8"))
