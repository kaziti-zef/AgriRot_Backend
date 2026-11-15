"""Pré-téléchargement des données NASA pour la région pilote (cm_yaounde).

Usage :
    pip install requests xarray netCDF4 rasterio numpy pandas
    export EARTHDATA_USER=...  EARTHDATA_PASS=...  OPENTOPO_KEY=...

    python pretelecharger.py appeears-submit      # envoie la requête SMAP + NDVI (asynchrone)
    python pretelecharger.py appeears-status      # vérifie l'avancement
    python pretelecharger.py appeears-download    # télécharge les NetCDF une fois "done"
    python pretelecharger.py srtm                 # télécharge le MNT SRTM 30 m de la zone
    python pretelecharger.py aggregate            # produit les fichiers mensuels lus par data-service

Les fichiers finaux vont dans ../data/preaggregated/ :
    smap_monthly.nc, ndvi_monthly.nc, imerg_daily.csv (Giovanni), srtm_30m.tif

NB : script non testé contre les API réelles (pas d'accès réseau lors de sa rédaction) ;
vérifier les noms de produits et de couches avec `appeears-products`.
"""
import json, os, sys, time
from pathlib import Path
import requests

# ---- Zone pilote (identique à data/regions.csv du moteur) ----
BBOX = {"south": 3.4, "north": 4.3, "west": 11.0, "east": 12.0}
START, END = "01-01-2015", "12-31-2025"   # SMAP commence le 31/03/2015

OUT = Path(__file__).resolve().parents[1] / "data" / "preaggregated"
RAW = OUT / "raw"
API = "https://appeears.earthdatacloud.nasa.gov/api/"
TASK_FILE = RAW / "appeears_task_id.txt"

# Produits et couches (vérifier les versions avec `appeears-products`)
LAYERS = [
    {"product_prefix": "MOD13Q1", "layer": "_250m_16_days_NDVI"},          # NDVI MODIS 250 m, 16 j
    {"product_prefix": "SPL3SMP_E", "layer": "Soil_Moisture_Retrieval_Data_AM_soil_moisture"},  # SMAP 9 km
]


def token() -> str:
    r = requests.post(API + "login", auth=(os.environ["EARTHDATA_USER"], os.environ["EARTHDATA_PASS"]))
    r.raise_for_status()
    return r.json()["token"]


def latest_version(prefix: str) -> str:
    prods = requests.get(API + "product").json()
    ids = sorted(p["ProductAndVersion"] for p in prods if p["ProductAndVersion"].startswith(prefix + "."))
    if not ids:
        sys.exit(f"Produit {prefix} introuvable dans AppEEARS")
    return ids[-1]


def bbox_geojson() -> dict:
    s, n, w, e = BBOX["south"], BBOX["north"], BBOX["west"], BBOX["east"]
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}]}


def appeears_products():
    for p in LAYERS:
        print(p["product_prefix"], "->", latest_version(p["product_prefix"]))


def appeears_submit():
    RAW.mkdir(parents=True, exist_ok=True)
    layers = [{"product": latest_version(p["product_prefix"]), "layer": p["layer"]} for p in LAYERS]
    task = {"task_type": "area", "task_name": "agrorot_cm_yaounde",
            "params": {"dates": [{"startDate": START, "endDate": END}], "layers": layers,
                       "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
                       "geo": bbox_geojson()}}
    r = requests.post(API + "task", json=task, headers={"Authorization": f"Bearer {token()}"})
    r.raise_for_status()
    tid = r.json()["task_id"]
    TASK_FILE.write_text(tid)
    print("Requête envoyée :", tid, "(compter de quelques minutes à quelques heures)")


def appeears_status():
    tid = TASK_FILE.read_text().strip()
    r = requests.get(API + f"task/{tid}", headers={"Authorization": f"Bearer {token()}"}).json()
    print(r.get("status"), r.get("progress", ""))


def appeears_download():
    tid = TASK_FILE.read_text().strip()
    h = {"Authorization": f"Bearer {token()}"}
    bundle = requests.get(API + f"bundle/{tid}", headers=h).json()
    for f in bundle["files"]:
        if not f["file_name"].endswith((".nc", ".csv", ".json", ".txt")):
            continue
        dest = RAW / Path(f["file_name"]).name
        with requests.get(API + f"bundle/{tid}/{f['file_id']}", headers=h, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        print("ok", dest.name)


def srtm():
    OUT.mkdir(parents=True, exist_ok=True)
    url = "https://portal.opentopography.org/API/globaldem"
    params = {"demtype": "SRTMGL1", **BBOX, "outputFormat": "GTiff", "API_Key": os.environ["OPENTOPO_KEY"]}
    r = requests.get(url, params=params, timeout=300)
    r.raise_for_status()
    (OUT / "srtm_30m.tif").write_bytes(r.content)
    print("ok srtm_30m.tif", len(r.content) // 1_000_000, "Mo")


def aggregate():
    """NetCDF AppEEARS -> moyennes mensuelles, NDVI ramené à ~0,05° pour alléger."""
    import xarray as xr
    for nc in RAW.glob("*.nc"):
        ds = xr.open_dataset(nc)
        var = [v for v in ds.data_vars if "NDVI" in v or "soil_moisture" in v]
        if not var:
            continue
        da = ds[var[0]]
        if "NDVI" in var[0]:
            da = da.where(da > -0.2)                          # valeurs de remplissage
            da = da.coarsen(lat=20, lon=20, boundary="trim").mean()   # 250 m -> ~5 km
            name = "ndvi_monthly.nc"
        else:
            da = da.where(da >= 0)
            name = "smap_monthly.nc"
        monthly = da.resample(time="MS").mean()
        monthly.to_netcdf(OUT / name)
        print("ok", name, dict(monthly.sizes))


if __name__ == "__main__":
    cmds = {"appeears-products": appeears_products, "appeears-submit": appeears_submit,
            "appeears-status": appeears_status, "appeears-download": appeears_download,
            "srtm": srtm, "aggregate": aggregate}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit("Commandes : " + ", ".join(cmds))
    cmds[sys.argv[1]]()
