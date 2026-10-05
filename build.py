"""Build the site's data files from the public sources.

    python build.py            fetch everything live and write site/virginia/data/*.json
    python build.py --offline  rebuild from the cached raw files in .cache/ (for working without network)

Writes:
  site/virginia/data/facilities.json  every DEQ-flagged data center: location, stage, locality, permits
  site/virginia/data/schools.json     Virginia public schools (landmark search)
  site/virginia/data/zips.json        Virginia ZIP code center points (ZIP search)
  site/virginia/data/meta.json        counts, build time, sources, DEQ's data disclaimer
  site/virginia/data/filings.json     county filings that mention a data center (Loudoun so far; optional source)
  site/virginia/data/meetings.json    county meetings with data center items (pipeline/civic.py; optional)

Refuses to write anything if the data looks broken (see check()), so a source outage can't publish an empty map.
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pipeline"))
import changes  # noqa: E402
import civic  # noqa: E402
import filings  # noqa: E402
import geo  # noqa: E402
import pages  # noqa: E402
import sources  # noqa: E402

SITE = os.path.join(HERE, "site")
STATE = "virginia"  # this build's state; its map, data and pages live under site/virginia/
OUT = os.path.join(SITE, STATE, "data")
CACHE = os.path.join(HERE, ".cache")
PERMIT_SNAPSHOTS = sorted(glob.glob(os.path.join(HERE, "data", "deq_issued_permits_*.tsv")))
ALIASES = os.path.join(HERE, "data", "landmark_aliases.json")
SITE_CONFIG = os.path.join(HERE, "data", "site_config.json")

# DEQ operating status -> the map's stage. Order matters: it's the lifecycle order used for sorting and legends.
STAGES = {"Planned": "planned", "Under Construction": "construction", "Operating": "operating",
          "Temporarily Shutdown": "shutdown"}
VA_BBOX = (36.5, 39.5, -83.7, -75.2)  # lat min, lat max, lon min, lon max


CONFIG = json.load(open(SITE_CONFIG, encoding="utf-8"))


def cached(name, fetch, offline):
    path = os.path.join(CACHE, name)
    if offline:
        return json.load(open(path, encoding="utf-8"))
    data = fetch()
    os.makedirs(CACHE, exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"))
    return data


def parse_date(s):
    """DEQ's list uses MM/DD/YYYY, with the odd typo like 03/26-2026."""
    m = re.fullmatch(r"\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*", s or "")
    return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat() if m else None


def load_permits():
    """{registration number: [permit, ...]} from the newest hand-saved snapshot of DEQ's issued-permits page."""
    if not PERMIT_SNAPSHOTS:
        return {}, None
    path = PERMIT_SNAPSHOTS[-1]
    snap_date = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)).group(1)
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
        reg = int(r["permit_no"].split("-")[0])
        program = re.sub(r"\s*-?\s*mNSR", " - mNSR", r["program"]).replace("6  -", "6 -").strip()
        locality = r["locality"].strip().replace(" Co.", " County")
        out.setdefault(reg, []).append({"no": r["permit_no"].strip(), "issued": parse_date(r["issued"]),
                                        "program": program, "locality": locality})
    for permits in out.values():
        permits.sort(key=lambda p: p["issued"] or "", reverse=True)
    return out, snap_date


def locality_label(name, fips):
    # FIPS 510 and up are Virginia's independent cities; below are counties.
    return f"{name} City" if int(fips) >= 510 else f"{name} County"


def build(offline=False):
    raw_dc = cached("deq_data_centers.json", sources.deq_data_centers, offline)
    raw_co = cached("deq_counties.json", sources.deq_counties, offline)
    raw_sc = cached("nces_va_schools.json", sources.nces_va_schools, offline)
    raw_zip = cached("va_zip_centers.json", sources.va_zip_centers, offline)
    permits, snap_date = load_permits()
    aliases = json.load(open(ALIASES, encoding="utf-8")) if os.path.exists(ALIASES) else {}

    counties = [(locality_label(c["attributes"]["NAME"], c["attributes"]["FIPS"]), c["geometry"]["rings"])
                for c in raw_co]

    def locality_of(lon, lat):
        hits = [name for name, rings in counties if geo.in_esri_polygon(lon, lat, rings)]
        return hits[0] if len(hits) == 1 else (" / ".join(sorted(hits)) if hits else None)

    facilities, disclaimer = [], None
    for f in raw_dc:
        a, g = f["attributes"], f["geometry"]
        reg = a["PLA_REG_NUM"]
        disclaimer = disclaimer or a.get("Data_Disclaimer")
        p = permits.get(reg, [])
        facilities.append({
            "id": reg,
            "name": (a["PLA_NAME"] or "").strip(),
            "address": (a["FAC_L_ADDR_1"] or "").strip(),
            "city": (a["FAC_L_CITY"] or "").strip(),
            "zip": (a["FAC_L_ZIP5"] or "").strip(),
            "lat": round(g["y"], 6), "lon": round(g["x"], 6),
            "status": a["AIR_OP_STATUS"],
            "stage": STAGES.get(a["AIR_OP_STATUS"], "other"),
            "permit_class": a["PCL_STATE_DESC"],
            "locality": locality_of(g["x"], g["y"]),
            # When DEQ's permit list names a different locality (seen at the Manassas City line), show both
            # rather than pick one: the two official sources disagree and we can't settle it from here.
            "listed_locality": next((q["locality"] for q in p if q["locality"]), None),
            "permits": [{k: q[k] for k in ("no", "issued", "program")} for q in p],
            "latest_permit": p[0]["issued"] if p else None,
        })
    facilities.sort(key=lambda x: (x["locality"] or "", x["name"]))

    schools = []
    for s in raw_sc:
        a = s["attributes"]
        if a["LAT"] is None or a["LON"] is None:
            continue
        schools.append({"id": a["NCESSCH"], "name": a["NAME"].strip(), "city": (a["CITY"] or "").strip().title(),
                        "street": (a["STREET"] or "").strip(), "lat": round(a["LAT"], 6), "lon": round(a["LON"], 6),
                        "aka": aliases.get(a["NCESSCH"], [])})
    schools.sort(key=lambda x: x["name"])

    zips = {z: list(ll) for z, ll in sorted(raw_zip.items())}

    stage_counts = Counter(f["stage"] for f in facilities)
    permit_years = Counter((p["issued"] or "")[:4] for ps in permits.values() for p in ps if p["issued"])
    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "facilities": len(facilities),
        "stages": {k: stage_counts.get(k, 0) for k in ["planned", "construction", "operating", "shutdown", "other"]},
        "localities": Counter(f["locality"] for f in facilities).most_common(),
        "permit_snapshot": snap_date,
        "permits_in_snapshot": sum(len(v) for v in permits.values()),
        "permits_by_year": dict(sorted(permit_years.items())),
        "facilities_without_permit_row": sum(1 for f in facilities if not f["permits"]),
        "schools": len(schools),
        "zips": len(zips),
        "deq_disclaimer": disclaimer,
        # Reuse terms for anyone reading the JSON directly (the CSVs can't carry them); see DATA-LICENSE.md.
        "license": "CC BY-NC-SA 4.0, with extra permissions for news reporting, embedding, government, education and "
                   "research; commercial use needs a license. Terms: " + CONFIG["site_url"].rstrip("/") + "/terms/",
        # Site settings the page needs (the donate link stays hidden while support_url is null).
        "support_url": CONFIG.get("support_url"),
        "support_label": CONFIG.get("support_label"),
        "sources": {
            "deq_air_sites": f"{sources.DEQ}/{sources.DEQ_AIR_SITES}",
            "deq_permit_page": "https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers",
            "nces_schools": sources.NCES.rsplit("/query", 1)[0],
            "census_zcta": sources.GAZETTEER,
        },
    }
    check(facilities, schools, zips, meta)
    return facilities, schools, zips, meta


def check(facilities, schools, zips, meta):
    """Stop before publishing anything that looks like a broken source."""
    problems = []
    if not 120 <= len(facilities) <= 800:
        problems.append(f"{len(facilities)} data centers is outside the plausible range 120-800")
    prev = os.path.join(OUT, "meta.json")
    if os.path.exists(prev):
        before = json.load(open(prev, encoding="utf-8")).get("facilities", 0)
        if before and len(facilities) < 0.75 * before:
            problems.append(f"data centers fell from {before} to {len(facilities)} (over 25%); refusing to publish")
    lat0, lat1, lon0, lon1 = VA_BBOX
    outside = [f["name"] for f in facilities if not (lat0 <= f["lat"] <= lat1 and lon0 <= f["lon"] <= lon1)]
    if outside:
        problems.append(f"outside Virginia: {outside}")
    no_loc = [f["name"] for f in facilities if not f["locality"]]
    if len(no_loc) > 2:
        problems.append(f"{len(no_loc)} facilities matched no locality: {no_loc[:5]}")
    unknown = sorted({f["status"] for f in facilities if f["stage"] == "other"})
    if unknown:
        print("warning: unmapped DEQ statuses shown as 'other':", unknown)
    if len(schools) < 1500:
        problems.append(f"only {len(schools)} schools")
    if len(zips) < 800:
        problems.append(f"only {len(zips)} ZIP codes")
    if problems:
        raise SystemExit("build check failed:\n  " + "\n  ".join(problems))


# County filings: (county, cache file, fetcher, adapter). Each is optional: see build_filings().
FILING_SOURCES = [("Loudoun County", "loudoun_lola.json", sources.loudoun_filings, filings.loudoun)]
FILINGS = os.path.join(OUT, "filings.json")


def build_filings(offline=False):
    """County filings, one county source at a time. Never stops the build: when a county's server is down (LOLA
    sometimes answers with an HTML error page) or its data fails filings.problems(), that county keeps the filings
    published last time (the committed filings.json), so broken data is never published and nothing disappears.
    Returns (filings, the previously published filings, {county: status})."""
    before = json.load(open(FILINGS, encoding="utf-8")) if os.path.exists(FILINGS) else []
    rings = {locality_label(c["attributes"]["NAME"], c["attributes"]["FIPS"]): c["geometry"]["rings"]
             for c in json.load(open(os.path.join(CACHE, "deq_counties.json"), encoding="utf-8"))}

    def inside(county, lon, lat):
        return county in rings and geo.in_esri_polygon(lon, lat, rings[county])

    out, status = [], {}
    for county, cache_name, fetch, adapt in FILING_SOURCES:
        prev = [f for f in before if f["county"] == county]
        try:
            new = adapt(cached(cache_name, fetch, offline))
            bad = filings.problems(new, prev, inside)
        except Exception as ex:  # server down, HTML instead of JSON, changed fields: keep the last good copy
            bad = [f"{county} source unavailable ({type(ex).__name__}: {str(ex)[:120]})"]
        if bad:
            print(f"warning: {county} filings not updated; keeping the {len(prev)} published before:\n  "
                  + "\n  ".join(bad[:8]))
            out += prev
            status[county] = {"updated": False, "filings": len(prev), "problem": bad[0]}
        else:
            out += new
            status[county] = {"updated": True, "filings": len(new)}
    out.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return out, before, status


def write(facilities, schools, zips, meta):
    os.makedirs(OUT, exist_ok=True)
    for name, obj in [("facilities", facilities), ("schools", schools), ("zips", zips), ("meta", meta)]:
        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    fac, sch, zp, meta = build(offline=args.offline)
    fil, fil_before, meta["filings"] = build_filings(offline=args.offline)
    meta["sources"]["loudoun_lola"] = sources.LOUDOUN_LOLA
    # Change log: compare with the facility list already committed, before overwriting it.
    prev_path = os.path.join(OUT, "facilities.json")
    before = json.load(open(prev_path, encoding="utf-8")) if os.path.exists(prev_path) else None
    # Offline builds use cached (possibly days-old) source data, so they never add to the change log.
    log, added = changes.update(os.path.join(OUT, "changes.json"), None if args.offline else before, fac,
                                dt.date.today().isoformat())
    # New county filings and status changes (not on the first run, when there's no previous list to compare with).
    if not args.offline and fil_before:
        added += changes.add(log, filings.diff(fil_before, fil, dt.date.today().isoformat()))
    write(fac, sch, zp, meta)
    with open(FILINGS, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(fil, fh, ensure_ascii=False, indent=0)
        fh.write("\n")
    with open(os.path.join(OUT, "changes.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"change log: {len(added)} new event(s) today; {len(log['events'])} since {log['since']}")
    civic.refresh(os.path.join(OUT, "meetings.json"), CACHE, offline=args.offline)  # optional; never fails
    counts = pages.build_pages(SITE, STATE, fac, sch, zp, meta, log, CONFIG, filings=fil)
    print(f"pages: {counts['localities']} counties/cities, {counts['zips']} ZIP codes, {counts['schools']} schools, "
          f"{counts['facilities']} data centers ({counts['total']} total) + sitemap, RSS")
    print(f"{meta['facilities']} data centers {meta['stages']}; {meta['schools']} schools; {meta['zips']} ZIPs; "
          f"permit snapshot {meta['permit_snapshot']} ({meta['permits_in_snapshot']} permits, "
          f"{meta['facilities_without_permit_row']} facilities not on the list yet)")
    print("top localities:", meta["localities"][:6])
    print("county filings:", {c: (v["filings"], "updated" if v["updated"] else "kept previous") for c, v in meta["filings"].items()})
