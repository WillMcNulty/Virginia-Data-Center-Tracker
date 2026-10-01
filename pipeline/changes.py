"""The change log: what changed on DEQ's records between one build and the next.

Each build compares the new facility list with the one already committed (site/virginia/data/facilities.json) and
appends any differences to site/virginia/data/changes.json, which is committed too, so the history accumulates:

  {"since": "2026-09-30", "events": [
     {"date": "2026-10-02", "type": "new", "id": 74350, "name": "...", "locality": "...", "stage": "planned"},
     {"date": "2026-10-05", "type": "stage", "id": 74332, ..., "from": "planned", "to": "construction"},
     {"date": "...", "type": "removed" | "permit" | "renamed", ...},
     {"date": "...", "type": "filing-new", "id": "EPLAN-2026-0140", "name": "...", "locality": "Loudoun County",
      "kind": "site-plan", "filing_type": "Site plan", "label": "Site plan in review"},
     {"date": "...", "type": "filing-status", "id": "LEGI-...", ..., "from": "<old label>", "to": "<new label>"}]}

Facility events have DEQ registration numbers (integers) as ids; county filing events (see filings.diff) have the
county's plan numbers (strings).

Rebuilding twice on the same day doesn't log the same change twice. The "New this week" page, its RSS feed and
(later) email alerts all read this file.
"""
import json
import os

KEYS = ("date", "type", "id", "from", "to")


def diff(before, after, date):
    """Events between two facility lists (each a list of dicts keyed by 'id')."""
    old = {f["id"]: f for f in before}
    new = {f["id"]: f for f in after}
    events = []

    def ev(kind, f, **extra):
        e = {"date": date, "type": kind, "id": f["id"], "name": f["name"], "locality": f.get("locality"),
             "stage": f.get("stage")}
        e.update(extra)
        events.append(e)

    for fid, f in new.items():
        if fid not in old:
            ev("new", f)
            continue
        o = old[fid]
        if o.get("stage") != f.get("stage"):
            ev("stage", f, **{"from": o.get("stage"), "to": f.get("stage")})
        if (f.get("latest_permit") or "") > (o.get("latest_permit") or ""):
            ev("permit", f, **{"from": o.get("latest_permit"), "to": f.get("latest_permit")})
        if o.get("name") != f.get("name"):
            ev("renamed", f, **{"from": o.get("name"), "to": f.get("name")})
    for fid, o in old.items():
        if fid not in new:
            ev("removed", o)
    order = {"new": 0, "stage": 1, "permit": 2, "renamed": 3, "removed": 4}
    events.sort(key=lambda e: (order[e["type"]], e["name"]))
    return events


def update(path, before, after, date):
    """Append today's events to the log at `path` (created with today as its start if missing). Returns new events."""
    log = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"since": date, "events": []}
    if before is None:
        return log, []
    return log, add(log, diff(before, after, date))


def add(log, events):
    """Put `events` at the top of `log` (newest first), skipping any already logged. Returns the ones added."""
    seen = {tuple(e.get(k) for k in KEYS) for e in log["events"]}
    added = [e for e in events if tuple(e.get(k) for k in KEYS) not in seen]
    log["events"] = added + log["events"]
    return added
