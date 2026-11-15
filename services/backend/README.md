# backend — API publique AgroRot (contrat v2)

Implémente les 39 opérations du **Contrat d'API REST v2.0** sous `/api/v1`. Délègue les données climatiques au data-service et le calcul au moteur agrorot-core.

Tâches du plan couvertes : **T40 à T52**. Tests : `pytest` (15 tests de bout en bout, ~8 s). Ils lancent pour de vrai agrorot-core et data-service (uvicorn), avec NASA POWER simulé (`POWER_SIMULE=1`) et une base SQLite temporaire.

```bash
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --port 8000       # http://localhost:8000/docs
```

Schéma OpenAPI complet pour le frontend : `../../docs/openapi.json`.

## Organisation

| Fichier | Rôle |
|---|---|
| `errors.py` | Format §3 : codes métier, 422 → `details.fields[]` (`required`, `too_short`, `out_of_range`…), JSON illisible → 400 `INVALID_REQUEST`, `X-Request-ID` |
| `security.py` | bcrypt, JWT 60 min, renouvellement 7 jours, limitation 5 échecs / 15 min (`429` + `Retry-After`), matrice des rôles §2, `If-Match` → `VERSION_CONFLICT` |
| `db/models.py` | Utilisateurs, fermes, membres, parcelles, saisies (JSON), calculs (24 h), stratégies retenues (instantanés), notes |
| `domain/geometrie.py` | Shapely : validité, 3 sommets, 0,01 à 1 000 ha (projection UTM), chevauchement ; un anneau non fermé est refermé |
| `domain/preferences.py` | Classement → poids ROC (reproduit les poids de l'exemple du contrat) |
| `domain/contexte.py` | Construit le `Contexte` du moteur (saisies + série climatique + corrections de l'agriculteur) |
| `domain/pdf.py` | Fiche A4 (reportlab) |
| `clients/core.py`, `clients/data.py` | Appels internes ; pannes → `ENGINE_UNAVAILABLE` / `CLIMATE_DATA_UNAVAILABLE` ; 2 nouvelles tentatives sur les lectures climatiques |

## Écarts et ajouts par rapport au contrat v2 (à communiquer au frontend)

| Endroit | Ajout | Pourquoi |
|---|---|---|
| `PUT /local-inputs` | `practices: {fertilizer_use, residue_return}`, `pest_history: [ids]`, `planned_rotation: [{season, crop_id}]` | Extensions décidées au plan (engrais, maladies déjà vues, rotation prévue) |
| `nasa_overrides[].field` | `temp_avg_c` (°C, ±5) en plus de `rain_mm` (%, ±100) | Correction de la température |
| Chaque stratégie (§10) | `scores` (S1–S6), `delta_vs_existing`, `violations`, `off_rotation_advice` ; dans `sequence` : `sowing_month`, `harvest_month`, `continuation` | Détail pour les écrans de comparaison |
| `warnings` (§10) | `SYNTHETIC_CLIMATE` | Série climatique simulée (jeu de secours) |
| `GET /parcels/{id}/climate` | `?year=`, `year`, `synthetique`, `monthly_series[].corrected_by_user` | Diagnostic d'une autre année ; corrections visibles |
| `GET /api/v1/health` | `cache` = état du data-service | Le cache vit dans le data-service |
| `GET /parcels/{id}/strategies/computed/{computation_id}` | Nouvelle route : relit un calcul non sauvegardé (24 h) | Page de détail `/strategies/{type}?c=…` sans relancer le moteur (guide frontend) |
| `Accept-Language: en` | Messages d'erreur, avertissements et disclaimer en anglais ; explications du moteur toujours en français | Guide frontend §i18n |
| Surveillance (T65) | `GET /parcels/{id}/monitoring`, `POST /parcels/{id}/monitoring/run[?date=AAAA-MM-JJ]`, `PUT /parcels/{id}/strategies/saved/{saved_id}/monitoring {active}` ; `POST …/strategies/save` accepte `monitor` (défaut `true`) et renvoie `monitoring_active` | La rotation choisie est vérifiée chaque jour contre la météo récente et prévue |
| Notifications (T65) | `GET /notifications[?unread_only&severity&cursor&limit]`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | Le contrat n'avait pas de route ; une notification par membre de la ferme |
| `DATABASE_URL` | Accepte `postgres://…` / `postgresql://…` (pilote psycopg 3) en plus de SQLite | Hébergeurs sans disque persistant |
| `POST /parcels` | Lance en arrière-plan le préchargement de 30 ans de NASA POWER | Les calculs suivants répondent en ~1 s |

## Points d'attention

- **Mot de passe oublié** : sans service d'e-mail, le lien de réinitialisation est écrit dans les journaux du serveur (priorité C du contrat).
- **Invitations** : le lien renvoyé est `PUBLIC_URL/invite/<jeton>` ; l'inscription avec le même identifiant (ou avec `invitation_token`) active l'invitation.
- **CORS** : origines autorisées dans `CORS_ORIGINS` (défaut `http://localhost:3000`, Next.js).
- **Base** : SQLite par défaut (`DATABASE_URL`) ; tables créées au démarrage, pas de migration pour le hackathon.


## Surveillance de la rotation choisie (T65)

Sauvegarder une stratégie la rend « surveillée » (une seule par parcelle). Une tournée tourne dans le backend
au démarrage (+1 min) puis toutes les `MONITORING_INTERVAL_HOURS` heures (24 par défaut, 0 = désactivée) ;
`POST /parcels/{id}/monitoring/run` vérifie immédiatement. Chaque vérification :

1. date la rotation (labels `2027-S1` + mois de semis/récolte) et situe le jour : `not_started`,
   `sowing_window` (21 j avant à 10 j après le semis prévu), `in_crop`, `between_crops`, `finished` ;
2. lit `GET /v1/forecast/daily` du data-service : 30 jours passés + 10 jours prévus (Meteomatics si
   identifiants, sinon Open-Meteo ; normales NASA POWER) ;
3. applique les règles de `app/domain/surveillance.py` (seuils en tête du fichier) :

| Code | Gravité | Déclencheur |
|---|---|---|
| `SOWING_FAVORABLE` / `SOWING_DELAY` | info / avertissement | fenêtre de semis : pluie 10 j passés + 7 j prévus ≥ 40 mm / < 20 mm |
| `WATER_STRESS` | avertissement / critique | culture en place, sans irrigation : Kc × ET0 − 80 % de la pluie − 30 mm de réserve, sur 14 j passés + 7 j prévus, au-delà de 35/70 mm (seuils plus bas ou plus hauts selon la sensibilité à la sécheresse) |
| `HEAVY_RAIN` | avertissement / critique | un jour prévu ≥ 50 / 80 mm ; conseils selon la pente et la tolérance à l'engorgement |
| `HEAT_STRESS` | avertissement | ≥ 2 jours prévus au-dessus de l'optimum de la culture + 3 °C |
| `SEASON_ANOMALY` / `ROTATION_MISMATCH` | info / critique | pluie des 30 derniers jours < 60 % ou > 160 % de la normale : le moteur réévalue la rotation « si la saison continue ainsi » ; critique si la note baisse ≥ 10 points ou si la saison en cours/suivante passe sous 50 (le scénario proposé est dans `data.suggested_scenario`) |

4. enregistre l'état (`GET …/monitoring`) et crée une notification par membre actif, sans doublon sur 7 jours.

Les textes sont en français ; le `code` et `data` permettent au frontend de les traduire.
Démo hors ligne : `PREVISION_SIMULEE=sec|pluie_forte|chaleur|normal` pour le data-service et
`?date=` sur `monitoring/run` (la prévision est alors recalée sur la date simulée).
