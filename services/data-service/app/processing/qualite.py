"""T12 - Nettoyage des séries journalières POWER.

- Les -999 sont déjà des valeurs manquantes (voir sources/nasa_power.py).
- Températures, humidité, vent, rayonnement : trous de 2 jours au plus interpolés.
- Pluie : jamais interpolée au jour le jour (un mois incomplet est traité à l'agrégation).
"""
import pandas as pd

CONTINUES = ["t_moy", "t_max", "t_min", "hr", "vent", "rayonnement"]


def nettoyer(jours: pd.DataFrame) -> pd.DataFrame:
    df = jours.copy()
    for c in CONTINUES:
        if c in df:
            df[c] = df[c].interpolate(limit=2, limit_area="inside")
    if "pluie" in df:
        df["pluie"] = df["pluie"].clip(lower=0)
    return df
