"""Fetch the public sources the map is built from. Standard library only.

- DEQ "Air Sites (Daily)": every air-permitted site in Virginia; DEQ flags data centers itself
  (PLA_DATA_CENTER_YN = 'Y'). Address, coordinates and operating status.
- DEQ "Virginia County Boundaries": the 133 counties and independent cities, to name each site's locality.
- NCES EDGE public school locations: Virginia public schools, for landmark search.
- Census ZCTA Gazetteer: a center point for every Virginia ZIP code, for ZIP search.

Every request identifies itself and is made once per build; nothing here scrapes HTML pages.
"""
import io
import json
import time
import urllib.parse
import urllib.request
import zipfile

UA = "Virginia-Data-Center-Tracker/1.0 (+https://github.com/WillMcNulty/Virginia-Data-Center-Tracker)"
DEQ = "https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer"
DEQ_AIR_SITES = 294
DEQ_COUNTIES = 157
NCES = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
        "EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0/query")
GAZETTEER = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_zcta_national.zip"

# Virginia's ZIP prefixes: 201 (Dulles, Herndon, Manassas) and 220-246. 200 and 202-205 are DC; 206-219 are Maryland.
VA_ZIP_PREFIXES = {"201"} | {str(p) for p in range(220, 247)}


def get(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def arcgis_query(layer_url, where, out_fields="*", geometry=True, offset_step=1000, extra=None):
    """All features matching `where`, following resultOffset paging, in WGS84."""
    feats, offset = [], 0
    while True:
        params = {"where": where, "outFields": out_fields, "returnGeometry": str(geometry).lower(),
                  "outSR": 4326, "f": "json", "resultOffset": offset, "resultRecordCount": offset_step}
        params.update(extra or {})
        d = json.loads(get(layer_url + "/query" if not layer_url.endswith("/query") else layer_url, params))
        if "error" in d:
            raise RuntimeError(f"{layer_url}: {d['error']}")
        page = d.get("features", [])
        feats += page
        if not d.get("exceededTransferLimit") and len(page) < offset_step:
            return feats
        offset += len(page)


def deq_data_centers():
    return arcgis_query(f"{DEQ}/{DEQ_AIR_SITES}", "PLA_DATA_CENTER_YN='Y'")


def deq_counties():
    # maxAllowableOffset simplifies the outlines (about 100 m); plenty for naming the locality of a point.
    return arcgis_query(f"{DEQ}/{DEQ_COUNTIES}", "1=1", out_fields="NAME,FIPS",
                        extra={"maxAllowableOffset": 0.001})


def nces_va_schools():
    return arcgis_query(NCES, "STATE='VA'", out_fields="NCESSCH,NAME,STREET,CITY,ZIP,LAT,LON", geometry=False)


LOUDOUN_LOLA = "https://logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0"


def loudoun_filings():
    """Loudoun County land applications since 2005 that mention a data center (LOLA). Only the fields the site uses:
    the staff-assignment fields (a reviewer's name and email) are deliberately not requested."""
    where = ("PlanDescription LIKE '%data center%' OR PlanName LIKE '%data center%' "
             "OR PlanDescription LIKE '%datacenter%' OR PlanName LIKE '%datacenter%'")
    return arcgis_query(LOUDOUN_LOLA, where,
                        out_fields="PlanNumber,PlanApplicationDate,PlanType,PlanStatus,PlanName,PlanDescription",
                        extra={"maxAllowableOffset": 0.0001})


def va_zip_centers():
    """{zip: (lat, lon)} for Virginia ZCTAs, from the Census Gazetteer (a delimited text file inside a zip)."""
    raw = get(GAZETTEER)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        text = z.read(name).decode("utf-8", "replace")
    lines = text.splitlines()
    sep = "|" if "|" in lines[0] else "\t"  # the 2025 file switched from tabs to pipes
    head = [h.strip() for h in lines[0].split(sep)]
    i_zip, i_lat, i_lon = head.index("GEOID"), head.index("INTPTLAT"), head.index("INTPTLONG")
    out = {}
    for line in lines[1:]:
        cells = line.split(sep)
        z = cells[i_zip].strip()
        if z[:3] in VA_ZIP_PREFIXES:
            out[z] = (round(float(cells[i_lat]), 5), round(float(cells[i_lon]), 5))
    return out
