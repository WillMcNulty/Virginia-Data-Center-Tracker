"""County filings: the earliest stage, before any DEQ air permit. Loudoun County first (its LOLA land applications).

Turns raw applications into what residents care about:
  - land-use approvals (rezonings, special exceptions, legislative applications, concept plan amendments,
    commission permits): the county board decides these, usually after a public hearing;
  - site plans (engineering plans): the construction plans, reviewed by county staff.
Bonds, plats, floodplain studies and correspondence are left out as paperwork.

Loudoun files one umbrella legislative application (LEGI-...) plus sub-applications whose description starts
"SEE LEGI-... FOR DOCUMENTS"; those are folded into their umbrella so each proposal appears once.

Every county adapter returns the same shape (site/virginia/data/filings.json is a list of these, newest first):
  id           the county's plan/case number, e.g. "EPLAN-2026-0140" (must be unique across counties)
  county       locality name as the site writes it, e.g. "Loudoun County"
  kind         "land-use" (the board decides, usually after a hearing) or "site-plan" (staff review)
  type         plain-English application type, e.g. "Rezoning", "Special exception", "Site plan"
  status       "in-review", "approved", "denied" (or the county's own word, lowercased)
  label        the status as residents read it, e.g. "Proposed: in county review"
  date         application date, ISO (YYYY-MM-DD)
  name         the plan's name as filed (a private person's name is withheld)
  description  the county's description, cleaned of staff initials and personal references, at most 500 characters
  lat, lon     center of the application's parcel outline (WGS84)
  source       link to the official county record
  related      sub-applications folded into this one, e.g. ["Special exception SPEX-2026-0037"]
"""
import datetime as dt
import re

LAND_USE = {"Legislative Application": "Legislative application", "Zoning Map Amendment": "Rezoning",
            "Special Exception": "Special exception", "Zoning Concept Plan Amendment": "Concept plan amendment",
            "Commission Permit": "Commission permit"}
SITE_PLAN = {"Engineering Plan": "Site plan"}
IN_REVIEW = {"In Review", "Submitted", "Submitted - Online"}
KEEP_DECIDED_SINCE = dt.date(2021, 1, 1)  # decided filings older than this are history, not news
STATUS_LABEL = {("land-use", "in-review"): "Proposed: in county review",
                ("land-use", "approved"): "Approved by the county",
                ("land-use", "denied"): "Denied by the county",
                ("site-plan", "in-review"): "Site plan in review",
                ("site-plan", "approved"): "Site plan approved",
                ("site-plan", "denied"): "Site plan denied"}
# Personal data: LOLA descriptions can name people (a landowner, an applicant's attorney) and many end with the
# reviewing planner's initials ("... ZONING DISTRICT. HV"). None of that is published: initials and review-session
# numbers are stripped, a description that names someone acting "on behalf of" an owner is replaced, and the few
# plan names that carry a private person's name are withheld (hand-kept list; add to it when a new one appears).
WITHHELD_NAME_WORDS = {"LAKHVINDER"}
PERSONAL_HINTS = re.compile(r"on behalf of|\bEsq\b|\b(?:Mr|Mrs|Ms|Dr)\.\s|@|\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b", re.I)
CODES = {"STPL", "STMP", "SPAM", "SPEX", "ZMAP", "LEGI", "CMPT", "ZRTD", "FAR", "IP", "PD", "SWM", "BMP", "AC", "SF",
         "GFA", "MRHI", "PDIP", "PDOP", "PDGI", "TLTD", "CLI", "LB", "SPMI", "CPAR", "CPAP"}
SOURCE = ("https://logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0/query?where=PlanNumber%3D%27{}%27"
          "&outFields=PlanNumber,PlanApplicationDate,PlanType,PlanStatus,PlanName,PlanDescription&returnGeometry=false&f=html")


# Every filing has these fields, whatever the county (the Fairfax and Prince William adapters must match):
FIELDS = ("id", "county", "kind", "type", "status", "label", "date", "name", "description", "lat", "lon", "source",
          "related")


def status_of(raw):
    if raw in IN_REVIEW:
        return "in-review"
    return {"Approved": "approved", "Denied": "denied"}.get(raw, (raw or "unknown").lower())


def centroid(rings):
    """Center of the largest ring (the parcel outline), by the shoelace formula."""
    best, best_area = None, 0.0
    for ring in rings:
        a = cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            cross = x1 * y2 - x2 * y1
            a += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if abs(a) > best_area and a:
            best_area, best = abs(a), (cy / (3 * a), cx / (3 * a))
    if best is None:  # degenerate outline: average the points
        pts = [p for r in rings for p in r]
        best = (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))
    return round(best[0], 6), round(best[1], 6)


def clean_text(s, limit=500):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def scrub(text):
    """A LOLA description with staff initials, review-session numbers and personal references removed."""
    s = re.sub(r"\s+", " ", text or "").strip()
    s = re.sub(r"\(?\bBluebeam\s+session\s*(?:#|id|number)?\s*(?:is)?\s*#?\s*[\d-]{7,}\)?\.?", "", s, flags=re.I)
    # the reviewer's initials, after the zoning district or a closing parenthesis, at the end of the description or
    # just before a plan number ("... (PDIP) ZONING DISTRICT. AM", "... DISTRICT. JAB STMP-2022-0006.")
    s = re.sub(r"(DIST\w*\.?|[.)])\s+([A-Z]{2,4})\.?(?=\s*$|\s+[A-Z]{4,5}-\d{4}-\d{4})",
               lambda m: m.group(0) if m.group(2) in CODES else m.group(1), s)
    for w in WITHHELD_NAME_WORDS:
        s = re.sub(rf"\b{w}\b", "(name withheld)", s, flags=re.I)
    if PERSONAL_HINTS.search(s):
        return "The county record's description names individuals; see the county record."
    return re.sub(r"\s+", " ", s).strip()


def display_name(raw_name, plan_type, plan_number):
    name = clean_text(raw_name, 120)
    if not name or any(re.search(rf"\b{w}\b", name, re.I) for w in WITHHELD_NAME_WORDS) or PERSONAL_HINTS.search(name):
        return f"{plan_type} {plan_number}"
    return name


def problems(filings, before=None, inside=None):
    """What's wrong with a filings list, for the build's publish-or-keep-yesterday's decision (empty = fine).
    `before` is the previously published list; `inside(county, lon, lat)` says whether a point is in that county."""
    out = []
    counts = {}
    for f in filings:
        counts[f.get("county")] = counts.get(f.get("county"), 0) + 1
    prev = {}
    for f in before or []:
        prev[f.get("county")] = prev.get(f.get("county"), 0) + 1
    for county, n in prev.items():
        if counts.get(county, 0) < 0.75 * n:
            out.append(f"{county}: filings fell from {n} to {counts.get(county, 0)} (over 25%)")
    if not filings:
        out.append("no filings")
    # A parcel on the county line can have its center a few meters over the (simplified) boundary; more than a couple
    # outside means the coordinates are wrong (projection, swapped axes), so nothing is published.
    located = lambda f: all(isinstance(f.get(k), (int, float)) for k in ("lat", "lon"))  # noqa: E731
    outside = [f.get("id") for f in filings if inside and not (located(f) and inside(f["county"], f["lon"], f["lat"]))]
    if len(outside) > 2:
        out.append(f"{len(outside)} filings are outside their county: {outside[:5]}")
    ids = [f.get("id") for f in filings]
    if len(set(ids)) != len(ids):
        out.append("duplicate filing ids")
    for f in filings:
        missing = [k for k in FIELDS if f.get(k) is None or (f.get(k) == "" and k != "description")]
        if missing:
            out.append(f"{f.get('id')}: missing {missing}")
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["date"]):
            out.append(f"{f['id']}: bad date {f['date']}")
        if not f["source"].startswith("https://"):
            out.append(f"{f['id']}: source is not a link")
        if PERSONAL_HINTS.search(f["name"] + " " + f.get("description", "")):
            out.append(f"{f['id']}: text looks like it names a person")
    return out


def diff(before, after, date):
    """Change-log events between two filings lists: new filings and status changes (e.g. in review -> approved)."""
    old = {f["id"]: f for f in before}
    events = []
    for f in after:
        base = {"date": date, "id": f["id"], "name": f["name"], "locality": f["county"], "kind": f["kind"],
                "filing_type": f["type"], "label": f["label"]}
        o = old.get(f["id"])
        if o is None:
            events.append(dict(base, type="filing-new"))
        elif o.get("status") != f.get("status"):
            events.append(dict(base, type="filing-status", **{"from": o.get("label"), "to": f.get("label")}))
    events.sort(key=lambda e: (e["type"] != "filing-new", e["name"]))
    return events


def loudoun(raw):
    """Raw LOLA features -> filings (list of dicts), one per proposal."""
    rows = []
    for f in raw:
        a, g = f["attributes"], f.get("geometry") or {}
        kind = "land-use" if a["PlanType"] in LAND_USE else "site-plan" if a["PlanType"] in SITE_PLAN else None
        if not kind or not g.get("rings") or not a.get("PlanApplicationDate"):
            continue
        date = dt.datetime.fromtimestamp(a["PlanApplicationDate"] / 1000, dt.timezone.utc).date()
        status = status_of(a["PlanStatus"])
        if status != "in-review" and date < KEEP_DECIDED_SINCE:
            continue
        lat, lon = centroid(g["rings"])
        rows.append({
            "id": a["PlanNumber"], "county": "Loudoun County", "kind": kind,
            "type": (LAND_USE | SITE_PLAN)[a["PlanType"]], "status": status,
            "label": STATUS_LABEL.get((kind, status), a["PlanStatus"]),
            "date": date.isoformat(), "name": display_name(a.get("PlanName"), (LAND_USE | SITE_PLAN)[a["PlanType"]], a["PlanNumber"]),
            "description": clean_text(scrub(a.get("PlanDescription"))), "lat": lat, "lon": lon,
            "source": SOURCE.format(a["PlanNumber"]), "related": [],
        })
    # Fold "SEE LEGI-XXXX-XXXX FOR DOCUMENTS" sub-applications into their umbrella application.
    by_id = {r["id"]: r for r in rows}
    out = []
    for r in rows:
        m = re.match(r"SEE (LEGI-\d{4}-\d{4})", r["description"], re.I)
        if m and m.group(1).upper() in by_id:
            by_id[m.group(1).upper()]["related"].append(f"{r['type']} {r['id']}")
            continue
        out.append(r)
    for r in out:
        r["related"].sort()
    out.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return out
