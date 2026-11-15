"""T33 (1/2) - Génération des rotations candidates : recherche en faisceau, saison par saison.

À chaque saison, on étend chaque rotation partielle avec les cultures admissibles pour cette saison
(C1, C2, C6 pré-calculées ; C3, C4, C5 vérifiées au fil de l'eau), on note les rotations partielles
et l'on garde les meilleures (`largeur_faisceau`). Résultat déterministe : égalités départagées
par l'ordre alphabétique de la séquence.
"""
from app.engine import contraintes as K
from app.engine.evaluation import Evaluation, evaluer
from app.engine.precalcul import Precalcul, seuil_eau
from app.params import P
from app.referentiel.loader import JACHERE, REF
from app.schemas import Contexte, EtapeRotation


def cultures_par_saison(pc: Precalcul, ctx: Contexte) -> dict[str, list[str]]:
    """Cultures admissibles pour chaque code de saison, les mieux adaptées d'abord."""
    p = P()
    out = {}
    for code in ("S1", "S2"):
        notes = []
        for c in pc.candidates:
            f = pc.fiche(c, code)
            if f is None or K.statiques(c, code, pc, ctx):
                continue
            eta = p["s2"]["eta"][REF.cultures[c].secheresse]
            eau = 1 - eta * (1 - float((f.sigma >= seuil_eau(REF.cultures[c])).mean()))
            notes.append((-(float(f.opt.mean()) + eau), c))
        out[code] = [c for _, c in sorted(notes)][: p["generateur"]["cultures_par_saison_max"]]
    return out


def _etat(seq: list[str], pc: Precalcul, ctx: Contexte):
    """Dernière occupation en place après `seq` : (culture, mois absolu de récolte)."""
    en_place, recolte = None, -10 ** 6
    for i, crop in enumerate(seq, start=1):
        debut = pc.cal.debut(i)
        if en_place and debut < recolte and crop == en_place:
            continue
        if crop == JACHERE:
            en_place, recolte = None, -10 ** 6
            continue
        en_place, recolte = crop, debut + REF.cultures[crop].cycle_mois - 1
    return en_place, recolte


def _plantations(seq, pc, ctx) -> list[tuple[str, int]]:
    """(culture, mois absolu de semis), historique compris."""
    out = [(h.crop_id, pc.cal.debut(h.season_index + 1)) for h in sorted(ctx.historique, key=lambda x: x.season_index)
           if h.crop_id in REF.cultures]
    en_place, recolte = None, -10 ** 6
    for i, crop in enumerate(seq, start=1):
        debut = pc.cal.debut(i)
        if en_place and debut < recolte and crop == en_place:
            continue
        if crop == JACHERE:
            en_place = None
            continue
        out.append((crop, debut))
        en_place, recolte = crop, debut + REF.cultures[crop].cycle_mois - 1
    return out


def _extensions(seq, s, permises, pc, ctx, strict: bool, n: int) -> list[str]:
    en_place, recolte = _etat(seq, pc, ctx)
    debut = pc.cal.debut(s)
    if en_place and debut < recolte:
        return [en_place]                                   # culture longue : continuation forcée
    code = pc.cal.saison(s)[1]
    plant = _plantations(seq, pc, ctx)
    # Saisons sans production (jachère, plante de service) : au plus une sur `saisons_par_plante_service`
    n_service = sum(1 for c in seq if c == JACHERE or (c in REF.cultures and REF.cultures[c].service))
    max_service = max(1, n // P()["generateur"]["saisons_par_plante_service"])
    out = [JACHERE] if n_service < max_service else []
    for c in permises[code]:
        cul = REF.cultures[c]
        if cul.service and n_service >= max_service:
            continue                                        # au plus une plante de service par 4 saisons
        if strict:
            if plant and REF.cultures[plant[-1][0]].famille == cul.famille:
                continue                                    # C5
            dernier = max((am for x, am in plant if x == c), default=None)
            if dernier is not None and (debut - dernier) / 12 + 1e-9 < cul.delai_retour_ans:
                continue                                    # C4
        out.append(c)
    return out


def _etapes(seq: list[str]) -> list[EtapeRotation]:
    return [EtapeRotation(season=i, crop_id=c) for i, c in enumerate(seq, start=1)]


def rechercher(pc: Precalcul, ctx: Contexte, n: int, strict: bool = True) -> list[Evaluation]:
    """Rotations complètes de n saisons, triées par note globale décroissante."""
    largeur = max(30, P()["generateur"]["largeur_faisceau"] * 6 // max(6, n))   # horizon long : faisceau plus étroit
    permises = cultures_par_saison(pc, ctx)
    faisceau: list[list[str]] = [[]]
    finales: list[Evaluation] = []
    for s in range(1, n + 1):
        notees = []
        for seq in faisceau:
            for c in _extensions(seq, s, permises, pc, ctx, strict, n):
                nouv = seq + [c]
                ev = evaluer(_etapes(nouv), pc, ctx)
                notees.append(ev)
        notees.sort(key=lambda e: (-e.G, e.cle))
        if s == n:
            finales = [e for e in notees if not strict or e.admissible]
        else:
            faisceau = [list(e.cle) for e in notees[:largeur]]
    # Une rotation qui ne cultive rien n'est pas une proposition
    return [e for e in finales if any(c != JACHERE for c in e.cle)]


def difference(a: tuple, b: tuple) -> float:
    """Part des saisons où les deux rotations n'ont pas la même culture."""
    return sum(x != y for x, y in zip(a, b)) / max(1, len(a))


def distance_cultures(a: tuple, b: tuple) -> float:
    """Distance de Jaccard entre les ensembles de cultures (0 = mêmes cultures, 1 = aucune en commun)."""
    A, B = set(a) - {JACHERE}, set(b) - {JACHERE}
    return 1 - len(A & B) / max(1, len(A | B))


def choisir_alternative(pool: list, reco, seuil: float):
    """La meilleure rotation qui diffère sur au moins `seuil` des saisons ET introduit d'autres cultures ;
    on relâche progressivement si le faisceau n'en contient pas."""
    for jac in (0.34, 0.01, 0.0):
        for e in pool[1:]:
            if difference(e.cle, reco.cle) >= seuil and distance_cultures(e.cle, reco.cle) >= jac:
                return e
    return max(pool[1:] or [reco], key=lambda e: (difference(e.cle, reco.cle), e.G))


def normaliser(etapes: list[EtapeRotation], pc: Precalcul) -> list[EtapeRotation]:
    """Après une modification manuelle : une culture longue occupe les saisons suivantes qu'elle couvre."""
    etapes = sorted(etapes, key=lambda e: e.season)
    out = []
    i = 0
    while i < len(etapes):
        e = etapes[i]
        out.append(e)
        if e.crop_id in REF.cultures and REF.cultures[e.crop_id].longue:
            recolte = pc.cal.debut(e.season) + REF.cultures[e.crop_id].cycle_mois - 1
            j = i + 1
            while j < len(etapes) and pc.cal.debut(etapes[j].season) < recolte:
                out.append(EtapeRotation(season=etapes[j].season, crop_id=e.crop_id, modified_by_user=e.modified_by_user))
                j += 1
            i = j
        else:
            i += 1
    return out
