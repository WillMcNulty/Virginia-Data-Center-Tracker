"""Civic layer, v1: public meetings whose published agendas mention data centers, and how to take part.

Sources (official agenda pages, published by each county through Granicus):
  Fairfax County       video.fairfaxcounty.gov  view 7   Board of Supervisors
  Loudoun County       loudoun.granicus.com     view 89  Board of Supervisors, Planning Commission, committees
  Prince William County pwcgov.granicus.com     view 23  Board of County Supervisors and joint meetings
Each publishes an agenda RSS feed (ViewPublisherRSS.php?view_id=N&mode=agendas). For the meetings in our window
(upcoming, plus the last WINDOW_DAYS_BACK days) we read the agenda HTML, split it into numbered items, and keep the
items whose text says "data center" (or names a Loudoun case number that is a data center filing, once
site/virginia/data/filings.json exists). Fairfax links its agendas to a PDF board package, which the standard
library can't search, so Fairfax meetings are listed as "not searched".

Item text is shown as the agenda shows it, minus presenter/staff names (Prince William appends "- Name, Department";
Loudoun appends "Project Manager: Name"): no staff names on this site. check() refuses output that still has them.

robots.txt: in September 2026 all three Granicus hosts answered "User-agent: * / Disallow: /" (only named search
engines allowed). The project doesn't fetch pages that block bots, so with RESPECT_ROBOTS_TXT = True the daily build
skips those counties with a warning and keeps the last good meetings.json. Until the owner decides otherwise (for
example after asking the counties), meetings.json is refreshed by hand, like DEQ's permit list:

    save each county's agenda RSS feed and the agendas you want searched from a browser into
      DIR/<county-slug>/feed.xml            (the ViewPublisherRSS.php page)
      DIR/<county-slug>/<id>.html           (id = "clip-<clip_id>" or "event-<event_id>" from the agenda link)
    python pipeline/civic.py --saved DIR [--checked YYYY-MM-DD]

The build (build.py) calls refresh(); it never fails the build: a county that can't be read keeps its last good data.
Standard library only.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

UA = "Virginia-Data-Center-Tracker/1.0 (+https://github.com/WillMcNulty/Virginia-Data-Center-Tracker)"
RESPECT_ROBOTS_TXT = True  # owner's call; see the module docstring
WINDOW_DAYS_BACK = 21      # recent meetings kept alongside upcoming ones
MAX_AGENDAS = 10           # per county per run: be polite
PAUSE = 2.0                # seconds between requests to the same county
TIMEOUT = 30
MAX_MATCHES_PER_AGENDA = 20  # more than this means we matched boilerplate, not items

COUNTIES = [
    {"locality": "Fairfax County", "slug": "fairfax-county", "host": "https://video.fairfaxcounty.gov", "view": 7,
     "agenda": "pdf",
     "pdf_note": "Fairfax posts its Board agendas as a PDF board package, which this site doesn't search yet. "
                 "Open the agenda to check it."},
    {"locality": "Loudoun County", "slug": "loudoun-county", "host": "https://loudoun.granicus.com", "view": 89,
     "agenda": "html"},
    {"locality": "Prince William County", "slug": "prince-william-county", "host": "https://pwcgov.granicus.com",
     "view": 23, "agenda": "html"},
]
BY_LOCALITY = {c["locality"]: c for c in COUNTIES}

DC_RE = re.compile(r"\bdata[\s-]*cent(?:er|re)s?\b", re.I)
CASE_RE = re.compile(r"\b[A-Z]{3,5}-\d{4}-\d{4,5}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NUMBER_RE = re.compile(r"^(?:[IVXL]+|\d{1,2}|[A-Z])(?:\.(?:[A-Z]|\d{1,2}))*\.?$")
ROMAN_RE = re.compile(r"^[IVXL]+\.?$")
# "Name Name, Department" (or "Name / Name, Department") at the end of a Prince William item: the presenters.
_NAME = r"(?:Dr\.\s)?[A-Z][A-Za-z.'’-]*(?:\s[A-Z][A-Za-z.'’-]*){1,3}"
PRESENTER_RE = re.compile(rf"^{_NAME}(?:\s*(?:/|and|&)\s*{_NAME})*,\s.+$")
STAFF_LABEL_RE = re.compile(r"\s*(?:Project Manager|Staff Contact|Staff|Presenter)s?:.*$", re.I)


# ---- the feed -------------------------------------------------------------------------------------------------------

def feed_url(county):
    return f"{county['host']}/ViewPublisherRSS.php?view_id={county['view']}&mode=agendas"


def meeting_id(link):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    for key in ("event_id", "clip_id"):
        if q.get(key):
            return f"{key.split('_')[0]}-{q[key][0]}"
    return None


def parse_rss(xml_bytes):
    """Granicus agenda RSS -> [{id, date, name, link, published}] (one per meeting, Spanish-caption copies dropped)."""
    root = ET.fromstring(xml_bytes)
    ns = {"gran": "https://www.granicus.com/schema/rss-supplements"}
    out, seen = [], set()
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        m = re.search(r"\s+-\s+([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$", title)
        if m:
            date = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
            # Fairfax repeats the date in front ("September 29, 2026 Board of Supervisors Meeting")
            name = re.sub(r"^[A-Z][a-z]+ \d{1,2}, \d{4},?\s+", "", title[:m.start()]).strip()
        else:
            p = it.find("gran:pubDateParts", ns)
            if p is None:
                continue
            date = dt.date(int(p.get("yr")), int(p.get("mo")), int(p.get("day")))
            name = title
        if "spanish captions" in name.lower():
            continue  # Fairfax posts each meeting twice; the captioned copy has the same agenda
        mid = meeting_id(link)
        if not mid or not link.startswith("https://") or (date, name) in seen:
            continue
        seen.add((date, name))
        desc = (it.findtext("description") or "").lower()
        out.append({"id": mid, "date": date.isoformat(), "name": name, "link": link,
                    "published": "has been archived" not in desc})
    return out


# ---- the agenda -----------------------------------------------------------------------------------------------------

def _lines(markup):
    s = re.sub(r"<(script|style|head)\b.*?</\1\s*>", " ", markup, flags=re.S | re.I)
    # attachment links (Loudoun: class="Document ..."; Prince William: title="Attachment") aren't item text
    s = re.sub(r"<a\b[^>]*(?:class=\"Document|title=\"Attachment\")[^>]*>.*?</a>", " ", s, flags=re.S | re.I)
    # Prince William italicizes the strategic-plan goal at the end of each item; mark it so it can be dropped
    s = re.sub(r"<em\b[^>]*>(.*?)</em>", "\x01\\1\x02", s, flags=re.S | re.I)
    s = re.sub(r"<(?:br|/tr|/td|/p|/div|/li|/h\d|/table)\b[^>]*>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return [" ".join(line.replace("\xa0", " ").split()) for line in s.splitlines() if line.strip(" \xa0\t")]


def clean_item(text):
    """The item as the agenda shows it, minus presenter/staff names and the strategic-plan goal."""
    text = re.sub(r"\s*-\s*\x01[^\x02]*\x02\s*$", "", text)  # "- <em>goal</em>" at the end
    text = text.replace("\x01", "").replace("\x02", "")
    text = STAFF_LABEL_RE.sub("", text)
    parts = text.split(" - ")
    last = parts[-1].strip()
    if len(parts) > 2 and "District" not in last and PRESENTER_RE.match(last):
        parts = parts[:-1]
    return " - ".join(parts).strip(" -")


def agenda_items(markup):
    """Agenda HTML -> [{number, section, text}]: every numbered line and the heading line that follows it."""
    lines = _lines(markup)
    roman = any(ROMAN_RE.match(x) for x in lines)
    items, section = [], None
    for i, line in enumerate(lines[:-1]):
        if not NUMBER_RE.match(line) or NUMBER_RE.match(lines[i + 1]):
            continue
        text = clean_item(lines[i + 1])
        if not text:
            continue
        top = bool(ROMAN_RE.match(line)) if roman else bool(re.fullmatch(r"\d{1,2}\.?", line))
        if top:
            section = text
        items.append({"number": line, "section": None if top else section, "text": text})
    return items


def match_items(items, cases=frozenset()):
    """The items that mention a data center, or a case number known to be a data center filing."""
    out = []
    for it in items:
        why = None
        if DC_RE.search(it["text"]):
            why = "mentions a data center"
        else:
            hit = next((c for c in CASE_RE.findall(it["text"]) if c in cases), None)
            if hit:
                why = f"{hit} is a data center filing on the county's records"
        if why:
            out.append(dict(it, why=why))
    return out


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def known_cases(filings_path):
    """Case numbers of county data center filings (site/virginia/data/filings.json, once filings are wired in)."""
    if not os.path.exists(filings_path):
        return frozenset()
    try:
        data = _read_json(filings_path)
    except (OSError, ValueError):
        return frozenset()
    rows = data.get("filings", data) if isinstance(data, dict) else data
    cases = set()
    for r in rows if isinstance(rows, list) else []:
        cases.add(str(r.get("id", "")))
        cases.update(CASE_RE.findall(" ".join(r.get("related") or [])))
    return frozenset(c for c in cases if CASE_RE.fullmatch(c))


# ---- fetching -------------------------------------------------------------------------------------------------------

class Skip(Exception):
    """This county can't be read right now; keep its last good data."""


class LiveFetcher:
    """Fetches from the county's Granicus host, obeying robots.txt, and saves what it reads to cache_dir."""

    def __init__(self, cache_dir):
        self.cache_dir, self.robots, self.last = cache_dir, {}, 0.0

    def allowed(self, url):
        if not RESPECT_ROBOTS_TXT:
            return True
        host = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(self._get(host + "/robots.txt").decode("utf-8", "replace").splitlines())
            except Exception:
                rp = None  # no robots.txt we can read: no stated rules
            self.robots[host] = rp
        rp = self.robots[host]
        return rp is None or rp.can_fetch(UA, url)

    def _get(self, url):
        wait = PAUSE - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(3_000_000)

    def __call__(self, county, name, url):
        if not self.allowed(url):
            raise Skip(f"robots.txt on {urllib.parse.urlparse(url).netloc} asks automated clients not to fetch it")
        try:
            body = self._get(url)
        except Exception as ex:
            raise Skip(f"{url}: {ex}")
        d = os.path.join(self.cache_dir, county["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(body)
        return body


class SavedFetcher:
    """Reads pages saved earlier: the build's cache (offline builds) or pages saved by hand from a browser."""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, county, name, url):
        path = os.path.join(self.folder, county["slug"], name)
        if not os.path.exists(path):
            raise Skip(f"no saved copy of {url} at {path}")
        with open(path, "rb") as fh:
            return fh.read()


# ---- one county -----------------------------------------------------------------------------------------------------

def read_county(county, fetch, today, cases=frozenset()):
    """-> the county's block for meetings.json. Raises Skip if the feed can't be read or looks broken."""
    try:
        meetings = parse_rss(fetch(county, "feed.xml", feed_url(county)))
    except ET.ParseError as ex:
        raise Skip(f"feed is not valid RSS ({ex})")
    if not meetings:
        raise Skip("feed has no meetings")
    start = (today - dt.timedelta(days=WINDOW_DAYS_BACK)).isoformat()
    window = sorted((m for m in meetings if m["date"] >= start), key=lambda m: m["date"])
    out, fetched = [], 0
    for m in window:
        row = {"id": m["id"], "date": m["date"], "name": m["name"], "agenda_url": m["link"],
               "searched": False, "items": []}
        if county["agenda"] != "html":
            row["note"] = county.get("pdf_note")
        elif fetched >= MAX_AGENDAS:
            row["note"] = "Not searched this time (limit reached). Open the agenda to check it."
        else:
            fetched += 1
            try:
                markup = fetch(county, f"{m['id']}.html", m["link"]).decode("utf-8", "replace")
                items = agenda_items(markup)
            except Skip as ex:
                if "robots.txt" in str(ex):
                    raise
                items, markup = [], None
                print(f"warning: civic: {county['locality']}: {ex}")
            if items:
                matched = match_items(items, cases)
                if len(matched) > MAX_MATCHES_PER_AGENDA:
                    raise Skip(f"{m['link']}: {len(matched)} data center items; the agenda layout may have changed")
                row.update(searched=True, item_count=len(items), items=matched)
            else:
                row["note"] = "This site couldn't read this agenda. Open it to check it."
        out.append(row)
    return {"checked": today.isoformat(), "feed": feed_url(county), "meetings": out}


# ---- the output file ------------------------------------------------------------------------------------------------

def check(data):
    """Stop before publishing meetings data that looks broken or carries personal data."""
    problems = []
    if set(data.get("counties", {})) - set(BY_LOCALITY):
        problems.append(f"unknown counties: {set(data['counties']) - set(BY_LOCALITY)}")
    for loc, block in data.get("counties", {}).items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", block.get("checked", "")):
            problems.append(f"{loc}: bad checked date")
        for m in block.get("meetings", []):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.get("date", "")):
                problems.append(f"{loc}: bad meeting date {m.get('date')}")
            if not m.get("agenda_url", "").startswith("https://"):
                problems.append(f"{loc}: agenda link missing for {m.get('name')}")
            if len(m.get("items", [])) > MAX_MATCHES_PER_AGENDA:
                problems.append(f"{loc}: {len(m['items'])} items on one agenda")
            for it in m.get("items", []):
                text = " ".join(str(it.get(k) or "") for k in ("text", "section"))
                if EMAIL_RE.search(text) or STAFF_LABEL_RE.search(text):
                    problems.append(f"{loc}: staff contact left in item text: {text[:80]}")
                if not it.get("text") or len(it["text"]) > 1500:
                    problems.append(f"{loc}: implausible item text: {it.get('text', '')[:80]}")
    if problems:
        raise ValueError("meetings check failed:\n  " + "\n  ".join(problems))


def load(path):
    try:
        data = _read_json(path)
        check(data)
        return data
    except (OSError, ValueError):
        return {"counties": {}}


def update(prev, fetch, today, cases=frozenset(), counties=COUNTIES):
    """New meetings data: each county re-read, or its previous block kept (with a warning) if it can't be."""
    data = {"window_days_back": WINDOW_DAYS_BACK, "counties": {}}
    for county in counties:
        loc = county["locality"]
        try:
            block = read_county(county, fetch, today, cases)
            check({"counties": {loc: block}})
        except (Skip, ValueError, OSError) as ex:
            print(f"warning: civic: {loc} skipped ({ex}); keeping its last good data")
            block = prev.get("counties", {}).get(loc)
        if block:
            data["counties"][loc] = block
    check(data)
    return data


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def refresh(out_path, cache_dir, offline=False, today=None):
    """Called by build.py. Never raises: civic data is optional and a failure keeps the last good file."""
    try:
        today = today or dt.date.today()
        prev = load(out_path)
        folder = os.path.join(cache_dir, "civic")
        fetch = SavedFetcher(folder) if offline else LiveFetcher(folder)
        cases = known_cases(os.path.join(os.path.dirname(out_path), "filings.json"))
        data = update(prev, fetch, today, cases)
        if data["counties"] != prev.get("counties"):
            write(out_path, data)
        n = sum(len(m["items"]) for b in data["counties"].values() for m in b["meetings"])
        print(f"meetings: {len(data['counties'])} counties, {n} data center item(s) in the window")
    except Exception as ex:  # noqa: BLE001 - optional source; never take the build down
        print(f"warning: civic: not updated ({ex!r}); keeping {out_path} as it was")


# ---- for the pages --------------------------------------------------------------------------------------------------

PARTICIPATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "participation.json")


def for_pages(data_dir):
    """What pages.py needs: {"meetings": meetings.json or {}, "participation": data/participation.json or {}}."""
    meetings = load(os.path.join(data_dir, "meetings.json"))
    try:
        participation = _read_json(PARTICIPATION)
    except (OSError, ValueError):
        participation = {}
    return {"meetings": meetings, "participation": participation}


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Rebuild meetings.json from agenda pages saved by hand.")
    ap.add_argument("--saved", required=True, help="folder with <county-slug>/feed.xml and <county-slug>/<id>.html")
    ap.add_argument("--checked", help="date the pages were saved (YYYY-MM-DD); default today")
    ap.add_argument("--out", default=os.path.join(here, "site", "virginia", "data", "meetings.json"))
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.checked) if a.checked else dt.date.today()
    result = update(load(a.out), SavedFetcher(a.saved), day,
                    known_cases(os.path.join(os.path.dirname(a.out), "filings.json")))
    write(a.out, result)
    for loc, b in result["counties"].items():
        items = sum(len(m["items"]) for m in b["meetings"])
        print(f"{loc}: checked {b['checked']}, {len(b['meetings'])} meetings in the window, {items} data center item(s)")
    sys.exit(0)
