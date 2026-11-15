"""T62 - Vérification agronomique sur la VRAIE série NASA POWER de Mbankomo (1996-2025).

Ces tests figent des classements qui doivent rester vrais quand on recalibre les paramètres.
Si l'un casse après un changement de parametres.yaml, c'est le signe d'un recalibrage à discuter."""
import json
import time
from pathlib import Path

import pytest

from app.engine import scenario as sc
from app.engine.evaluation import evaluer
from app.engine.pipeline import proposer
from app.engine.precalcul import construire
from app.engine.temps import calendrier_contexte
from app.referentiel.loader import REF
from app.schemas import Contexte, RequeteStrategies

from .conftest import seq

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ctx_reel_dict():
    d = json.loads((FIX / "contexte_demo.json").read_text())
    d["climat"] = json.loads((FIX / "site_climat_mbankomo_reel.json").read_text())
    return d


@pytest.fixture(scope="module")
def ctx_reel(ctx_reel_dict):
    return Contexte(**ctx_reel_dict)


@pytest.fixture(scope="module")
def pc_reel(ctx_reel):
    return construire(ctx_reel, sc.depuis_site(ctx_reel.climat), calendrier_contexte(ctx_reel))


def G(pc, ctx, *crops):
    return evaluer(seq(*crops), pc, ctx).G


def test_serie_reelle_plausible(ctx_reel):
    cl = sc.depuis_site(ctx_reel.climat)
    assert 1200 < cl.pluie_annuelle < 1800 and 22 < cl.t_annuelle < 26 and not cl.synthetique


def test_calendrier_regional_garde(ctx_reel):
    """POWER lisse la petite saison sèche : la détection ne doit pas décaler S2 en juillet."""
    cal = calendrier_contexte(ctx_reel)
    assert cal.semis == {"S1": 3, "S2": 8}


def test_cultures_de_base_retenues(pc_reel):
    for c in ("mais", "arachide", "niebe", "manioc", "patate_douce", "haricot"):
        assert c in pc_reel.candidates


def test_niebe_pas_penalise_par_la_temperature(pc_reel):
    assert pc_reel.fiche("niebe", "S1").opt.mean() > 0.7


def test_classements_attendus(pc_reel, ctx_reel):
    mono = G(pc_reel, ctx_reel, *("mais",) * 6)
    diversifiee = G(pc_reel, ctx_reel, "mais", "arachide", "manioc", "manioc", "patate_douce", "mais")
    solanacees = G(pc_reel, ctx_reel, *("tomate", "piment") * 3)
    assert solanacees < mono < diversifiee


def test_legumineuse_apres_mais_ameliore_le_sol(pc_reel, ctx_reel):
    a = evaluer(seq("mais", "niebe", "mais", "arachide"), pc_reel, ctx_reel).scores["S3"]
    b = evaluer(seq("mais", "mais", "mais", "mais"), pc_reel, ctx_reel).scores["S3"]
    assert a > b + 15


def test_strategies_sur_donnees_reelles(ctx_reel_dict):
    t = time.time()
    r = proposer(RequeteStrategies(contexte=ctx_reel_dict, horizon_seasons=6))
    assert time.time() - t < 3.0
    ex, reco, alt = r.strategies
    assert reco.score > ex.score + 10
    assert any(REF.cultures[e.crop_id].fixe_azote for e in reco.sequence if e.crop_id in REF.cultures)
    assert not any(w.code == "SYNTHETIC_CLIMATE" for w in r.warnings)
    assert reco.confidence.level in ("élevée", "moyenne")


def test_secheresse_plus_dure_pour_les_cultures_longues(ctx_reel):
    cl = sc.depuis_site(ctx_reel.climat)
    cal = calendrier_contexte(ctx_reel)
    sec = construire(ctx_reel, sc.appliquer(cl, sc.ScenarioClimat(rain_delta_pct=-30)), cal)
    base = construire(ctx_reel, cl, cal)
    assert (sec.fiche("manioc", "S1").sigma.mean() < base.fiche("manioc", "S1").sigma.mean())


# ---------------------------------------------------------------- recalibrage du 15/11 (réserve du sol, seuils)
def test_manioc_plus_penalise_a_tort(pc_reel):
    """Le manioc (peu sensible à la sécheresse, racines profondes) traverse la saison sèche :
    avec la réserve du sol et sigma* = 0,65, il réussit au moins 7 années sur 10 semé en S1."""
    from app.engine.precalcul import seuil_eau
    f = pc_reel.fiche("manioc", "S1")
    assert float((f.sigma >= seuil_eau(REF.cultures["manioc"])).mean()) >= 0.7


def test_reserve_du_sol_aide_les_racines_profondes(ctx_reel):
    from dataclasses import replace
    pc = construire(ctx_reel, sc.depuis_site(ctx_reel.climat), calendrier_contexte(ctx_reel))
    c = REF.cultures["manioc"]
    profond = pc.fiche("manioc", "S2").sigma.mean()
    REF.cultures["manioc"] = replace(c, racines_m=0.0)
    try:
        pc2 = construire(ctx_reel, sc.depuis_site(ctx_reel.climat), calendrier_contexte(ctx_reel))
        sans = pc2.fiche("manioc", "S2").sigma.mean()
    finally:
        REF.cultures["manioc"] = c
    assert profond > sans + 0.03


def test_folon_et_igname_admissibles_a_mbankomo(ctx_reel, pc_reel):
    from app.engine import contraintes as K
    assert "folon" in pc_reel.candidates                       # règle cycle court : pas de borne haute de pluie
    assert not [v for v in K.statiques("igname", "S1", pc_reel, ctx_reel) if v.code == "C6"]   # pH 5,8 accepté
