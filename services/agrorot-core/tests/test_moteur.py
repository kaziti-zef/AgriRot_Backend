"""Tests unitaires du moteur (T20 à T34) et tests d'acceptation de la spécification backend
qui concernent le moteur (4, 5, 6, 7, 8, 9, 11). Aucun accès réseau : fixtures de T04."""
import time

import numpy as np
import pytest

from app.engine import contraintes as K
from app.engine import scenario as sc
from app.engine.evaluation import confiance, evaluer, poids_criteres
from app.engine.pipeline import proposer
from app.engine.temps import calendrier_contexte, interpreter
from app.errors import ApiError
from app.referentiel.loader import REF
from app.schemas import Contexte, RequeteStrategies, ScenarioClimat

from .conftest import seq


# ------------------------------------------------------------------ T20 référentiel
def test_referentiel_conversions():
    assert REF.cultures["niebe"].fixe_azote and REF.cultures["niebe"].azote_fixe == (30, 100)
    assert REF.cultures["manioc"].couverture == "moyenne"          # « faible au départ, moyenne ensuite »
    assert REF.cultures["manioc"].longue and not REF.cultures["mais"].longue
    assert "fourrage" in REF.cultures["arachide"].usages
    assert REF.cultures["mucuna"].service


# ------------------------------------------------------------------ T21 scénarios
def test_scenario_pluie_et_neutre(ctx):
    base = sc.depuis_site(ctx.climat)
    assert sc.appliquer(base, ScenarioClimat()) is base
    sec = sc.appliquer(base, ScenarioClimat(rain_delta_pct=-30))
    assert np.allclose(sec.pluie, base.pluie * 0.7)
    chaud = sc.appliquer(base, ScenarioClimat(temp_delta_c=2))
    assert np.allclose(chaud.t_max, base.t_max + 2)
    assert (chaud.chaleur[32] >= base.chaleur[32]).all()


def test_scenario_hors_bornes(ctx):
    base = sc.depuis_site(ctx.climat)
    with pytest.raises(ApiError) as e:
        sc.appliquer(base, ScenarioClimat.model_construct(rain_delta_pct=-50, temp_delta_c=0, horizon_years=0))
    assert e.value.code == "INVALID_SCENARIO"


# ------------------------------------------------------------------ T22 aptitude
def test_aptitude_cultures_de_base(pc, ctx):
    for c in ("mais", "arachide", "niebe", "manioc"):
        assert c in pc.candidates
    assert "gombo" not in pc.candidates            # exclue par l'agriculteur dans le contexte de démo


# ------------------------------------------------------------------ T23 occupation
def test_culture_longue_occupe_deux_saisons(ctx):
    cal = calendrier_contexte(ctx)
    r = interpreter(seq("manioc", "manioc", "mais"), cal)
    assert r.continuation[2] and not r.continuation[3]
    assert len(r.occupations) == 2 and not r.conflits
    r2 = interpreter(seq("manioc", "arachide"), cal)
    assert r2.conflits and r2.conflits[0][0] == 2


# ------------------------------------------------------------------ T24 précalcul
def test_precalcul_bornes_et_vitesse(ctx):
    t = time.time()
    cl = sc.depuis_site(ctx.climat)
    from app.engine.precalcul import construire
    pc = construire(ctx, cl, calendrier_contexte(ctx))
    assert time.time() - t < 1.0
    for f in pc.fiches.values():
        assert ((f.sigma >= 0) & (f.sigma <= 1)).all()


# ------------------------------------------------------------------ T25 contraintes
def test_acceptation_4_tomate_apres_tomate(pc, ctx):
    ev = evaluer(seq("tomate", "tomate"), pc, ctx)
    codes = {v.code for v in ev.violations}
    assert {"C4", "C5"} <= codes and not ev.admissible


def test_manioc_pas_elimine_par_C2(pc, ctx):
    assert not [v for v in K.statiques("manioc", "S1", pc, ctx) if v.code == "C2"]


# ------------------------------------------------------------------ T26-T31 notes
def test_acceptation_5_arachide_apres_mais(pc, ctx):
    a = evaluer(seq("mais", "arachide"), pc, ctx).scores["S3"]
    b = evaluer(seq("mais", "mais"), pc, ctx).scores["S3"]
    assert a > b


def test_acceptation_8_secheresse_baisse_S2(ctx):
    base = sc.depuis_site(ctx.climat)
    cal = calendrier_contexte(ctx)
    from app.engine.precalcul import construire
    pc0 = construire(ctx, base, cal)
    pc1 = construire(ctx, sc.appliquer(base, ScenarioClimat(rain_delta_pct=-30)), cal)
    s = seq("macabo", "macabo", "mais", "haricot")      # cultures sensibles à la sécheresse
    assert evaluer(s, pc1, ctx).scores["S2"] < evaluer(s, pc0, ctx).scores["S2"]


def test_S5_succession_solanacees_penalisee(pc, ctx):
    mauvais = evaluer(seq("tomate", "piment", "tomate", "piment"), pc, ctx)
    bon = evaluer(seq("tomate", "mais", "mucuna", "piment"), pc, ctx)
    assert bon.scores["S5"] > mauvais.scores["S5"] + 30
    assert any(v.code == "C7" for v in mauvais.violations)


def test_S4_pente_nulle(pc, ctx):
    plat = ctx.model_copy(update={"sol": ctx.sol.model_copy(update={"slope_deg": 0.0})})
    assert evaluer(seq("mais", "jachere"), pc, plat).scores["S4"] == 100


def test_S6_debouches(pc, ctx):
    ev = evaluer(seq("tomate", "piment"), pc, ctx)          # aucune des deux sur les marchés déclarés
    assert any("débouché" in t.texte for t in ev.traces)


def test_poids_planchers(ctx):
    w = poids_criteres(ctx)
    assert abs(sum(w.values()) - 1) < 1e-9
    assert w["S1"] >= 0.15 and w["S5"] >= 0.15


# ------------------------------------------------------------------ T32 confiance (acceptation 9)
def test_acceptation_9_confiance(pc, ctx):
    s = seq("mais", "arachide")
    ev = evaluer(s, pc, ctx)
    confirme, _, _ = confiance(ev, ctx, pc)
    defauts = ctx.model_copy(update={"sol": ctx.sol.model_copy(update={"confidences": {}, "ph": None, "texture": None})})
    defaut, _, d = confiance(evaluer(s, pc, defauts), defauts, pc)
    assert defaut < confirme and "ph" in d


# ------------------------------------------------------------------ T33-T34 stratégies
def _req(ctx_dict, **kw):
    return RequeteStrategies(contexte=Contexte(**ctx_dict), **kw)


def test_acceptation_7_trois_strategies(ctx_dict):
    r = proposer(_req(ctx_dict, horizon_seasons=6))
    assert [s.id for s in r.strategies] == ["existing", "recommended", "alternative"]
    ex, reco, alt = r.strategies
    assert ex.violations                                    # l'existante est notée malgré ses violations
    assert reco.score > ex.score
    assert all(len(s.sequence) == 6 for s in r.strategies)
    diff = sum(a.crop_id != b.crop_id for a, b in zip(reco.sequence, alt.sequence)) / 6
    assert diff >= 0.5
    for s in r.strategies:
        for rubrique in s.explanation.model_dump().values():
            assert rubrique                                  # jamais vide (sinon « Information indisponible »)


def test_acceptation_6_culture_exclue(ctx_dict):
    r = proposer(_req(ctx_dict))
    for s in r.strategies[1:]:
        assert all(e.crop_id != "gombo" for e in s.sequence)
    with pytest.raises(ApiError) as e:
        proposer(_req(ctx_dict, manual_overrides={"recommended": {"2": "gombo"}}))
    assert e.value.code == "EXCLUDED_CROP"


def test_modification_manuelle_recalcule(ctx_dict):
    r = proposer(_req(ctx_dict, manual_overrides={"recommended": {"2": "niebe"}}))
    reco = r.strategies[1]
    assert reco.sequence[1].crop_id == "niebe" and reco.sequence[1].modified_by_user


def test_culture_inconnue(ctx_dict):
    with pytest.raises(ApiError) as e:
        proposer(_req(ctx_dict, manual_overrides={"alternative": {"1": "ble"}}))
    assert e.value.code == "CROP_NOT_FOUND"


def test_acceptation_11_determinisme(ctx_dict):
    a = proposer(_req(ctx_dict)).model_dump()
    b = proposer(_req(ctx_dict)).model_dump()
    assert a == b


def test_performance_6_saisons(ctx_dict):
    t = time.time()
    proposer(_req(ctx_dict, horizon_seasons=6))
    assert time.time() - t < 3.0


def test_sans_historique_monoculture_temoin(ctx_dict):
    ctx_dict["historique"] = []
    r = proposer(_req(ctx_dict, horizon_seasons=4))
    assert r.strategies[0].name.startswith("Monoculture témoin")


def test_rotation_prevue_utilisee(ctx_dict):
    ctx_dict["planned_rotation"] = [{"season": 1, "crop_id": "mais"}, {"season": 2, "crop_id": "niebe"}]
    r = proposer(_req(ctx_dict, horizon_seasons=4))
    seq = [e.crop_id for e in r.strategies[0].sequence]
    # Chaque culture prévue vaut une saison (pas de répétition du plan) ; la suite reprend l'historique.
    habitudes = [h["crop_id"] for h in sorted(ctx_dict.get("historique", []), key=lambda h: h["season_index"])]
    assert seq[:2] == ["mais", "niebe"]
    assert seq[2:] == ([habitudes[i % len(habitudes)] for i in range(2)] if habitudes else ["jachere", "jachere"])


def test_rotation_prevue_une_saison_par_culture(ctx_dict):
    ctx_dict["planned_rotation"] = [{"season": 1, "crop_id": "gombo"}]
    ctx_dict["historique"] = []
    r = proposer(_req(ctx_dict, horizon_seasons=4))
    assert [e.crop_id for e in r.strategies[0].sequence] == ["gombo", "jachere", "jachere", "jachere"]


# ------------------------------------------------------------------ API HTTP
def test_api_strategies_et_erreurs(client, ctx_dict):
    r = client.post("/v1/strategies", json={"contexte": ctx_dict, "horizon_seasons": 4})
    assert r.status_code == 200 and len(r.json()["strategies"]) == 3
    r = client.post("/v1/strategies", json={"contexte": ctx_dict, "scenario": {"rain_delta_pct": -80}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post("/v1/evaluate", json={"contexte": ctx_dict, "sequence": [{"season": 1, "crop_id": "mais"},
                                                                             {"season": 2, "crop_id": "mais"}]})
    assert r.status_code == 200 and r.json()["strategy"]["violations"]
    bad = dict(ctx_dict, region="cm_douala")
    r = client.post("/v1/strategies", json={"contexte": bad})
    assert r.status_code == 404 and r.json()["error"]["code"] == "REGION_NOT_SUPPORTED"
    assert r.headers.get("X-Request-ID")
