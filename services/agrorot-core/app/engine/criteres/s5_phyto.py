"""T30 - S5 Maladies et ravageurs : dynamique de pression par bioagresseur + alerte C7.

Pour chaque bioagresseur noté (sol, résidus, plante parasite ; rotation efficace), la pression
P monte quand une culture hôte est en place et décroît sinon (persistance delta). On simule
historique -> cycle 1 -> cycle 2 et l'on ne note que le cycle 2 (régime permanent).
"""
import math

from app.engine.criteres import Resultat, Trace, clip
from app.params import P, calendrier
from app.referentiel.loader import REF
from app.schemas import Violation


def _actifs(region: str):
    mots = calendrier(region).get("mots_zones", [])
    for b in REF.bioagresseurs.values():
        if not mots or any(m.lower() in b.zones.lower() for m in mots):
            yield b


def noter(rot, pc, ctx) -> Resultat:
    p = P()["s5"]
    res = Resultat(note=100.0)
    saisons = list(range(1, rot.n + 1))
    S = max(1, len(saisons))
    present = {s: (rot.par_saison[s].crop if rot.par_saison.get(s) else None) for s in saisons}
    hist = [o.crop for o in rot.historique]
    expo_saison = {s: 0.0 for s in saisons}
    Pi, contrib, violations = 0.0, {}, []

    for b in _actifs(ctx.region):
        if not b.note:
            continue
        P0 = p["pression_initiale_si_observe"] if b.id in ctx.pest_history else 0.0
        pression = P0

        def etape(crop, pr):
            h = b.hotes.get(crop, 0.0) if crop else 0.0
            if h > 0:
                return min(p["p_max"], b.delta * pr + h)
            if crop in b.assainissantes:
                return p["rho"] * b.delta * pr
            return b.delta * pr

        for crop in hist:
            pression = etape(crop, pression)
        for cycle in (1, 2):
            for s in saisons:
                crop = present[s]
                h = b.hotes.get(crop, 0.0) if crop else 0.0
                if cycle == 2 and h > 0:
                    x = h * pression
                    Pi += b.gravite * x
                    expo_saison[s] += b.gravite * x
                    contrib[b.id] = contrib.get(b.id, 0.0) + b.gravite * x
                    if h == 1 and b.gravite == 3 and pression >= p["p_crit"] and not rot.continuation.get(s):
                        violations.append(Violation(code="C7", season=s, crop_id=crop,
                                                    message=f"{REF.nom(crop)} semé sur une pression élevée de {b.nom.lower()}",
                                                    details={"bioagresseur": b.id, "pression": round(pression, 2)}))
                pression = etape(crop, pression)

    familles = sum(1 for a, c in zip(rot.occupations, rot.occupations[1:])
                   if REF.cultures[a.crop].famille == REF.cultures[c.crop].famille)
    Pi += p["phi_famille"] * familles
    Pi /= S
    res.note = clip(100 * math.exp(-Pi / p["pi0"]))
    res.par_saison = {s: clip(100 * math.exp(-v / p["pi0"])) for s, v in expo_saison.items() if present[s]}
    res.extra = {"Pi": round(Pi, 3), "violations": violations}

    for bid, v in sorted(contrib.items(), key=lambda kv: -kv[1])[:3]:
        if v / S < 0.3:
            continue
        b = REF.bioagresseurs[bid]
        hotes = [REF.nom(c) for c in dict.fromkeys(present.values()) if c and b.hotes.get(c)]
        res.traces.append(Trace("S5", "why", f"Pression de {b.nom.lower()} : {', '.join(hotes)} "
                                f"{'le nourrissent' if len(hotes) > 1 else 'le nourrit'} saison après saison.",
                                "R6", poids=v / S))
    for v in violations:
        res.traces.append(Trace("S5", "local_risks_to_check", v.message + " : vérifier l'état sanitaire de la parcelle.",
                                "C7", v.season, 1.0))
    if familles:
        res.traces.append(Trace("S5", "why", f"{familles} succession(s) de cultures de la même famille botanique.",
                                "R1", poids=0.6 * familles))
    cultures = {c for c in present.values() if c}
    for c in cultures:
        for b in _actifs(ctx.region):
            if c in b.assainissantes and any(b.hotes.get(x) for x in cultures):
                res.traces.append(Trace("S5", "benefits", f"{REF.nom(c)} réduit {b.nom.lower()} avant les cultures "
                                        f"sensibles.", "R6", poids=0.7))
    if Pi < 0.3 and cultures:
        res.traces.append(Trace("S5", "benefits", "Les cultures alternent des familles différentes : pas "
                                "d'accumulation forte de bioagresseurs du sol.", "R1", poids=0.5))
    conseils = []
    for b in _actifs(ctx.region):
        if not b.note and any(b.hotes.get(c, 0) == 1.0 for c in cultures) and b.conseil:
            conseils.append(f"{b.nom} : {b.conseil}")
    res.extra["conseils"] = conseils
    if ctx.pest_history:
        noms = [REF.bioagresseurs[i].nom.lower() for i in ctx.pest_history if i in REF.bioagresseurs]
        res.traces.append(Trace("S5", "proofs", f"Bioagresseurs déjà observés sur la parcelle : {', '.join(noms)}.",
                                poids=0.3))
    else:
        res.traces.append(Trace("S5", "information_gaps", "Présence réelle de bioagresseurs non renseignée : "
                                "pression initiale supposée nulle.", poids=0.3))
    res.traces.append(Trace("S5", "proofs", "Hôtes et persistance des bioagresseurs : table des bioagresseurs "
                            "(littérature, à valider localement).", poids=0.1))
    return res
