"""Sources NASA en ligne, utilisées quand les fichiers pré-agrégés (pre_agreges.py) manquent.

Sans fichiers préparés par scripts/pretelecharger.py, l'humidité du sol, le NDVI et le relief restaient
« indisponibles » partout. Ces lecteurs vont chercher l'équivalent en direct, sans compte Earthdata :

- Humidité du sol : NASA POWER mensuel, GWETROOT (humidité de la zone racinaire, MERRA-2, 0 à 1).
  On en tire l'anomalie mensuelle comme pour SMAP (z-score par mois).
- NDVI : MODIS MOD13Q1 (250 m, 16 jours) via le service web ORNL DAAC, maximum mensuel. Ce service est lent
  (10 à 60 s par requête) : le téléchargement se fait en tâche de fond, le diagnostic lit le cache.
- Relief : SRTM 30 m via l'API publique OpenTopoData (3 x 3 points espacés de 30 m -> altitude et pente).

Chaque lecteur renvoie None en cas d'échec : l'appelant garde alors son comportement d'origine
(indicateur listé dans missing_indicators, avertissement SRTM_UNAVAILABLE).
Désactivation : DONNEES_EN_LIGNE=0 (tests, démonstration hors ligne).
"""
import json
import math
import os
import threading
import datetime as dt

import httpx
import pandas as pd

from app.cache import CACHE_DIR

POWER_MENSUEL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
MODIS = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
OPENTOPO = os.getenv("OPENTOPODATA_URL", "https://api.opentopodata.org/v1/srtm30m")
DELAI_POWER = float(os.getenv("POWER_MENSUEL_TIMEOUT_S", 15))
DELAI_MODIS = float(os.getenv("MODIS_TIMEOUT_S", 90))
DELAI_TOPO = float(os.getenv("OPENTOPODATA_TIMEOUT_S", 6))
DOSSIER = CACHE_DIR / "en_ligne"

_verrou = threading.Lock()
_en_cours: set[str] = set()


def actif() -> bool:
    return os.getenv("DONNEES_EN_LIGNE", "1") != "0" and os.getenv("POWER_SIMULE") != "1"


def _fichier(nom: str):
    DOSSIER.mkdir(parents=True, exist_ok=True)
    return DOSSIER / nom


def _lire(nom: str):
    f = DOSSIER / nom
    try:
        return json.loads(f.read_text()) if f.exists() else None
    except (OSError, ValueError):
        return None


def _ecrire(nom: str, valeur) -> None:
    try:
        _fichier(nom).write_text(json.dumps(valeur))
    except OSError:
        pass


def _cle(lat: float, lon: float) -> str:
    return f"{lat:.3f}_{lon:.3f}"


# ------------------------------------------------------------------ humidité du sol (POWER GWETROOT)
def humidite_sol(lat: float, lon: float, fin: int | None = None):
    """Série mensuelle (pandas, index = 1er du mois) de l'humidité racinaire, ou None."""
    if not actif():
        return None
    fin = fin or dt.date.today().year - 1
    nom = f"gwetroot_{lat:.2f}_{lon:.2f}_{fin}.json"
    valeurs = _lire(nom)
    if valeurs is None:
        try:
            r = httpx.get(POWER_MENSUEL, timeout=DELAI_POWER, params={
                "parameters": "GWETROOT", "community": "AG", "latitude": round(lat, 4), "longitude": round(lon, 4),
                "start": fin - 24, "end": fin, "format": "JSON"})
            r.raise_for_status()
            brut = r.json()["properties"]["parameter"]["GWETROOT"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        # Clés AAAAMM ; le mois « 13 » est la moyenne annuelle ; -999 = valeur manquante.
        valeurs = {k: v for k, v in brut.items() if k[4:] != "13" and v is not None and v > -998}
        _ecrire(nom, valeurs)
    if not valeurs:
        return None
    s = pd.Series({pd.Timestamp(int(k[:4]), int(k[4:]), 1): float(v) for k, v in valeurs.items()}).sort_index()
    return s


# ------------------------------------------------------------------ NDVI (MODIS MOD13Q1, ORNL DAAC)
# Composites 16 jours : jours 1, 17, 33… 353. Le service accepte 10 dates au plus par requête.
_TRANCHES = [(1, 145), (161, 305), (321, 366)]


def _telecharger_ndvi(lat: float, lon: float, annee: int) -> dict | None:
    points: dict[int, list[float]] = {}
    with httpx.Client(timeout=DELAI_MODIS, headers={"Accept": "application/json"}) as c:
        for debut, fin in _TRANCHES:
            for essai in range(2):
                try:
                    r = c.get(MODIS, params={"latitude": round(lat, 4), "longitude": round(lon, 4),
                                             "band": "250m_16_days_NDVI", "startDate": f"A{annee}{debut:03d}",
                                             "endDate": f"A{annee}{fin:03d}", "kmAboveBelow": 0, "kmLeftRight": 0})
                    r.raise_for_status()
                    for x in r.json().get("subset", []):
                        v = (x.get("data") or [None])[0]
                        if v is None or v <= -2000:          # -3000 = valeur de remplissage MODIS
                            continue
                        mois = int(x["calendar_date"][5:7])
                        points.setdefault(mois, []).append(v * 0.0001)
                    break
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    if essai == 1:
                        return None
    # Maximum du mois (composition « max-NDVI ») : écarte les images voilées par les nuages en saison des pluies.
    return {str(m): round(max(v), 3) for m, v in sorted(points.items())}


def precharger_ndvi(lat: float, lon: float, annee: int | None = None) -> None:
    """Télécharge le NDVI d'une année (bloquant). Sans effet si déjà en cache ou en cours."""
    if not actif():
        return
    annee = annee or dt.date.today().year - 1
    nom = f"ndvi_{_cle(lat, lon)}_{annee}.json"
    with _verrou:
        if nom in _en_cours or (DOSSIER / nom).exists():
            return
        _en_cours.add(nom)
    try:
        res = _telecharger_ndvi(lat, lon, annee)
        if res:
            _ecrire(nom, res)
    finally:
        with _verrou:
            _en_cours.discard(nom)


def ndvi_mensuel(lat: float, lon: float, annee: int):
    """NDVI mensuel de l'année (pandas), depuis le cache ; sinon lance le téléchargement et renvoie None."""
    if not actif():
        return None
    valeurs = _lire(f"ndvi_{_cle(lat, lon)}_{annee}.json")
    if valeurs is None:
        threading.Thread(target=precharger_ndvi, args=(lat, lon, annee), daemon=True).start()
        return None
    return pd.Series({pd.Timestamp(annee, int(m), 1): float(v) for m, v in valeurs.items()}).sort_index()


# ------------------------------------------------------------------ relief (SRTM 30 m, OpenTopoData)
_ARCSEC = 1 / 3600


def srtm(lat: float, lon: float) -> tuple[float | None, float | None]:
    """(altitude m, pente °) au point, d'après 9 points SRTM espacés d'environ 30 m ; (None, None) sinon."""
    if not actif():
        return None, None
    nom = f"srtm_{lat:.4f}_{lon:.4f}.json"
    cache = _lire(nom)
    if cache:
        return cache["alt"], cache["pente"]
    grille = [(lat + dy * _ARCSEC, lon + dx * _ARCSEC) for dy in (1, 0, -1) for dx in (-1, 0, 1)]
    try:
        r = httpx.get(OPENTOPO, timeout=DELAI_TOPO,
                      params={"locations": "|".join(f"{a:.6f},{b:.6f}" for a, b in grille)})
        r.raise_for_status()
        z = [x["elevation"] for x in r.json()["results"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None, None
    if len(z) != 9 or any(v is None for v in z):
        return None, None
    w = [z[0:3], z[3:6], z[6:9]]                      # ligne 0 = nord
    dy = _ARCSEC * 111_320
    dx = _ARCSEC * 111_320 * math.cos(math.radians(lat))
    gx = ((w[0][2] + 2 * w[1][2] + w[2][2]) - (w[0][0] + 2 * w[1][0] + w[2][0])) / (8 * dx)
    gy = ((w[2][0] + 2 * w[2][1] + w[2][2]) - (w[0][0] + 2 * w[0][1] + w[0][2])) / (8 * dy)
    alt, pente = float(w[1][1]), float(math.degrees(math.atan(math.hypot(gx, gy))))
    _ecrire(nom, {"alt": alt, "pente": pente})
    return alt, pente
