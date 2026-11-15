# Kit d'intégration frontend (Next.js 16)

À copier dans le dépôt du frontend : le dossier `src/` de ce kit se superpose au `src/` existant
(aucun fichier existant n'est écrasé).

```
src/app/api/v1/[...path]/route.ts   BFF : relais vers le backend, jetons en cookies httpOnly, 1 renouvellement
src/lib/api/session.server.ts       lecture / écriture des cookies (serveur uniquement)
src/lib/api/server-fetch.ts         apiServeur() pour les Server Components
src/lib/api/client.ts               api() pour le navigateur : Accept-Language, X-Request-ID, If-Match, 2 réessais sur 503
src/lib/api/endpoints.ts            une fonction par route (auth, farms, parcels, inputs, strategies…)
src/lib/api/errors.ts               ApiError, fieldErrors (422), reaction() selon le contrat §3.8
src/lib/api/adapters.ts             points de carte -> GeoJSON, priorités, historique, substitutions
src/lib/api/types.ts                types des réponses (champs null compris)
src/lib/api/schema.gen.ts           types générés depuis docs/openapi.json (ne pas éditer)
```

## Installation

```bash
npm i server-only
# .env.local  (SANS préfixe NEXT_PUBLIC_ : l'URL du backend reste côté serveur)
AGROROT_API_URL=http://localhost:8000/api/v1
```

Régénérer les types après une modification de l'API :
`npx openapi-typescript ../agrorot/docs/openapi.json -o src/lib/api/schema.gen.ts`

## Vérifié

- `tsc --strict` et `next build` (Next 16.x, React 19) sans erreur ;
- parcours réel navigateur → BFF → backend → moteur : inscription (2 cookies httpOnly posés),
  `/auth/me`, ferme, parcelle, calcul en anglais, relecture du calcul, cookie d'accès supprimé →
  renouvellement automatique transparent, erreur traduite, `/auth/refresh` bloqué côté navigateur,
  sauvegarde + PDF (`application/pdf`), déconnexion → 401.

Non vérifié : l'intégration dans VOTRE code (je n'ai pas le dépôt). Le `proxy.ts` de locale ne doit pas
réécrire `/api/*` : ajoutez `api` aux exclusions de son `matcher` si besoin.

## Remplacer les mocks : écran → appel

| Écran | Appels |
|---|---|
| Connexion / Inscription | `endpoints.auth.login` / `register` → `{ user }` ; puis `router.push("/[lang]/farms")` |
| Mot de passe oublié | `auth.forgotPassword`, `auth.resetPassword(token, mdp)` |
| Liste des fermes | `farms.list()` ; création `farms.create(nom, "cm_yaounde")` |
| Membres | `farms.members`, `addMember` (404 USER_NOT_FOUND → proposer l'invitation : la réponse 201 `status: "pending"` contient `invitation.link`) |
| Carte / parcelles | `parcels.listAll(farmId)` ; création `parcels.create(farmId, nom, pointsVersPolygone(points))`. Afficher `area_ha` et `centroid` **de la réponse** |
| Diagnostic climat | `parcels.climate(id)` ; bandeau si `data_source_status !== "live"` ; toute valeur peut être `null` → afficher « — » |
| Terrain (sol, eau, pratiques) | `inputs.getLocal` puis `inputs.putLocal(id, corps, version)` |
| Historique | `inputs.putHistory(id, historiqueVersApi([c1, c2, c3]), version)` |
| Priorités | `inputs.putPreferences(id, prioritesVersPreferences(ordre, exclues), version)` |
| Stratégies (comparaison) | `strategies.compute(id, { horizon_seasons: 4, climate_scenario })` |
| Modifier une culture | `strategies.compute(id, { manual_overrides: substitutionsVersOverrides(subs) })` |
| Détail d'une stratégie | voir « Navigation » ci-dessous |
| Sauvegarder | `strategies.save(id, computation_id, "recommended", note?)` |
| Historique des plans | `strategies.saved(id)`, `savedDetail`, `addNote`, PDF : `window.open(strategies.pdfUrl(...))` |

### Navigation vers le détail (conflit relevé dans le guide)

La route UI `/strategies/{existing|recommended|alternative}` n'identifie pas un calcul. Deux cas :

- **calcul non sauvegardé** : mettre l'identifiant dans l'URL,
  `/strategies/recommended?c=<computation_id>`, et charger `strategies.computed(parcelId, c)` (**route
  ajoutée**, conservée 24 h ; 404 STRATEGY_NOT_FOUND → bouton « Relancer le calcul ») ;
- **plan sauvegardé** : `/history/<saved_id>` → `strategies.savedDetail(parcelId, savedId)`.

### Concurrence (If-Match)

Toujours renvoyer la `version` lue. Sur `VERSION_CONFLICT` (409) : `reaction(e) === "reload_conflict"` →
recharger la ressource et proposer de réappliquer la saisie.

### Erreurs

```ts
try { await endpoints.inputs.putLocal(id, corps, version); }
catch (e) {
  if (e instanceof ApiError) switch (reaction(e)) {
    case "highlight_fields": setErreurs(e.fieldErrors); break;     // { "soil.ph": "…" }
    case "relogin": router.push(`/${lang}/login`); break;
    case "wait": toast(`${e.message} (${e.retryAfter}s)`); break;
    default: toast(`${e.message} — code ${e.requestId}`);
  }
}
```

## Ce que le serveur renvoie en plus du contrat v2

- `strategy.scores` (S1…S6 sur 100) et `delta_vs_existing` : graphique radar / barres ; libellés dans `CRITERES` ;
- `violations`, `off_rotation_advice`, `sequence[].sowing_month / harvest_month / continuation`
  (une culture longue occupe plusieurs saisons : afficher « suite » plutôt qu'un doublon) ;
- `local-inputs.practices`, `pest_history`, `planned_rotation` ;
- `monthly_series[].corrected_by_user`.

## Langue

`Accept-Language: en` traduit les messages d'erreur, les avertissements et le disclaimer. **Les textes
d'explication du moteur (why, proofs, benefits…) et les noms de cultures restent en français** :
point ouvert, à traiter si le jury est anglophone.

## Surveillance et notifications (ajout T65)

| Écran | Appels |
|---|---|
| Cloche / liste des notifications | `endpoints.notifications.list({ unreadOnly })`, `unreadCount()` (à interroger toutes les 1–5 min), `markRead(id)`, `markAllRead()` |
| Parcelle : « Suivi de ma rotation » | `endpoints.monitoring.get(parcelId)` → phase, culture en place, météo 30 j / 7 j, alertes avec conseils |
| Bouton « Vérifier maintenant » | `endpoints.monitoring.run(parcelId)` (démo : `run(parcelId, "2027-03-10")`) |
| Arrêter / reprendre le suivi | `endpoints.monitoring.setActive(parcelId, savedId, false)` |
| Alerte `ROTATION_MISMATCH` | bouton « Relancer le calcul » : `strategies.compute(parcelId, { climate_scenario: alert.data.suggested_scenario })` |

Sauvegarder une stratégie la met sous surveillance par défaut (`save(…, monitor = true)`).
Les textes sont en français : pour l'anglais, traduire à partir de `code` et `data`.
