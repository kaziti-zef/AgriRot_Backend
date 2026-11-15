"""T29 - S4 Érosion : sol nu x part des pluies intenses du mois x facteur de pente (RUSLE simplifiée)."""
import math

from app.engine.criteres import MOIS, Resultat, Trace, clip, pct
from app.engine.temps import mois_calendaire
from app.params import P
from app.referentiel.loader import REF

PENTE_DEFAUT_DEG = 3.0
COUVERTURES = ("mucuna", "crotalaire", "niebe")


def couverture_mensuelle(rot, pc) -> dict[int, float]:
    """Mois absolu -> couverture 0..1 (0 = sol nu)."""
    kappa = {am: 0.0 for am in range(rot.debut_am, rot.fin_am + 1)}
    for o in rot.occupations:
        f = pc.fiche(o.crop, o.code)
        if f is None:
            continue
        for k, cv in enumerate(f.couverture):
            am = o.semis_am + k
            if am in kappa:
                kappa[am] = max(kappa[am], cv)
    return kappa


def noter(rot, pc, ctx) -> Resultat:
    p = P()["s4"]
    res = Resultat(note=100.0)
    pente_deg = ctx.sol.slope_deg
    if pente_deg is None:
        pente_deg = PENTE_DEFAUT_DEG
        res.traces.append(Trace("S4", "information_gaps", f"Pente inconnue : {PENTE_DEFAUT_DEG:g}° supposés.", poids=0.5))
    pente_pct = 100 * math.tan(math.radians(pente_deg))
    lam = min(1.0, pente_pct / p["pente_ref_pct"])
    kappa = couverture_mensuelle(rot, pc)
    R = {am: float(pc.agressivite[mois_calendaire(am) - 1]) for am in kappa}
    total = sum(R.values()) or 1.0
    contrib = {am: (1 - kappa[am]) * R[am] for am in kappa}
    E = lam * sum(contrib.values()) / total
    res.note = clip(100 * (1 - E))
    res.extra = {"facteur_pente": round(lam, 2), "pente_pct": round(pente_pct, 1)}

    pires = sorted((am for am in contrib if kappa[am] < 0.4 and R[am] > 0.05), key=lambda am: -contrib[am])
    vus = set()
    for am in pires:
        m = mois_calendaire(am)
        if m in vus or len(vus) >= p["nb_fenetres_risque"]:
            continue
        vus.add(m)
        suggestion = next((REF.nom(c) for c in COUVERTURES if c in pc.candidates), None)
        piste = f" Piste : une couverture ({suggestion}) à ce moment-là." if suggestion else ""
        etat = "nu" if kappa[am] == 0 else "peu couvert"
        res.traces.append(Trace("S4", "local_risks_to_check",
                                f"Sol {etat} en {MOIS[m - 1]}, mois qui reçoit {pct(R[am])} des pluies intenses de "
                                f"l'année (pente {pente_pct:.0f} %).{piste}", "R5", poids=contrib[am] * lam * 3))
    if lam > 0 and res.note >= 85:
        res.traces.append(Trace("S4", "benefits", "Sol couvert pendant la plupart des mois de fortes pluies : "
                                "risque d'érosion faible.", "R5", poids=0.4))
    res.traces.append(Trace("S4", "proofs", f"Part des pluies intenses par mois (au-dessus du 95e centile journalier) "
                            f"et pente de la parcelle ({pente_pct:.0f} %, SRTM ou saisie).", poids=0.1))
    return res
