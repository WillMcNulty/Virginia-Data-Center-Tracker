"""County filings: the earliest stage, before any DEQ air permit. Loudoun County first (its LOLA land applications).

Turns raw applications into what residents care about:
  - land-use approvals (rezonings, special exceptions, legislative applications, concept plan amendments,
    commission permits): the county board decides these, usually after a public hearing;
  - site plans (engineering plans): the construction plans, reviewed by county staff.
Bonds, plats, floodplain studies and correspondence are left out as paperwork.

Loudoun files one umbrella legislative application (LEGI-...) plus sub-applications whose description starts
"SEE LEGI-... FOR DOCUMENTS"; those are folded into their umbrella so each proposal appears once.
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
SOURCE = ("https://logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0/query?where=PlanNumber%3D%27{}%27"
          "&outFields=PlanNumber,PlanApplicationDate,PlanType,PlanStatus,PlanName,PlanDescription&returnGeometry=false&f=html")


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
            "date": date.isoformat(), "name": clean_text(a.get("PlanName"), 120) or a["PlanNumber"],
            "description": clean_text(a.get("PlanDescription")), "lat": lat, "lon": lon,
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
