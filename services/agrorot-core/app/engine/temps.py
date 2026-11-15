"""T23 - Modèle d'occupation : d'une séquence de saisons à des occupations datées au mois.

Repères de temps
- Une saison s (1..N) correspond à une année relative `ar` (0, 1, 2…) et un code S1/S2.
- Un « mois absolu » vaut 12 * ar + mois (mois de 1 à 12) : mars de l'année 0 = 3, mars de l'année 1 = 15.
- L'historique (season_index -1, -2, -3) occupe les saisons s = 0, -1, -2.
"""
from dataclasses import dataclass, field
from statistics import median

from app.params import calendrier
from app.referentiel.loader import JACHERE, REF
from app.schemas import Contexte, EtapeRotation


@dataclass
class Calendrier:
    semis: dict[str, int]          # code -> mois de semis
    fin: dict[str, int]            # code -> dernier mois de pluie
    tolerance: int
    premiere_saison: str
    premiere_annee: int

    def saison(self, s: int) -> tuple[int, str]:
        """Saison s -> (année relative, code). Fonctionne aussi pour s <= 0 (historique)."""
        decalage = 0 if self.premiere_saison == "S1" else 1
        k = s - 1 + decalage
        return k // 2, ("S1", "S2")[k % 2]

    def debut(self, s: int) -> int:
        ar, code = self.saison(s)
        return 12 * ar + self.semis[code]

    def label(self, s: int) -> str:
        ar, code = self.saison(s)
        return f"{self.premiere_annee + ar}-{code}"

    def fenetre(self, code: str) -> set[int]:
        """Mois calendaires où une culture de la saison `code` peut être en place (C2)."""
        a, b = self.semis[code], self.fin[code] + self.tolerance
        return {((m - 1) % 12) + 1 for m in range(a, b + 1)}

    def mois_humides(self) -> set[int]:
        return self.fenetre("S1") | self.fenetre("S2")


def calendrier_contexte(ctx: Contexte) -> Calendrier:
    cal = calendrier(ctx.region)
    semis = {k: v["semis"] for k, v in cal["saisons"].items()}
    fin = {k: v["fin_pluies"] for k, v in cal["saisons"].items()}
    # Saisons détectées par data-service : médiane des années, appliquée SEULEMENT si elle reste
    # cohérente avec le calendrier régional (décalage <= 1 mois, S2 semée après la fin de S1).
    # Sur la vraie série POWER de Yaoundé, la petite saison sèche de juillet est lissée par la
    # réanalyse et la détection placerait le semis de S2 en juillet : le calendrier régional prévaut.
    detecte_s, detecte_f = dict(semis), dict(fin)
    for code in ("S1", "S2"):
        ss = [x for x in ctx.climat.saisons if x.code == code]
        if len(ss) >= 5:
            detecte_s[code] = round(median(x.debut_mois for x in ss))
            detecte_f[code] = round(median(x.fin_mois for x in ss))
    coherent = (all(abs(detecte_s[c] - semis[c]) <= 1 and abs(detecte_f[c] - fin[c]) <= 1 for c in ("S1", "S2"))
                and detecte_s["S2"] > detecte_f["S1"])
    if coherent:
        semis, fin = detecte_s, detecte_f
    return Calendrier(semis, fin, cal.get("tolerance_mois", 1), ctx.premiere_saison, ctx.premiere_annee)


@dataclass
class Occupation:
    crop: str
    s0: int                        # saison de semis
    semis_am: int                  # mois absolu de semis
    recolte_am: int                # mois absolu de récolte (inclus)
    saisons: list[int] = field(default_factory=list)
    modifiee: bool = False
    code: str = "S1"               # saison de semis (S1 / S2)


@dataclass
class Rotation:
    """Séquence interprétée : occupations, saisons nues, conflits d'occupation (C3)."""
    etapes: list[EtapeRotation]
    occupations: list[Occupation]                 # rotation proposée (s >= 1)
    historique: list[Occupation]                  # saisons passées (s <= 0)
    par_saison: dict[int, Occupation | None]      # s -> occupation en place (None = jachère / sol nu)
    continuation: dict[int, bool]
    conflits: list[tuple[int, str, str]]          # (saison, culture voulue, culture en place)
    n: int
    debut_am: int
    fin_am: int                                   # dernier mois de l'horizon (inclus)


def interpreter(etapes: list[EtapeRotation], cal: Calendrier, historique=()) -> Rotation:
    etapes = sorted(etapes, key=lambda e: e.season)
    n = max((e.season for e in etapes), default=0)
    par_s = {e.season: e for e in etapes}
    occs, hist, conflits = [], [], []
    par_saison: dict[int, Occupation | None] = {}
    continuation: dict[int, bool] = {}

    # Historique : saisons 0, -1, -2 (season_index -1 -> s = 0)
    for h in sorted(historique, key=lambda x: x.season_index):
        s = h.season_index + 1
        if h.crop_id in REF.cultures:
            c = REF.cultures[h.crop_id]
            hist.append(Occupation(h.crop_id, s, cal.debut(s), cal.debut(s) + c.cycle_mois - 1, [s], False, cal.saison(s)[1]))

    courante: Occupation | None = None
    for s in range(1, n + 1):
        e = par_s.get(s)
        crop = e.crop_id if e else JACHERE
        debut = cal.debut(s)
        occupee = courante is not None and debut < courante.recolte_am
        if occupee and crop == courante.crop:
            courante.saisons.append(s)
            par_saison[s], continuation[s] = courante, True
            continue
        if occupee and crop != courante.crop:
            conflits.append((s, crop, courante.crop))
        if crop == JACHERE or crop not in REF.cultures:
            par_saison[s], continuation[s] = None, False
            if not occupee:
                courante = None
            continue
        c = REF.cultures[crop]
        courante = Occupation(crop, s, debut, debut + c.cycle_mois - 1, [s], bool(e and e.modified_by_user), cal.saison(s)[1])
        occs.append(courante)
        par_saison[s], continuation[s] = courante, False

    debut_am = cal.debut(1)
    fin_am = max([cal.debut(n + 1) - 1] + [o.recolte_am for o in occs])
    return Rotation(etapes, occs, hist, par_saison, continuation, conflits, n, debut_am, fin_am)


def mois_calendaire(am: int) -> int:
    return ((am - 1) % 12) + 1
