"""Réponse NASA POWER SIMULÉE, au format exact de l'API (point journalier, communauté AG).

Sert aux tests hors ligne et au jeu de secours `data/fallback/cm_yaounde_daily.csv.gz`
(Plan B, marqué synthétique). Régime bimodal de Yaoundé, ordres de grandeur réalistes.
    python tests/power_simule.py     -> régénère le jeu de secours
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

PLUIE = [20, 50, 140, 180, 200, 150, 60, 80, 220, 290, 120, 25]
JOURS_PLUIE = [2, 5, 12, 15, 17, 13, 7, 9, 18, 22, 12, 3]
T_MOY = [25.0, 25.8, 25.4, 25.0, 24.6, 23.8, 23.0, 23.1, 23.6, 23.8, 24.3, 24.6]
AMPL = [12.0, 12.0, 10.5, 9.5, 9.0, 8.5, 8.0, 8.0, 8.5, 8.5, 9.5, 11.5]
HR = [70, 72, 78, 81, 83, 85, 85, 85, 85, 85, 82, 75]
RAY = [17.5, 17.8, 17.0, 16.5, 15.8, 14.5, 13.5, 13.8, 14.5, 14.8, 15.5, 16.8]   # MJ/m²/jour


def jours(debut=1995, fin=2024, graine=7) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    idx = pd.date_range(f"{debut}-01-01", f"{fin}-12-31", freq="D")
    out = {k: np.empty(len(idx)) for k in ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN")}
    for (a, m), pos in pd.Series(range(len(idx)), index=idx).groupby([idx.year, idx.month]):
        i = pos.values
        n = len(i)
        k = m - 1
        total = PLUIE[k] * rng.lognormal(0, 0.28)
        humides = rng.random(n) < min(0.95, JOURS_PLUIE[k] / n)
        w = rng.gamma(0.8, 1.0, n) * humides
        pluie = total * w / w.sum() if w.sum() > 0 else np.zeros(n)
        tm = T_MOY[k] + 0.02 * (a - debut) + rng.normal(0, 0.4)
        out["PRECTOTCORR"][i] = pluie
        out["T2M_MAX"][i] = tm + AMPL[k] / 2 + rng.normal(0, 1.3, n) - 1.2 * (pluie > 10)
        out["T2M_MIN"][i] = tm - AMPL[k] / 2 + rng.normal(0, 0.8, n)
        out["T2M"][i] = (out["T2M_MAX"][i] + out["T2M_MIN"][i]) / 2
        out["RH2M"][i] = np.clip(HR[k] + 6 * (pluie > 1) + rng.normal(0, 3, n), 30, 100)
        out["WS2M"][i] = np.clip(rng.normal(1.4, 0.4, n), 0.3, 5)
        out["ALLSKY_SFC_SW_DWN"][i] = np.clip(RAY[k] - 4 * (pluie > 5) + rng.normal(0, 2, n), 4, 28)
    return pd.DataFrame(out, index=idx)


def payload(lat=3.813, lon=11.452, debut=1995, fin=2024, trous=True) -> dict:
    df = jours(debut, fin).round(2)
    if trous:                                  # quelques -999, comme dans les vraies réponses
        df.iloc[100:103, df.columns.get_loc("PRECTOTCORR")] = -999
        df.iloc[len(df) // 2, df.columns.get_loc("WS2M")] = -999
    params = {c: {d.strftime("%Y%m%d"): float(v) for d, v in df[c].items()} for c in df.columns}
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat, 742.3]},
            "properties": {"parameter": params},
            "header": {"title": "NASA/POWER Daily (SIMULÉ)", "fill_value": -999, "start": f"{debut}0101",
                       "end": f"{fin}1231", "time_standard": "LST"}}


if __name__ == "__main__":
    from app.sources.nasa_power import analyser
    s = analyser(payload(trous=False), 3.813, 11.452)
    d = Path(__file__).resolve().parents[1] / "data" / "fallback"
    d.mkdir(parents=True, exist_ok=True)
    s.jours.to_csv(d / "cm_yaounde_daily.csv.gz")
    (d / "cm_yaounde_daily.json").write_text(json.dumps({"altitude_m": 742.3, "synthetique": True,
                                                         "note": "Jeu de secours SIMULÉ ; remplacer par une vraie "
                                                                 "série POWER de Yaoundé avant la démo (T61)."}))
    print("jeu de secours écrit :", len(s.jours), "jours")
