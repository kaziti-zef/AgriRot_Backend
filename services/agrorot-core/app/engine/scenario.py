"""T21 - Climat de travail : série en tableaux (années x 12 mois) + scénarios « Et si… » et tendance.

Le reste du moteur ne lit le climat qu'à travers `Climat` : des tableaux numpy de forme (Y, 12).
"""
from dataclasses import dataclass, replace

import numpy as np

from app.errors import ApiError
from app.params import P
from app.schemas import SEUILS_CHALEUR, ScenarioClimat, SiteClimat


@dataclass(frozen=True)
class Climat:
    annees: np.ndarray            # (Y,)
    pluie: np.ndarray             # (Y, 12) mm/mois
    t_moy: np.ndarray
    t_min: np.ndarray
    t_max: np.ndarray
    et0: np.ndarray
    pluie_intense: np.ndarray     # mm tombés en épisodes intenses
    chaleur: dict                 # seuil (int) -> (Y, 12) jours au-dessus du seuil ; vide si inconnu
    source_status: str = "live"
    synthetique: bool = False

    @property
    def pluie_annuelle(self) -> float:
        return float(self.pluie.sum(axis=1).mean())

    @property
    def t_annuelle(self) -> float:
        return float(self.t_moy.mean())


def depuis_site(site: SiteClimat) -> Climat:
    """Ne garde que les années complètes (12 mois)."""
    par_annee: dict[int, dict[int, object]] = {}
    for m in site.serie_mensuelle:
        par_annee.setdefault(m.annee, {})[m.mois] = m
    annees = sorted(a for a, ms in par_annee.items() if len(ms) == 12)
    if len(annees) < 5:
        raise ApiError("CLIMATE_DATA_UNAVAILABLE", 503, "Les données climatiques sont momentanément indisponibles.",
                       {"reason": "moins de 5 années complètes"})

    def tab(attr):
        return np.array([[getattr(par_annee[a][m], attr) for m in range(1, 13)] for a in annees], dtype=float)

    avec_chaleur = all(par_annee[a][m].jours_chaleur for a in annees for m in range(1, 13))
    chaleur = {}
    if avec_chaleur:
        for s in SEUILS_CHALEUR:
            chaleur[s] = np.array([[par_annee[a][m].jours_chaleur.get(str(s), 0) for m in range(1, 13)] for a in annees],
                                  dtype=float)
    return Climat(np.array(annees), tab("pluie_mm"), tab("t_moy_c"), tab("t_min_c"), tab("t_max_c"), tab("et0_mm"),
                  tab("pluie_intense_mm"), chaleur, site.source_status, site.synthetique)


def _decaler_chaleur(chaleur: dict, dt: np.ndarray) -> dict:
    """+dt °C : les jours au-dessus de s deviennent ceux au-dessus de s - dt (interpolation entre seuils)."""
    if not chaleur:
        return chaleur
    seuils = np.array(sorted(chaleur))
    pile = np.stack([chaleur[s] for s in seuils])                 # (S, Y, 12)
    pente = (pile[0] - pile[1]) / (seuils[1] - seuils[0])        # jours gagnés par °C sous le 1er seuil
    out = {}
    for s in seuils:
        cible = s - dt                                             # (12,) ou scalaire
        val = np.empty_like(pile[0])
        for j in range(12):
            c = cible[j] if np.ndim(cible) else cible
            if c <= seuils[0]:
                val[:, j] = pile[0][:, j] + pente[:, j] * (seuils[0] - c)
            else:
                val[:, j] = np.array([np.interp(c, seuils, pile[:, y, j]) for y in range(pile.shape[1])])
        out[int(s)] = np.clip(val, 0, 31)
    return out


def tendances(cl: Climat) -> tuple[np.ndarray, np.ndarray]:
    """Pente linéaire par mois : (°C / an, part de pluie / an)."""
    x = cl.annees - cl.annees.mean()
    vx = (x ** 2).sum()
    pt = (x[:, None] * (cl.t_moy - cl.t_moy.mean(axis=0))).sum(axis=0) / vx
    moy = np.maximum(cl.pluie.mean(axis=0), 1.0)
    pp = (x[:, None] * (cl.pluie - cl.pluie.mean(axis=0))).sum(axis=0) / vx / moy
    return pt, pp


def appliquer(cl: Climat, sc: ScenarioClimat) -> Climat:
    if not (-30 <= sc.rain_delta_pct <= 30 and 0 <= sc.temp_delta_c <= 3 and sc.horizon_years in (0, 5, 10)):
        raise ApiError("INVALID_SCENARIO", 422, "Valeurs de simulation hors des bornes autorisées.")
    dt = np.full(12, float(sc.temp_delta_c))
    fp = np.full(12, 1 + sc.rain_delta_pct / 100)
    if sc.horizon_years:
        pt, pp = tendances(cl)
        ecart = (cl.annees.max() - cl.annees.mean()) + sc.horizon_years   # du milieu de la série à l'horizon
        dt = dt + pt * ecart
        fp = fp * np.clip(1 + pp * ecart, 0.7, 1.3)
    if not dt.any() and np.allclose(fp, 1):
        return cl
    k = P()["scenario"]["et0_par_degre"]
    return replace(cl, pluie=cl.pluie * fp, pluie_intense=cl.pluie_intense * fp,
                   t_moy=cl.t_moy + dt, t_min=cl.t_min + dt, t_max=cl.t_max + dt,
                   et0=cl.et0 * (1 + k * dt), chaleur=_decaler_chaleur(cl.chaleur, dt))
