# AgroRot — Architecture backend (microservices)

NASA Space Apps Challenge 2026 — *Field Shift: Adapting Farms with NASA Data*.
Ce squelette implémente le **Contrat d'API REST v2.0** (14/11/2026) côté public, et sépare le moteur de scoring dans un service à part.

```
                Frontend React
                      │  HTTPS, JSON, JWT  (contrat v2 : /api/v1/...)
                      ▼
          ┌───────────────────────┐
          │  backend   :8000      │  public — auth, fermes, parcelles, saisies,
          │  (FastAPI + SQLite)   │  sauvegardes, PDF ; construit le Contexte
          └──────┬─────────┬──────┘
     HTTP interne│         │HTTP interne
                 ▼         ▼
   ┌──────────────────┐  ┌───────────────────────┐
   │ data-service     │  │ agrorot-core  :8002   │
   │ :8001            │  │ moteur de scoring     │
   │ NASA POWER, GPM, │  │ SANS ÉTAT : reçoit un │
   │ SMAP, NDVI, SRTM,│  │ Contexte, rend des    │
   │ SoilGrids,       │  │ stratégies notées et  │
   │ Meteomatics      │  │ expliquées            │
   │ + cache / Plan B │  │ + CSV de référence    │
   └──────────────────┘  └───────────────────────┘
```

**Règle d'or :** seul le backend est exposé, et lui seul connaît les utilisateurs et les fermes. Le moteur ne voit **jamais** de base de données ni d'API externe : il reçoit toutes ses données dans la requête. On peut donc le tester, le remplacer ou le faire tourner en local sans rien d'autre.

## État d'avancement (15 novembre 2026)

| Lot | Tâches | État | Tests |
|---|---|---|---|
| Phase 0 | T03, T04, T05 | Fait (côté moteur) | — |
| A — data-service | T10 à T17 | Fait ; vérifié sur la vraie API NASA POWER (15/11) | 15 |
| B — agrorot-core | T20 à T34 | Fait ; recalibré sur la vraie série de Mbankomo | 33 |
| C — backend | T40 à T52 | Fait | 15 (bout en bout, 3 services) |
| D — intégration | T60 à T65 | T60 (CI `.github/workflows/ci.yml`), T61 (vraie série en secours), T62 (tests `test_coherence_reel.py`), T64 (`scripts/preparer_demo.py`, `docs/demo.md`) faits ; T63 fait côté backend : kit `frontend-kit/` (types, client, BFF Next 16 testé de bout en bout), reste à brancher dans le dépôt frontend ; T65 fait : surveillance quotidienne de la rotation choisie + notifications (Meteomatics ou Open-Meteo) | — |

Détails : `services/*/README.md`. Vérifier toute la chaîne : `python scripts/verifier_chaine.py [--reel]`.

## Démarrer

```bash
cp .env.example .env
docker compose up --build          # tout
# ou, en développement, un service par terminal :
make dev-core   # :8002
make dev-data   # :8001
make dev-back   # :8000  -> http://localhost:8000/docs
make test       # tests du moteur
```

Tous les services renvoient les erreurs au **format du contrat** (§3.1 : `error.code / message / details / request_id`) et propagent l'en-tête `X-Request-ID`. Un endpoint non encore codé renvoie `501 NOT_IMPLEMENTED` au même format.

---

## Déploiement

Voir `deploy/` : un VPS Linux (2 vCPU, 2–4 Go de RAM suffisent) avec Docker, puis
`docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build`.
Caddy fournit le HTTPS ; seuls les ports 80/443 sont ouverts ; SQLite et le cache NASA vivent dans des
volumes Docker (à sauvegarder). Le frontend peut tourner sur Vercel (`AGROROT_API_URL=https://api.…/api/v1`)
ou sur la même machine. Compose ≥ 2.24 requis pour `!reset`.

## Arborescence

```
agrorot/
├── docker-compose.yml          3 services ; seul backend publie un port
├── .env.example                secrets JWT, délais, identifiants Meteomatics
├── Makefile
├── principe_scoring.pdf        spécification mathématique du moteur
└── services/
    ├── backend/                ── SERVICE PUBLIC (contrat v2)
    │   └── app/
    │       ├── main.py         montage des routeurs sous /api/v1
    │       ├── config.py       URL des services internes, TTL
    │       ├── errors.py       format d'erreur du contrat, X-Request-ID, 422 converties
    │       ├── security.py     JWT, bcrypt, require_role() -> NOT_FARM_MEMBER / FORBIDDEN_ROLE
    │       ├── db/models.py    users, farms, members, parcels, local_inputs, history,
    │       │                   preferences, computations (24 h), saved_strategies, notes
    │       ├── clients/
    │       │   ├── core.py     appels à agrorot-core  -> 503 ENGINE_UNAVAILABLE si panne
    │       │   └── data.py     appels à data-service  -> 503 CLIMATE_DATA_UNAVAILABLE
    │       ├── domain/
    │       │   ├── contexte.py ★ assemble le Contexte moteur (base + data-service)
    │       │   ├── preferences.py  classement -> poids normalisés
    │       │   ├── geometrie.py    Shapely : validité, surface, centroïde, chevauchement
    │       │   └── pdf.py          fiche A4 (reportlab)
    │       └── routers/        auth, referentiel, farms, members, parcels, climate,
    │                           inputs, strategies, saved, health
    │
    ├── data-service/           ── SERVICE INTERNE : données
    │   ├── app/
    │   │   ├── routers/        climate.py, terrain.py, forecast.py
    │   │   ├── sources/        nasa_power, gpm_imerg, smap, modis_ndvi, srtm, soilgrids, meteomatics
    │   │   ├── processing/     et0 (Penman-Monteith FAO-56), saisons, climatologie, qualite
    │   │   └── cache.py        Plan B : live -> fallback_cache -> fallback_local
    │   └── data/fallback/      série de secours pour la démo
    │
    └── agrorot-core/           ── SERVICE INTERNE : moteur (sans état)
        ├── app/
        │   ├── schemas.py      ★ contrat interne (Contexte, requêtes, réponses)
        │   ├── routers/        referentiel, evaluation, strategies
        │   ├── referentiel/loader.py   chargement des CSV au démarrage
        │   └── engine/
        │       ├── pipeline.py     scénario -> précalcul -> génération -> notes -> sélection -> explications
        │       ├── scenario.py     curseurs « Et si… » (pluie, température, horizon)
        │       ├── precalcul.py    table (culture, saison, année) -> eau, chaleur, sol nu
        │       ├── generateur.py   rotations candidates + règles éliminatoires C1..C7
        │       ├── criteres/       s1_climat … s6_priorites, agregation (poids du contrat)
        │       ├── selection.py    recommended + alternative (diversité, Jaccard)
        │       ├── resilience.py   indice 0..1 sous scénarios de stress
        │       ├── confiance.py    score et niveau (élevée / moyenne / faible)
        │       ├── explications.py traces -> why / proofs / benefits / gaps / risks
        │       └── regles.py       catalogue R1..R8, C1..C7 (cité dans les explications)
        ├── config/parametres.yaml  tous les paramètres du scoring (à calibrer)
        ├── data/               crops_cm.csv (= fiche culture), bioagresseurs.csv,
        │                       bioagresseurs_cultures.csv, regions.csv
        └── tests/
```

---

## 1. backend — API publique `/api/v1` (contrat v2)

| § | Méthode et chemin | Rôle | Appelle |
|---|---|---|---|
| 4 | `POST /auth/register` · `/auth/login` · `/auth/refresh` · `/auth/logout` | Comptes et jetons | base |
| 4 | `GET /auth/me` · `POST /auth/forgot-password` · `/auth/reset-password` | Profil, mot de passe | base |
| 5 | `GET /regions` · `GET /crops?region=` | Référentiel | **agrorot-core** `/v1/regions`, `/v1/crops` |
| 6 | `POST/GET /farms` · `GET/PATCH/DELETE /farms/{farm_id}` · `POST …/transfer-ownership` | Fermes | base |
| 6 | `GET/POST /farms/{farm_id}/members` · `PATCH/DELETE …/members/{member_id}` | Membres | base |
| 7 | `POST /parcels` · `GET /farms/{farm_id}/parcels` · `GET/PATCH/DELETE /parcels/{parcel_id}` | Parcelles (Shapely) | base + **data-service** `/v1/terrain` (SRTM) |
| 8 | `GET /parcels/{parcel_id}/climate` | Diagnostic NASA | **data-service** `/v1/climate/diagnostic` |
| 9 | `GET/PUT /parcels/{parcel_id}/local-inputs` · `/history` · `/preferences` | Saisies agriculteur | base |
| 10 | `POST /parcels/{parcel_id}/strategies` | ★ Calcul des 3 stratégies | **data-service** `/v1/climate/series` + **agrorot-core** `/v1/strategies` |
| 11 | `POST …/strategies/save` · `GET …/strategies/saved` · `GET …/saved/{saved_id}` | Sauvegarde (instantané) | base |
| 11 | `POST/DELETE …/saved/{saved_id}/notes[/{note_id}]` · `GET …/export.pdf` | Notes, PDF | base |
| 12 | `GET /health` | État des composants | ping des 2 services |

### Flux de `POST /parcels/{id}/strategies`
1. Vérifie le rôle (`require_role`) et les préconditions (sinon `409 PRECONDITION_FAILED`).
2. Lit la parcelle, `local-inputs`, `history` et `preferences` en base. Les `priorities` et `constraints` de la requête remplacent les préférences pour ce calcul.
3. `GET data-service /v1/climate/series?lat&lon` donne la série mensuelle sur 25 ans, les saisons et `data_source_status`.
4. `domain/contexte.py` assemble le **Contexte**.
5. `POST agrorot-core /v1/strategies` avec le Contexte, `horizon_seasons`, le scénario et `manual_overrides`.
6. Le backend ajoute `computation_id`, `computed_at`, `disclaimer`, les libellés de saison (`2027-S1`…), puis mémorise le résultat 24 h.

## 2. agrorot-core — API interne du moteur (sans état)

| Méthode et chemin | Entrée | Sortie |
|---|---|---|
| `GET /v1/regions` | — | régions prises en charge (`data/regions.csv`) |
| `GET /v1/crops?region=` | — | cultures au format du contrat §5 |
| `GET /v1/pests` | — | bioagresseurs (pour une future saisie « problèmes observés ») |
| `GET /v1/rules` | — | catalogue des règles C1..C7, R1..R8 |
| `POST /v1/evaluate` | `RequeteEvaluation` {contexte, sequence, scenario} | notes S1..S6, score, résilience, confiance, explication |
| `POST /v1/strategies` | `RequeteStrategies` {contexte, horizon_seasons, scenario, sequence_existante?, manual_overrides} | `{applied_scenario, warnings, strategies:[existing, recommended, alternative]}` |
| `GET /health` | — | état et nombre de cultures et bioagresseurs chargés |

Le **Contexte** (`app/schemas.py`) contient tout ce dont le moteur a besoin : série climatique mensuelle et saisons, sol, eau, historique des 3 saisons, poids des priorités, contraintes, bioagresseurs observés.

**Correspondance des priorités du contrat avec les critères du moteur** (`criteres/agregation.py`) :

| Priorité du contrat | Critère |
|---|---|
| `water_saving` | S2 Eau |
| `soil_health` | S3 Fertilité (matière organique) |
| `nitrogen` | S3 Fertilité (azote) |
| `erosion_control` | S4 Érosion |
| `income`, `fodder` | S6 Usages et débouchés |
| *(non réglable)* | S1 Climat et S5 Maladies : poids fixes |

## 3. data-service — API interne des données

| Méthode et chemin | Rôle | Sources |
|---|---|---|
| `GET /v1/climate/series?lat&lon&start_year&end_year` | Série mensuelle sur 20 à 40 ans (pluie, T, ET0, pluies intenses) et saisons détectées : **entrée du moteur** | NASA POWER (+ GPM) |
| `GET /v1/climate/diagnostic?lat&lon` | 12 mois lisibles pour l'écran §8 (normales, SMAP, NDVI, bilan, alertes, glossaire) | POWER, SMAP, MODIS |
| `GET /v1/terrain?lat&lon` | Altitude, pente, sol estimé | SRTM, SoilGrids |
| `GET /v1/forecast/seasonal?lat&lon` | Prévision saisonnière en ensemble *(bonus)* | Meteomatics |
| `GET /v1/forecast/short?lat&lon&days` | Prévision à 14 jours, fenêtre de semis *(bonus)* | Meteomatics |
| `GET /health` | État de NASA POWER et du cache | — |

Chaque réponse climatique porte `data_source_status` (`live`, `fallback_cache` ou `fallback_local`) et `cached_at`, comme l'exige le contrat §3.6.

---

## Écarts entre le contrat v2 et le moteur (à trancher en équipe)

| # | Point | Proposition |
|---|---|---|
| 1 | Le contrat ne permet pas de déclarer des maladies ou ravageurs déjà observés | Ajouter `pest_history: [id]` à `local-inputs` (liste via `GET /pests`). Le Contexte a déjà le champ `bioagresseurs_observes`. |
| 2 | Les textures du contrat (`argilo-limoneux`…) diffèrent de celles d'ECOCROP (`lourde / moyenne / légère`) | Table de correspondance dans `referentiel/` |
| 3 | `horizon_years` 5 ou 10 dans le scénario | Extrapoler la tendance observée (récent contre ancien) et l'ajouter aux deltas |
| 4 | « Saison à venir » avec Meteomatics absente du contrat | Ajouter plus tard `GET /parcels/{id}/season-outlook` ; data-service est déjà prêt |
| 5 | Les explications citent « Règle R1, R2, R5 » | Le catalogue est dans `engine/regles.py` ; aligner la numérotation avec le cahier des charges |
| 6 | `crops_cm.csv` | C'est notre `fiche_culture.csv` renommé ; y ajouter crotalaire, mucuna et la colonne `ky` |
| 7 | SMAP et NDVI « pré-agrégés » | Préparer à l'avance des fichiers pour la région `cm_yaounde`, servis par data-service |

## Ordre d'implémentation conseillé

1. **data-service** `/v1/climate/series` : NASA POWER, ET0 et saisons, avec un cache disque.
2. **agrorot-core** : `precalcul` → S2 eau → S5 maladies → les autres critères → `generateur` → `selection` → `explications`.
3. **backend** : `strategies` et `contexte` d'abord, avec une parcelle de démo en dur, puis auth, fermes et parcelles.
4. Diagnostic climat, sauvegarde, PDF.
5. Bonus : Meteomatics.
