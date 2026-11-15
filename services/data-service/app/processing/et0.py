"""T13 - Évapotranspiration de référence ET0, méthode FAO-56 Penman-Monteith (équation 6), pas journalier.

Entrées POWER : Tmax, Tmin (°C), humidité relative moyenne RH2M (%), vent à 2 m WS2M (m/s),
rayonnement global ALLSKY_SFC_SW_DWN (MJ/m²/jour, communauté AG), altitude (m), latitude (°).
Repli Hargreaves (FAO-56, équation 52) les jours où l'humidité, le vent ou le rayonnement manquent.
"""
import numpy as np
import pandas as pd

SIGMA = 4.903e-9          # MJ K-4 m-2 jour-1


def e_sat(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def rayonnement_extraterrestre(lat_deg, doy):
    """Ra (MJ/m²/jour), FAO-56 équation 21."""
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def penman_monteith(tmax, tmin, ea, u2, rs, z, lat_deg, doy):
    """ET0 (mm/jour). `ea` = pression de vapeur réelle (kPa)."""
    tmean = (tmax + tmin) / 2
    pres = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    gamma = 0.000665 * pres
    es = (e_sat(tmax) + e_sat(tmin)) / 2
    delta = 4098 * e_sat(tmean) / (tmean + 237.3) ** 2
    ra = rayonnement_extraterrestre(lat_deg, doy)
    rso = (0.75 + 2e-5 * z) * ra
    rns = 0.77 * rs
    ratio = np.clip(rs / rso, 0.25, 1.0)
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return np.maximum(et0, 0.0)


def hargreaves(tmax, tmin, lat_deg, doy):
    ra = rayonnement_extraterrestre(lat_deg, doy)
    tmean = (tmax + tmin) / 2
    return np.maximum(0.0023 * (tmean + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0)) * 0.408 * ra, 0.0)


def journaliere(jours: pd.DataFrame, altitude_m: float | None, lat: float) -> tuple[pd.Series, str]:
    """ET0 journalière ; renvoie aussi la méthode dominante (« penman-monteith » ou « hargreaves »)."""
    z = altitude_m or 0.0
    doy = jours.index.dayofyear.values
    tx, tn = jours["t_max"].values, jours["t_min"].values
    es = (e_sat(tx) + e_sat(tn)) / 2
    ea = jours["hr"].values / 100 * es if "hr" in jours else np.full(len(jours), np.nan)
    u2 = jours["vent"].values if "vent" in jours else np.full(len(jours), np.nan)
    rs = jours["rayonnement"].values if "rayonnement" in jours else np.full(len(jours), np.nan)
    pm = penman_monteith(tx, tn, ea, u2, rs, z, lat, doy)
    hg = hargreaves(tx, tn, lat, doy)
    ok = ~np.isnan(pm)
    et0 = np.where(ok, pm, hg)
    methode = "penman-monteith" if ok.mean() >= 0.5 else "hargreaves"
    return pd.Series(et0, index=jours.index), methode
