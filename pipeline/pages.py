"""Static pages generated from the built data, so search engines and link previews can read the content (the map
itself is a JavaScript app, which crawlers mostly can't read).

Layout (the domain is state-neutral, so each state gets its own folder):
  /                                   front door: search near you, coverage
  /about/  /privacy/                  site-wide pages
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

import geo

STAGE_LABEL = {"planned": "Planned", "construction": "Under construction", "operating": "Operating",
               "shutdown": "Temporarily shut down", "other": "Other"}
STAGE_ORDER = ["planned", "construction", "operating", "shutdown", "other"]
SCHOOL_RADIUS, ZIP_RADIUS, NEIGHBOR_RADIUS = 2, 5, 1
STATE_NAME = {"virginia": "Virginia"}
ROOT_GENERATED = ["index.html", "about", "privacy", "sitemap.xml", "robots.txt",
                  "places", "zip", "schools", "browse"]  # the last four are the forwarding pages
STATE_GENERATED = ["places", "zip", "schools", "data-centers", "new", "browse"]
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

def shell(path, title, description, body, cfg, state="virginia"):
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
<meta name="twitter:card" content="summary">
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
        Data from public state records. <a href="{up}privacy/">Privacy</a> · <a href="{up}about/">About</a> ·
        <a href="https://github.com/WillMcNulty/Virginia-Data-Center-Tracker">Code</a></div>
    </div>
  </footer>
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
      appear; earlier-stage proposals filed with the county are not included yet.</p>"""
        write(ctx, path, shell(path, title, desc, body, cfg))
        index.append((loc, path, len(items), n_future))
    return index


def zip_pages(ctx):
    s, cfg = ctx["state"], ctx["cfg"]
    index = []
    for z, (lat, lon) in sorted(ctx["zips"].items()):
        items = near(ctx["facilities"], lat, lon, ZIP_RADIUS)
        if not items:
            continue
        within1 = sum(1 for f in items if f["distance"] <= 1)
        within3 = sum(1 for f in items if f["distance"] <= 3)
        path = f"{s}/zip/{z}/"
        up = "../" * path.count("/")
        title = f"Data centers near ZIP code {z}, {STATE_NAME[s]}"
        desc = (f"{plural(len(items), 'data center')} within {ZIP_RADIUS} miles of ZIP code {z} on Virginia DEQ's "
                f"records ({stage_summary(items)}), nearest {fmt_mi(items[0]['distance'])} from the ZIP code's center.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › ZIP {z}</p>
    <h1>Data centers near ZIP code {z}</h1>
    <p class="lede"><b>{plural(len(items), 'data center')}</b> within {ZIP_RADIUS} miles of the center of ZIP code {z}:
      {e(stage_summary(items))}. {within1} within 1 mile, {within3} within 3 miles.</p>
    <p><a class="btn" href="{up}{s}/#zip={z}&amp;r={ZIP_RADIUS}">Open on the map</a></p>
{facility_list(items, up, s)}
    <p class="note">Distances are straight-line from the ZIP code's center point (Census). For a precise spot, use a
      school or drop a pin on the map.</p>"""
        write(ctx, path, shell(path, title, desc, body, cfg))
        index.append((z, path, len(items), within1))
    return index


def school_pages(ctx):
    s, cfg = ctx["state"], ctx["cfg"]
    index, seen, seen_old = [], {}, {}
    ctx["school_path"], ctx["legacy_school"] = {}, {}
    for sc in ctx["schools"]:
        items = near(ctx["facilities"], sc["lat"], sc["lon"], SCHOOL_RADIUS)
        if not items:
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
        desc = (f"{plural(len(items), 'data center')} within {SCHOOL_RADIUS} miles of {display} in {sc['city']}, "
                f"{STATE_NAME[s]} ({stage_summary(items)}); nearest {fmt_mi(items[0]['distance'])} away.")
        body = f"""    <p class="crumbs"><a href="{up}{s}/browse/">Browse</a> › Schools › {e(display)}</p>
    <h1>Data centers near {e(display)}</h1>
    <p class="lede">{e(display)}{e(aka)}, {e(sc['street'])}, {e(sc['city'])}. Virginia DEQ's records show
      <b>{plural(len(items), 'data center')}</b> within {SCHOOL_RADIUS} miles: {e(stage_summary(items))}.
      {within1} within 1 mile.</p>
    <p><a class="btn" href="{up}{s}/#school={sc['id']}&amp;r={SCHOOL_RADIUS}">Open on the map</a></p>
{facility_list(items, up, s)}
    <p class="note">Straight-line distance from the school's location (National Center for Education Statistics).
      Virginia's 2026 siting law requires a sound study covering schools within 500 feet of a new high-energy
      facility before a county can approve it.</p>"""
        write(ctx, path, shell(path, title, desc, body, cfg))
        index.append((f"{display} ({sc['city']})", path, len(items), within1))
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
    <h2>Source</h2>
    <p><a href="{DEQ_RECORD.format(f['id'])}">DEQ Air Sites record {f['id']}</a> (permit class: {e(f.get('permit_class') or 'not given')}).
      The stage is DEQ's own. This page is rebuilt every morning from DEQ's records.</p>"""
        write(ctx, path, shell(path, title, desc, body, cfg))


EVENT_TEXT = {
    "new": lambda ev: f"New on DEQ's data center records ({STAGE_LABEL.get(ev.get('stage'), '').lower()})",
    "stage": lambda ev: f"Stage changed from {STAGE_LABEL.get(ev.get('from'), ev.get('from'))} to {STAGE_LABEL.get(ev.get('to'), ev.get('to'))}",
    "permit": lambda ev: f"Air permit issued {fmt_date(ev.get('to')) or ''}",
    "renamed": lambda ev: f"Renamed from “{ev.get('from')}”",
    "removed": lambda ev: "No longer on DEQ's data center records",
}


def new_page(ctx):
    s, cfg, log = ctx["state"], ctx["cfg"], ctx["log"]
    by_id = {f["id"]: f for f in ctx["facilities"]}
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
            f = by_id.get(ev["id"])
            name = f'<a href="{up}{facility_path(s, f)}">{e(ev["name"])}</a>' if f else e(ev["name"])
            items.append(f"<li><b>{name}</b> ({e(ev.get('locality') or '')}): {e(EVENT_TEXT[ev['type']](ev))} "
                         f"<span class=\"when\">{fmt_date(ev['date'])}</span></li>")
        parts.append(f"    <h2>Week of {fmt_date(monday.isoformat())}</h2>\n    <ul class=\"plain\">{''.join(items)}</ul>")
    changes = "\n".join(parts) if parts else (
        f"    <p>Nothing has changed on DEQ's records since tracking began on {fmt_date(log['since'])}. "
        "This page updates every morning.</p>")
    body = f"""    <h1>New this week</h1>
    <p class="lede">What changed on Virginia DEQ's data center records: new sites, stage changes (planned, under
      construction, operating) and new air permits. Checked every morning since {fmt_date(log['since'])}.
      <a href="feed.xml">Subscribe by RSS</a>.</p>
{changes}"""
    write(ctx, path, shell(path, "New this week: Virginia data center records",
                           "New data centers, stage changes and air permits on Virginia DEQ's records, updated daily.", body, cfg))
    # RSS 2.0 feed of the latest 50 events
    base = cfg["site_url"].rstrip("/")
    items = []
    for ev in log["events"][:50]:
        f = by_id.get(ev["id"])
        link = f"{base}/{facility_path(s, f)}" if f else f"{base}/{path}"
        pub = dt.datetime.fromisoformat(ev["date"] + "T12:00:00+00:00").strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>{e(ev['name'])}: {e(EVENT_TEXT[ev['type']](ev))}</title><link>{e(link)}</link>"
                     f"<guid isPermaLink=\"false\">{e(ev['date'])}-{e(ev['type'])}-{ev['id']}</guid><pubDate>{pub}</pubDate>"
                     f"<description>{e(ev.get('locality') or '')}</description></item>")
    rss = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Data Centers Near You: Virginia changes</title>'
           f"<link>{e(base)}/{path}</link><description>New data centers, stage changes and air permits on Virginia DEQ's records.</description>"
           + "".join(items) + "</channel></rss>\n")
    with open(os.path.join(ctx["out"], path, "feed.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rss)


def browse_page(ctx, loc_idx, zip_idx, school_idx):
    s, cfg, meta = ctx["state"], ctx["cfg"], ctx["meta"]
    path = f"{s}/browse/"
    up = "../" * path.count("/")

    def ul(rows, fmt):
        return "<ul class=\"idx\">" + "".join(fmt(r) for r in rows) + "</ul>"
    body = f"""    <h1>Browse {STATE_NAME[s]} data centers by place</h1>
    <p class="lede">Every county, ZIP code and public school in {STATE_NAME[s]} with a data center nearby on DEQ's
      records. {meta['facilities']} data centers statewide as of the last refresh.</p>
    <h2>Counties and cities</h2>
    {ul(loc_idx, lambda r: f'<li><a href="{up}{r[1]}">{e(r[0])}</a> <span>{plural(r[2], "data center")}' + (f', {r[3]} not yet operating' if r[3] else '') + '</span></li>')}
    <h2>Schools with a data center within {SCHOOL_RADIUS} miles</h2>
    {ul(sorted(school_idx), lambda r: f'<li><a href="{up}{r[1]}">{e(r[0])}</a> <span>{r[2]} within {SCHOOL_RADIUS} mi, {r[3]} within 1 mi</span></li>')}
    <h2>ZIP codes with a data center within {ZIP_RADIUS} miles</h2>
    {ul(zip_idx, lambda r: f'<li><a href="{up}{r[1]}">{r[0]}</a> <span>{r[2]} within {ZIP_RADIUS} mi</span></li>')}"""
    write(ctx, path, shell(path, f"Browse {STATE_NAME[s]} data centers by county, ZIP code or school",
                           f"Every {STATE_NAME[s]} county, ZIP code and public school with a data center nearby, from state records.", body, cfg))


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
                         body, cfg))


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
      build refuses to publish if a source looks broken. Every site links to its DEQ record.</p>
    <h2>What's not here yet</h2>
    <p>Earlier-stage proposals (rezonings and special exceptions filed with a county before any air permit), cost
      and size from county building permits, and, by ZIP code, the upcoming hearings, comment periods and elections
      where residents can weigh in. Those are being added next, then more states.</p>
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
    <p>Nothing about you. There are no accounts, forms that send data, cookies, analytics or ads. Searches by ZIP
      code, school or map pin run entirely in your browser; nothing you enter is sent to this site or anyone else. A
      search you share as a link keeps its details after the <code>#</code> in the address, which browsers don't send
      to servers.</p>
    <h2>What your browser stores</h2>
    <p>If you pick a color theme, that choice is saved in your browser's local storage so it's remembered next time.
      It never leaves your device. Clearing your browser's site data removes it.</p>
    <h2>Other services the page contacts</h2>
    <p>Map images come from <a href="https://openfreemap.org/">OpenFreeMap</a>, which therefore sees which area of the
      map is being viewed (like any map image server). The site is served by its host, which, like any web server,
      receives standard request information such as your IP address; this project doesn't collect or use it.</p>
    <h2>Changes</h2>
    <p>If this site ever adds analytics, email alerts, ads or donations, this page will be updated first to say
      exactly what is collected and by whom, with any choices you have.</p>
    <h2>Contact</h2>
    <p><a href="{e(cfg['contact_url'])}">Contact the author</a>.</p>"""
    write(ctx, "privacy/", shell("privacy/", "Privacy policy · Data Centers Near You",
                                 "What Data Centers Near You collects (nothing about you) and what your browser stores.", body, cfg))


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


def build_pages(site_dir, state, facilities, schools, zips, meta, log, cfg):
    for name in ROOT_GENERATED:
        p = os.path.join(site_dir, name)
        shutil.rmtree(p) if os.path.isdir(p) else (os.remove(p) if os.path.exists(p) else None)
    for name in STATE_GENERATED:
        p = os.path.join(site_dir, state, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
    ctx = {"out": site_dir, "state": state, "facilities": facilities, "schools": schools, "zips": zips,
           "meta": meta, "log": log, "cfg": cfg, "urls": []}
    loc_idx = locality_pages(ctx)
    zip_idx = zip_pages(ctx)
    ctx["zip_has_page"] = {r[0]: True for r in zip_idx}
    school_idx = school_pages(ctx)
    facility_pages(ctx)
    new_page(ctx)
    browse_page(ctx, loc_idx, zip_idx, school_idx)
    front_door(ctx)
    about_page(ctx)
    privacy_page(ctx)
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
    return {"localities": len(loc_idx), "zips": len(zip_idx), "schools": len(school_idx),
            "facilities": len(facilities), "total": len(ctx["urls"])}
