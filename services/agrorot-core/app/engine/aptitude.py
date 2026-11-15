"""T22 - Pré-filtre d'aptitude A(c) : moyenne géométrique de deux trapèzes (température, pluie)."""
import math

from app.engine.scenario import Climat
from app.params import P
from app.referentiel.loader import REF, Culture
from app.schemas import Contexte


def trapeze(x: float, a, b, c, d) -> float:
    if None in (a, b, c, d):
        return 1.0                                  # borne inconnue : on ne pénalise pas (lacune signalée ailleurs)
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    return (x - a) / (b - a) if x < b else (d - x) / (d - c)


def cycle_court(c: Culture) -> bool:
    return (c.cycle_jours or 999) <= P()["aptitude"].get("cycle_court_jours", 0)


def aptitude(c: Culture, cl: Climat, ctx: Contexte) -> float:
    ft = trapeze(cl.t_annuelle, c.t_abs[0], c.t_opt[0], c.t_opt[1], c.t_abs[1])
    if cycle_court(c):          # seule la borne basse compte (voir aptitude.cycle_court_jours)
        fp = 1.0 if c.pluie_opt[0] is None or cl.pluie_annuelle >= c.pluie_opt[0] else \
            trapeze(cl.pluie_annuelle, c.pluie_abs[0], c.pluie_opt[0], 1e9, 2e9)
    else:
        fp = trapeze(cl.pluie_annuelle, c.pluie_abs[0], c.pluie_opt[0], c.pluie_opt[1], c.pluie_abs[1])
    if ctx.eau.has_irrigation:
        fp = max(fp, 0.8)
    if ctx.sol.elevation_m and c.altitude_max and ctx.sol.elevation_m > c.altitude_max:
        return 0.0
    return math.sqrt(ft * fp)


def candidates(ctx: Contexte, cl: Climat) -> tuple[list[str], dict[str, float]]:
    """Cultures de rotation retenues pour la parcelle, et l'aptitude de toutes les cultures de la région."""
    exclues = set(ctx.contraintes.excluded_crops)
    apt = {c.id: aptitude(c, cl, ctx) for c in REF.cultures_region(ctx.region) if c.en_rotation}
    seuil = P()["aptitude"]["seuil"]
    return [k for k, a in apt.items() if a >= seuil and k not in exclues], apt
