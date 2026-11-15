"""T26 - S1 Adéquation climatique : part du cycle en plage optimale - lambda x chaleur à mi-saison."""
import numpy as np

from app.engine.criteres import Resultat, Trace, clip, pct, source_climat
from app.params import P
from app.referentiel.loader import REF


def noter(rot, pc, ctx) -> Resultat:
    lam = P()["s1"]["lambda_chaleur"]
    res = Resultat(note=100.0)
    a_list, sans_chaleur = [], False
    for o in rot.occupations:
        f = pc.fiche(o.crop, o.code)
        if f is None:
            continue
        c = REF.cultures[o.crop]
        chaleur = f.chaleur if f.chaleur is not None else np.zeros_like(f.opt)
        sans_chaleur |= f.chaleur is None
        a = float(np.mean(f.opt - lam * chaleur))
        a_list.append(a)
        for s in o.saisons:
            res.par_saison[s] = clip(100 * a)
        opt, ch = float(f.opt.mean()), float(chaleur.mean())
        if opt < 0.7:
            res.traces.append(Trace("S1", "why", f"{c.nom} en {o.code} : températures peu favorables ({pct(opt)} de l'idéal ; "
                                    f"optimum {c.t_opt[0]:g}–{c.t_opt[1]:g} °C).", "R7", o.s0, 1 - opt))
        if ch > 0.15:
            res.traces.append(Trace("S1", "local_risks_to_check",
                                    f"{c.nom} en {o.code} : jours de forte chaleur pendant la floraison "
                                    f"({pct(ch)} de la mi-saison en moyenne).", "R7", o.s0, ch))
    if a_list:
        res.note = clip(100 * float(np.mean(a_list)))
    res.traces.append(Trace("S1", "proofs", f"Températures mensuelles et jours de chaleur : {source_climat(pc)} ; "
                            f"plages optimales : FAO ECOCROP.", poids=0.1))
    if sans_chaleur:
        res.traces.append(Trace("S1", "information_gaps", "Jours de forte chaleur indisponibles : le stress thermique "
                                "pendant la floraison n'est pas évalué.", poids=0.5))
    return res
