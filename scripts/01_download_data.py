"""Download all open data used in the project.

Sources (Open Government Licence - Canada):
  * Open Database of Healthcare Facilities (ODHF v1.1), Statistics Canada
  * National Road Network (NRN) for Saskatchewan, Statistics Canada / NRCan
  * 2021 Census dissemination area (DA) boundaries, StatCan ArcGIS REST service
  * 2021 Census Profile by DA, StatCan SDMX API
"""
import io
import json
import time
import zipfile

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CITIES, RAW, SK_PRUID

ODHF_URL = "https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/ODHF_v1.1.zip"
NRN_URL = "https://geo.statcan.gc.ca/nrn_rrn/sk/nrn_rrn_sk_GPKG.zip"
BOUNDARY_SERVICE = ("https://geo.statcan.gc.ca/geo_wa/rest/services/2021/"
                    "Digital_boundary_files/MapServer")
DA_SERVICE = f"{BOUNDARY_SERVICE}/12/query"
CSD_SERVICE = f"{BOUNDARY_SERVICE}/9/query"
CENSUS_API = ("https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest/"
              "data/STC_CP,DF_DA/A5..1.{chars}.1")

# Census Profile characteristic codes (CL_CHARACTERISTIC)
CENSUS_VARS = {
    1: "pop_2021",
    24: "pop_65plus",
    229: "med_hh_income",
    1388: "indig_base",
    1389: "indig_pop",
}

# StatCan servers drop connections intermittently, so retry with backoff
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "Mozilla/5.0 (sk-health-access research script)"
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=6, backoff_factor=3, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=None)))


def download_zip(url, dest):
    if dest.exists() and any(dest.iterdir()):
        print(f"  already have {dest.name}")
        return
    print(f"  downloading {url}")
    r = SESSION.get(url, timeout=600)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(dest)


def query_service(params, url=DA_SERVICE, attempts=8):
    """The boundary service returns sporadic HTTP 500s, so retry each request until it parses."""
    for i in range(attempts):
        r = SESSION.get(url, params=params, timeout=300)
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                pass
        time.sleep(2 + 2 * i)
    raise RuntimeError(f"DA service failed after {attempts} attempts: {params}")


def download_da_boundaries(dest, chunk=100):
    """Fetch object IDs first, then request boundaries in small batches (WGS84 GeoJSON)."""
    if dest.exists():
        print(f"  already have {dest.name}")
        return
    ids = query_service({"where": f"PRUID='{SK_PRUID}'", "returnIdsOnly": "true",
                         "f": "json"})["objectIds"]
    ids.sort()
    features = []
    for start in range(0, len(ids), chunk):
        batch = ",".join(str(i) for i in ids[start:start + chunk])
        page = query_service({"objectIds": batch, "outFields": "DAUID,DGUID,LANDAREA",
                              "f": "geojson"})
        features += page["features"]
        print(f"  {len(features)}/{len(ids)} DAs", end="\r")
    print()
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def download_city_boundaries(dest):
    """2021 census subdivision boundaries for the eight largest cities."""
    if dest.exists():
        print(f"  already have {dest.name}")
        return
    ids = ",".join(f"'{c}'" for c in CITIES.values())
    page = query_service({"where": f"CSDUID IN ({ids})", "outFields": "CSDUID,CSDNAME",
                          "f": "geojson"}, url=CSD_SERVICE)
    print(f"  {len(page['features'])} city boundaries")
    dest.write_text(json.dumps(page))


def download_census(dest):
    if dest.exists():
        print(f"  already have {dest.name}")
        return
    url = CENSUS_API.format(chars="+".join(str(c) for c in CENSUS_VARS))
    print("  querying Census Profile API (all DAs in Canada, filtered to SK)")
    r = SESSION.get(url, params={"format": "csv"}, timeout=900)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype={"ALT_GEO_CODE": str, "PROV_TERR": str})
    df = df[df["PROV_TERR"] == SK_PRUID]
    wide = (df.pivot_table(index="ALT_GEO_CODE", columns="CHARACTERISTIC",
                           values="OBS_VALUE", aggfunc="first")
              .rename(columns=CENSUS_VARS).reset_index()
              .rename(columns={"ALT_GEO_CODE": "DAUID"}))
    wide.to_csv(dest, index=False)
    print(f"  {len(wide)} SK DAs, population {wide['pop_2021'].sum():,.0f}")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    print("Healthcare facilities (ODHF)")
    download_zip(ODHF_URL, RAW / "odhf")
    print("Road network (NRN Saskatchewan)")
    download_zip(NRN_URL, RAW / "nrn")
    print("Dissemination area boundaries")
    download_da_boundaries(RAW / "sk_da_2021.geojson")
    print("Census profile")
    download_census(RAW / "sk_da_census_2021.csv")
    print("City boundaries")
    download_city_boundaries(RAW / "sk_cities_2021.geojson")
