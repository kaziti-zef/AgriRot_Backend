# agrorot-core — moteur de scoring des rotations

Service interne, **sans état et sans réseau** : il reçoit un `Contexte` complet (climat déjà récupéré + saisies de l'agriculteur) et renvoie la rotation existante critiquée, une stratégie recommandée et une alternative, notées et expliquées.

Tâches du plan couvertes : **T03 (côté moteur), T04, T05, T20 à T34**. Tests : `pytest` (33 tests, ~10 s, sans réseau), dont 8 sur la vraie série NASA POWER de Mbankomo.

```bash
pip install -r requirements.txt
pytest                                    # tests unitaires + tests d'acceptation 4, 5, 6, 7, 8, 9, 11
uvicorn app.main:app --reload --port 8002 # http://localhost:8002/docs
```

## Routes

| Route | Rôle |
|---|---|
| `POST /v1/strategies` | `RequeteStrategies` → existante + recommandée + alternative (contrat §10) |
| `POST /v1/evaluate` | `RequeteEvaluation` → note et explique UNE séquence |
| `GET /v1/regions`, `/v1/crops?region=`, `/v1/pests`, `/v1/rules` | Référentiel |
| `GET /health` | État |

Exemples complets de requêtes et réponses : `../../contracts/core_*.json`.

## Fichiers

```
app/
├── schemas.py              contrat interne (T03) — Contexte, requêtes, réponses
├── params.py               chargement des paramètres et calendriers
├── referentiel/loader.py   T20 — catalogue, bioagresseurs, conversions catégories → nombres
├── engine/
│   ├── scenario.py         T21 — climat en tableaux (années × 12 mois), curseurs « Et si… », tendance
│   ├── aptitude.py         T22 — pré-filtre A(c) (trapèzes température et pluie)
│   ├── temps.py            T23 — calendrier, saisons → mois, cultures longues sur plusieurs saisons
│   ├── precalcul.py        T24 — table (culture, saison, année) : eau FAO-56, chaleur, couverture
│   ├── contraintes.py      T25 — C1 à C6 (C0 = culture exclue)
│   ├── criteres/s1…s6      T26 à T31 — les six notes, avec leurs phrases d'explication
│   ├── evaluation.py       T32 — note globale, pénalité de non-admissibilité, résilience, confiance
│   ├── generateur.py       T33 — recherche en faisceau, choix de l'alternative
│   ├── explications.py     T34 — traces → why / proofs / benefits / information_gaps / local_risks_to_check
│   └── pipeline.py         T33-T34 — orchestration, modifications manuelles, avertissements
config/parametres.yaml      tous les paramètres (à calibrer en T62)
data/                       crops_cm.csv, bioagresseurs*.csv, calendrier_cm_yaounde.yaml, correspondances.yaml
tests/fixtures/             série climatique SYNTHÉTIQUE de Mbankomo + contexte de démo (make_synthetic.py)
```

## Ce que le backend doit envoyer (rappel)

- `contexte.climat.serie_mensuelle` : 20 à 40 années complètes, avec `et0_mm`, `pluie_intense_mm` et `jours_chaleur` (`{"30": n, "32": n, "34": n, "36": n, "38": n}`). Sans `jours_chaleur`, le stress thermique est ignoré et signalé.
- `premiere_annee` et `premiere_saison` : pour les libellés `2027-S1`.
- `poids` : les poids ROC du contrat (somme 1). Vide → pondération équilibrée.
- Extensions au contrat v2 : `planned_rotation`, `pest_history`, `pratiques.fertilizer_use`, `pratiques.residue_return`.

## Ajouts par rapport au contrat v2 (dans chaque stratégie)

`scores` (S1 à S6), `delta_vs_existing`, `violations`, `off_rotation_advice`, et dans `sequence` : `sowing_month`, `harvest_month`, `continuation`. Avertissement supplémentaire `SYNTHETIC_CLIMATE` tant que la série de test est utilisée.

## Décisions de calibrage prises pendant le développement (à valider en T62)

| Point | Choix | Pourquoi |
|---|---|---|
| Échelle de S5 (`pi0`) | 6 | Les nématodes à galles ont presque toutes les cultures pour hôtes modérés ; avec 3, même une bonne rotation plafonnait à 34 |
| Pénalité de non-admissibilité | G × (1 − 0,10 par règle dure violée et par culture), max − 50 % | Sinon maïs-maïs (inadmissible) n'était qu'à 4 points de la meilleure rotation |
| Saisons sans production | Jachère + plantes de service : au plus 1 saison sur 4 | Sinon « sol d'abord » recommandait presque que de la jachère |
| Alternative | ≥ 50 % des saisons différentes ET au moins un tiers de cultures différentes | Sinon l'alternative était parfois la recommandée décalée d'une saison |
| Cultures longues (C2) | Cycle ≥ 200 j ; traversée de la saison sèche permise sauf sensibilité « forte » | Manioc gardé ; macabo semé en S2 exclu (traverse janvier) |
| Calendrier Yaoundé | S1 : semis mars, pluies jusqu'en juin ; S2 : semis août, pluies jusqu'en novembre | À confirmer (FAO Crop Calendar, IRAD) |
| Saisons détectées | Appliquées seulement si cohérentes avec le calendrier régional (± 1 mois, S2 après S1) | Sur la vraie série POWER, la petite saison sèche de juillet est lissée : la détection aurait placé le semis de S2 en juillet |
| Note Climat (S1) | Adéquation progressive (trapèze ECOCROP) au lieu de « dans la plage / hors plage » | Sur les vraies températures (22,5–25 °C), le niébé était à 0 % d'adéquation alors qu'il est cultivé autour de Yaoundé |
| Bilan hydrique (S2) | Réserve du sol reportée d'un mois à l'autre, plafonnée à 0,5 × eau utile (selon la texture) × profondeur racinaire | Sans réserve, le manioc ne réussissait que 4 années sur 10 en S1 sur la vraie série (FAO-56 ch. 8) |
| Seuil d'une « bonne année » (S2) | 65 % du besoin couvert pour les cultures peu sensibles à la sécheresse, 80 % sinon | Manioc, patate douce, plantes de service réduisent leur feuillage puis reprennent (Ky < 1) |
| Cultures très courtes (≤ 60 j) | Seule la borne basse de pluie annuelle ECOCROP est utilisée | Le folon (45 j) était exclu à Yaoundé (1 458 mm > 700 mm « maximum ») alors qu'on en cultive partout |
| pH de l'igname | 5,5–6,5 au lieu de 6,4–6,7 (colonne `a_verifier` renseignée) | La plage ECOCROP excluait l'igname de presque tous les sols de Yaoundé |
| Mucuna en scénario sec | Conservé | Vérifié : en S1 (−30 % de pluie, +2 °C) il couvre son besoin aussi souvent que le maïs ; peu sensible à la sécheresse. Le choix revient aux priorités (S6) de l'exploitant |

## Limites connues

- **Deux séries de test** : `site_climat_mbankomo.json` (synthétique, tests unitaires) et `site_climat_mbankomo_reel.json` (vraie série NASA POWER 1996–2025, tests de cohérence T62 dans `test_coherence_reel.py`). La confiance est abaissée de 0,2 quand `synthetique = true`.
- **Mucuna en scénario très sec** : la plante de couverture reste proposée même quand elle manque d'eau la plupart des années (son rôle est la couverture, pas la récolte) ; le risque est signalé dans `local_risks_to_check`. À discuter.
- **Manioc et sécheresse** : le bilan FAO-56 (Kc constant en saison sèche) le pénalise un peu trop ; en réalité il perd ses feuilles et résiste. Sa faible sensibilité (η = 0,5) compense en partie.
- **Données ECOCROP discutables** : l'igname a une plage de pH de 6,4 à 6,7 et se trouve exclue des sols acides de Yaoundé ; la pluviométrie du folon est irréaliste (il est exclu). À corriger dans `crops_cm.csv` après avis agronomique.
- En zone humide, l'eau limite peu les cultures courtes : S2 discrimine surtout les cultures longues et les scénarios secs. C'est attendu.
- 6 saisons : ~1 s ; 12 saisons : ~2 s.
