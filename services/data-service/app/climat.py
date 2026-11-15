"""Chaîne complète : POWER (ou cache, ou secours) -> nettoyage -> ET0 -> mensuel -> saisons."""
import datetime as dt
from dataclasses import dataclass

import pandas as pd

from app import cache
from app.processing import climatologie, et0, qualite, saisons
from app.sources import nasa_power as power

NB_ANNEES = 30


def periode_defaut(debut: int | None, fin: int | None) -> tuple[int, int]:
    fin = fin or dt.date.today().year - 1          # dernière année complète
    debut = debut or fin - NB_ANNEES + 1
    return debut, fin


@dataclass
class Climat:
    mensuel: pd.DataFrame
    jours: pd.DataFrame
    saisons: list[dict]
    statut: str
    cached_at: str | None
    synthetique: bool
    altitude_m: float | None
    methode_et0: str


def calculer(lat: float, lon: float, debut: int | None = None, fin: int | None = None,
             delai: float = power.DELAI_COURT) -> Climat:
    debut, fin = periode_defaut(debut, fin)
    r = cache.obtenir(lat, lon, debut, fin, delai)
    jours = qualite.nettoyer(r.serie.jours.loc[f"{debut}-01-01":f"{fin}-12-31"])
    e, methode = et0.journaliere(jours, r.serie.altitude_m, lat)
    m = climatologie.mensuel(jours, e)
    return Climat(m, jours, saisons.detecter(m), r.statut, r.cached_at, r.synthetique, r.serie.altitude_m, methode)


def site_climat(c: Climat) -> dict:
    """Objet `SiteClimat` attendu tel quel par agrorot-core (contrat interne T03)."""
    return {"serie_mensuelle": climatologie.vers_moteur(c.mensuel), "saisons": c.saisons,
            "source_status": c.statut, "synthetique": c.synthetique}
