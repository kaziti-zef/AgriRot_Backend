"""Test de recette du backend AgroRot : parcourt TOUTES les fonctions de l'API, comme un utilisateur,
et affiche OK / ÉCHEC pour chacune. Les 3 services doivent tourner.

    python scripts/tester_backend.py                       # backend sur http://localhost:8000
    python scripts/tester_backend.py --url http://IP:8000  # serveur distant
    python scripts/tester_backend.py --garder              # ne supprime pas les données de test à la fin

Le script crée ses propres comptes (adresse unique à chaque lancement) : il ne touche pas aux données de démo.
Code de sortie : 0 si tout passe, 1 sinon.
"""
import os
import sys
import time

import httpx

if os.name == "nt":                                      # accents et ✓ dans la console Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

URL = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else "http://localhost:8000"
API = URL.rstrip("/") + "/api/v1"
GARDER = "--garder" in sys.argv
MDP = "test-agrorot-2026"
TAG = str(int(time.time()))
PARCELLE = {"type": "Polygon", "coordinates": [[[11.451, 3.812], [11.453, 3.812], [11.453, 3.814], [11.451, 3.814],
                                                 [11.451, 3.812]]]}
RESULTATS: list[tuple[str, bool, str]] = []


def etape(nom: str, condition: bool, detail: str = ""):
    RESULTATS.append((nom, bool(condition), detail))
    print(f"  {'OK    ' if condition else 'ÉCHEC '} {nom}" + (f"  ({detail})" if detail else ""))
    return condition


def code(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["code"]
    except Exception:  # noqa: BLE001
        return str(r.status_code)


def main() -> int:
    c = httpx.Client(timeout=200)
    print(f"Test du backend {API}\n")

    print("1. Santé")
    try:
        s = c.get(f"{API}/health").json()
    except httpx.HTTPError as e:
        print(f"  Backend injoignable : {e}\n  -> lancez les 3 services (voir le guide, partie 3).")
        return 1
    comp = s["components"]
    etape("le backend répond", True, s["status"])
    etape("base de données", comp["database"] == "ok", comp["database"])
    etape("moteur (agrorot-core)", comp["engine"] == "ok", comp["engine"])
    etape("cache climatique (data-service)", comp["cache"] == "ok", comp["cache"])
    print(f"  INFO   NASA POWER en direct : {comp['nasa_power']} (« error » est normal hors ligne : le secours prend le relais)")

    print("\n2. Comptes et connexion")
    r = c.post(f"{API}/auth/register", json={"full_name": "Testeur AgroRot", "identifier": f"test{TAG}@agrorot.cm",
                                             "password": MDP})
    etape("inscription", r.status_code == 201, str(r.status_code))
    tok = r.json()["access_token"]
    refresh = r.json()["refresh_token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = c.post(f"{API}/auth/login", json={"identifier": f"test{TAG}@agrorot.cm", "password": MDP})
    etape("connexion", r.status_code == 200)
    etape("mauvais mot de passe refusé", code(c.post(f"{API}/auth/login", json={"identifier": f"test{TAG}@agrorot.cm",
                                                                                "password": "faux-mot-de-passe"})) == "INVALID_CREDENTIALS")
    etape("profil (/auth/me)", c.get(f"{API}/auth/me", headers=h).json().get("identifier") == f"test{TAG}@agrorot.cm")
    etape("renouvellement du jeton", c.post(f"{API}/auth/refresh", json={"refresh_token": refresh}).status_code == 200)
    etape("accès sans jeton refusé", code(c.get(f"{API}/farms")) == "TOKEN_INVALID")
    r = c.post(f"{API}/auth/register", json={"full_name": "Conseiller Test", "identifier": f"conseil{TAG}@agrorot.cm",
                                             "password": MDP})
    h_cons = {"Authorization": f"Bearer {r.json()['access_token']}"}

    print("\n3. Référentiel")
    regions = c.get(f"{API}/regions", headers=h).json()["regions"]
    etape("régions", any(x["code"] == "cm_yaounde" for x in regions))
    crops = c.get(f"{API}/crops", params={"region": "cm_yaounde"}, headers=h).json()["crops"]
    etape("cultures de Yaoundé", len(crops) >= 15, f"{len(crops)} cultures")

    print("\n4. Ferme, membres, parcelle")
    ferme = c.post(f"{API}/farms", json={"name": f"Ferme test {TAG}", "region": "cm_yaounde"}, headers=h).json()
    fid = ferme.get("id")
    etape("création de la ferme", bool(fid))
    r = c.post(f"{API}/farms/{fid}/members", json={"identifier": f"conseil{TAG}@agrorot.cm", "role": "advisor"}, headers=h)
    etape("ajout d'un conseiller", r.status_code == 201)
    r = c.post(f"{API}/farms/{fid}/members", json={"identifier": f"inconnu{TAG}@agrorot.cm", "role": "co_farmer"}, headers=h)
    etape("invitation d'une personne sans compte", r.status_code in (201, 404), code(r) if r.status_code != 201 else "lien créé")
    r = c.post(f"{API}/parcels", json={"farm_id": fid, "name": "Parcelle test", "geometry": PARCELLE}, headers=h)
    p = r.json()
    pid = p.get("id")
    etape("création de la parcelle", r.status_code == 201, f"{p.get('area_ha')} ha")
    croise = {"type": "Polygon", "coordinates": [[[11.45, 3.81], [11.46, 3.82], [11.45, 3.82], [11.46, 3.81], [11.45, 3.81]]]}
    etape("polygone invalide refusé", code(c.post(f"{API}/parcels", json={"farm_id": fid, "name": "X", "geometry": croise},
                                                  headers=h)) == "INVALID_POLYGON")
    etape("le conseiller ne peut pas créer de parcelle", code(c.post(
        f"{API}/parcels", json={"farm_id": fid, "name": "Y", "geometry": PARCELLE}, headers=h_cons)) == "FORBIDDEN_ROLE")

    print("\n5. Diagnostic climatique (premier appel : jusqu'à 2 minutes si NASA POWER télécharge 30 ans)")
    t = time.time()
    r = c.get(f"{API}/parcels/{pid}/climate", headers=h)
    d = r.json()
    etape("diagnostic 12 mois", r.status_code == 200 and len(d.get("monthly_series", [])) == 12,
          f"{time.time() - t:.1f} s, source {d.get('data_source_status')}")

    print("\n6. Saisies de l'agriculteur")
    loc = c.get(f"{API}/parcels/{pid}/local-inputs", headers=h).json()
    r = c.put(f"{API}/parcels/{pid}/local-inputs", headers={**h, "If-Match": str(loc["version"])}, json={
        "soil": {"texture": "argilo-limoneux", "ph": 5.8, "drainage": "moyen", "organic_matter": "moyenne",
                 "slope_deg": 3.2, "slope_confirmed": True},
        "water": {"has_irrigation": False, "dry_season_availability": "faible"},
        "practices": {"fertilizer_use": "organique", "residue_return": 0.5}, "nasa_overrides": []})
    etape("sol, eau, pratiques", r.status_code == 200, f"confiance {r.json().get('parcel_confidence', {}).get('level')}")
    corps = {k: r.json()[k] for k in ("soil", "water", "practices", "nasa_overrides")}
    etape("conflit de version détecté", code(c.put(f"{API}/parcels/{pid}/local-inputs",
                                                   headers={**h, "If-Match": "999"}, json=corps)) == "VERSION_CONFLICT")
    r = c.put(f"{API}/parcels/{pid}/local-inputs", headers=h, json={**loc, "soil": {**loc["soil"], "ph": 14}})
    etape("valeur impossible refusée (pH 14)", r.status_code in (409, 422), code(r))
    r = c.put(f"{API}/parcels/{pid}/history", headers=h, json={"seasons": [
        {"season_index": -3, "crop_id": "mais"}, {"season_index": -2, "crop_id": "mais"}, {"season_index": -1, "crop_id": "manioc"}]})
    etape("historique des 3 dernières saisons", r.status_code == 200)
    r = c.put(f"{API}/parcels/{pid}/preferences", headers=h, json={
        "ranking": ["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"],
        "constraints": {"equipment": [], "labor": "familiale", "excluded_crops": ["gombo"],
                        "market_available_crops": ["mais", "niebe", "arachide", "manioc"]}})
    etape("priorités et cultures exclues", r.status_code == 200)

    print("\n7. Stratégies")
    t = time.time()
    r = c.post(f"{API}/parcels/{pid}/strategies", json={"horizon_seasons": 6}, headers=h)
    res = r.json()
    ok = etape("calcul des 3 stratégies", r.status_code == 200 and len(res.get("strategies", [])) == 3,
               f"{time.time() - t:.1f} s")
    if not ok:
        print("   ", r.text[:300])
        return bilan()
    for s in res["strategies"]:
        print(f"         {s['name'][:48]:48} {s['score']:5.1f}  {[e['crop_id'] for e in s['sequence']]}")
    ex, reco, alt = res["strategies"]
    etape("la recommandée fait mieux que l'existante", reco["score"] >= ex["score"], f"{ex['score']} -> {reco['score']}")
    etape("chaque stratégie est expliquée", all(s["explanation"]["why"] for s in res["strategies"][1:]))
    etape("aucune culture exclue proposée", all(e["crop_id"] != "gombo" for s in res["strategies"][1:] for e in s["sequence"]))
    r = c.post(f"{API}/parcels/{pid}/strategies", headers=h, json={
        "horizon_seasons": 6, "climate_scenario": {"rain_delta_pct": -30, "temp_delta_c": 2, "horizon_years": 10}})
    sec = r.json()["strategies"]
    etape("scénario « et si » (−30 % de pluie, +2 °C)", r.status_code == 200,
          f"existante {sec[0]['score']}, recommandée {sec[1]['score']}")
    etape("scénario hors limites refusé", code(c.post(f"{API}/parcels/{pid}/strategies", headers=h, json={
        "climate_scenario": {"rain_delta_pct": -80, "temp_delta_c": 0, "horizon_years": 0}})) in ("INVALID_SCENARIO", "VALIDATION_ERROR"))
    r = c.post(f"{API}/parcels/{pid}/strategies", headers=h, json={
        "horizon_seasons": 6, "manual_overrides": {"recommended": {"2": "niebe"}}})
    mod = r.json()
    etape("modification manuelle d'une culture", r.status_code == 200 and mod["strategies"][1]["sequence"][1]["crop_id"] == "niebe")
    cid = mod["computation_id"]
    etape("relecture d'un calcul", c.get(f"{API}/parcels/{pid}/strategies/computed/{cid}", headers=h).status_code == 200)
    r = c.post(f"{API}/parcels/{pid}/strategies", headers={**h, "Accept-Language": "en"}, json={"horizon_seasons": 4})
    etape("messages en anglais", r.json().get("disclaimer", "").startswith("Decision"))

    print("\n8. Sauvegarde, notes, PDF")
    r = c.post(f"{API}/parcels/{pid}/strategies/save", headers=h,
               json={"computation_id": res["computation_id"], "strategy_id": "recommended", "note": "Test de recette"})
    sid = r.json().get("saved_id")
    etape("sauvegarde de la recommandée", r.status_code == 201 and r.json().get("monitoring_active"))
    r = c.post(f"{API}/parcels/{pid}/strategies/saved/{sid}/notes", headers=h_cons,
               json={"kind": "validation", "text": "Validé par le conseiller (test)."})
    etape("note de validation du conseiller", r.status_code == 201)
    etape("historique des plans", len(c.get(f"{API}/parcels/{pid}/strategies/saved", headers=h).json()["saved"]) >= 1)
    r = c.get(f"{API}/parcels/{pid}/strategies/saved/{sid}/export.pdf", headers=h)
    etape("export PDF", r.status_code == 200 and r.content[:4] == b"%PDF", f"{len(r.content) // 1024} Ko")

    print("\n9. Surveillance et notifications")
    m = c.get(f"{API}/parcels/{pid}/monitoring", headers=h).json()
    etape("la rotation sauvegardée est surveillée", m["active"] and m["saved_id"] == sid)
    premiere = next(e for e in reco["sequence"] if not e["continuation"] and e["sowing_month"])
    annee, mois = int(premiere["label"][:4]), premiere["sowing_month"]
    for date, phase in ((f"{annee}-{mois:02d}-10", "sowing_window"), (f"{annee}-{mois + 1:02d}-20", "in_crop")):
        r = c.post(f"{API}/parcels/{pid}/monitoring/run", params={"date": date}, headers=h)
        st = r.json().get("state") or {}
        alertes = ", ".join(a["code"] for a in st.get("alerts", [])) or "aucune alerte"
        etape(f"vérification au {date}", r.status_code == 200 and st["position"]["phase"] == phase,
              f"météo {st.get('weather', {}).get('status')} ; {alertes}")
    if st.get("weather", {}).get("status") == "unavailable":
        print("  INFO   Prévision indisponible (pas d'Internet, ou Open-Meteo/Meteomatics bloqués) : aucune alerte possible.\n"
              "         Pour tester hors ligne : relancer le data-service avec PREVISION_SIMULEE=sec.")
    n = c.get(f"{API}/notifications", headers=h_cons).json()
    etape("le conseiller voit les notifications", "unread_count" in n, f"{n.get('unread_count')} non lue(s)")
    etape("tout marquer comme lu", c.post(f"{API}/notifications/read-all", headers=h_cons).status_code == 204)

    if not GARDER:
        print("\n10. Nettoyage")
        etape("suppression de la parcelle", c.delete(f"{API}/parcels/{pid}", headers=h).status_code == 204)
        etape("suppression de la ferme", c.request("DELETE", f"{API}/farms/{fid}", headers=h,
                                                    json={"confirm_name": f"Ferme test {TAG}"}).status_code == 204)
    return bilan()


def bilan() -> int:
    echecs = [n for n, ok, _ in RESULTATS if not ok]
    print(f"\n{len(RESULTATS) - len(echecs)}/{len(RESULTATS)} vérifications réussies.")
    if echecs:
        print("Échecs :\n  - " + "\n  - ".join(echecs) + "\nVoir la partie « Dépannage » du guide de test.")
        return 1
    print("Le backend fonctionne.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
