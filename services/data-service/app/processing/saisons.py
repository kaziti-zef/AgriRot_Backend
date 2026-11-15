"""T14 - Saisons des pluies par année.

Un mois est « humide » si la pluie efficace (0,8 x P) atteint RATIO x ET0. Dans chaque fenêtre
(S1 : février-juillet, S2 : juillet-décembre), la plus longue suite de mois humides donne le début
et la fin de la saison. RATIO = 0,75 sépare S1 et S2 sur le régime de Yaoundé (la petite saison
sèche de juillet passe sous le seuil) ; avec 0,5 les deux saisons fusionnent. À VÉRIFIER sur la vraie
série POWER (point ouvert du plan). Sans détection fiable, le moteur garde le calendrier régional.
"""
import pandas as pd

RATIO = 0.75
FENETRES = {"S1": range(2, 8), "S2": range(7, 13)}


def _plus_longue_suite(mois: list[int]) -> list[int]:
    meilleure, courante = [], []
    for m in mois:
        if courante and m == courante[-1] + 1:
            courante.append(m)
        else:
            courante = [m]
        if len(courante) > len(meilleure):
            meilleure = list(courante)
    return meilleure


def detecter(m: pd.DataFrame, ratio: float = RATIO) -> list[dict]:
    out = []
    ok = m[m["qualite"] != "unavailable"]
    for annee in sorted(set(ok.index.get_level_values("annee"))):
        a = ok.loc[annee]
        humides = [int(mo) for mo, r in a.iterrows() if 0.8 * r.pluie_mm >= ratio * r.et0_mm]
        for code, fen in FENETRES.items():
            suite = _plus_longue_suite([x for x in humides if x in fen])
            if len(suite) >= 2:
                out.append({"annee": int(annee), "code": code, "debut_mois": suite[0], "fin_mois": suite[-1]})
    return out
