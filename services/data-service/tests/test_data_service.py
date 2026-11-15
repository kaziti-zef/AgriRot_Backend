"""Tests du lot A, hors ligne : POWER est remplacé par une réponse simulée au format exact de l'API."""
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import cache
from app.main import app
from app.processing import climatologie, et0, qualite, saisons
from app.sources import nasa_power as power

from .power_simule import payload

LAT, LON = 3.813, 11.452


@pytest.fixture(autouse=True)
def cache_temporaire(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


@pytest.fixture
def power_ok(monkeypatch):
    appels = []

    def faux(lat, lon, debut, fin, delai=5):
        appels.append(delai)
        return power.analyser(payload(lat, lon, debut, fin), lat, lon)
    monkeypatch.setattr(power, "telecharger", faux)
    return appels


@pytest.fixture
def power_en_panne(monkeypatch):
    def panne(*a, **k):
        raise power.PowerIndisponible("timeout")
    monkeypatch.setattr(power, "telecharger", panne)


# ------------------------------------------------------------------ T10 client POWER
def test_url_et_analyse():
    base, q = power.url(LAT, LON, 1995, 2024)
    assert base.endswith("/api/temporal/daily/point") and q["community"] == "AG"
    assert "WS2M" in q["parameters"] and q["start"] == "19950101" and q["end"] == "20241231"
    s = power.analyser(payload(), LAT, LON)
    assert s.altitude_m == 742.3 and set(power.COLONNES.values()) <= set(s.jours.columns)
    assert s.jours["pluie"].isna().sum() == 3 and (s.jours.min(numeric_only=True) > -998).all()


def test_telechargement_delai_depasse():
    def lent(request):
        raise httpx.ReadTimeout("trop lent", request=request)
    client = httpx.Client(transport=httpx.MockTransport(lent))
    with pytest.raises(power.PowerIndisponible):
        power.telecharger(LAT, LON, 1995, 2024, client=client)


def test_telechargement_reponse_mockee():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload(debut=2020, fin=2021))))
    s = power.telecharger(LAT, LON, 2020, 2021, client=client)
    assert len(s.jours) == 731


# ------------------------------------------------------------------ T11 Plan B
def test_plan_b_les_trois_paliers(power_ok, monkeypatch):
    r = cache.obtenir(LAT, LON, 1995, 2024)
    assert r.statut == "live" and r.cached_at is None
    r = cache.obtenir(LAT, LON, 1995, 2024)                      # cache frais : pas de nouvel appel
    assert r.statut == "live" and r.cached_at and len(power_ok) == 1
    monkeypatch.setattr(cache, "CACHE_FRAIS_JOURS", 0)
    monkeypatch.setattr(power, "telecharger", lambda *a, **k: (_ for _ in ()).throw(power.PowerIndisponible("x")))
    assert cache.obtenir(LAT, LON, 1995, 2024).statut == "fallback_cache"


def test_plan_b_secours_local_puis_503(power_en_panne):
    r = cache.obtenir(LAT, LON, 1996, 2025)
    assert r.statut == "fallback_local" and not r.synthetique          # vraie série POWER de Yaoundé
    assert r.serie.jours.index.min().year == 1996 and len(r.serie.jours) == 10958
    from app.errors import ApiError
    with pytest.raises(ApiError) as e:
        cache.obtenir(48.85, 2.35, 1995, 2024)                   # hors zone de secours
    assert e.value.code == "CLIMATE_DATA_UNAVAILABLE" and e.value.http == 503


# ------------------------------------------------------------------ T12 qualité
def test_les_999_n_entrent_dans_aucune_moyenne():
    s = power.analyser(payload(), LAT, LON)
    j = qualite.nettoyer(s.jours)
    e, _ = et0.journaliere(j, s.altitude_m, LAT)
    m = climatologie.mensuel(j, e)
    assert (m[["pluie_mm", "t_max_c", "et0_mm"]] >= 0).all().all()


def test_mois_isole_reconstitue_et_deux_mois_exclus():
    s = power.analyser(payload(trous=False), LAT, LON)
    j = s.jours.copy()
    j.loc["2000-03-01":"2000-03-31", ["pluie", "t_max", "t_min"]] = np.nan              # un mois isolé
    j.loc["2010-05-01":"2010-06-30", ["pluie", "t_max", "t_min"]] = np.nan              # deux mois de suite
    e, _ = et0.journaliere(j, 742, LAT)
    m = climatologie.mensuel(j, e)
    assert m.loc[(2000, 3), "qualite"] == "interpolated"
    assert m.loc[(2010, 5), "qualite"] == "unavailable" and m.loc[(2010, 6), "qualite"] == "unavailable"
    envoyes = {(x["annee"], x["mois"]) for x in climatologie.vers_moteur(m)}
    assert (2000, 3) in envoyes and (2010, 5) not in envoyes


# ------------------------------------------------------------------ T13 ET0
def test_et0_exemple_18_fao56():
    """FAO-56, exemple 18 (Bruxelles, 6 juillet) : ET0 = 3,9 mm/jour."""
    v = et0.penman_monteith(21.5, 12.3, 1.409, 2.078, 22.07, 100, 50.8, 187)
    assert abs(float(v) - 3.9) < 0.1


def test_et0_repli_hargreaves():
    s = power.analyser(payload(debut=2020, fin=2020, trous=False), LAT, LON)
    j = s.jours.drop(columns=["vent"])
    e, methode = et0.journaliere(j, 742, LAT)
    assert methode == "hargreaves" and (e > 0).all()


# ------------------------------------------------------------------ T14 saisons
def test_deux_saisons_par_an():
    s = power.analyser(payload(trous=False), LAT, LON)
    e, _ = et0.journaliere(s.jours, 742, LAT)
    m = climatologie.mensuel(s.jours, e)
    sa = saisons.detecter(m)
    for a in range(1995, 2025):
        assert {x["code"] for x in sa if x["annee"] == a} == {"S1", "S2"}
    assert all(x["fin_mois"] <= 7 for x in sa if x["code"] == "S1")


# ------------------------------------------------------------------ T15 / T16 / T17 routes
def test_route_series_acceptee_par_le_moteur(power_ok):
    c = TestClient(app)
    r = c.get("/v1/climate/series", params={"lat": LAT, "lon": LON, "start_year": 1995, "end_year": 2024})
    assert r.status_code == 200
    body = r.json()
    assert body["data_source_status"] == "live" and body["qualite"]["methode_et0"] == "penman-monteith"
    site = body["site_climat"]
    assert len(site["serie_mensuelle"]) == 360 and site["saisons"]
    assert set(site["serie_mensuelle"][0]["jours_chaleur"]) == {"30", "32", "34", "36", "38"}


def test_route_prefetch_utilise_le_delai_long(power_ok):
    c = TestClient(app)
    r = c.post("/v1/climate/prefetch", params={"lat": LAT, "lon": LON})
    assert r.status_code == 200 and power_ok[-1] == power.DELAI_LONG


def test_route_diagnostic_format_contrat(power_ok):
    c = TestClient(app)
    r = c.get("/v1/climate/diagnostic", params={"lat": LAT, "lon": LON})
    assert r.status_code == 200
    d = r.json()
    assert len(d["monthly_series"]) == 12
    champs = {"month", "label", "temp_avg_c", "temp_normal_c", "rain_mm", "rain_normal_mm", "soil_moisture_anomaly",
              "ndvi", "evapotranspiration_mm", "water_balance_mm", "frost_risk", "quality", "alerts"}
    assert champs == set(d["monthly_series"][0])
    assert {"soil_moisture_anomaly", "ndvi"} <= set(d["missing_indicators"])     # pas de fichiers pré-agrégés ici
    assert any(p["type"] == "water_stress" for p in d["vulnerable_periods"])        # saison sèche déc.-fév.
    assert "dry_season" in d["monthly_series"][0]["alerts"]                          # janvier


def test_route_climat_503_hors_zone_sans_power(power_en_panne):
    r = TestClient(app).get("/v1/climate/series", params={"lat": 48.85, "lon": 2.35})
    assert r.status_code == 503 and r.json()["error"]["code"] == "CLIMATE_DATA_UNAVAILABLE"


def test_route_terrain_sans_srtm():
    r = TestClient(app).get("/v1/terrain", params={"lat": LAT, "lon": LON}).json()
    assert r["elevation_m"] is None and r["warnings"][0]["code"] == "SRTM_UNAVAILABLE"
    r = TestClient(app).get("/v1/terrain", params={"lat": 48.85, "lon": 2.35}).json()
    assert any(w["code"] == "OUTSIDE_COVERED_REGION" for w in r["warnings"])


# ---------------------------------------------------------------- T65 prévisions
def test_prevision_simulee_et_normales(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.sources import previsions
    monkeypatch.setenv("PREVISION_SIMULEE", "sec")
    previsions._cache.clear()
    r = TestClient(app).get("/v1/forecast/daily", params={"lat": 3.813, "lon": 11.452}).json()
    assert r["status"] == "simulated" and len(r["days"]) == 40
    assert sum(d["pluie_mm"] for d in r["days"][-30:]) == 0
    assert r["days"][0]["observe"] and not r["days"][-1]["observe"]
    assert r["normals"] is None or 1 <= len(r["normals"]["par_mois"]) <= 12


def test_analyse_open_meteo_et_meteomatics():
    from app.sources import previsions as P
    om = {"daily": {"time": ["2026-11-14", "2026-11-15"], "temperature_2m_max": [29.1, 30.0],
                    "temperature_2m_min": [20.2, None], "precipitation_sum": [4.0, 0.0],
                    "et0_fao_evapotranspiration": [3.5, 3.9]}}
    a = P.analyser_open_meteo(om)
    assert a[1]["t_min"] is None and a[0]["pluie_mm"] == 4.0
    mm = {"data": [{"parameter": "precip_24h:mm", "coordinates": [{"lat": 3.8, "lon": 11.4, "dates": [
        {"date": "2026-11-15T00:00:00Z", "value": 7.5}, {"date": "2026-11-16T00:00:00Z", "value": -999}]}]},
        {"parameter": "t_max_2m_24h:C", "coordinates": [{"lat": 3.8, "lon": 11.4, "dates": [
            {"date": "2026-11-15T00:00:00Z", "value": 30.2}, {"date": "2026-11-16T00:00:00Z", "value": 31.0}]}]}]}
    b = P.analyser_meteomatics(mm)
    assert b[0]["date"] == "2026-11-14" and b[0]["pluie_mm"] == 7.5 and b[1]["pluie_mm"] is None


def test_prevision_indisponible_sans_reseau(monkeypatch):
    from app.sources import previsions as P
    monkeypatch.delenv("PREVISION_SIMULEE", raising=False)
    monkeypatch.delenv("METEOMATICS_USER", raising=False)
    P._cache.clear()
    def boom(*a, **k):
        raise P.PrevisionIndisponible("hors ligne")
    monkeypatch.setattr(P, "open_meteo", boom)
    r = P.obtenir(3.8, 11.4)
    assert r["status"] == "unavailable" and r["days"] == []
