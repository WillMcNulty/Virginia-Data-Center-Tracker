"""Static pages generated from the built data, so search engines and link previews can read the content (the map
itself is a JavaScript app, which crawlers mostly can't read).

Layout (the domain is state-neutral, so each state gets its own folder):
  /                                   front door: search near you, coverage
  /about/  /privacy/                  site-wide pages
  /data/  /methodology/               CSV downloads (pipeline/downloads.py) + embed code; sources and known issues
  /virginia/                          the Virginia map (hand-written, site/virginia/index.html)
  /virginia/places/<locality>/        one page per county or city with any data center on DEQ's records
  /virginia/zip/<zip>/                one per ZIP code with a data center within 5 miles of its center
  /virginia/schools/<slug>/           one per public school with a data center within 2 miles
  /virginia/data-centers/<id>-<name>/ one per data center
  /virginia/new/  (+ feed.xml)        what changed on DEQ's records, from the change log
  /virginia/browse/                   an index of all of the above
  /sitemap.xml  /robots.txt
Pages from the first version lived at /places/, /zip/, /schools/ and /browse/; small forwarding pages there send
visitors (and search engines) to the new addresses.

Everything here is generated and not committed; the daily build regenerates it.
"""
import datetime as dt
import html
import os
import re
import shutil

import cards
import civic
import downloads
import geo

STAGE_LABEL = {"planned": "Planned", "construction": "Under construction", "operating": "Operating",
               "shutdown": "Temporarily shut down", "other": "Other"}
STAGE_ORDER = ["planned", "construction", "operating", "shutdown", "other"]
SCHOOL_RADIUS, ZIP_RADIUS, NEIGHBOR_RADIUS = 2, 5, 1
FILING_RADIUS = 2  # county filings are listed within 2 miles of a school, ZIP center or data center
STATE_NAME = {"virginia": "Virginia"}
ROOT_GENERATED = ["index.html", "about", "privacy", "data", "methodology", "sitemap.xml", "robots.txt",
                  "places", "zip", "schools", "browse"]  # the last four are the forwarding pages
STATE_GENERATED = ["places", "zip", "schools", "data-centers", "new", "browse", "meetings"]
DEQ_RECORD = "https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294/query?where=PLA_REG_NUM%3D{}&amp;outFields=*&amp;f=html"
e = html.escape


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fmt_date(iso):
    if not iso:
        return None
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def fmt_mi(d):
    return f"{d:.2f} mi" if d < 10 else f"{d:.1f} mi"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def stage_summary(items):
    counts = {}
    for f in items:
        counts[f["stage"]] = counts.get(f["stage"], 0) + 1
    return ", ".join(f"{counts[k]} {STAGE_LABEL[k].lower()}" for k in STAGE_ORDER if counts.get(k))


def near(items, lat, lon, radius, exclude=None):
    out = [dict(f, distance=geo.miles(lat, lon, f["lat"], f["lon"])) for f in items if f.get("id") != exclude]
    return sorted([f for f in out if f["distance"] <= radius], key=lambda f: f["distance"])


def facility_path(state, f):
    return f"{state}/data-centers/{f['id']}-{slug(f['name'])[:60].strip('-')}/"


def school_display(s):
    return s["aka"][0] if s.get("aka") else s["name"]


# ---- page shell ---------------------------------------------------------------------------------------------------

def shell(path, title, description, body, cfg, state="virginia", card=None):
    """card: {"headline", "sub"} for the page's link-preview image (see cards.py); None uses the generic card."""
    up = "../" * path.count("/")
    canonical = f"{cfg['site_url'].rstrip('/')}/{path}"
    support = (f'<a href="{e(cfg["support_url"])}">{e(cfg.get("support_label") or "Support this project")}</a>'
               if cfg.get("support_url") else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:site_name" content="Data Centers Near You">
{cards.meta_tags(cfg, path, card)}
<meta name="theme-color" content="#232d4b">
<link rel="stylesheet" href="{up}pages.css">
<script src="{up}theme.js"></script>
</head>
<body>
  <header class="topbar band">
    <div class="wrap">
      <a class="brand" href="{up or './'}">Data Centers Near You</a>
      <nav aria-label="Links">
        <a href="{up}{state}/">Virginia map</a>
        <a href="{up}{state}/new/">New this week</a>
        <a href="{up}{state}/browse/">Browse</a>
        <a href="{up}about/">About</a>
        {support}
        <button type="button" class="theme-btn" data-theme-toggle>&#9680; Auto</button>
      </nav>
    </div>
  </header>
  <main class="wrap">
{body}
  </main>
  <footer class="band">
    <div class="wrap">
      <div>An independent project; not affiliated with Virginia DEQ, any locality, or any company shown.
        Data from public state records. <a href="{up}privacy/">Privacy</a> · <a href="{up}about/">About</a> · <a href="{up}data/">Data</a> · <a href="{up}methodology/">Methodology</a> ·
        <a href="https://github.com/WillMcNulty/Virginia-Data-Center-Tracker">Code</a></div>
    </div>
  </footer>
<!-- Cloudflare Web Analytics -->
<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "a6c6e47a18a143f28f11aff1ab47154b"}}'></script>
<!-- End Cloudflare Web Analytics -->
</body>
</html>
"""


def facility_list(items, up, state, with_distance=True):
    rows = []
    for f in items:
        dist = f'<span class="dist">{fmt_mi(f["distance"])}</span>' if with_distance else ""
        date = fmt_date(f.get("latest_permit"))
        permit = f"air permit {date}" if date else "no issued air permit on DEQ's list yet"
        address = f["address"] or "street address not listed by DEQ"
        loc = e(f["locality"] or "")
        if f.get("listed_locality") and f["listed_locality"] != f["locality"]:
            loc += f" (DEQ's permit list says {e(f['listed_locality'])})"
        rows.append(f"""      <li class="fac">
        <div class="fac-head"><i class="dot {f['stage']}" aria-hidden="true"></i><a class="nm" href="{up}{facility_path(state, f)}">{e(f['name'])}</a>{dist}</div>
        <div class="meta"><span class="tag {f['stage']}">{STAGE_LABEL[f['stage']]}</span> {e(address)}, {e(f['city'])} · {loc} · {e(permit)}</div>
      </li>""")
    return "    <ul class=\"facs\">\n" + "\n".join(rows) + "\n    </ul>" if rows else "    <p>None on DEQ's records.</p>"


# ---- county filings -------------------------------------------------------------------------------------------------

def filing_counties(ctx):
    """The counties whose filings the site has (Loudoun so far), as readable text."""
    names = sorted({f["county"] for f in ctx.get("filings") or []})
    return " and ".join(names) if names else "no county yet"


def short(text, limit=220):
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def filing_list(items, up, state, with_distance=True):
    rows = []
    for f in items:
        dist = f'<span class="dist">{fmt_mi(f["distance"])}</span>' if with_distance else ""
        related = f" · with {e(', '.join(f['related']))}" if f.get("related") else ""
        desc = f'\n        <div class="meta">{e(short(f["description"]))}</div>' if f.get("description") else ""
        rows.append(f"""      <li class="fac">
        <div class="fac-head"><i class="dia {e(f['status'])}" aria-hidden="true"></i><a class="nm" href="{e(f['source'])}">{e(f['name'])}</a>{dist}</div>
        <div class="meta"><span class="tag filing">{e(f['label'])}</span> {e(f['type'])} {e(f['id'])}, filed {fmt_date(f['date'])} · {e(f['county'])}{related} ·
          <a href="{up}{state}/#pin={f['lat']},{f['lon']}&amp;r=1">on the map</a></div>{desc}
      </li>""")
    return "    <ul class=\"facs\">\n" + "\n".join(rows) + "\n    </ul>"


def filings_section(ctx, lat, lon, up):
    """'County filings within 2 miles' for a school, ZIP code or data center page."""
    items = near(ctx.get("filings") or [], lat, lon, FILING_RADIUS)
    head = f"    <h2>County filings within {FILING_RADIUS} miles</h2>\n"
    if not items:
        return head + (f"    <p>None in the county filings this site tracks ({e(filing_counties(ctx))} so far).</p>")
    n_review = sum(1 for f in items if f["status"] == "in-review")
    return head + (f"    <p>{plural(len(items), 'filing')} (land-use applications and site plans) that mention a data center, from "
                   f"{e(filing_counties(ctx))} records; {n_review} still in county review. Filings come before any DEQ "
                   f"air permit, so some of these may not be on DEQ's records yet.</p>\n"
                   + filing_list(items, up, ctx["state"]))


def locality_filings(ctx, loc, up):
    """Every tracked filing in a county, newest first: the ones in review, then the decided ones."""
    items = [f for f in ctx.get("filings") or [] if f["county"] == loc]
    if not items:
        return (f"    <p class=\"note\">County filings (rezonings, special exceptions, site plans) are tracked for "
                f"{e(filing_counties(ctx))} so far; {e(loc)}'s are not included yet.</p>")
    review = [f for f in items if f["status"] == "in-review"]
    decided = [f for f in items if f["status"] != "in-review"]
    out = (f"    <h2>County filings that mention a data center</h2>\n"
           f"    <p>{plural(len(items), 'filing')} from {e(loc)}'s land-use records: {len(review)} in county review and "
           f"{len(decided)} decided (filed since 2021). Land-use applications go to the county board, usually after a public "
           f"hearing; site plans are reviewed by county staff. Each links to the county record.</p>\n")
    if review:
        out += "    <h2>In county review</h2>\n" + filing_list(review, up, ctx["state"], with_distance=False) + "\n"
    if decided:
        out += "    <h2>Decided</h2>\n" + filing_list(decided, up, ctx["state"], with_distance=False) + "\n"
    return out


# ---- state pages ----------------------------------------------------------------------------------------------------

def locality_pages(ctx):
    s, cfg, out = ctx["state"], ctx["cfg"], ctx["out"]
    by_loc = {}
    for f in ctx["facilities"]:
        by_loc.setdefault(f["locality"], []).append(f)
    index = []
    for loc, items in sorted(by_loc.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        items = sorted(items, key=lambda f: (STAGE_ORDER.index(f["stage"]), f["name"]))
        path = f"{s}/places/{slug(loc)}/"
        up = "../" * path.count("/")
        n_future = sum(1 for f in items if f["stage"] in ("planned", "construction"))
        title = f"Data centers in {loc}, {STATE_NAME[s]}"
        desc = (f"{plural(len(items), 'data center')} in {loc} on Virginia DEQ's records "
                f"({stage_summary(items)}), with addresses, stages and air permit dates.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › {e(loc)}</p>
    <h1>Data centers in {e(loc)}</h1>
    <p class="lede">Virginia DEQ's records list <b>{plural(len(items), 'data center')}</b> in {e(loc)}: {e(stage_summary(items))}.
      {"<b>" + str(n_future) + " not yet operating.</b>" if n_future else ""}</p>
    <p><a class="btn" href="{up}{s}/">Open the map</a></p>
{facility_list(items, up, s, with_distance=False)}
    <p class="note">Stages are DEQ's own. Only sites that have applied for a DEQ air permit for backup generators
      appear in the list above; earlier-stage proposals are filed with the county.</p>
{locality_filings(ctx, loc, up)}
{civic_section(ctx, loc, up)}"""
        card = {"headline": f"{plural(len(items), 'data center')} in {loc}, {STATE_NAME[s]}",
                "sub": f"On Virginia DEQ records: {stage_summary(items)}."}
        write(ctx, path, shell(path, title, desc, body, cfg, card=card))
        index.append((loc, path, len(items), n_future))
    return index


def zip_pages(ctx):
    s, cfg = ctx["state"], ctx["cfg"]
    index = []
    for z, (lat, lon) in sorted(ctx["zips"].items()):
        items = near(ctx["facilities"], lat, lon, ZIP_RADIUS)
        n_filings = len(near(ctx.get("filings") or [], lat, lon, FILING_RADIUS))
        if not items and not n_filings:
            continue
        within1 = sum(1 for f in items if f["distance"] <= 1)
        within3 = sum(1 for f in items if f["distance"] <= 3)
        path = f"{s}/zip/{z}/"
        up = "../" * path.count("/")
        title = f"Data centers near ZIP code {z}, {STATE_NAME[s]}"
        if items:
            desc = (f"{plural(len(items), 'data center')} within {ZIP_RADIUS} miles of ZIP code {z} on Virginia DEQ's "
                    f"records ({stage_summary(items)}), nearest {fmt_mi(items[0]['distance'])} from the ZIP code's center.")
            lede = (f"<b>{plural(len(items), 'data center')}</b> within {ZIP_RADIUS} miles of the center of ZIP code {z}:\n"
                    f"      {e(stage_summary(items))}. {within1} within 1 mile, {within3} within 3 miles.")
        else:
            desc = (f"No data centers within {ZIP_RADIUS} miles of ZIP code {z} on Virginia DEQ's records; "
                    f"{plural(n_filings, 'county filing')} mentioning a data center within {FILING_RADIUS} miles.")
            lede = (f"Virginia DEQ's records show no data centers within {ZIP_RADIUS} miles of the center of ZIP code {z}, "
                    f"but county records show <b>{plural(n_filings, 'filing')}</b> that mention a data center within "
                    f"{FILING_RADIUS} miles.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › ZIP {z}</p>
    <h1>Data centers near ZIP code {z}</h1>
    <p class="lede">{lede}</p>
    <p><a class="btn" href="{up}{s}/#zip={z}&amp;r={ZIP_RADIUS}">Open on the map</a></p>
{facility_list(items, up, s) if items else ""}
{filings_section(ctx, lat, lon, up)}
    <p class="note">Distances are straight-line from the ZIP code's center point (Census). For a precise spot, use a
      school or drop a pin on the map.</p>"""
        if items:
            card = {"headline": f"{plural(len(items), 'data center')} within {ZIP_RADIUS} miles of ZIP code {z}",
                    "sub": f"On Virginia DEQ records: {stage_summary(items)}. {within1} within 1 mile, {within3} within 3 miles."}
        else:
            card = {"headline": f"{plural(n_filings, 'county filing')} mentioning a data center within {FILING_RADIUS} miles of ZIP code {z}",
                    "sub": f"On county records. None on Virginia DEQ records within {ZIP_RADIUS} miles."}
        write(ctx, path, shell(path, title, desc, body, cfg, card=card))
        index.append((z, path, len(items), within1, n_filings))
    return index


def school_pages(ctx):
    s, cfg = ctx["state"], ctx["cfg"]
    index, seen, seen_old = [], {}, {}
    ctx["school_path"], ctx["legacy_school"] = {}, {}
    for sc in ctx["schools"]:
        items = near(ctx["facilities"], sc["lat"], sc["lon"], SCHOOL_RADIUS)
        n_filings = len(near(ctx.get("filings") or [], sc["lat"], sc["lon"], FILING_RADIUS))
        if not items and not n_filings:
            continue
        display = school_display(sc)
        base = slug(f"{display} {sc['city']}")
        seen[base] = seen.get(base, 0) + 1
        path = f"{s}/schools/{base}{'' if seen[base] == 1 else '-' + sc['id'][-4:]}/"
        ctx["school_path"][sc["id"]] = path
        # The first version's address used the official NCES name ("carson-middle-herndon"); keep it forwarding.
        old = slug(f"{sc['name']} {sc['city']}")
        seen_old[old] = seen_old.get(old, 0) + 1
        ctx["legacy_school"][f"schools/{old}{'' if seen_old[old] == 1 else '-' + sc['id'][-4:]}/"] = path
        up = "../" * path.count("/")
        within1 = sum(1 for f in items if f["distance"] <= 1)
        aka = f" (official name: {sc['name']})" if sc.get("aka") else ""
        title = f"Data centers near {display}, {sc['city']}"
        if items:
            desc = (f"{plural(len(items), 'data center')} within {SCHOOL_RADIUS} miles of {display} in {sc['city']}, "
                    f"{STATE_NAME[s]} ({stage_summary(items)}); nearest {fmt_mi(items[0]['distance'])} away.")
            found = (f"Virginia DEQ's records show <b>{plural(len(items), 'data center')}</b> within {SCHOOL_RADIUS} "
                     f"miles: {e(stage_summary(items))}. {within1} within 1 mile.")
        else:
            desc = (f"No data centers within {SCHOOL_RADIUS} miles of {display} in {sc['city']}, {STATE_NAME[s]} on DEQ's "
                    f"records; {plural(n_filings, 'county filing')} mentioning a data center within {FILING_RADIUS} miles.")
            found = (f"Virginia DEQ's records show no data centers within {SCHOOL_RADIUS} miles, but county records show "
                     f"<b>{plural(n_filings, 'filing')}</b> that mention a data center within {FILING_RADIUS} miles.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › Schools › {e(display)}</p>
    <h1>Data centers near {e(display)}</h1>
    <p class="lede">{e(display)}{e(aka)}, {e(sc['street'])}, {e(sc['city'])}. {found}</p>
    <p><a class="btn" href="{up}{s}/#school={sc['id']}&amp;r={SCHOOL_RADIUS}">Open on the map</a></p>
{facility_list(items, up, s) if items else ""}
{filings_section(ctx, sc["lat"], sc["lon"], up)}
    <p class="note">Straight-line distance from the school's location (National Center for Education Statistics).
      Virginia's 2026 siting law requires a sound study covering schools within 500 feet of a new high-energy
      facility before a county can approve it.</p>"""
        if not items:
            headline = f"{plural(n_filings, 'county filing')} mentioning a data center within {FILING_RADIUS} miles of {display}"
            detail = None
        elif within1 in (0, len(items)):  # all of them within 1 mile, or none: one number says it
            headline = f"{plural(len(items), 'data center')} within {plural(1 if within1 else SCHOOL_RADIUS, 'mile')} of {display}"
            detail = stage_summary(items)
        else:
            headline = f"{plural(within1, 'data center')} within 1 mile of {display}"
            detail = f"{plural(len(items), 'data center')} within {SCHOOL_RADIUS} miles ({stage_summary(items)})"
        sub = (f"{sc['city']}, {STATE_NAME[s]}. On Virginia DEQ records: {detail}." if detail else
               f"{sc['city']}, {STATE_NAME[s]}. On county records. None on Virginia DEQ records within {SCHOOL_RADIUS} miles.")
        card = {"headline": headline, "sub": sub}
        write(ctx, path, shell(path, title, desc, body, cfg, card=card))
        index.append((f"{display} ({sc['city']})", path, len(items), within1, n_filings))
    return index


def facility_pages(ctx):
    s, cfg, facs = ctx["state"], ctx["cfg"], ctx["facilities"]
    zips = ctx["zips"]
    for f in facs:
        path = facility_path(s, f)
        up = "../" * path.count("/")
        schools = near(ctx["schools"], f["lat"], f["lon"], SCHOOL_RADIUS)
        neighbors = near(facs, f["lat"], f["lon"], NEIGHBOR_RADIUS, exclude=f["id"])
        address = f["address"] or "Street address not listed by DEQ"
        loc = e(f["locality"] or "")
        if f.get("listed_locality") and f["listed_locality"] != f["locality"]:
            loc += f" (DEQ's permit list says {e(f['listed_locality'])})"
        permits = "".join(f"<li>{e(p['no'])}, issued {fmt_date(p['issued']) or 'date not given'} ({e(p['program'])})</li>"
                          for p in f["permits"]) or "<li>No issued air permit on DEQ's list yet</li>"
        school_items = "".join(
            f'<li><a href="{up}{ctx["school_path"][sc["id"]]}">{e(school_display(sc))}</a> ({e(sc["city"])}), {fmt_mi(sc["distance"])}</li>'
            for sc in schools if sc["id"] in ctx["school_path"]) or "<li>None within 2 miles.</li>"
        zip_link = (f' · <a href="{up}{s}/zip/{f["zip"]}/">ZIP {f["zip"]}</a>'
                    if f.get("zip") and f["zip"] in zips and ctx.get("zip_has_page", {}).get(f["zip"]) else "")
        title = f"{f['name']}: data center in {f['locality']}, {STATE_NAME[s]}"
        desc = (f"{f['name']}, {address}, {f['city']}: {STAGE_LABEL[f['stage']].lower()} data center on Virginia DEQ's "
                f"records. {plural(len(schools), 'school')} within 2 miles; {plural(len(neighbors), 'other data center')} within 1 mile.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › <a href="{up}{s}/places/{slug(f['locality'])}/">{e(f['locality'])}</a> › Data center</p>
    <h1>{e(f['name'])}</h1>
    <p class="lede"><span class="tag {f['stage']}">{STAGE_LABEL[f['stage']]}</span> on Virginia DEQ's records ·
      {e(address)}, {e(f['city'])} {e(f.get('zip') or '')} · {loc}{zip_link}</p>
    <p><a class="btn" href="{up}{s}/#pin={f['lat']},{f['lon']}&amp;r=1">See it on the map</a></p>
    <h2>Air permits</h2>
    <ul class="plain">{permits}</ul>
    <h2>Schools within {SCHOOL_RADIUS} miles</h2>
    <ul class="plain">{school_items}</ul>
    <h2>Other data centers within {NEIGHBOR_RADIUS} mile</h2>
{facility_list(neighbors, up, s)}
{filings_section(ctx, f["lat"], f["lon"], up)}
    <h2>Source</h2>
    <p><a href="{DEQ_RECORD.format(f['id'])}">DEQ Air Sites record {f['id']}</a> (permit class: {e(f.get('permit_class') or 'not given')}).
      The stage is DEQ's own. This page is rebuilt every morning from DEQ's records.</p>"""
        card = {"headline": f["name"],
                "sub": f"{f['locality']}, {STATE_NAME[s]}. Stage on Virginia DEQ records: {STAGE_LABEL[f['stage']].lower()}. "
                       f"{plural(len(schools), 'school')} within {SCHOOL_RADIUS} miles; "
                       f"{plural(len(neighbors), 'other data center')} within {NEIGHBOR_RADIUS} mile."}
        write(ctx, path, shell(path, title, desc, body, cfg, card=card))


EVENT_TEXT = {
    "new": lambda ev: f"New on DEQ's data center records ({STAGE_LABEL.get(ev.get('stage'), '').lower()})",
    "stage": lambda ev: f"Stage changed from {STAGE_LABEL.get(ev.get('from'), ev.get('from'))} to {STAGE_LABEL.get(ev.get('to'), ev.get('to'))}",
    "permit": lambda ev: f"Air permit issued {fmt_date(ev.get('to')) or ''}",
    "renamed": lambda ev: f"Renamed from “{ev.get('from')}”",
    "removed": lambda ev: "No longer on DEQ's data center records",
    "filing-new": lambda ev: f"New county filing: {ev.get('filing_type', 'application')} ({ev.get('label', '')})",
    "filing-status": lambda ev: f"County filing changed from “{ev.get('from')}” to “{ev.get('to')}”",
}


def new_page(ctx):
    s, cfg, log = ctx["state"], ctx["cfg"], ctx["log"]
    by_id = {f["id"]: f for f in ctx["facilities"]}
    filing_by_id = {f["id"]: f for f in ctx.get("filings") or []}
    path = f"{s}/new/"
    up = "../" * path.count("/")
    weeks = {}
    for ev in log["events"]:
        d = dt.date.fromisoformat(ev["date"])
        monday = d - dt.timedelta(days=d.weekday())
        weeks.setdefault(monday, []).append(ev)
    parts = []
    for monday in sorted(weeks, reverse=True):
        items = []
        for ev in weeks[monday]:
            f, fil = by_id.get(ev["id"]), filing_by_id.get(ev["id"])
            name = (f'<a href="{up}{facility_path(s, f)}">{e(ev["name"])}</a>' if f else
                    f'<a href="{e(fil["source"])}">{e(ev["name"])}</a> ({e(ev["id"])})' if fil else e(ev["name"]))
            items.append(f"<li><b>{name}</b> ({e(ev.get('locality') or '')}): {e(EVENT_TEXT[ev['type']](ev))} "
                         f"<span class=\"when\">{fmt_date(ev['date'])}</span></li>")
        parts.append(f"    <h2>Week of {fmt_date(monday.isoformat())}</h2>\n    <ul class=\"plain\">{''.join(items)}</ul>")
    changes = "\n".join(parts) if parts else (
        f"    <p>Nothing has changed on DEQ's records since tracking began on {fmt_date(log['since'])}. "
        "This page updates every morning.</p>")
    body = f"""    <h1>New this week</h1>
    <p class="lede">What changed on Virginia DEQ's data center records: new sites, stage changes (planned, under
      construction, operating) and new air permits; plus new county filings that mention a data center and their
      status changes ({e(filing_counties(ctx))} so far). Checked every morning since {fmt_date(log['since'])}.
      <a href="feed.xml">Subscribe by RSS</a>.</p>
{changes}"""
    write(ctx, path, shell(path, "New this week: Virginia data center records",
                           "New data centers, stage changes and air permits on Virginia DEQ's records, updated daily.", body, cfg))
    # RSS 2.0 feed of the latest 50 events
    base = cfg["site_url"].rstrip("/")
    items = []
    for ev in log["events"][:50]:
        f, fil = by_id.get(ev["id"]), filing_by_id.get(ev["id"])
        link = f"{base}/{facility_path(s, f)}" if f else fil["source"] if fil else f"{base}/{path}"
        pub = dt.datetime.fromisoformat(ev["date"] + "T12:00:00+00:00").strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>{e(ev['name'])}: {e(EVENT_TEXT[ev['type']](ev))}</title><link>{e(link)}</link>"
                     f"<guid isPermaLink=\"false\">{e(ev['date'])}-{e(ev['type'])}-{ev['id']}</guid><pubDate>{pub}</pubDate>"
                     f"<description>{e(ev.get('locality') or '')}</description></item>")
    rss = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Data Centers Near You: Virginia changes</title>'
           f"<link>{e(base)}/{path}</link><description>New data centers, stage changes and air permits on Virginia DEQ's records.</description>"
           + "".join(items) + "</channel></rss>\n")
    with open(os.path.join(ctx["out"], path, "feed.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rss)


def filings_note(row):
    """', 3 county filings within 2 mi' for a browse-index row (school or ZIP) that has any."""
    return f", {plural(row[4], 'county filing')} within {FILING_RADIUS} mi" if len(row) > 4 and row[4] else ""


def browse_page(ctx, loc_idx, zip_idx, school_idx):
    s, cfg, meta = ctx["state"], ctx["cfg"], ctx["meta"]
    path = f"{s}/browse/"
    up = "../" * path.count("/")

    def ul(rows, fmt):
        return "<ul class=\"idx\">" + "".join(fmt(r) for r in rows) + "</ul>"
    body = f"""    <h1>Browse {STATE_NAME[s]} data centers by place</h1>
    <p class="lede">Every county, ZIP code and public school in {STATE_NAME[s]} with a data center nearby on DEQ's
      records. {meta['facilities']} data centers statewide as of the last refresh.</p>
    <p><a href="{up}{s}/meetings/">Upcoming county meetings with data center items</a>, and how to take part.</p>
    <h2>Counties and cities</h2>
    {ul(loc_idx, lambda r: f'<li><a href="{up}{r[1]}">{e(r[0])}</a> <span>{plural(r[2], "data center")}' + (f', {r[3]} not yet operating' if r[3] else '') + '</span></li>')}
    <h2>Schools with a data center within {SCHOOL_RADIUS} miles</h2>
    {ul(sorted(school_idx), lambda r: f'<li><a href="{up}{r[1]}">{e(r[0])}</a> <span>{r[2]} within {SCHOOL_RADIUS} mi, {r[3]} within 1 mi' + filings_note(r) + '</span></li>')}
    <h2>ZIP codes with a data center within {ZIP_RADIUS} miles</h2>
    {ul(zip_idx, lambda r: f'<li><a href="{up}{r[1]}">{r[0]}</a> <span>{r[2]} within {ZIP_RADIUS} mi' + filings_note(r) + '</span></li>')}
    <p class="note">Schools and ZIP codes are also listed when a county filing that mentions a data center is within
      {FILING_RADIUS} miles ({e(filing_counties(ctx))} so far), even before any DEQ record.</p>"""
    write(ctx, path, shell(path, f"Browse {STATE_NAME[s]} data centers by county, ZIP code or school",
                           f"Every {STATE_NAME[s]} county, ZIP code and public school with a data center nearby, from state records.", body, cfg))


# ---- civic: meetings with data center items, and how to take part (data from pipeline/civic.py) -------------------

STALE_DAYS = 7  # say so when the agendas were last read longer ago than this


def _today(ctx):
    return ctx.get("today") or dt.date.today()


def _split_meetings(block, today):
    """(upcoming, recent) meetings in date order; recent = the last WINDOW_DAYS_BACK days."""
    start = (today - dt.timedelta(days=civic.WINDOW_DAYS_BACK)).isoformat()
    ms = sorted(block.get("meetings", []), key=lambda m: (m["date"], m["name"]))
    return ([m for m in ms if m["date"] >= today.isoformat()],
            [m for m in ms if start <= m["date"] < today.isoformat()])


def _item_rows(meetings):
    rows = []
    for m in meetings:
        for it in m["items"]:
            where = f"{e(it['section'])} › " if it.get("section") else ""
            rows.append(f"""      <li class="fac">
        <div class="fac-head"><span><b>{fmt_date(m['date'])}</b> · {e(m['name'])}</span></div>
        <div class="meta">{where}{e(it['number'])} {e(it['text'])}</div>
        <div class="meta"><a href="{e(m['agenda_url'])}">Official agenda</a> · confirm there: agendas can change before and during a meeting</div>
      </li>""")
    return "    <ul class=\"facs\">\n" + "\n".join(rows) + "\n    </ul>" if rows else ""


def _checked_line(block, today):
    checked = block["checked"]
    age = (today - dt.date.fromisoformat(checked)).days
    stale = (f" That was {age} days ago, so newer agendas may be posted: check the county's agenda page."
             if age > STALE_DAYS else "")
    return (f'    <p class="when">Agendas last checked {fmt_date(checked)} from the county\'s '
            f'<a href="{e(block["feed"])}">official agenda feed</a>.{stale}</p>')


def _take_part(loc, part, level="h3"):
    if not part:
        return ""
    facts = "".join(f'<li>{e(f["text"])} <span class="when">(<a href="{e(f["source"])}">source</a>, '
                    f'checked {fmt_date(f["checked"])})</span></li>' for f in part["facts"])
    links = " · ".join(f'<a href="{e(x["url"])}">{e(x["label"])}</a>' for x in part.get("links", []))
    return f"""    <{level}>How to take part in {e(loc)}</{level}>
    <p>Procedures of the {e(part['body'])}, from the county's own pages. Confirm on the county's page before a
      meeting; procedures and deadlines can change.</p>
    <ul class="plain">{facts}</ul>
    <p>{links}</p>"""


def _county_block(ctx, loc, up):
    """The meetings page's section for one county."""
    civ = ctx["civic"]
    block = civ["meetings"].get("counties", {}).get(loc)
    part = civ["participation"].get(loc)
    head = f'    <h2 id="{slug(loc)}">{e(loc)}</h2>'
    if not block:
        return "\n".join([head, "    <p>This county's agendas haven't been checked yet.</p>", _take_part(loc, part)])
    today = _today(ctx)
    upcoming, recent = _split_meetings(block, today)
    parts = [head, _checked_line(block, today)]
    weeks = f"Past {civic.WINDOW_DAYS_BACK // 7} weeks"
    for label, ms, empty in [("Upcoming", upcoming, "No upcoming agendas were posted when last checked."),
                             (weeks, recent, f"No meetings in the {weeks.lower()} on the county's agenda feed.")]:
        none = (empty if not ms else "No item that mentions a data center on the agendas checked."
                if any(m["searched"] for m in ms) else "These agendas couldn't be searched (see below).")
        parts.append(f"    <h3>{label}</h3>")
        parts.append(_item_rows(ms) or f"    <p>{none}</p>")
    checked = [m for m in upcoming + recent if m["searched"] and not m["items"]]
    unsearched = [m for m in upcoming + recent if not m["searched"]]
    if checked:
        parts.append("    <p>Also checked, with no item that mentions a data center: " + "; ".join(
            f'<a href="{e(m["agenda_url"])}">{fmt_date(m["date"])}, {e(m["name"])}</a>' for m in checked) + ".</p>")
    if unsearched:
        notes = sorted({m.get("note") or "" for m in unsearched})
        parts.append("    <p>Not searched: " + "; ".join(
            f'<a href="{e(m["agenda_url"])}">{fmt_date(m["date"])}, {e(m["name"])}</a>' for m in unsearched)
            + ". " + " ".join(e(n) for n in notes if n) + "</p>")
    parts.append(_take_part(loc, part))
    return "\n".join(p for p in parts if p)


def meetings_page(ctx):
    s, cfg = ctx["state"], ctx["cfg"]
    path = f"{s}/meetings/"
    up = "../" * path.count("/")
    counties = [c["locality"] for c in civic.COUNTIES]
    today = _today(ctx)
    n = 0
    for loc in counties:
        block = ctx["civic"]["meetings"].get("counties", {}).get(loc)
        if block:
            n += sum(len(m["items"]) for m in _split_meetings(block, today)[0])
    jump = " · ".join(f'<a href="#{slug(c)}">{e(c)}</a>' for c in counties)
    body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › Meetings</p>
    <h1>Upcoming meetings with data center items</h1>
    <p class="lede">Agenda items that mention data centers at county board meetings in {e(', '.join(counties[:-1]))}
      and {e(counties[-1])}, from each county's published agendas, with how to take part. <b>{plural(n, 'item')}</b>
      on upcoming agendas as of the last check.</p>
    <p>{jump}</p>
    <p class="note">How items are found: an item is listed when its title on the agenda says "data center" (or names a
      case number that is a data center filing on the county's records). Items about a data center that don't say so
      in their title are not caught, and a listed item may only touch on a data center. Item text is shown as the
      agenda shows it, without staff names. Always confirm on the official agenda.</p>
{chr(10).join(_county_block(ctx, loc, up) for loc in counties)}"""
    write(ctx, path, shell(path, "Upcoming county meetings with data center items: Fairfax, Loudoun, Prince William",
                           "Agenda items that mention data centers at upcoming county board meetings in Fairfax, Loudoun "
                           "and Prince William counties, with how to sign up to speak or send written comments.",
                           body, cfg))


def civic_section(ctx, loc, up):
    """A short "Public meetings" section for a county page (empty for places the civic layer doesn't cover)."""
    civ = ctx.get("civic")
    if not civ or loc not in civic.BY_LOCALITY:
        return ""
    s = ctx["state"]
    block = civ["meetings"].get("counties", {}).get(loc)
    more = f'<a href="{up}{s}/meetings/#{slug(loc)}">All agendas checked, and how to take part</a>'
    if not block:
        return f"    <h2>Public meetings</h2>\n    <p>{more}.</p>"
    today = _today(ctx)
    upcoming, recent = _split_meetings(block, today)
    n_up, n_recent = (sum(len(m["items"]) for m in ms) for ms in (upcoming, recent))
    summary = (f"Agenda items that mention data centers: <b>{n_up}</b> on upcoming agendas, {n_recent} in the past "
               f"{civic.WINDOW_DAYS_BACK // 7} weeks.")
    return f"""    <h2>Public meetings</h2>
    <p>{summary} {more}.</p>
{_item_rows(upcoming + recent)}
{_checked_line(block, today)}"""


# ---- site-wide pages ------------------------------------------------------------------------------------------------

def front_door(ctx):
    s, cfg, meta = ctx["state"], ctx["cfg"], ctx["meta"]
    planned = meta["stages"]["planned"] + meta["stages"]["construction"]
    body = f"""    <h1>Data centers near you</h1>
    <p class="lede">See what data centers are planned, being built or running near your home or your kid's school,
      straight from state records. Free, independent, and nothing you search is sent anywhere.</p>
    <form class="zipform" id="zipform" action="{s}/" autocomplete="off">
      <label for="zip">Your ZIP code</label>
      <div><input id="zip" name="zip" inputmode="numeric" pattern="[0-9]{{5}}" maxlength="5" placeholder="e.g. 20171" required>
        <button class="btn" type="submit">Search</button></div>
      <p id="zipmsg" class="note" hidden></p>
    </form>
    <h2>Coverage</h2>
    <ul class="plain">
      <li><b><a href="{s}/">Virginia</a></b>: {meta['facilities']} data centers on DEQ's records, {planned} planned or under
        construction. <a href="{s}/new/">New this week</a> · <a href="{s}/browse/">Browse by county, ZIP code or school</a></li>
      <li>Maryland and Georgia: coming next.</li>
    </ul>
    <p class="note">Other states work differently, so each one is added only once its official records have been checked.</p>
    <script>
      // Old links to the map (#zip=..., #school=..., #pin=...) now live under /{s}/.
      if (/^#(zip|school|pin)=/.test(location.hash)) location.replace("{s}/" + location.hash);
      document.getElementById("zipform").addEventListener("submit", async (ev) => {{
        ev.preventDefault();
        const z = document.getElementById("zip").value.trim(), msg = document.getElementById("zipmsg");
        const zips = await fetch("{s}/data/zips.json").then((r) => r.json()).catch(() => ({{}}));
        if (zips[z]) location.href = "{s}/#zip=" + z + "&r=5";
        else {{ msg.hidden = false; msg.textContent = z + " isn't in a state we cover yet. We currently cover Virginia; Maryland and Georgia are next."; }}
      }});
    </script>"""
    write(ctx, "", shell("", "Data Centers Near You: data centers planned, being built and running near you",
                         "Search your ZIP code, school or neighborhood for data centers planned, under construction or operating, from state records.",
                         body, cfg, card={"headline": f"{meta['facilities']} data centers on Virginia DEQ's records",
                                          "sub": f"{planned} planned or under construction. Search by ZIP code or school."}))


def about_page(ctx):
    cfg, meta = ctx["cfg"], ctx["meta"]
    body = f"""    <h1>About this project</h1>
    <h2>Why it exists</h2>
    <p>This started with my mom. My little brother goes to Rachel Carson Middle School in Herndon, and over about six
      months, three data centers went up within a mile of his school. What bothered her most was that our family had
      no idea any of them were coming until they were there. She asked for a simple map built from the best data
      available, where you could look around where you live and see what's planned, under construction or
      operating. This is that map.</p>
    <h2>Where the data comes from</h2>
    <p>In Virginia: every site the Department of Environmental Quality flags as a data center in its daily Air Sites
      records ({meta['facilities']} today). Data centers need a DEQ air permit for their backup diesel generators, so
      a project appears once it applies for one; the stage shown is DEQ's own. Permit dates come from DEQ's list of
      issued data center air permits. Schools are from the National Center for Education Statistics and ZIP codes
      from the U.S. Census Bureau. The data refreshes every morning, changes are logged on "New this week", and the
      build refuses to publish if a source looks broken. Every site links to its DEQ record. The
      <a href="../methodology/">methodology</a> explains each source and its known issues, and the
      <a href="../data/">data downloads</a> page has the data as spreadsheets (free to reuse with attribution) and
      an embed code for the map.</p>
    <p>Earlier-stage proposals come from county records: land-use applications (rezonings, special exceptions) and
      site plans that mention a data center, from {e(filing_counties(ctx))}'s public land application records so far.
      They're shown as diamonds on the map and listed on school, ZIP code, county and data center pages, each linked
      to its county record. The status is the county's own.</p>
    <h2>What's not here yet</h2>
    <p>Cost and size from county building permits, county filings from more counties, and, by ZIP code, the
      upcoming hearings, comment periods and elections where residents can weigh in. Those are being added next,
      then more states. A first piece is up:
      <a href="../virginia/meetings/">upcoming county meetings with data center items</a> in Fairfax, Loudoun and
      Prince William, from the counties' published agendas, with how to sign up to speak or send comments.</p>
    <h2>Who made it</h2>
    <p>William McNulty, a Computer Science and Economics student at the University of Virginia. An independent project,
      not affiliated with Virginia DEQ, any locality or any company shown. <a href="{e(cfg['contact_url'])}">Contact</a> ·
      <a href="https://github.com/WillMcNulty/Virginia-Data-Center-Tracker">Code and data on GitHub</a></p>
    <h2>Related work</h2>
    <p>The Piedmont Environmental Council's <a href="https://www.pecva.org/region/culpeper/existing-and-proposed-data-centers-a-web-map/">Existing and Proposed Data Centers</a>
      map, and <a href="https://brockovichdatacenter.com/">Brockovich Data Center Reporting</a>.</p>"""
    write(ctx, "about/", shell("about/", "About Data Centers Near You",
                               "Why this map exists, where its data comes from, and what's coming next.", body, cfg))


def privacy_page(ctx):
    cfg = ctx["cfg"]
    body = f"""    <h1>Privacy policy</h1>
    <p class="note">Last updated {fmt_date(dt.date.today().isoformat())}.</p>
    <h2>What this site collects</h2>
    <p>There are no visitor accounts, advertising cookies or ads. Searches by ZIP
      code, school or map pin and distance calculations run in your browser. A
      search you share as a link keeps its details after the <code>#</code> in the address, which browsers don't send
      to servers.</p>
    <h2>What your browser stores</h2>
    <p>If you pick a color theme, that choice is saved in your browser's local storage so it's remembered next time.
      It never leaves your device. Clearing your browser's site data removes it.</p>
    <h2>Other services the page contacts</h2>
    <p>We use <a href="https://developers.cloudflare.com/web-analytics/">Cloudflare Web Analytics</a>
      to understand visits, page views, referring sites and page performance. Its script sends usage and
      performance information to Cloudflare. Cloudflare says it does not use cookies or browser storage for
      this analytics service or track individuals across websites. Reports can include page paths, country,
      browser and device type. We do not add search-event or map-pin tracking.</p>
    <p>Map images come from <a href="https://openfreemap.org/">OpenFreeMap</a>, which therefore sees which area of the
      map is being viewed (like any map image server). The site is served by its host, which, like any web server,
      receives standard request information such as your IP address; this project doesn't collect or use it.</p>
    <h2>Changes</h2>
    <p>If this site changes its analytics or adds email alerts, ads or donations, this page will be updated first to say
      exactly what is collected and by whom, with any choices you have.</p>
    <h2>Contact</h2>
    <p><a href="{e(cfg['contact_url'])}">Contact the author</a>.</p>"""
    write(ctx, "privacy/", shell("privacy/", "Privacy policy · Data Centers Near You",
                                 "How Data Centers Near You uses cookieless analytics and what your browser stores.", body, cfg))


# ---- data downloads, methodology, embed snippet ---------------------------------------------------------------------

CODE = "https://github.com/WillMcNulty/Virginia-Data-Center-Tracker"
RADII = [1, 3, 5, 10, 30]  # the map's radius choices (site/geo.js parseHash)
EMBED_JS = """
(() => {
  const form = document.getElementById("embedform"), out = document.getElementById("snippet");
  const base = form.dataset.base, schools = new Map();
  const $ = (id) => document.getElementById(id);
  function build() {
    const q = new URLSearchParams({ embed: "1" });
    if ($("e-theme").value) q.set("theme", $("e-theme").value);
    let hash = "", msg = "";
    const start = form.querySelector("input[name=start]:checked").value, r = $("e-r").value;
    if (start === "zip") {
      const z = $("e-zip").value.trim();
      if (/^\\d{5}$/.test(z)) hash = "#zip=" + z + "&r=" + r; else msg = "Enter a 5-digit ZIP code.";
    } else if (start === "school") {
      const id = schools.get($("e-school").value.trim());
      if (id) hash = "#school=" + encodeURIComponent(id) + "&r=" + r; else msg = "Pick a school from the list.";
    }
    const w = $("e-w").value.trim() || "100%", h = Math.max(300, Number($("e-h").value) || 600);
    const width = /^\\d+$/.test(w) ? w : (/^\\d{1,3}%$/.test(w) ? w : "100%");
    const src = base + "?" + q.toString() + hash;
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    out.value = '<iframe src="' + esc(src) + '" width="' + width + '" height="' + h + '" style="border:0" ' +
      'title="Data Centers Near You: map of Virginia data centers" loading="lazy"></iframe>';
    $("e-msg").textContent = msg; $("e-msg").hidden = !msg;
    $("e-preview").href = src;
  }
  form.addEventListener("input", build); form.addEventListener("change", build);
  $("e-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(out.value); } catch { out.select(); document.execCommand("copy"); }
    $("e-copied").hidden = false; setTimeout(() => { $("e-copied").hidden = true; }, 2000);
  });
  fetch(form.dataset.schools).then((r) => r.json()).then((list) => {
    const dl = $("e-schools");
    for (const s of list) {
      const label = (s.aka && s.aka[0] ? s.aka[0] : s.name) + " (" + s.city + ")";
      if (schools.has(label)) continue;
      schools.set(label, s.id); const o = document.createElement("option"); o.value = label; dl.append(o);
    }
  }).catch(() => {});
  build();
})();
"""


def columns_table(key):
    rows = "".join(f"<tr><td><code>{e(c)}</code></td><td>{e(d)}</td></tr>" for c, d in downloads.COLUMNS[key])
    return f'    <table class="cols"><thead><tr><th>Column</th><th>What it holds</th></tr></thead><tbody>{rows}</tbody></table>'


def data_page(ctx):
    """/data/: the CSV downloads (written here, after build_pages cleared the folder), their columns, the reuse
    note and the embed snippet generator."""
    s, cfg, meta = ctx["state"], ctx["cfg"], ctx["meta"]
    path, up = "data/", "../"
    files = downloads.write(os.path.join(ctx["out"], "data"), s, ctx["facilities"], ctx["log"], ctx["filings"])
    built = fmt_date(meta["built_at"][:10]) if meta.get("built_at") else fmt_date(dt.date.today().isoformat())
    base = cfg["site_url"].rstrip("/")

    def dl(key, what):
        name, n = files[key]
        size = os.path.getsize(os.path.join(ctx["out"], "data", name))
        return f'<li><a href="{e(name)}" download>{e(name)}</a> <span class="when">{plural(n, "row")}, {max(1, round(size / 1024))} KB</span>: {what}</li>'
    radius = "".join(f'<option value="{r}"{" selected" if r == 3 else ""}>{plural(r, "mile")}</option>' for r in RADII)
    body = f"""    <h1>Data downloads</h1>
    <p class="lede">The data behind the map, as spreadsheets (CSV, UTF-8 with a byte-order mark so Excel shows accented characters and dashes correctly). Built {built} from the official records
      described in the <a href="{up}methodology/">methodology</a>; the files are rebuilt every morning with the map.</p>
    <ul class="plain">
      {dl("data-centers", f"every data center on Virginia DEQ's records ({meta['facilities']} today), with stage, address, locality and issued air permits (DEQ's permit list as of {fmt_date(meta.get('permit_snapshot'))}).")}
      {dl("changes", f"every change logged on <a href=\"{up}{s}/new/\">New this week</a> since {fmt_date(ctx['log']['since'])}: new sites, stage changes, new air permits, new county filings and their status changes.")}
      {dl("county-filings", f"county land-use applications and site plans that mention a data center ({e(filing_counties(ctx))} so far).")}
    </ul>
    <p class="note">Each row links to its official record. The same data is also published as JSON for the map,
      in <a href="{up}{s}/data/facilities.json">facilities.json</a>, <a href="{up}{s}/data/changes.json">changes.json</a>
      and <a href="{up}{s}/data/filings.json">filings.json</a>. No personal data is included: no visitor data, no
      county staff names or emails, and no private landowner names.</p>
    <h2>Reusing this data</h2>
    <p>You may reuse, republish and adapt these files, including in news stories and research, with attribution:
      credit “Data Centers Near You, from Virginia DEQ and county records” and link to
      <a href="{e(base)}/">{e(base)}/</a>. The underlying public records belong to their publishers (Virginia DEQ,
      the counties, NCES and the Census Bureau), and their own terms and notices still apply; DEQ's data notice is
      on the map page. Stages and statuses are the agencies' own; anything this site calculates is marked as ours in
      the column notes below. Please check important facts against the linked official record.</p>
    <h2>Columns</h2>
    <h3>{e(files["data-centers"][0])}</h3>
{columns_table("data-centers")}
    <h3>{e(files["changes"][0])}</h3>
{columns_table("changes")}
    <h3>{e(files["county-filings"][0])}</h3>
{columns_table("county-filings")}
    <p class="note">Columns stay the same from day to day; new ones are only ever added at the end.</p>
    <h2 id="embed">Embed the map</h2>
    <p>Newsrooms, schools and community groups can put the map on their own page. Choose a starting point and size,
      then copy the code.</p>
    <form id="embedform" class="embedform" data-base="{e(base)}/{s}/" data-schools="{up}{s}/data/schools.json" onsubmit="return false">
      <fieldset><legend>Start the map at</legend>
        <label><input type="radio" name="start" value="none" checked> All of Virginia</label>
        <label><input type="radio" name="start" value="zip"> A ZIP code
          <input id="e-zip" inputmode="numeric" maxlength="5" placeholder="e.g. 20171" aria-label="ZIP code"></label>
        <label><input type="radio" name="start" value="school"> A school
          <input id="e-school" list="e-schools" placeholder="Type a school name" aria-label="School"></label>
        <datalist id="e-schools"></datalist>
        <label>Within <select id="e-r">{radius}</select></label>
      </fieldset>
      <div class="row">
        <label>Width <input id="e-w" value="100%" size="6" aria-describedby="e-w-hint"></label>
        <label>Height (px) <input id="e-h" type="number" value="600" min="300" max="2000" step="10"></label>
        <label>Colors <select id="e-theme"><option value="">Follow the reader's device</option><option value="light">Light</option><option value="dark">Dark</option></select></label>
      </div>
      <p class="note" id="e-w-hint">Width: pixels (e.g. 800) or a percentage (e.g. 100%).</p>
      <p class="note" id="e-msg" hidden></p>
      <label for="snippet">Embed code</label>
      <textarea id="snippet" rows="4" readonly></textarea>
      <p><button class="btn" type="button" id="e-copy">Copy code</button> <span id="e-copied" hidden>Copied.</span>
        <a id="e-preview" href="{up}{s}/" target="_blank" rel="noopener">Preview in a new tab</a></p>
    </form>
    <p class="note">The embedded map shows a small “Data Centers Near You” credit link; please leave it in place.
      Searches in the embedded map run in the reader's browser, like on this site.</p>
    <script>{EMBED_JS}</script>"""
    write(ctx, path, shell(path, "Data downloads · Data Centers Near You",
                           "Download Virginia data center records, the change log and county filings as CSV, "
                           "with column notes, reuse terms and an embed code for the map.", body, cfg))
    return files


def methodology_page(ctx):
    s, cfg, meta = ctx["state"], ctx["cfg"], ctx["meta"]
    path, up = "methodology/", "../"
    src = meta.get("sources", {})
    air = src.get("deq_air_sites", "https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294")
    permit_page = src.get("deq_permit_page", "https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers")
    counties = air.rsplit("/", 1)[0] + "/157"
    lola = src.get("loudoun_lola", "https://logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0")
    nces = src.get("nces_schools", "https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0")
    zcta = src.get("census_zcta", "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_zcta_national.zip")
    feeds = " · ".join(f'<a href="{c["host"]}/ViewPublisherRSS.php?view_id={c["view"]}&amp;mode=agendas">{e(c["locality"])}</a>'
                       for c in civic.COUNTIES)
    robots = " · ".join(f'<a href="{c["host"]}/robots.txt">{e(c["locality"])}</a>' for c in civic.COUNTIES)
    split = [f for f in ctx["facilities"] if f.get("listed_locality") and f["listed_locality"] != f["locality"]]
    split_links = ", ".join(f'<a href="{downloads_record(f["id"])}">{f["id"]}</a>' for f in split)
    no_addr = sum(1 for f in ctx["facilities"] if not f["address"])
    no_zip = sum(1 for f in ctx["facilities"] if not f["zip"])
    fil = ctx.get("filings") or []
    old_review = [f for f in fil if f["status"] == "in-review" and f["date"] < "2021-01-01"]
    old_links = ", ".join(f'<a href="{e(f["source"])}">{e(f["id"])}</a>' for f in old_review[:5])
    stage_rows = "".join(f"<tr><td>{e(k)}</td><td>{e(STAGE_LABEL[v])}</td></tr>" for k, v in
                         [("Planned", "planned"), ("Under Construction", "construction"), ("Operating", "operating"),
                          ("Temporarily Shutdown", "shutdown")])
    body = f"""    <h1>Methodology</h1>
    <p class="lede">Where every piece of this site's data comes from, how it is put together, and what it can't tell
      you. The data itself is on the <a href="{up}data/">downloads page</a>.</p>
    <h2>Sources</h2>
    <ul class="plain">
      <li><b>Virginia DEQ, Air Sites (daily).</b> Every site DEQ flags as a data center on its
        <a href="{e(air)}">Air Sites layer</a> ({meta['facilities']} on the last refresh), with its name, address,
        location and operating status. Data centers need a DEQ air permit for their backup generators, so a project
        appears here once it applies for one.</li>
      <li><b>Virginia DEQ, issued air permits for data centers.</b> Permit numbers, dates and programs come from
        <a href="{e(permit_page)}">DEQ's list of issued air permits for data centers</a>. That page blocks automated
        requests, so it is saved by hand from a normal browser as a dated snapshot (currently as of
        {fmt_date(meta.get('permit_snapshot'))}) and joined to the Air Sites records by registration number.</li>
      <li><b>Virginia DEQ, county and city boundaries.</b> Which county or independent city a site is in comes from
        DEQ's <a href="{e(counties)}">boundary layer</a>: a point-in-polygon calculation by this site.</li>
      <li><b>Loudoun County land applications (LOLA).</b> Rezonings, special exceptions, other land-use applications
        and site plans that mention a data center, from
        <a href="{e(lola)}">Loudoun's public land application records</a>. Sub-applications are folded into their
        umbrella application so each proposal appears once. The fields that name reviewing staff are never
        downloaded, and names of people are removed from descriptions.</li>
      <li><b>Public schools.</b> Names and locations from the National Center for Education Statistics'
        <a href="{e(nces)}">school locations</a> (2024-25). Common names (such as “Rachel Carson Middle School” for
        NCES's “Carson Middle”) are added by hand.</li>
      <li><b>ZIP codes.</b> Center points of ZIP Code Tabulation Areas from the U.S. Census Bureau's
        <a href="{e(zcta)}">2025 Gazetteer file</a>.</li>
      <li><b>County meeting agendas.</b> The <a href="{up}{s}/meetings/">meetings page</a> lists agenda items that
        mention a data center, from the agenda feeds that Fairfax, Loudoun and Prince William publish
        ({feeds}). Those servers ask automated programs not to fetch them in their robots.txt files ({robots}), so
        this site doesn't fetch them automatically: the agendas are saved by hand from a normal browser and
        refreshed periodically. The page says when they were last checked.</li>
    </ul>
    <h2>Stages</h2>
    <p>The stage shown for each data center is DEQ's own operating status on the
      <a href="{e(air)}">Air Sites layer</a>, renamed only for readability. This site does not judge a site's stage
      itself.</p>
    <table class="cols"><thead><tr><th>DEQ status</th><th>Shown as</th></tr></thead><tbody>{stage_rows}</tbody></table>
    <p>County filings show the county's own status (for example “In Review” or “Approved”), with a plain-language
      label. Grouping filings into land-use applications (decided by the county board, usually after a public
      hearing) and site plans (reviewed by county staff) is this site's own classification of the county's
      application types.</p>
    <h2>Distances</h2>
    <p>Distances are straight-line (“as the crow flies”) between two points, using the haversine formula on a sphere
      with the Earth's mean radius (3,958.8 miles), not driving distance. A ZIP code search measures from the ZIP
      code's Census center point, which can be a few miles from a given home in it; a school or a dropped pin gives a
      precise point. The calculation is the same in the build (<a href="{CODE}/blob/main/pipeline/geo.py">geo.py</a>)
      and in your browser (<a href="{CODE}/blob/main/site/geo.js">geo.js</a>), and tests check the two agree.
      A data center's point is DEQ's location for the site; a county filing's point is the center of its parcel
      outline, calculated by this site.</p>
    <h2>The change log</h2>
    <p>Every morning the build compares the day's records with the previous day's and logs what changed: new sites,
      stage changes, new air permits, renamed or removed sites, new county filings and filing status changes. The
      log started on {fmt_date(ctx['log']['since'])}; it shows when this site noticed a change, which can be later
      than the date the agency made it. It feeds <a href="{up}{s}/new/">New this week</a>, its RSS feed and the
      <a href="{up}data/">changes download</a>. If a source looks broken (for example, far fewer data centers than the
      day before), the build refuses to publish and the previous day's data stays up.</p>
    <h2>Our own classifications and estimates</h2>
    <ul class="plain">
      <li>The locality of each data center (point-in-polygon on DEQ's boundaries, above).</li>
      <li>Land-use application versus site plan for county filings, the plain-English application types and status
        labels, and the filing's point (the parcel center).</li>
      <li>Which schools and ZIP codes get a page: those with a data center within {SCHOOL_RADIUS} miles of the school
        or {ZIP_RADIUS} miles of the ZIP code's center, or a county filing within {FILING_RADIUS} miles.</li>
      <li>Common school names, added by hand to NCES's official short names.</li>
      <li>Which agenda items are about data centers (the item's text says “data center” or names a tracked case
        number).</li>
    </ul>
    <h2>Known issues</h2>
    <ul class="plain">
      <li><b>Manassas city line.</b> {plural(len(split), 'site')} near the Manassas airport ({split_links}) fall in
        Prince William County on DEQ's <a href="{e(counties)}">boundary layer</a>, but
        <a href="{e(permit_page)}">DEQ's permit list</a> says Manassas City. The two official sources disagree, so
        the site shows both rather than pick one.</li>
      <li><b>Missing addresses.</b> {plural(no_addr, 'DEQ record')} {'has' if no_addr == 1 else 'have'} no street
        address and {plural(no_zip, 'record')} no ZIP code on the <a href="{e(air)}">Air Sites layer</a>; pages say
        “not listed by DEQ”.</li>
      <li><b>Permits not yet on the list.</b> {plural(meta.get('facilities_without_permit_row', 0), 'site')} on the
        Air Sites layer {'has' if meta.get('facilities_without_permit_row', 0) == 1 else 'have'} no row on DEQ's issued-permit list yet,
        probably because the permit is still in progress; and the list itself is a hand-saved snapshot, so the newest
        permits can lag.</li>
      <li><b>Old applications still “In Review”.</b> A few Loudoun applications filed years ago still show “In Review”
        on the county's records ({old_links or 'none at the moment'}). The site shows the county's status as it is.</li>
      <li><b>County filings are Loudoun only so far.</b> Fairfax and Prince William filings are not included yet,
        so a project there appears only once it is on DEQ's records.</li>
      <li><b>Agenda items can be missed.</b> An agenda item about a data center project that doesn't say “data
        center” or name a tracked case number isn't found; Fairfax's agendas are PDF board packages and aren't
        searched.</li>
    </ul>
    <p class="note">Spotted a mistake? Each item on the site links to its official record; if the site differs from
      the record, the record is right. <a href="{e(cfg['contact_url'])}">Tell us</a> and it will be fixed. The full
      source notes, including dates checked, are in the
      <a href="{CODE}/blob/main/data/sources.md">project's source notes</a>.</p>"""
    write(ctx, path, shell(path, "Methodology · Data Centers Near You",
                           "Where the data comes from, how stages and distances work, what this site calculates "
                           "itself, and known issues.", body, cfg))


def downloads_record(reg):
    return e(DEQ_RECORD.replace("&amp;", "&").format(reg))


def legacy_redirects(ctx, pairs):
    """Forwarding pages at the first version's addresses (/places/..., /zip/..., /schools/..., /browse/)."""
    base = ctx["cfg"]["site_url"].rstrip("/")
    for old, new in pairs:
        up = "../" * old.count("/")
        target = f"{up}{new}"
        page = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Moved</title>'
                f'<link rel="canonical" href="{e(base)}/{e(new)}"><meta name="robots" content="noindex">'
                f'<meta http-equiv="refresh" content="0; url={e(target)}"></head>'
                f'<body><p>This page moved to <a href="{e(target)}">its new address</a>.</p>'
                f'<script>location.replace("{target}" + location.hash);</script></body></html>\n')
        d = os.path.join(ctx["out"], old)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)


# ---- output -------------------------------------------------------------------------------------------------------

def write(ctx, path, text):
    d = os.path.join(ctx["out"], path)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    ctx["urls"].append(path)


def build_pages(site_dir, state, facilities, schools, zips, meta, log, cfg, filings=None):
    for name in ROOT_GENERATED:
        p = os.path.join(site_dir, name)
        shutil.rmtree(p) if os.path.isdir(p) else (os.remove(p) if os.path.exists(p) else None)
    for name in STATE_GENERATED:
        p = os.path.join(site_dir, state, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
    cards.reset()
    ctx = {"out": site_dir, "state": state, "facilities": facilities, "schools": schools, "zips": zips,
           "meta": meta, "log": log, "cfg": cfg, "urls": [], "filings": filings or []}
    ctx["civic"] = civic.for_pages(os.path.join(site_dir, state, "data"))  # meetings + how to take part
    loc_idx = locality_pages(ctx)
    zip_idx = zip_pages(ctx)
    ctx["zip_has_page"] = {r[0]: True for r in zip_idx}
    school_idx = school_pages(ctx)
    facility_pages(ctx)
    new_page(ctx)
    meetings_page(ctx)
    browse_page(ctx, loc_idx, zip_idx, school_idx)
    front_door(ctx)
    about_page(ctx)
    privacy_page(ctx)
    data_page(ctx)  # also writes the CSV downloads (pipeline/downloads.py), checked like the build's data
    methodology_page(ctx)
    # forward the first version's addresses to the new ones
    old_new = [("browse/", f"{state}/browse/")]
    old_new += [(p.replace(f"{state}/", "", 1), p) for p in ctx["urls"]
                if p.startswith((f"{state}/places/", f"{state}/zip/"))]
    old_new += list(ctx["legacy_school"].items())
    legacy_redirects(ctx, old_new)
    today = dt.date.today().isoformat()
    base = cfg["site_url"].rstrip("/")
    with open(os.path.join(site_dir, "sitemap.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in [f"{state}/"] + ctx["urls"]:
            fh.write(f"  <url><loc>{e(base)}/{u}</loc><lastmod>{today}</lastmod></url>\n")
        fh.write("</urlset>\n")
    with open(os.path.join(site_dir, "robots.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    card_stats = cards.render_queued(site_dir)  # the link-preview images the pages above point to
    return {"localities": len(loc_idx), "zips": len(zip_idx), "schools": len(school_idx),
            "facilities": len(facilities), "total": len(ctx["urls"]), "cards": card_stats}
