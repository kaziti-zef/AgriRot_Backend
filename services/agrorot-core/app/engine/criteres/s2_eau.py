"""T27 - S2 Eau : probabilité (sur les années) que la satisfaction FAO-56 atteigne sigma*."""
import numpy as np

from app.engine.criteres import MOIS, Resultat, Trace, clip, source_climat
from app.engine.precalcul import seuil_eau
from app.params import P
from app.referentiel.loader import REF


def noter(rot, pc, ctx) -> Resultat:
    prm = P()["s2"]
    eta = prm["eta"]
    res = Resultat(note=100.0)
    termes, probas = [], []
    for o in rot.occupations:
        f = pc.fiche(o.crop, o.code)
        if f is None:
            continue
        c = REF.cultures[o.crop]
        seuil = seuil_eau(c)
        p = float((f.sigma >= seuil).mean())
        probas.append(p)
        t = 1 - eta[c.secheresse] * (1 - p)
        termes.append(t)
        for s in o.saisons:
            res.par_saison[s] = clip(100 * t)
        n_ech, n = int((f.sigma < seuil).sum()), len(f.sigma)
        if p < 0.8:
            quand = f", surtout en {MOIS[f.mois_deficit - 1]}" if f.mois_deficit else ""
            res.traces.append(Trace("S2", "why", f"{c.nom} en {o.code} : dans {n_ech} années sur {n}, moins de "
                                    f"{round(seuil * 100)} % de son besoin en eau couvert{quand}.", "R4", o.s0,
                                    (1 - p) * eta[c.secheresse]))
        elif p < 0.95 and c.secheresse == "forte":
            res.traces.append(Trace("S2", "local_risks_to_check", f"{c.nom} est sensible à la sécheresse : "
                                    f"{n_ech} années sur {n} déficitaires.", "R4", o.s0, 0.3))
    if termes:
        res.note = clip(100 * float(np.mean(termes)))
        if min(probas) >= 0.9:
            res.traces.append(Trace("S2", "benefits", "Besoin en eau couvert au moins 9 années sur 10 pour chaque culture "
                                    "de la rotation, sans irrigation." if not pc.irrigation_mm else
                                    "Besoin en eau couvert au moins 9 années sur 10 pour chaque culture.", poids=0.6))
    res.traces.append(Trace("S2", "proofs", f"Bilan hydrique FAO-56 (Kc x ET0, 80 % de la pluie efficace) sur "
                            f"{source_climat(pc)}.", poids=0.2))
    if ctx.eau.has_irrigation:
        res.traces.append(Trace("S2", "information_gaps", "Volume d'irrigation estimé à partir de la catégorie déclarée "
                                f"({ctx.eau.dry_season_availability}) : à préciser.", poids=0.3))
    return res
