"""T64 - Prépare la démo via l'API publique : compte, ferme, conseiller, parcelle de Mbankomo,
saisies, premier calcul (qui remplit le cache NASA POWER).

    python scripts/preparer_demo.py [--url http://localhost:8000] [--surveillance]

--surveillance : retient la stratégie recommandée et lance la surveillance à deux dates simulées
(fenêtre de semis, puis un mois après), pour que des notifications soient visibles pendant la démo.

Les trois services doivent tourner (docker compose up, ou trois terminaux : voir docs/demo.md).
Identifiants créés : demo@agrorot.cm / demo-agrorot-2026 et conseiller@agrorot.cm / demo-agrorot-2026.
"""
import sys
import time

import httpx

URL = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else "http://localhost:8000"
API = URL + "/api/v1"
MDP = "demo-agrorot-2026"
PARCELLE = {"type": "Polygon", "coordinates": [[[11.451, 3.812], [11.453, 3.812], [11.453, 3.814], [11.451, 3.814],
                                                 [11.451, 3.812]]]}


def ok(r: httpx.Response, *attendus):
    if r.status_code not in (attendus or (200, 201, 204)):
        sys.exit(f"Échec {r.request.method} {r.request.url} -> {r.status_code} {r.text[:300]}")
    return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None


def compte(c, nom, ident):
    r = c.post(f"{API}/auth/register", json={"full_name": nom, "identifier": ident, "password": MDP})
    if r.status_code == 409:
        r = c.post(f"{API}/auth/login", json={"identifier": ident, "password": MDP})
    return ok(r)["access_token"]


def main():
    with httpx.Client(timeout=200) as c:
        print("Santé :", ok(c.get(f"{API}/health")))
        tok = compte(c, "Jean Mbarga (démo)", "demo@agrorot.cm")
        h = {"Authorization": f"Bearer {tok}"}
        fermes = ok(c.get(f"{API}/farms", headers=h))["farms"]
        ferme = next((f for f in fermes if f["name"] == "Ferme de Mbankomo"), None) or \
            ok(c.post(f"{API}/farms", json={"name": "Ferme de Mbankomo", "region": "cm_yaounde"}, headers=h))
        fid = ferme["id"]
        conseiller = compte(c, "A. Fouda (IRAD, démo)", "conseiller@agrorot.cm")
        c.post(f"{API}/farms/{fid}/members", json={"identifier": "conseiller@agrorot.cm", "role": "advisor"}, headers=h)
        parcelles = ok(c.get(f"{API}/farms/{fid}/parcels", headers=h))["parcels"]
        p = next((x for x in parcelles if x["name"] == "Parcelle Bas-Fond Nord"), None) or \
            ok(c.post(f"{API}/parcels", json={"farm_id": fid, "name": "Parcelle Bas-Fond Nord", "geometry": PARCELLE},
                      headers=h))
        pid = p["id"]
        ok(c.put(f"{API}/parcels/{pid}/local-inputs", headers=h, json={
            "soil": {"texture": "argilo-limoneux", "ph": 5.8, "drainage": "moyen", "organic_matter": "moyenne",
                     "slope_deg": 3.2, "slope_confirmed": True},
            "water": {"has_irrigation": False, "dry_season_availability": "faible"},
            "practices": {"fertilizer_use": "aucun", "residue_return": 0.5}, "pest_history": [], "planned_rotation": []}))
        ok(c.put(f"{API}/parcels/{pid}/history", headers=h, json={"seasons": [
            {"season_index": -3, "label": "2025-S2", "crop_id": "mais"},
            {"season_index": -2, "label": "2026-S1", "crop_id": "mais"},
            {"season_index": -1, "label": "2026-S2", "crop_id": "manioc"}]}))
        ok(c.put(f"{API}/parcels/{pid}/preferences", headers=h, json={
            "ranking": ["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"],
            "constraints": {"equipment": ["houe"], "labor": "familiale", "excluded_crops": ["gombo"],
                            "market_available_crops": ["mais", "niebe", "arachide", "manioc", "patate_douce", "haricot"]}}))
        print("Premier calcul (télécharge NASA POWER si le cache est vide, jusqu'à 2 minutes)...")
        t = time.time()
        r = ok(c.post(f"{API}/parcels/{pid}/strategies", json={"horizon_seasons": 6}, headers=h))
        print(f"  {time.time() - t:.1f} s, données : {r['data_source_status']}")
        for s in r["strategies"]:
            print(f"  {s['name'][:46]:46} {s['score']:5}  {[e['crop_id'] for e in s['sequence']]}")
        if "--surveillance" in sys.argv:
            rec = next(s for s in r["strategies"] if s["id"] == "recommended")
            ok(c.post(f"{API}/parcels/{pid}/strategies/save", headers=h, json={
                "computation_id": r["computation_id"], "strategy_id": "recommended", "monitor": True}), 201)
            debut = next(e for e in rec["sequence"] if not e["continuation"] and e["sowing_month"])
            annee, mois = int(debut["label"][:4]), debut["sowing_month"]
            for date in (f"{annee}-{mois:02d}-10", f"{annee}-{mois + 1:02d}-20"):
                st = ok(c.post(f"{API}/parcels/{pid}/monitoring/run", params={"date": date}, headers=h))["state"]
                print(f"Surveillance au {date} ({st['position']['phase']}, météo {st['weather']['status']}) :")
                for a in st["alerts"] or [{"severity": "-", "title": "aucune alerte"}]:
                    print(f"  [{a['severity']}] {a['title']}")
        print(f"\nPrêt. Ferme {fid}, parcelle {pid}.\nComptes : demo@agrorot.cm et conseiller@agrorot.cm, mot de passe {MDP}")
        _ = conseiller


if __name__ == "__main__":
    main()
