"""Génère une série climatique SYNTHÉTIQUE réaliste pour Mbankomo (Yaoundé), 1995-2024.

Pourquoi : les tests du moteur ne doivent dépendre d'aucune API. Les normales mensuelles
ci-dessous reproduisent le régime bimodal de Yaoundé (ordres de grandeur, pas des mesures).
À remplacer par la vraie série NASA POWER dès que le data-service (T15) la produit :
    python make_synthetic.py            -> site_climat_mbankomo.json, contexte_demo.json
La série est marquée "synthetique": true.
"""
import json
from pathlib import Path

import numpy as np

SEED = 20261115
ANNEES = range(1995, 2025)
# Normales mensuelles approximatives (janvier -> décembre)
PLUIE = [20, 50, 140, 180, 200, 150, 60, 80, 220, 290, 120, 25]          # mm/mois, ~1 535 mm/an
JOURS_PLUIE = [2, 5, 12, 15, 17, 13, 7, 9, 18, 22, 12, 3]
T_MOY = [25.0, 25.8, 25.4, 25.0, 24.6, 23.8, 23.0, 23.1, 23.6, 23.8, 24.3, 24.6]
AMPLITUDE = [12.0, 12.0, 10.5, 9.5, 9.0, 8.5, 8.0, 8.0, 8.5, 8.5, 9.5, 11.5]   # Tmax - Tmin
ET0 = [110, 115, 115, 105, 100, 85, 80, 80, 85, 90, 95, 105]                 # mm/mois
JOURS_MOIS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
TENDANCE_T = 0.02          # °C par an (réchauffement modéré)
SEUILS = (30, 32, 34, 36, 38)


def generer():
    rng = np.random.default_rng(SEED)
    jours = []   # (annee, mois, pluie, tmin, tmax)
    for a in ANNEES:
        facteur_annee = rng.lognormal(0, 0.12)                 # années sèches / humides
        for m in range(12):
            n = JOURS_MOIS[m]
            total = PLUIE[m] * facteur_annee * rng.lognormal(0, 0.25)
            p = min(0.95, JOURS_PLUIE[m] / n)
            humides = rng.random(n) < p
            if not humides.any():
                humides[rng.integers(n)] = total > 5
            poids = rng.gamma(0.8, 1.0, n) * humides
            pluie = total * poids / poids.sum() if poids.sum() > 0 else np.zeros(n)
            tmoy = T_MOY[m] + TENDANCE_T * (a - 1995) + rng.normal(0, 0.4)
            tmax = tmoy + AMPLITUDE[m] / 2 + rng.normal(0, 1.3, n) - 1.2 * (pluie > 10)
            tmin = tmoy - AMPLITUDE[m] / 2 + rng.normal(0, 0.8, n)
            for d in range(n):
                jours.append((a, m + 1, float(pluie[d]), float(tmin[d]), float(tmax[d])))
    humides = np.array([j[2] for j in jours if j[2] >= 1.0])
    p95 = float(np.percentile(humides, 95))
    return jours, p95, rng


def agreger(jours, p95, rng):
    serie = []
    for a in ANNEES:
        for m in range(1, 13):
            js = [j for j in jours if j[0] == a and j[1] == m]
            pluie = np.array([j[2] for j in js])
            tmin = np.array([j[3] for j in js])
            tmax = np.array([j[4] for j in js])
            intense = pluie > p95
            # ET0 : légère hausse avec le réchauffement, plus faible les mois très nuageux (pluvieux)
            ratio = pluie.sum() / max(1.0, PLUIE[m - 1])
            et0 = ET0[m - 1] * (1 + 0.002 * (a - 1995)) * rng.normal(1, 0.05)
            et0 *= 1 - 0.1 * float(np.clip(ratio - 1, -0.5, 1.0))
            serie.append({
                "annee": a, "mois": m,
                "pluie_mm": round(float(pluie.sum()), 1),
                "t_moy_c": round(float(((tmin + tmax) / 2).mean()), 2),
                "t_min_c": round(float(tmin.mean()), 2),
                "t_max_c": round(float(tmax.mean()), 2),
                "et0_mm": round(float(et0), 1),
                "pluie_intense_mm": round(float(pluie[intense].sum()), 1),
                "jours_pluie_intense": int(intense.sum()),
                "jours_chaleur": {str(s): int((tmax > s).sum()) for s in SEUILS},
            })
    return serie


def main():
    jours, p95, rng = generer()
    serie = agreger(jours, p95, rng)
    ici = Path(__file__).parent
    site = {"serie_mensuelle": serie, "saisons": [], "source_status": "live", "synthetique": True}
    (ici / "site_climat_mbankomo.json").write_text(json.dumps(site, ensure_ascii=False, indent=1))
    contexte = {
        "region": "cm_yaounde",
        "premiere_annee": 2027,
        "premiere_saison": "S1",
        "climat": site,
        "sol": {"texture": "argilo-limoneux", "ph": 5.8, "drainage": "moyen", "organic_matter": "moyenne",
                "slope_deg": 3.2, "elevation_m": 742,
                "confidences": {"ph": 1.0, "texture": 1.0, "organic_matter": 1.0, "drainage": 1.0, "slope_deg": 0.7}},
        "eau": {"has_irrigation": False, "dry_season_availability": "faible"},
        "pratiques": {"fertilizer_use": "aucun", "residue_return": 0.5},
        "historique": [{"season_index": -3, "crop_id": "mais"},
                       {"season_index": -2, "crop_id": "mais"},
                       {"season_index": -1, "crop_id": "manioc"}],
        "planned_rotation": [],
        "pest_history": [],
        "poids": {"water_saving": 0.41, "income": 0.24, "soil_health": 0.16,
                  "nitrogen": 0.10, "erosion_control": 0.06, "fodder": 0.03},
        "contraintes": {"equipment": ["houe"], "labor": "familiale", "excluded_crops": ["gombo"],
                        "market_available_crops": ["mais", "niebe", "arachide", "manioc", "patate_douce", "haricot"]},
    }
    (ici / "contexte_demo.json").write_text(json.dumps(contexte, ensure_ascii=False, indent=1))
    annuel = sum(s["pluie_mm"] for s in serie) / len(ANNEES)
    print(f"p95 journalier = {p95:.1f} mm ; pluie annuelle moyenne = {annuel:.0f} mm ; {len(serie)} mois")


if __name__ == "__main__":
    main()
