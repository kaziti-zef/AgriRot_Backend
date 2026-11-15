"""T28 - S3 Fertilité : bilan azoté par points (R2, R3) + matière organique restituée."""
from app.engine.criteres import Resultat, Trace, clip
from app.params import P, correspondances
from app.referentiel.loader import REF


def _norm(x, bornes):
    lo, hi = bornes
    return clip(100 * (x - lo) / (hi - lo))


def noter(rot, pc, ctx) -> Resultat:
    p, cor = P()["s3"], correspondances()
    eng = cor["engrais"][ctx.pratiques.fertilizer_use or "aucun"]
    eps = ctx.pratiques.residue_return
    res = Resultat(note=50.0)
    if eps is None:
        eps = cor["residus_restitues_defaut"]
        res.traces.append(Trace("S3", "information_gaps", f"Part des résidus laissés au champ non renseignée : "
                                f"{round(eps * 100)} % par défaut.", poids=0.4))
    if ctx.pratiques.fertilizer_use is None:
        res.traces.append(Trace("S3", "information_gaps", "Usage d'engrais non renseigné : supposé nul.", poids=0.3))

    occs = rot.occupations
    if not occs:
        return res
    precedent = rot.historique[-1].crop if rot.historique else None
    N = M = 0.0
    n_r2 = n_r3 = 0
    for o in occs:
        c = REF.cultures[o.crop]
        b = p["b"][c.besoin_azote]
        N += p["nu_fix"] * c.fixe_azote - p["nu_bes"] * b
        M += eps * p["m"][c.residus] + eng["bonus_matiere_organique"]
        if precedent:
            cp = REF.cultures[precedent]
            if cp.fixe_azote and b == 3:
                N += p["nu_pre"]
                n_r2 += 1
                lo, hi = cp.azote_fixe
                apport = f" (environ {lo:g} à {hi:g} kg N/ha selon la littérature)" if lo else ""
                res.traces.append(Trace("S3", "benefits", f"{cp.nom} (légumineuse) avant {c.nom} : apport d'azote pour "
                                        f"une culture exigeante{apport}.", "R2", o.s0, 0.8))
            if p["b"][cp.besoin_azote] == 3 and b == 3:
                N -= p["nu_seq"] * eng["facteur_penalite_sequence"]
                n_r3 += 1
                res.traces.append(Trace("S3", "why", f"{cp.nom} puis {c.nom} : deux cultures très exigeantes en azote "
                                        f"à la suite.", "R3", o.s0, 0.8))
        precedent = o.crop
    jach = sum(1 for s in range(1, rot.n + 1) if rot.par_saison.get(s) is None)
    M += jach * p["m_jachere"]
    K = len(occs)
    sN = _norm(N / K, p["bornes_n_par_culture"])
    sM = _norm(M / (K + jach), p["bornes_m_par_culture"])
    res.note = clip(p["part_azote"] * sN + (1 - p["part_azote"]) * sM)
    res.extra = {"azote": round(sN, 1), "matiere_organique": round(sM, 1), "r2": n_r2, "r3": n_r3}

    legumineuses = [REF.nom(o.crop) for o in occs if REF.cultures[o.crop].fixe_azote]
    if not legumineuses:
        res.traces.append(Trace("S3", "why", "Aucune légumineuse dans la rotation : rien ne restitue l'azote "
                                "prélevé par les cultures.", "R2", poids=0.9))
    else:
        res.traces.append(Trace("S3", "benefits", f"Légumineuses présentes ({', '.join(dict.fromkeys(legumineuses))}) : "
                                f"elles fixent l'azote de l'air.", "R2", poids=0.5))
    res.traces.append(Trace("S3", "proofs", "Fixation d'azote, exigence et résidus : fiche culture (littérature "
                            "agronomique, ordres de grandeur).", poids=0.1))
    return res
