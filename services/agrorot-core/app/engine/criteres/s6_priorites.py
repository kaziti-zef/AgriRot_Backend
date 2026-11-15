"""T31 - S6 Priorités : part des saisons couvertes par les usages que l'agriculteur valorise (R8)."""
from app.engine.criteres import Resultat, Trace, clip, pct
from app.referentiel.loader import REF

POIDS_ALIMENTATION = 0.1     # l'alimentation familiale compte toujours un peu


def noter(rot, pc, ctx, poids: dict) -> Resultat:
    res = Resultat(note=0.0)
    marche = set(ctx.contraintes.market_available_crops)
    pi = {"vente": poids.get("income", 0.0), "fourrage": poids.get("fodder", 0.0), "alimentation": POIDS_ALIMENTATION}
    saisons = range(1, rot.n + 1)
    theta = {u: 0.0 for u in pi}
    sans_debouche = []
    for s in saisons:
        o = rot.par_saison.get(s)
        if not o:
            continue
        c = REF.cultures[o.crop]
        for u in c.usages:
            if u == "vente" and marche and o.crop not in marche:
                if o.crop not in sans_debouche:
                    sans_debouche.append(o.crop)
                continue
            theta[u] += 1 / len(saisons)
    total = sum(pi.values()) or 1.0
    res.note = clip(100 * sum(pi[u] * theta[u] for u in pi) / total)
    res.extra = {"theta": {u: round(v, 2) for u, v in theta.items()}}
    for c in sans_debouche:
        res.traces.append(Trace("S6", "local_risks_to_check", f"Pas de débouché déclaré pour {REF.nom(c)} : "
                                f"vérifier qui achète avant de semer.", "R8", poids=0.5))
    if theta["vente"] >= 0.5 and pi["vente"] > 0.15:
        res.traces.append(Trace("S6", "benefits", f"{pct(theta['vente'])} des saisons portent une culture vendable "
                                f"sur vos marchés.", poids=0.4 * pi["vente"] * 4))
    if pi["fourrage"] > 0.15 and theta["fourrage"] > 0:
        res.traces.append(Trace("S6", "benefits", f"Fourrage disponible sur {pct(theta['fourrage'])} des saisons "
                                f"(fanes, lianes, feuilles).", poids=0.3))
    if not marche:
        res.traces.append(Trace("S6", "information_gaps", "Débouchés commerciaux non renseignés.", poids=0.3))
    return res
