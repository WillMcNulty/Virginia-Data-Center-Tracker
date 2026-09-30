"""Static pages generated from the built data, so search engines and link previews can see the content
(the map itself is a JavaScript app, which crawlers mostly can't read).

Writes under site/ (generated, not committed; the daily build regenerates them):
  places/<locality>/     one page per county or city with any data center on DEQ's records
  zip/<zip>/             one per ZIP code with any data center within 5 miles of its center
  schools/<slug>/        one per public school with any data center within 2 miles
  browse/                an index of all of the above
  about/, privacy/       about the project and the privacy policy
  sitemap.xml, robots.txt

Every page links back to the interactive map, opened on the same search.
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
SCHOOL_RADIUS, ZIP_RADIUS = 2, 5
GENERATED = ["places", "zip", "schools", "browse", "about", "privacy", "sitemap.xml", "robots.txt"]
e = html.escape


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fmt_date(iso):
    if not iso:
        return None
    d = dt.date.fromisoformat(iso)
    return d.strftime("%b %-d, %Y") if os.name != "nt" else d.strftime("%b %#d, %Y")


def fmt_mi(d):
    return f"{d:.2f} mi" if d < 10 else f"{d:.1f} mi"


def stage_summary(items):
    counts = {}
    for f in items:
        counts[f["stage"]] = counts.get(f["stage"], 0) + 1
    parts = [f"{counts[k]} {STAGE_LABEL[k].lower()}" for k in STAGE_ORDER if counts.get(k)]
    return ", ".join(parts)


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---- page shell ---------------------------------------------------------------------------------------------------

def shell(depth, title, description, canonical, body, cfg):
    up = "../" * depth
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
<meta property="og:site_name" content="Virginia Data Center Tracker">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#232d4b">
<link rel="stylesheet" href="{up}pages.css">
<script src="{up}theme.js"></script>
</head>
<body>
  <header class="topbar band">
    <div class="wrap">
      <a class="brand" href="{up}">Virginia Data Center Tracker</a>
      <nav aria-label="Links">
        <a href="{up}">Map</a>
        <a href="{up}browse/">Browse</a>
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
      <div>Independent project; not affiliated with Virginia DEQ, any locality, or any company shown.
        Data from Virginia DEQ records. <a href="{up}privacy/">Privacy</a> · <a href="{up}about/">About</a> ·
        <a href="https://github.com/WillMcNulty/Virginia-Data-Center-Tracker">Code</a></div>
    </div>
  </footer>
</body>
</html>
"""


def facility_list(items, up, with_distance=True):
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
        <div class="fac-head"><i class="dot {f['stage']}" aria-hidden="true"></i><span class="nm">{e(f['name'])}</span>{dist}</div>
        <div class="meta"><span class="tag {f['stage']}">{STAGE_LABEL[f['stage']]}</span> {e(address)}, {e(f['city'])} · {loc} · {e(permit)} ·
          <a href="https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294/query?where=PLA_REG_NUM%3D{f['id']}&amp;outFields=*&amp;f=html">DEQ record {f['id']}</a></div>
      </li>""")
    return "    <ul class=\"facs\">\n" + "\n".join(rows) + "\n    </ul>" if rows else "    <p>None on DEQ's records.</p>"


def near(facilities, lat, lon, radius):
    out = [dict(f, distance=geo.miles(lat, lon, f["lat"], f["lon"])) for f in facilities]
    return sorted([f for f in out if f["distance"] <= radius], key=lambda f: f["distance"])


# ---- pages ----------------------------------------------------------------------------------------------------------

def locality_pages(facilities, meta, cfg, out, urls):
    by_loc = {}
    for f in facilities:
        by_loc.setdefault(f["locality"], []).append(f)
    index = []
    for loc, items in sorted(by_loc.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        items = sorted(items, key=lambda f: (STAGE_ORDER.index(f["stage"]), f["name"]))
        path = f"places/{slug(loc)}/"
        n_future = sum(1 for f in items if f["stage"] in ("planned", "construction"))
        title = f"Data centers in {loc}, Virginia"
        desc = (f"{plural(len(items), 'data center')} in {loc} on Virginia DEQ's records "
                f"({stage_summary(items)}), with addresses, stages and air permit dates.")
        body = f"""    <p class="crumbs"><a href="../../browse/">Browse</a> › {e(loc)}</p>
    <h1>Data centers in {e(loc)}</h1>
    <p class="lede">Virginia DEQ's records list <b>{plural(len(items), 'data center')}</b> in {e(loc)}: {e(stage_summary(items))}.
      {"<b>" + str(n_future) + " not yet operating.</b>" if n_future else ""}</p>
    <p><a class="btn" href="../../">Open the map</a></p>
{facility_list(items, "../../", with_distance=False)}
    <p class="note">Stages are DEQ's own. Only sites that have applied for a DEQ air permit for backup generators
      appear; earlier-stage proposals filed with the county are not included yet.</p>"""
        write(out, path, shell(2, title, desc, f"{cfg['site_url']}/{path}", body, cfg), urls)
        index.append((loc, path, len(items), n_future))
    return index


def zip_pages(facilities, zips, cfg, out, urls):
    index = []
    for z, (lat, lon) in sorted(zips.items()):
        items = near(facilities, lat, lon, ZIP_RADIUS)
        if not items:
            continue
        within1 = sum(1 for f in items if f["distance"] <= 1)
        within3 = sum(1 for f in items if f["distance"] <= 3)
        path = f"zip/{z}/"
        title = f"Data centers near ZIP code {z}, Virginia"
        desc = (f"{plural(len(items), 'data center')} within {ZIP_RADIUS} miles of ZIP code {z} on Virginia DEQ's "
                f"records ({stage_summary(items)}), nearest {fmt_mi(items[0]['distance'])} from the ZIP code's center.")
        body = f"""    <p class="crumbs"><a href="../../browse/">Browse</a> › ZIP {z}</p>
    <h1>Data centers near ZIP code {z}</h1>
    <p class="lede"><b>{plural(len(items), 'data center')}</b> within {ZIP_RADIUS} miles of the center of ZIP code {z}:
      {e(stage_summary(items))}. {within1} within 1 mile, {within3} within 3 miles.</p>
    <p><a class="btn" href="../../#zip={z}&amp;r={ZIP_RADIUS}">Open on the map</a></p>
{facility_list(items, "../../")}
    <p class="note">Distances are straight-line from the ZIP code's center point (Census). For a precise spot, use a
      school or drop a pin on the map.</p>"""
        write(out, path, shell(2, title, desc, f"{cfg['site_url']}/{path}", body, cfg), urls)
        index.append((z, path, len(items), within1))
    return index


def school_pages(facilities, schools, cfg, out, urls):
    index = []
    seen = {}
    for s in schools:
        items = near(facilities, s["lat"], s["lon"], SCHOOL_RADIUS)
        if not items:
            continue
        base = slug(f"{s['name']} {s['city']}")
        seen[base] = seen.get(base, 0) + 1
        path = f"schools/{base}{'' if seen[base] == 1 else '-' + s['id'][-4:]}/"
        within1 = sum(1 for f in items if f["distance"] <= 1)
        # Lead with the name people use when there is one ("Rachel Carson Middle School", not NCES's "Carson Middle").
        display = s["aka"][0] if s.get("aka") else s["name"]
        aka = f" (official name: {s['name']})" if s.get("aka") else ""
        title = f"Data centers near {display}, {s['city']}"
        desc = (f"{plural(len(items), 'data center')} within {SCHOOL_RADIUS} miles of {display} in {s['city']}, "
                f"Virginia ({stage_summary(items)}); nearest {fmt_mi(items[0]['distance'])} away.")
        body = f"""    <p class="crumbs"><a href="../../browse/">Browse</a> › Schools › {e(display)}</p>
    <h1>Data centers near {e(display)}</h1>
    <p class="lede">{e(display)}{e(aka)}, {e(s['street'])}, {e(s['city'])}. Virginia DEQ's records show
      <b>{plural(len(items), 'data center')}</b> within {SCHOOL_RADIUS} miles: {e(stage_summary(items))}.
      {within1} within 1 mile.</p>
    <p><a class="btn" href="../../#school={s['id']}&amp;r={SCHOOL_RADIUS}">Open on the map</a></p>
{facility_list(items, "../../")}
    <p class="note">Straight-line distance from the school's location (National Center for Education Statistics).
      Virginia's 2026 siting law requires a sound study covering schools within 500 feet of a new high-energy
      facility before a county can approve it.</p>"""
        write(out, path, shell(2, title, desc, f"{cfg['site_url']}/{path}", body, cfg), urls)
        index.append((f"{display} ({s['city']})", path, len(items), within1))
    return index


def browse_page(loc_idx, zip_idx, school_idx, meta, cfg, out, urls):
    def ul(rows, fmt):
        return "<ul class=\"idx\">" + "".join(fmt(r) for r in rows) + "</ul>"
    body = f"""    <h1>Browse data centers by place</h1>
    <p class="lede">Every county, ZIP code and public school in Virginia with a data center nearby on DEQ's records.
      {meta['facilities']} data centers statewide as of the last refresh.</p>
    <h2>Counties and cities</h2>
    {ul(loc_idx, lambda r: f'<li><a href="../{r[1]}">{e(r[0])}</a> <span>{plural(r[2], "data center")}' + (f', {r[3]} not yet operating' if r[3] else '') + '</span></li>')}
    <h2>Schools with a data center within {SCHOOL_RADIUS} miles</h2>
    {ul(sorted(school_idx), lambda r: f'<li><a href="../{r[1]}">{e(r[0])}</a> <span>{r[2]} within {SCHOOL_RADIUS} mi, {r[3]} within 1 mi</span></li>')}
    <h2>ZIP codes with a data center within {ZIP_RADIUS} miles</h2>
    {ul(zip_idx, lambda r: f'<li><a href="../{r[1]}">{r[0]}</a> <span>{r[2]} within {ZIP_RADIUS} mi</span></li>')}"""
    write(out, "browse/", shell(1, "Browse Virginia data centers by county, ZIP code or school",
                                "Every Virginia county, ZIP code and public school with a data center nearby, from Virginia DEQ records.",
                                f"{cfg['site_url']}/browse/", body, cfg), urls)


def about_page(meta, cfg, out, urls):
    body = f"""    <h1>About this project</h1>
    <h2>Why it exists</h2>
    <p>This started with my mom. My little brother goes to Rachel Carson Middle School in Herndon, and over about six
      months, three data centers went up within a mile of his school. What bothered her most was that our family had
      no idea any of them were coming until they were there. She asked for a simple map built from the best data
      available, where you could look around where you live and see what's planned, under construction or
      operating. This is that map.</p>
    <h2>Where the data comes from</h2>
    <p>Every site Virginia's Department of Environmental Quality flags as a data center in its daily Air Sites
      records ({meta['facilities']} today). Data centers need a DEQ air permit for their backup diesel generators, so
      a project appears once it applies for one; the stage shown is DEQ's own. Permit dates come from DEQ's list of
      issued data center air permits. Schools are from the National Center for Education Statistics and ZIP codes
      from the U.S. Census Bureau. The data refreshes every morning, and the build refuses to publish if a source
      looks broken. Every site links to its DEQ record.</p>
    <h2>What's not here yet</h2>
    <p>Earlier-stage proposals (rezonings and special exceptions filed with a county before any air permit), cost
      and size from county building permits, and, by ZIP code, the upcoming hearings, comment periods and elections
      where residents can weigh in. Those are being added next.</p>
    <h2>Who made it</h2>
    <p>William McNulty, a Computer Science and Economics student at the University of Virginia. An independent project,
      not affiliated with Virginia DEQ, any locality or any company shown. <a href="{e(cfg['contact_url'])}">Contact</a> ·
      <a href="https://github.com/WillMcNulty/Virginia-Data-Center-Tracker">Code and data on GitHub</a></p>
    <h2>Related work</h2>
    <p>The Piedmont Environmental Council's <a href="https://www.pecva.org/region/culpeper/existing-and-proposed-data-centers-a-web-map/">Existing and Proposed Data Centers</a>
      map, and <a href="https://brockovichdatacenter.com/">Brockovich Data Center Reporting</a>.</p>"""
    write(out, "about/", shell(1, "About the Virginia Data Center Tracker",
                               "Why this map exists, where its data comes from, and what's coming next.",
                               f"{cfg['site_url']}/about/", body, cfg), urls)


def privacy_page(cfg, out, urls):
    today = dt.date.today().isoformat()
    body = f"""    <h1>Privacy policy</h1>
    <p class="note">Last updated {today}.</p>
    <h2>What this site collects</h2>
    <p>Nothing about you. There are no accounts, forms, cookies, analytics or ads. Searches by ZIP code, school or map
      pin run entirely in your browser; nothing you enter is sent to this site or anyone else. A search you share as a
      link keeps its details after the <code>#</code> in the address, which browsers don't send to servers.</p>
    <h2>What your browser stores</h2>
    <p>If you pick a color theme, that choice is saved in your browser's local storage so it's remembered next time.
      It never leaves your device. Clearing your browser's site data removes it.</p>
    <h2>Other services the page contacts</h2>
    <p>Map images come from <a href="https://openfreemap.org/">OpenFreeMap</a>, which therefore sees which area of the
      map is being viewed (like any map image server). The site is served by its host, which, like any web server,
      receives standard request information such as your IP address; this project doesn't collect or use it.</p>
    <h2>Changes</h2>
    <p>If this site ever adds analytics, ads or donations, this page will be updated first to say exactly what is
      collected and by whom, with any choices you have.</p>
    <h2>Contact</h2>
    <p><a href="{e(cfg['contact_url'])}">Contact the author</a>.</p>"""
    write(out, "privacy/", shell(1, "Privacy policy · Virginia Data Center Tracker",
                                 "What the Virginia Data Center Tracker collects (nothing about you) and what your browser stores.",
                                 f"{cfg['site_url']}/privacy/", body, cfg), urls)


# ---- output -------------------------------------------------------------------------------------------------------

def write(out, path, text, urls):
    d = os.path.join(out, path)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    urls.append(path)


def build_pages(site_dir, facilities, schools, zips, meta, cfg):
    for name in GENERATED:
        p = os.path.join(site_dir, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    urls = []
    loc_idx = locality_pages(facilities, meta, cfg, site_dir, urls)
    zip_idx = zip_pages(facilities, zips, cfg, site_dir, urls)
    school_idx = school_pages(facilities, schools, cfg, site_dir, urls)
    browse_page(loc_idx, zip_idx, school_idx, meta, cfg, site_dir, urls)
    about_page(meta, cfg, site_dir, urls)
    privacy_page(cfg, site_dir, urls)
    today = dt.date.today().isoformat()
    base = cfg["site_url"].rstrip("/")
    with open(os.path.join(site_dir, "sitemap.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in [""] + urls:
            fh.write(f"  <url><loc>{e(base)}/{u}</loc><lastmod>{today}</lastmod></url>\n")
        fh.write("</urlset>\n")
    with open(os.path.join(site_dir, "robots.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    return {"localities": len(loc_idx), "zips": len(zip_idx), "schools": len(school_idx), "total": len(urls)}
