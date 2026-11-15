"""Parcours complet du contrat v2 et tests d'acceptation 1, 3, 6, 7, 10 de la spécification backend."""
import pytest

POLY = {"type": "Polygon", "coordinates": [[[11.451, 3.812], [11.453, 3.812], [11.453, 3.814], [11.451, 3.814],
                                            [11.451, 3.812]]]}
CROISE = {"type": "Polygon", "coordinates": [[[11.46, 3.82], [11.462, 3.822], [11.462, 3.82], [11.46, 3.822],
                                              [11.46, 3.82]]]}
ETAT = {}


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def inscrire(client, nom, ident, mdp="motdepasse123"):
    r = client.post("/api/v1/auth/register", json={"full_name": nom, "identifier": ident, "password": mdp})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ §4 authentification
def test_01_inscription_connexion(client):
    j = inscrire(client, "Jean Mbarga", "Jean.Mbarga@exemple.cm")
    assert j["user"]["identifier"] == "jean.mbarga@exemple.cm" and j["token_type"] == "bearer"
    ETAT["owner"] = j["access_token"]
    ETAT["refresh"] = j["refresh_token"]
    r = client.post("/api/v1/auth/register", json={"full_name": "Xavier", "identifier": "jean.mbarga@exemple.cm",
                                                    "password": "motdepasse123"})
    assert r.json()["error"]["code"] == "ACCOUNT_ALREADY_EXISTS"
    r = client.post("/api/v1/auth/register", json={"full_name": "Yves", "identifier": "y@x.cm", "password": "court"})
    assert r.status_code == 422 and r.json()["error"]["details"]["fields"][0]["reason"] == "too_short"
    assert client.get("/api/v1/auth/me", headers=h(ETAT["owner"])).json()["full_name"] == "Jean Mbarga"
    assert client.get("/api/v1/auth/me").json()["error"]["code"] == "TOKEN_INVALID"
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": ETAT["refresh"]})
    assert r.status_code == 200 and r.json()["access_token"]


def test_02_limitation_des_tentatives(client):
    inscrire(client, "Paul", "+237 6 99 00 00 01")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"identifier": "699000001", "password": "faux-mdp"})
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    r = client.post("/api/v1/auth/login", json={"identifier": "699000001", "password": "motdepasse123"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


# ------------------------------------------------------------------ §5 / §6
def test_03_referentiel_et_ferme(client):
    assert client.get("/api/v1/regions").json()["regions"][0]["code"] == "cm_yaounde"
    crops = client.get("/api/v1/crops", params={"region": "cm_yaounde"}).json()["crops"]
    assert {"mais", "niebe", "manioc"} <= {c["id"] for c in crops}
    assert client.get("/api/v1/crops", params={"region": "xx"}).json()["error"]["code"] == "REGION_NOT_SUPPORTED"
    r = client.post("/api/v1/farms", json={"name": "Ferme de Mbankomo", "region": "cm_yaounde"}, headers=h(ETAT["owner"]))
    assert r.status_code == 201 and r.json()["user_role"] == "owner"
    ETAT["farm"] = r.json()["id"]


def test_04_membres_et_invitation(client):
    f = ETAT["farm"]
    r = client.post(f"/api/v1/farms/{f}/members", json={"identifier": "conseiller.irad@exemple.cm", "role": "advisor"},
                    headers=h(ETAT["owner"]))
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["invitation"]["link"]
    ETAT["advisor"] = inscrire(client, "A. Fouda", "conseiller.irad@exemple.cm")["access_token"]
    ETAT["cofarmer"] = inscrire(client, "Marie", "marie@exemple.cm")["access_token"]
    r = client.post(f"/api/v1/farms/{f}/members", json={"identifier": "marie@exemple.cm", "role": "co_farmer"},
                    headers=h(ETAT["owner"]))
    assert r.json()["status"] == "active"
    membres = client.get(f"/api/v1/farms/{f}/members", headers=h(ETAT["advisor"])).json()["members"]
    assert {m["status"] for m in membres} == {"active"}
    r = client.post(f"/api/v1/farms/{f}/members", json={"identifier": "marie@exemple.cm", "role": "advisor"},
                    headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "MEMBER_ALREADY_EXISTS"
    r = client.delete(f"/api/v1/farms/{f}/members/me", headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "LAST_OWNER"


# ------------------------------------------------------------------ §7 parcelles (acceptation 1)
def test_05_parcelles(client):
    f = ETAT["farm"]
    r = client.post("/api/v1/parcels", json={"farm_id": f, "name": "Croisée", "geometry": CROISE},
                    headers=h(ETAT["owner"]))
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_POLYGON"
    r = client.post("/api/v1/parcels", json={"farm_id": f, "name": "Parcelle Bas-Fond Nord", "geometry": POLY},
                    headers=h(ETAT["cofarmer"]))
    assert r.status_code == 201, r.text
    p = r.json()
    assert 4.5 < p["area_ha"] < 5.1 and p["centroid"] == {"lat": 3.813, "lon": 11.452}
    assert any(w["code"] == "SRTM_UNAVAILABLE" for w in p["warnings"])
    ETAT["parcel"] = p["id"]
    autre = {"type": "Polygon", "coordinates": [[[11.452, 3.813], [11.455, 3.813], [11.455, 3.815], [11.452, 3.815]]]}
    r = client.post("/api/v1/parcels", json={"farm_id": f, "name": "Chevauche", "geometry": autre},
                    headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "PARCEL_OVERLAP"
    r = client.post("/api/v1/parcels", json={"farm_id": f, "name": "parcelle bas-fond nord", "geometry": CROISE},
                    headers=h(ETAT["advisor"]))
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"
    lst = client.get(f"/api/v1/farms/{f}/parcels", headers=h(ETAT["advisor"])).json()
    assert len(lst["parcels"]) == 1 and lst["next_cursor"] is None


# ------------------------------------------------------------------ §9 saisies (acceptation 10)
def test_06_saisies(client):
    p = ETAT["parcel"]
    loc = {"soil": {"texture": "argilo-limoneux", "ph": 5.8, "drainage": "moyen", "organic_matter": "moyenne",
                    "slope_deg": 3.2, "slope_confirmed": True},
           "water": {"has_irrigation": False, "dry_season_availability": "faible"},
           "nasa_overrides": [{"field": "rain_mm", "month": 3, "mode": "adjustment", "value": -10}],
           "practices": {"fertilizer_use": "aucun", "residue_return": 0.5}}
    r = client.put(f"/api/v1/parcels/{p}/local-inputs", json=loc, headers=h(ETAT["owner"]))
    assert r.status_code == 200 and r.json()["version"] == 1
    assert r.json()["parcel_confidence"]["level"] == "élevée" and r.json()["defaults_used"] == []
    r = client.put(f"/api/v1/parcels/{p}/local-inputs", json=loc, headers={**h(ETAT["owner"]), "If-Match": "7"})
    assert r.status_code == 409 and r.json()["error"]["details"] == {"current_version": 1, "your_version": 7}
    bad = {**loc, "soil": {**loc["soil"], "ph": 12}}
    r = client.put(f"/api/v1/parcels/{p}/local-inputs", json=bad, headers=h(ETAT["owner"]))
    assert r.status_code == 422 and r.json()["error"]["details"]["fields"][0]["path"] == "soil.ph"
    hist = {"seasons": [{"season_index": -3, "label": "2025-S2", "crop_id": "mais"},
                        {"season_index": -2, "label": "2026-S1", "crop_id": "mais"},
                        {"season_index": -1, "label": "2026-S2", "crop_id": "manioc"}]}
    assert client.put(f"/api/v1/parcels/{p}/history", json=hist, headers=h(ETAT["owner"])).status_code == 200
    r = client.put(f"/api/v1/parcels/{p}/history", json={"seasons": [{"season_index": -1, "crop_id": "ble"}]},
                   headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "CROP_NOT_FOUND"
    pref = {"ranking": ["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"],
            "constraints": {"equipment": ["houe"], "labor": "familiale", "excluded_crops": ["gombo"],
                            "market_available_crops": ["mais", "niebe", "arachide", "manioc", "patate_douce", "haricot"]}}
    r = client.put(f"/api/v1/parcels/{p}/preferences", json=pref, headers=h(ETAT["owner"]))
    assert r.json()["weights"] == {"water_saving": 0.41, "income": 0.24, "soil_health": 0.16, "nitrogen": 0.10,
                                   "erosion_control": 0.06, "fodder": 0.03}
    r = client.put(f"/api/v1/parcels/{p}/preferences", json=pref, headers=h(ETAT["advisor"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_ROLE"          # acceptation 10


# ------------------------------------------------------------------ §8 diagnostic
def test_07_diagnostic(client):
    r = client.get(f"/api/v1/parcels/{ETAT['parcel']}/climate", headers=h(ETAT["advisor"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["parcel_id"] == ETAT["parcel"] and len(d["monthly_series"]) == 12 and d["data_source_status"] == "live"
    assert d["monthly_series"][2].get("corrected_by_user")                                # correction de mars


# ------------------------------------------------------------------ §10 stratégies (acceptation 6, 7)
def test_08_strategies(client):
    p = ETAT["parcel"]
    body = {"horizon_seasons": 6, "climate_scenario": {"rain_delta_pct": -15, "temp_delta_c": 1.5, "horizon_years": 5}}
    r = client.post(f"/api/v1/parcels/{p}/strategies", json=body, headers=h(ETAT["advisor"]))
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["computation_id"].startswith("cmp_") and res["disclaimer"]
    assert [s["id"] for s in res["strategies"]] == ["existing", "recommended", "alternative"]
    assert res["strategies"][0]["violations"] and res["strategies"][1]["score"] > res["strategies"][0]["score"]
    assert res["strategies"][1]["sequence"][0]["label"].endswith("-S1")
    for s in res["strategies"][1:]:
        assert all(e["crop_id"] != "gombo" for e in s["sequence"])
    ETAT["cmp"] = res["computation_id"]
    r = client.post(f"/api/v1/parcels/{p}/strategies", json={**body, "manual_overrides": {"recommended": {"2": "niebe"}}},
                    headers=h(ETAT["owner"]))
    seq = r.json()["strategies"][1]["sequence"]
    assert seq[1]["crop_id"] == "niebe" and seq[1]["modified_by_user"]
    ETAT["cmp_modifie"] = r.json()["computation_id"]
    relu = client.get(f"/api/v1/parcels/{p}/strategies/computed/{ETAT['cmp_modifie']}", headers=h(ETAT["advisor"]))
    assert relu.status_code == 200 and relu.json()["strategies"][1]["sequence"][1]["crop_id"] == "niebe"
    en = client.post(f"/api/v1/parcels/{p}/strategies", json={"horizon_seasons": 4},
                     headers={**h(ETAT["owner"]), "Accept-Language": "en"}).json()
    assert en["disclaimer"].startswith("Decision-support")
    r = client.post(f"/api/v1/parcels/{p}/strategies", json={"manual_overrides": {"recommended": {"2": "gombo"}}},
                    headers=h(ETAT["owner"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "EXCLUDED_CROP"
    r = client.post(f"/api/v1/parcels/{p}/strategies", json={"climate_scenario": {"rain_delta_pct": -60}},
                    headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "INVALID_SCENARIO"


# ------------------------------------------------------------------ §11 sauvegarde, notes, PDF
def test_09_sauvegarde_notes_pdf(client):
    p = ETAT["parcel"]
    r = client.post(f"/api/v1/parcels/{p}/strategies/save",
                    json={"computation_id": ETAT["cmp_modifie"], "strategy_id": "recommended",
                          "note": "Labour léger avant le semis de S1."}, headers=h(ETAT["owner"]))
    assert r.status_code == 201, r.text
    sid = r.json()["saved_id"]
    assert r.json()["pdf_export_url"].endswith(f"/saved/{sid}/export.pdf")
    r = client.post(f"/api/v1/parcels/{p}/strategies/save", json={"computation_id": ETAT["cmp"], "strategy_id": "existing"},
                    headers=h(ETAT["advisor"]))
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"
    r = client.post(f"/api/v1/parcels/{p}/strategies/save", json={"computation_id": "cmp_inexistant",
                                                                   "strategy_id": "existing"}, headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "STRATEGY_NOT_FOUND"
    r = client.post(f"/api/v1/parcels/{p}/strategies/saved/{sid}/notes",
                    json={"kind": "validation", "text": "Validé lors de la visite terrain."}, headers=h(ETAT["advisor"]))
    assert r.status_code == 201 and r.json()["author"]["role"] == "advisor"
    r = client.post(f"/api/v1/parcels/{p}/strategies/saved/{sid}/notes",
                    json={"kind": "observation", "text": "x"}, headers=h(ETAT["advisor"]))
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"
    r = client.post(f"/api/v1/parcels/{p}/strategies/saved/{sid}/notes",
                    json={"kind": "validation", "text": "x" * 1001}, headers=h(ETAT["advisor"]))
    assert r.status_code == 422
    lst = client.get(f"/api/v1/parcels/{p}/strategies/saved", headers=h(ETAT["cofarmer"])).json()["saved"]
    assert lst[0]["notes_count"] == 2 and not lst[0]["outdated_geometry"]
    d = client.get(f"/api/v1/parcels/{p}/strategies/saved/{sid}", headers=h(ETAT["advisor"])).json()
    assert d["sequence"][1]["crop_id"] == "niebe" and len(d["notes"]) == 2
    r = client.get(f"/api/v1/parcels/{p}/strategies/saved/{sid}/export.pdf", headers=h(ETAT["advisor"]))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    ETAT["saved"] = sid


def test_09b_surveillance_et_notifications(client):
    """T65 : la stratégie sauvegardée est surveillée ; météo simulée « sec » (20 jours sans pluie)."""
    p, sid = ETAT["parcel"], ETAT["saved"]
    e = client.get(f"/api/v1/parcels/{p}/monitoring", headers=h(ETAT["advisor"])).json()
    assert e["saved_id"] == sid and e["active"]
    assert e["state"]["position"]["phase"] == "not_started" and e["state"]["alerts"] == []   # 1re vérif. de fond
    premier = e["state"]["position"]["next"]
    assert premier["label"].endswith("-S1")
    annee = int(premier["label"][:4])
    # fenêtre de semis : 5 jours avant la date prévue, rien n'est tombé -> retarder le semis
    r = client.post(f"/api/v1/parcels/{p}/monitoring/run", params={"date": f"{annee}-03-10"}, headers=h(ETAT["owner"]))
    assert r.status_code == 200, r.text
    st = r.json()["state"]
    codes = {a["code"] for a in st["alerts"]}
    assert st["position"]["phase"] == "sowing_window" and "SOWING_DELAY" in codes, st
    assert st["weather"]["status"] == "simulated" and st["weather"]["rain_ratio_30d"] < 0.6
    assert codes & {"ROTATION_MISMATCH", "SEASON_ANOMALY"} and st["evaluation"]["drop"] is not None
    # chaque membre reçoit les notifications ; une 2e vérification ne crée pas de doublon
    n1 = client.get("/api/v1/notifications", headers=h(ETAT["advisor"])).json()
    assert n1["unread_count"] >= 2 and n1["notifications"][0]["data"]["simulated_date"]
    client.post(f"/api/v1/parcels/{p}/monitoring/run", params={"date": f"{annee}-03-10"}, headers=h(ETAT["owner"]))
    assert client.get("/api/v1/notifications/unread-count", headers=h(ETAT["advisor"])).json()["unread_count"] == n1["unread_count"]
    assert client.get("/api/v1/notifications", headers=h(ETAT["cofarmer"])).json()["unread_count"] == n1["unread_count"]
    # culture en place un mois après le semis : manque d'eau
    st = client.post(f"/api/v1/parcels/{p}/monitoring/run", params={"date": f"{annee}-04-20"},
                     headers=h(ETAT["owner"])).json()["state"]
    assert st["position"]["phase"] == "in_crop" and "WATER_STRESS" in {a["code"] for a in st["alerts"]}, st
    # lecture
    n = client.get("/api/v1/notifications", params={"unread_only": True, "limit": 1}, headers=h(ETAT["advisor"])).json()
    assert len(n["notifications"]) == 1 and n["next_cursor"]
    assert client.post(f"/api/v1/notifications/{n['notifications'][0]['id']}/read", headers=h(ETAT["advisor"])).status_code == 204
    assert client.post(f"/api/v1/notifications/{n['notifications'][0]['id']}/read", headers=h(ETAT["owner"])).status_code == 404
    client.post("/api/v1/notifications/read-all", headers=h(ETAT["advisor"]))
    assert client.get("/api/v1/notifications/unread-count", headers=h(ETAT["advisor"])).json()["unread_count"] == 0
    # arrêt de la surveillance (exploitants seulement)
    r = client.put(f"/api/v1/parcels/{p}/strategies/saved/{sid}/monitoring", json={"active": False}, headers=h(ETAT["advisor"]))
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"
    r = client.put(f"/api/v1/parcels/{p}/strategies/saved/{sid}/monitoring", json={"active": False}, headers=h(ETAT["owner"]))
    assert r.json()["active"] is False
    r = client.post(f"/api/v1/parcels/{p}/monitoring/run", headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "PRECONDITION_FAILED"
    client.put(f"/api/v1/parcels/{p}/strategies/saved/{sid}/monitoring", json={"active": True}, headers=h(ETAT["owner"]))


def test_10_modification_contour(client):
    p = ETAT["parcel"]
    v = client.get(f"/api/v1/parcels/{p}", headers=h(ETAT["owner"])).json()["version"]
    nouveau = {"type": "Polygon", "coordinates": [[[11.451, 3.812], [11.4535, 3.812], [11.4535, 3.8145],
                                                   [11.451, 3.8145], [11.451, 3.812]]]}
    r = client.patch(f"/api/v1/parcels/{p}", json={"geometry": nouveau}, headers={**h(ETAT["owner"]), "If-Match": str(v)})
    assert r.status_code == 200 and r.json()["version"] == v + 1
    lst = client.get(f"/api/v1/parcels/{p}/strategies/saved", headers=h(ETAT["owner"])).json()["saved"]
    assert lst[0]["outdated_geometry"]


# ------------------------------------------------------------------ §12 santé et pannes (acceptation 3)
def test_11_sante(client):
    r = client.get("/api/v1/health").json()
    assert r["components"]["database"] == "ok" and r["components"]["engine"] == "ok"
    assert r["components"]["cache"] == "ok"


def test_12_moteur_en_panne(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "CORE_SERVICE_URL", "http://127.0.0.1:9")
    r = client.post(f"/api/v1/parcels/{ETAT['parcel']}/strategies", json={}, headers=h(ETAT["owner"]))
    assert r.status_code == 503 and r.json()["error"]["code"] == "ENGINE_UNAVAILABLE"


def test_13_suppression(client):
    p = ETAT["parcel"]
    assert client.delete(f"/api/v1/parcels/{p}", headers=h(ETAT["cofarmer"])).json()["error"]["code"] == "FORBIDDEN_ROLE"
    assert client.delete(f"/api/v1/parcels/{p}", headers=h(ETAT["owner"])).status_code == 204
    assert client.get(f"/api/v1/parcels/{p}", headers=h(ETAT["owner"])).json()["error"]["code"] == "PARCEL_NOT_FOUND"


@pytest.mark.parametrize("route", ["/api/v1/farms/frm_x", "/api/v1/parcels/pcl_x"])
def test_14_introuvables(client, route):
    code = client.get(route, headers=h(ETAT["owner"])).json()["error"]["code"]
    assert code in ("FARM_NOT_FOUND", "PARCEL_NOT_FOUND")


def test_15_langue_anglaise_et_relecture_calcul(client):
    r = client.get("/api/v1/parcels/pcl_inconnue", headers={**h(ETAT["owner"]), "Accept-Language": "en-US,en;q=0.9"})
    assert r.json()["error"]["message"] == "Parcel not found."
    r = client.post("/api/v1/auth/register", json={"full_name": "Zoé", "identifier": "z@x.cm", "password": "x"},
                    headers={"Accept-Language": "en"})
    assert r.json()["error"]["message"] == "Some values are invalid."
    r = client.get("/api/v1/parcels/pcl_inconnue/strategies/computed/cmp_x", headers=h(ETAT["owner"]))
    assert r.json()["error"]["code"] == "PARCEL_NOT_FOUND"


def test_16_secret_jwt_production():
    from app import config
    assert config.verifier_secret("production", "changez-moi")
    assert config.verifier_secret("production", "court")
    assert config.verifier_secret("production", "x" * 48) is None
    assert config.verifier_secret("development", "changez-moi") is None
