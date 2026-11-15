"""T12 + T14 - Agrégation mensuelle et indicateurs.

Par (année, mois) : pluie (somme), températures (moyennes), ET0 (somme), pluie et jours de pluie
intense (au-dessus du 95e centile des jours de pluie), jours de chaleur (Tmax > 30, 32, 34, 36, 38 °C).
Qualité : `ok` si au moins 80 % des jours sont valides ; un mois isolé manquant est reconstitué
(`interpolated`) ; deux mois manquants ou plus à la suite restent `unavailable` et ne sont pas envoyés
au moteur (qui écarte alors l'année).
"""
import numpy as np
import pandas as pd

SEUILS_CHALEUR = (30, 32, 34, 36, 38)
PART_VALIDE_MIN = 0.8


def p95_pluie(jours: pd.DataFrame) -> float:
    humides = jours["pluie"].dropna()
    humides = humides[humides >= 1.0]
    return float(np.percentile(humides, 95)) if len(humides) > 20 else 50.0


def mensuel(jours: pd.DataFrame, et0: pd.Series) -> pd.DataFrame:
    d = jours.copy()
    d["et0"] = et0
    p95 = p95_pluie(d)
    d["intense"] = d["pluie"].where(d["pluie"] > p95, 0.0)
    d["j_intense"] = (d["pluie"] > p95).astype(float)
    for s in SEUILS_CHALEUR:
        d[f"c{s}"] = (d["t_max"] > s).astype(float).where(d["t_max"].notna())
    g = d.groupby([d.index.year, d.index.month])
    n_jours = g.size()
    valides = g[["pluie", "t_max", "t_min"]].count().min(axis=1)
    part = valides / n_jours
    facteur = n_jours / g["pluie"].count().clip(lower=1)          # complète un mois presque entier
    m = pd.DataFrame({
        "pluie_mm": g["pluie"].sum() * facteur,
        "t_moy_c": g["t_moy"].mean() if "t_moy" in d else (g["t_max"].mean() + g["t_min"].mean()) / 2,
        "t_min_c": g["t_min"].mean(),
        "t_max_c": g["t_max"].mean(),
        "et0_mm": g["et0"].mean() * n_jours,
        "pluie_intense_mm": g["intense"].sum() * facteur,
        "jours_pluie_intense": g["j_intense"].sum(),
        **{f"c{s}": g[f"c{s}"].sum() for s in SEUILS_CHALEUR},
    })
    m.index.names = ["annee", "mois"]
    m["qualite"] = np.where(part >= PART_VALIDE_MIN, "ok", "unavailable")
    return _reconstituer(m)


def _reconstituer(m: pd.DataFrame) -> pd.DataFrame:
    """Un mois manquant isolé : températures = moyenne des voisins ; pluie, ET0 = normale du mois."""
    m = m.copy()
    absent = (m["qualite"] == "unavailable").values
    normales = m[m["qualite"] == "ok"].groupby(level="mois").mean(numeric_only=True)
    for i in np.where(absent)[0]:
        voisin_absent = (i > 0 and absent[i - 1]) or (i + 1 < len(m) and absent[i + 1])
        if voisin_absent or i == 0 or i == len(m) - 1:
            continue
        mois = m.index[i][1]
        for c in ("t_moy_c", "t_min_c", "t_max_c"):
            m.iloc[i, m.columns.get_loc(c)] = (m.iloc[i - 1][c] + m.iloc[i + 1][c]) / 2
        for c in ("pluie_mm", "et0_mm", "pluie_intense_mm", "jours_pluie_intense", *[f"c{s}" for s in SEUILS_CHALEUR]):
            if mois in normales.index:
                m.iloc[i, m.columns.get_loc(c)] = normales.loc[mois, c]
        m.iloc[i, m.columns.get_loc("qualite")] = "interpolated"
    return m


def vers_moteur(m: pd.DataFrame) -> list[dict]:
    """Format `MoisClimat` du moteur (mois `unavailable` exclus)."""
    out = []
    for (a, mo), r in m[m["qualite"] != "unavailable"].iterrows():
        if r[["pluie_mm", "t_max_c", "t_min_c", "et0_mm"]].isna().any():
            continue
        out.append({"annee": int(a), "mois": int(mo), "pluie_mm": round(float(r.pluie_mm), 1),
                    "t_moy_c": round(float(r.t_moy_c), 2), "t_min_c": round(float(r.t_min_c), 2),
                    "t_max_c": round(float(r.t_max_c), 2), "et0_mm": round(float(r.et0_mm), 1),
                    "pluie_intense_mm": round(float(r.pluie_intense_mm), 1),
                    "jours_pluie_intense": int(r.jours_pluie_intense),
                    "jours_chaleur": {str(s): int(r[f"c{s}"]) for s in SEUILS_CHALEUR}})
    return out


def normales(m: pd.DataFrame) -> pd.DataFrame:
    return m[m["qualite"] != "unavailable"].groupby(level="mois").mean(numeric_only=True)
