"""Downloadable CSVs for the /data/ page, written at build time from the same lists as the JSON files.

  <state>-data-centers.csv    one row per data center on DEQ's records (site/<state>/data/facilities.json)
  <state>-changes.csv         one row per change log event (site/<state>/data/changes.json)
  <state>-county-filings.csv  one row per county filing (site/<state>/data/filings.json; schema in filings.py)

Columns are stable: add new ones at the end, never rename or reorder (people's spreadsheets depend on them). Each
column's meaning is in COLUMNS and printed on the /data/ page. Every row carries the official source URL. UTF-8,
RFC 4180 quoting (the csv module), CRLF line endings as the RFC says. No personal data: the inputs carry none
(filings.py scrubs descriptions; LOLA's staff-assignment fields are never fetched), and check() refuses a file
with a column or a value that looks like one.
"""
import csv
import os
import re

import filings as filings_mod

DEQ_RECORD = ("https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294/query"
              "?where=PLA_REG_NUM%3D{}&outFields=*&f=html")
DEQ_PERMIT_PAGE = "https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers"

# (column, description). Order is the file's column order.
COLUMNS = {
    "data-centers": [
        ("deq_registration_number", "DEQ's air registration number for the site (its ID on DEQ's records)."),
        ("name", "Facility name as DEQ lists it."),
        ("street_address", "Street address as DEQ lists it (blank when DEQ doesn't list one)."),
        ("city", "City or town as DEQ lists it."),
        ("zip", "ZIP code as DEQ lists it (blank when DEQ doesn't list one)."),
        ("locality", "County or independent city the point falls in, by DEQ's boundary map (our calculation)."),
        ("permit_list_locality", "Locality named on DEQ's issued-permit list, when it has the site (can differ; see the methodology)."),
        ("latitude", "Latitude (WGS84) of DEQ's point for the site."),
        ("longitude", "Longitude (WGS84) of DEQ's point for the site."),
        ("deq_status", "DEQ's operating status, as DEQ writes it."),
        ("stage", "The site's stage on this map: planned, construction, operating, shutdown or other (DEQ's status, renamed)."),
        ("permit_class", "DEQ's permit class (for example Synthetic Minor)."),
        ("air_permit_count", "Number of issued air permits for the site on DEQ's issued-permit list (snapshot)."),
        ("latest_air_permit_date", "Issue date (YYYY-MM-DD) of the newest of those permits; blank if none yet."),
        ("air_permits", "Each issued permit as 'number (date, program)', separated by '; '."),
        ("deq_record_url", "The site's record on DEQ's Air Sites service (the official source)."),
        ("permit_list_url", "DEQ's issued-permit list, when the site has a row on it."),
    ],
    "changes": [
        ("date", "Date the change was noticed (YYYY-MM-DD), by comparing one morning's records with the day before."),
        ("event", "new, stage, permit, renamed or removed (DEQ records); filing-new or filing-status (county filings)."),
        ("record", "data-center (DEQ) or county-filing."),
        ("id", "DEQ registration number, or the county's plan/case number."),
        ("name", "Name on the record."),
        ("locality", "County or independent city."),
        ("stage", "The data center's stage after the change (DEQ records only)."),
        ("from", "Value before the change (stage, permit date, old name or filing status)."),
        ("to", "Value after the change."),
        ("filing_type", "Application type, for new county filings (for example Site plan)."),
        ("filing_status", "Status as residents read it, for new county filings."),
        ("source_url", "The official record (DEQ's Air Sites record or the county's record)."),
    ],
    "county-filings": [
        ("id", "The county's plan or case number."),
        ("county", "County."),
        ("kind", "land-use (the county board decides, usually after a public hearing) or site-plan (county staff review); our grouping of the county's types."),
        ("type", "Application type in plain English (our wording of the county's type)."),
        ("status", "in-review, approved or denied (the county's status, simplified)."),
        ("label", "The status as residents read it."),
        ("date", "Application date (YYYY-MM-DD)."),
        ("name", "Plan name as filed (a private person's name is withheld)."),
        ("description", "The county's description, with staff initials and references to people removed; at most 500 characters."),
        ("lat", "Latitude (WGS84) of the center of the application's parcel outline (our calculation)."),
        ("lon", "Longitude (WGS84) of that center."),
        ("source", "The county's record (the official source)."),
        ("related", "Sub-applications folded into this one, separated by '; '."),
    ],
}
FILES = {"data-centers": "{state}-data-centers.csv", "changes": "{state}-changes.csv",
         "county-filings": "{state}-county-filings.csv"}
# Column names or values that would mean personal data slipped in (LOLA's AssignedTo fields, emails, phones).
PERSONAL_COLUMN = re.compile(r"assigned|email|phone|owner|applicant|contact|staff|planner", re.I)
PERSONAL_VALUE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b")


def facility_rows(facilities):
    for f in facilities:
        yield [f["id"], f["name"], f["address"], f["city"], f["zip"], f["locality"] or "", f.get("listed_locality") or "",
               f["lat"], f["lon"], f["status"], f["stage"], f.get("permit_class") or "", len(f["permits"]),
               f.get("latest_permit") or "",
               "; ".join(f"{p['no']} ({p['issued'] or 'date not listed'}, {p['program']})" for p in f["permits"]),
               DEQ_RECORD.format(f["id"]), DEQ_PERMIT_PAGE if f["permits"] else ""]


def change_rows(log, filings):
    by_id = {f["id"]: f for f in filings}
    for ev in log["events"]:
        filing = ev["type"].startswith("filing-")
        if filing:
            source = by_id[ev["id"]]["source"] if ev["id"] in by_id else (
                filings_mod.SOURCE.format(ev["id"]) if ev.get("locality") == "Loudoun County" else "")
        else:
            source = DEQ_RECORD.format(ev["id"])
        yield [ev["date"], ev["type"], "county-filing" if filing else "data-center", ev["id"], ev.get("name") or "",
               ev.get("locality") or "", ev.get("stage") or "", ev.get("from") or "", ev.get("to") or "",
               ev.get("filing_type") or "", ev.get("label") or "", source]


def filing_rows(filings):
    for f in filings:
        yield [f[k] if k != "related" else "; ".join(f.get("related") or []) for k, _ in COLUMNS["county-filings"]]


def write(out_dir, state, facilities, log, filings):
    """Write the three CSVs into out_dir, then check() them. Returns {key: (file name, row count)}."""
    os.makedirs(out_dir, exist_ok=True)
    rows = {"data-centers": facility_rows(facilities), "changes": change_rows(log, filings),
            "county-filings": filing_rows(filings)}
    written = {}
    for key, gen in rows.items():
        name = FILES[key].format(state=state)
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)  # default dialect: RFC 4180 quoting, \r\n line endings
            w.writerow([c for c, _ in COLUMNS[key]])
            n = 0
            for r in gen:
                w.writerow(r)
                n += 1
        written[key] = (name, n)
    check(out_dir, written, {"data-centers": len(facilities), "changes": len(log["events"]),
                             "county-filings": len(filings)})
    return written


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def check(out_dir, written, expected):
    """Refuse to publish CSVs that don't match the JSON they came from, or that look like they carry personal data."""
    problems = []
    for key, (name, _) in written.items():
        table = read(os.path.join(out_dir, name))
        header, body = table[0], table[1:]
        if header != [c for c, _ in COLUMNS[key]]:
            problems.append(f"{name}: header {header} doesn't match the documented columns")
        if len(body) != expected[key]:
            problems.append(f"{name}: {len(body)} rows, but the JSON has {expected[key]}")
        if any(len(r) != len(header) for r in body):
            problems.append(f"{name}: rows with the wrong number of columns")
        if [c for c in header if PERSONAL_COLUMN.search(c)]:
            problems.append(f"{name}: a column looks like personal data")
        hits = [v for r in body for v in r if PERSONAL_VALUE.search(v)]
        if hits:
            problems.append(f"{name}: values that look like an email or phone number: {hits[:3]}")
        src = header.index("source" if key == "county-filings" else "deq_record_url" if key == "data-centers" else "source_url")
        if any(not r[src].startswith("https://") for r in body if key != "changes" or r[2] == "data-center"):
            problems.append(f"{name}: rows without an official source URL")
    if problems:
        raise SystemExit("download check failed:\n  " + "\n  ".join(problems))
