"""Vérifie la chaîne data-service -> agrorot-core sur la parcelle de démo (Mbankomo).

    python scripts/verifier_chaine.py           # POWER simulé (hors ligne)
    python scripts/verifier_chaine.py --reel    # VRAI appel NASA POWER (accès Internet requis)

Étape 1 (data-service) : télécharge / simule 30 ans de POWER, calcule ET0, saisons, série mensuelle.
Étape 2 (agrorot-core) : injecte la série dans le contexte de démo et calcule les 3 stratégies.
Les deux services ont chacun un paquet `app` : chaque étape tourne dans son propre processus.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DATA, CORE = RACINE / "services" / "data-service", RACINE / "services" / "agrorot-core"
LAT, LON = 3.813, 11.452

ETAPE1 = r"""
import json, sys, time
from fastapi.testclient import TestClient
from app.main import app
from app.sources import nasa_power as power
if not REEL:
    from tests.power_simule import payload
    power.telecharger = lambda lat, lon, d, f, delai=5: power.analyser(payload(lat, lon, d, f), lat, lon)
c = TestClient(app)
t = time.time()
if REEL:
    print("Préchargement POWER (peut prendre 10 à 60 s)...", file=sys.stderr)
    r = c.post("/v1/climate/prefetch", params={"lat": LAT, "lon": LON})
    print("  prefetch :", r.status_code, r.json(), file=sys.stderr)
r = c.get("/v1/climate/series", params={"lat": LAT, "lon": LON})
b = r.json()
if r.status_code != 200:
    print("ERREUR", r.status_code, b, file=sys.stderr); sys.exit(1)
if not REEL:
    print("  (POWER simulé : chiffres et niveau de confiance sans valeur réelle)", file=sys.stderr)
print(f"  statut={b['data_source_status']} synthetique={b['synthetique']} altitude={b['altitude_m']} "
      f"qualite={b['qualite']} ({time.time()-t:.1f} s)", file=sys.stderr)
json.dump(b["site_climat"], open(SORTIE, "w"))
"""

ETAPE2 = r"""
import json, time
from app.schemas import RequeteStrategies
from app.engine.pipeline import proposer
ctx = json.load(open("tests/fixtures/contexte_demo.json"))
ctx["climat"] = json.load(open(SORTIE))
s = ctx["climat"]["serie_mensuelle"]
pluie = sum(m["pluie_mm"] for m in s) / (len(s) / 12)
print(f"  {len(s)} mois, pluie annuelle moyenne {pluie:.0f} mm, {len(ctx['climat']['saisons'])} saisons détectées")
t = time.time()
r = proposer(RequeteStrategies(contexte=ctx, horizon_seasons=6))
print(f"  calcul en {time.time()-t:.1f} s ; avertissements : {[w.code for w in r.warnings]}")
for st in r.strategies:
    print(f"  {st.name[:48]:48} G={st.score:5} confiance={st.confidence.level:8} {[e.crop_id for e in st.sequence]}")
"""


def main():
    reel = "--reel" in sys.argv
    with tempfile.TemporaryDirectory() as d:
        sortie = str(Path(d) / "site_climat.json")
        entete = f"REEL = {reel}\nLAT, LON = {LAT}, {LON}\nSORTIE = {sortie!r}\n"
        print("1. data-service" + (" (NASA POWER réel)" if reel else " (POWER simulé)"))
        subprocess.run([sys.executable, "-c", entete + ETAPE1], cwd=DATA, check=True)
        print("2. agrorot-core")
        subprocess.run([sys.executable, "-c", entete + ETAPE2], cwd=CORE, check=True)


if __name__ == "__main__":
    main()
