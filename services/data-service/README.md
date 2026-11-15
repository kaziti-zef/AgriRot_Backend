# data-service — données climatiques et terrain

Service interne. Récupère NASA POWER, calcule l'ET0 et les saisons, prépare la série mensuelle que le moteur lit telle quelle, et applique le Plan B du contrat (live → cache → jeu de secours → 503).

Tâches du plan couvertes : **T10 à T17** (T16 en partie : SRTM et SMAP/NDVI lus seulement si les fichiers pré-agrégés existent). Tests : `pytest` (15 tests, ~3 s, sans réseau : POWER est simulé au format exact de l'API).

```bash
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --port 8001
python ../../scripts/verifier_chaine.py --reel   # VRAI appel NASA POWER puis moteur (Internet requis)
```

## Routes

| Route | Rôle | Appelée par le backend |
|---|---|---|
| `POST /v1/climate/prefetch?lat&lon` | Télécharge 30 ans de POWER (délai 120 s) et remplit le cache | À la création d'une parcelle (T44) |
| `GET /v1/climate/series?lat&lon[&start_year&end_year]` | `site_climat` à passer **tel quel** dans `Contexte.climat` du moteur, + statut et qualité | Avant chaque calcul de stratégies (T48) |
| `GET /v1/climate/diagnostic?lat&lon[&year]` | Format §8 du contrat (12 mois, normales, alertes, périodes vulnérables, glossaire) | `GET /parcels/{id}/climate` (T50) |
| `GET /v1/terrain?lat&lon` | Altitude et pente (SRTM local), avertissements `SRTM_UNAVAILABLE`, `OUTSIDE_COVERED_REGION` | Création de parcelle (T44) |
| `GET /v1/forecast/daily?lat&lon&past_days=30&days=10` | Météo récente + prévision quotidienne (t_max, t_min, pluie, ET0) et normales NASA POWER par mois | Meteomatics si `METEOMATICS_USER/PASSWORD`, sinon Open-Meteo (sans clé, usage non commercial) ; `PREVISION_SIMULEE` pour tests/démo ; `status: unavailable` si rien ne répond |
| `GET /v1/forecast/seasonal` | Prévision saisonnière (bonus) — non implémenté | — |

## Pourquoi un préchargement

30 ans de données journalières POWER prennent souvent plus de 5 secondes à arriver. Le délai de 5 s du contrat (§3.6) s'applique donc aux lectures. Le téléchargement complet se fait une fois, avec un délai long, à l'enregistrement de la parcelle. Le cache est considéré frais 7 jours ; au-delà, POWER est rappelé, et en cas d'échec l'ancien cache est servi (`fallback_cache`).

## Chaîne de calcul

| Étape | Fichier | Détail |
|---|---|---|
| Client POWER | `sources/nasa_power.py` | `T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS2M, ALLSKY_SFC_SW_DWN`, communauté AG ; `-999` → manquant |
| Cache et Plan B | `cache.py` | Clé = coordonnées arrondies à 0,5° + période ; secours : `data/fallback/cm_yaounde_daily.csv.gz` |
| Nettoyage | `processing/qualite.py` | Trous ≤ 2 jours interpolés (sauf la pluie) |
| ET0 | `processing/et0.py` | Penman-Monteith FAO-56 journalier (testé sur l'exemple 18 : 3,88 pour 3,9) ; repli Hargreaves |
| Agrégation | `processing/climatologie.py` | Mensuel, mois `ok` si ≥ 80 % de jours valides, mois isolé reconstitué, pluies intenses (> 95e centile), jours de chaleur (30 à 38 °C) |
| Saisons | `processing/saisons.py` | Mois humide si 0,8 × P ≥ 0,75 × ET0 ; plus longue suite dans chaque fenêtre (S1 : fév.–juil., S2 : juil.–déc.) |
| Pré-agrégés | `sources/pre_agreges.py` | SMAP, NDVI (xarray), SRTM (rasterio) — facultatifs |

## À faire / limites

- **Jeu de secours = vraie série NASA POWER** de Mbankomo (1996–2025, cellule 4,0° N / 11,5° E), téléchargée le 15/11/2026 (`data/fallback/cm_yaounde_daily.csv.gz`). Le simulateur `tests/power_simule.py` ne sert plus qu'aux tests.
- **Vérifié sur la vraie API** (15/11/2026) : 10 958 jours, aucun mois manquant, ET0 Penman-Monteith, 1 458 mm/an, 59 saisons détectées sur 60.
- **POWER lisse la petite saison sèche** (juillet : 117 mm, août : 161 mm, contre nettement moins au sol à Yaoundé). Le moteur garde donc le calendrier régional quand la détection le contredit. Brancher IMERG (pluie à 10 km, satellites) améliorerait la pluie de juillet-août.
- **Altitude** : celle de la cellule POWER (589 m) ; l'altitude de la parcelle viendra de SRTM.
- **IMERG non branché** : les pluies intenses viennent de la pluie journalière POWER (Plan B prévu au plan). Lire `imerg_daily.csv` est une amélioration possible.
- **SoilGrids non branché** : le sol vient des saisies de l'agriculteur (`local-inputs`).
- **Code non testé contre la vraie API** depuis l'environnement de développement (pas d'accès Internet) : le format suit la documentation officielle de POWER ; `verifier_chaine.py --reel` le confirme en une commande.
