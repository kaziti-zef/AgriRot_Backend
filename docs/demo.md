# Démo AgroRot — préparation et déroulé (T64)

## La veille

1. Lancer les trois services :
   - avec Docker : `cp .env.example .env` puis `docker compose up --build` ;
   - sans Docker, trois terminaux :
     ```
     cd services/agrorot-core  && uvicorn app.main:app --port 8002
     cd services/data-service  && uvicorn app.main:app --port 8001
     cd services/backend       && uvicorn app.main:app --port 8000
     ```
2. `python scripts/preparer_demo.py` : crée le compte, la ferme, le conseiller, la parcelle de Mbankomo et les saisies, puis lance un premier calcul qui remplit le cache NASA POWER.
3. Lancer le frontend Next.js (variable d'URL de l'API sur `http://localhost:8000/api/v1`).
4. Vérifier `http://localhost:8000/api/v1/health` : tout doit être `ok`.

## Juste avant de présenter

- `GET /api/v1/health` une dernière fois.
- **Réseau incertain ?** Rien à faire : sans NASA POWER, le data-service sert le cache (`fallback_cache`), sinon la vraie série de Yaoundé embarquée (`fallback_local`). Le bandeau correspondant s'affiche, le calcul fonctionne.
- Comptes : `demo@agrorot.cm` (agriculteur) et `conseiller@agrorot.cm` (conseiller), mot de passe `demo-agrorot-2026`.

### Préparer l'étape 8 (surveillance)

En novembre, la rotation commence en mars : rien à surveiller « aujourd'hui ». Pour la démo, simuler une date :

```bash
# data-service lancé avec PREVISION_SIMULEE=sec (20 jours sans pluie) — ou la vraie prévision si le réseau est bon
curl -X POST "http://localhost:8000/api/v1/parcels/<parcel_id>/monitoring/run?date=2027-03-10" -H "Authorization: Bearer <jeton>"
curl -X POST "http://localhost:8000/api/v1/parcels/<parcel_id>/monitoring/run?date=2027-04-20" -H "Authorization: Bearer <jeton>"
```

Les notifications apparaissent pour l'agriculteur et le conseiller (marquées « date simulée » dans `data`).

## Déroulé proposé (5 minutes)

| Étape | Ce qu'on montre | Message |
|---|---|---|
| 1. Carte | La parcelle de Mbankomo tracée point par point | Tout part de la parcelle réelle de l'agriculteur |
| 2. Diagnostic | 12 mois NASA : pluie, ET0, bilan, saison sèche déc.–fév. | 30 ans de données NASA POWER sur ce point précis |
| 3. Saisies | Sol, historique maïs-maïs-manioc, priorité « économiser l'eau » | L'agriculteur corrige et complète le satellite |
| 4. Stratégies | Actuelle ~65, recommandée ~85, alternative ~85 | 3 options comparées, chacune expliquée : pourquoi, preuves, bénéfices, lacunes, risques |
| 5. « Et si… » | Pluie −30 %, +2 °C, horizon 10 ans | La rotation actuelle perd ~15 points (eau : 97 → 67), la recommandée tient (~85) : c'est la résilience |
| 6. Modification | Remplacer une culture à la main, la note se recalcule | L'agriculteur garde la main |
| 7. Retenir + PDF | Sauvegarde, note de validation du conseiller, fiche A4 | Un outil d'aide, validé par l'expertise locale |
| 8. Surveillance | Cloche de notifications : « Retarder le semis », « Manque d'eau probable », « Votre rotation n'est plus bien adaptée » (score 85 → x, bouton « Relancer le calcul ») | Après le choix, l'outil veille chaque jour : météo des 30 derniers jours + prévision à 10 jours |

## À dire au jury

- Ce que la NASA apporte : POWER (température, pluie, rayonnement, vent, humidité → ET0 FAO-56), et selon les fichiers préparés, SMAP, MODIS NDVI, SRTM.
- Pas de « boîte noire » : un moteur de règles agronomiques ; chaque phrase d'explication vient d'une règle et d'un chiffre.
- Honnêteté : niveau de confiance, données manquantes listées, « à valider localement ».
