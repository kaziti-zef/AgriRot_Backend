"""T24 - Table pré-calculée (culture, saison, année).

Le résultat « maïs semé en S1, année 2001 » ne dépend pas de la rotation : on le calcule UNE fois,
puis toutes les rotations candidates lisent cette table. Contenu par (culture, code de saison) :
- sigma : satisfaction en eau FAO-56 pour chaque année (S2)
- opt, chaleur : part des mois en plage optimale, jours de chaleur à mi-saison / durée de la mi-saison (S1)
- couverture : couverture du sol par mois du cycle (S4)
"""
from dataclasses import dataclass, field

import numpy as np

from app.engine.aptitude import candidates
from app.engine.scenario import Climat
from app.engine.temps import Calendrier
from app.params import P, correspondances
from app.referentiel.loader import REF, Culture
from app.schemas import SEUILS_CHALEUR, Contexte


@dataclass
class Fiche:
    crop: str
    code: str
    semis: int                      # mois calendaire de semis
    mois: list[int]                 # mois calendaires du cycle
    sigma: np.ndarray               # (Yv,)
    opt: np.ndarray                 # (Yv,)
    chaleur: np.ndarray | None      # (Yv,) ou None si jours de chaleur inconnus
    couverture: list[float]         # par mois du cycle, 0..1
    mois_deficit: int | None        # mois calendaire le plus déficitaire en eau (médiane des années)


@dataclass
class Precalcul:
    climat: Climat
    cal: Calendrier
    candidates: list[str]
    aptitude: dict[str, float]
    fiches: dict[tuple[str, str], Fiche] = field(default_factory=dict)
    agressivite: np.ndarray = None   # (12,) part annuelle des pluies intenses par mois
    t10_min: np.ndarray = None
    t90_max: np.ndarray = None
    irrigation_mm: float = 0.0
    ru_mm_par_m: float = 130.0     # eau utile du sol (texture déclarée)

    def fiche(self, crop: str, code: str) -> Fiche | None:
        if (crop, code) not in self.fiches and crop in REF.cultures:
            f = _fiche(REF.cultures[crop], code, self)
            if f:
                self.fiches[(crop, code)] = f
        return self.fiches.get((crop, code))


def _profils(c: Culture) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Kc et facteur de couverture jour par jour sur le cycle ; fenêtre (début, fin) de la mi-saison."""
    p = P()["s4"]["facteur_stade"]
    i, dv, mi, fi = (round(x) for x in c.stades)
    kc0, kc1, kc2 = c.kc
    kc = np.concatenate([np.full(i, kc0), np.linspace(kc0, kc1, dv), np.full(mi, kc1), np.linspace(kc1, kc2, fi)])
    cv = np.concatenate([np.full(i, p["initial"]), np.linspace(p["initial"], p["mi_saison"], dv),
                         np.full(mi, p["mi_saison"]), np.full(fi, p["fin"])])
    return kc, cv, (i + dv, i + dv + mi)


def _fiche(c: Culture, code: str, pc: Precalcul) -> Fiche | None:
    if not c.stades:
        return None
    cl, prm = pc.climat, P()
    semis = pc.cal.semis[code]
    kc_j, cv_j, (m0, m1) = _profils(c)
    D = len(kc_j)
    L = int(np.ceil(D / 30))
    k = np.arange(L)
    cm = (semis - 1 + k) % 12                       # mois calendaire (0..11)
    yo = (semis - 1 + k) // 12                      # décalage d'année
    Yv = len(cl.annees) - int(yo.max())
    if Yv < 3:
        return None
    w = np.array([min(30, D - 30 * j) / 30 for j in k])
    kc_m = np.array([kc_j[30 * j: 30 * j + 30].mean() for j in k])
    kmax = prm["s4"]["couverture_max"][c.couverture]
    couverture = [float(cv_j[30 * j: 30 * j + 30].mean() * kmax) for j in k]
    mid = np.array([max(0, min(m1, 30 * j + 30) - max(m0, 30 * j)) for j in k])

    iy = np.arange(Yv)[:, None] + yo[None, :]       # (Yv, L) indices d'année
    pluie = cl.pluie[iy, cm[None, :]]
    et0 = cl.et0[iy, cm[None, :]]
    tm = cl.t_moy[iy, cm[None, :]]
    etc = kc_m * et0 * w
    apport = (prm["s2"]["part_pluie_efficace"] * pluie + pc.irrigation_mm) * w
    # Bilan mensuel avec réserve du sol : le surplus d'un mois humide couvre en partie un mois sec suivant.
    rmax = prm["s2"]["fraction_p"] * pc.ru_mm_par_m * c.racines_m
    stock = np.zeros(apport.shape[0])
    utilise = np.zeros_like(etc)
    for j in range(L):
        dispo = apport[:, j] + stock
        utilise[:, j] = np.minimum(dispo, etc[:, j])
        stock = np.minimum(rmax, dispo - utilise[:, j])
    sigma = utilise.sum(axis=1) / etc.sum(axis=1)
    deficit = np.median(etc - utilise, axis=0)
    mois_deficit = int(cm[int(np.argmax(deficit))] + 1) if deficit.max() > 5 else None
    # Adéquation thermique progressive (trapèze ECOCROP) plutôt que binaire : 1 dans la plage optimale,
    # décroissance linéaire jusqu'aux limites absolues (calibrage T62 sur la vraie série de Mbankomo).
    a, b, c_, d = c.t_abs[0], c.t_opt[0], c.t_opt[1], c.t_abs[1]
    if None in (a, b, c_, d):
        adeq = ((tm >= (b or -99)) & (tm <= (c_ or 99))).astype(float)
    else:
        adeq = np.clip(np.minimum((tm - a) / max(b - a, 1e-9), (d - tm) / max(d - c_, 1e-9)), 0, 1)
    opt = adeq @ w / w.sum()

    chaleur = None
    if cl.chaleur and c.t_opt[1] is not None and m1 > m0:
        cible = c.t_opt[1] + prm["s1"]["marge_chaleur_c"]
        seuil = min(SEUILS_CHALEUR, key=lambda s: abs(s - cible))
        jours = cl.chaleur[seuil][iy, cm[None, :]]          # jours chauds dans le mois
        chaleur = (jours * mid / 30).sum(axis=1) / (m1 - m0)
    return Fiche(c.id, code, semis, [int(x) + 1 for x in cm], sigma, opt, chaleur, couverture, mois_deficit)


def construire(ctx: Contexte, cl: Climat, cal: Calendrier) -> Precalcul:
    cands, apt = candidates(ctx, cl)
    irr = correspondances()["irrigation_mm_par_mois"][ctx.eau.dry_season_availability] if ctx.eau.has_irrigation else 0
    intense = cl.pluie_intense.mean(axis=0)
    pc = Precalcul(cl, cal, cands, apt,
                   agressivite=intense / max(intense.sum(), 1e-9),
                   t10_min=np.percentile(cl.t_min, 10, axis=0),
                   t90_max=np.percentile(cl.t_max, 90, axis=0),
                   irrigation_mm=float(irr),
                   ru_mm_par_m=float(P()["s2"]["reserve_utile_mm_par_m"][ctx.sol.texture or "inconnu"]))
    for c in cands:
        for code in ("S1", "S2"):
            pc.fiche(c, code)
    return pc


def seuil_eau(c: Culture) -> float:
    """sigma* propre à la culture (voir s2.seuil_par_sensibilite)."""
    s2 = P()["s2"]
    return s2.get("seuil_par_sensibilite", {}).get(c.secheresse, s2["seuil_satisfaction"])
