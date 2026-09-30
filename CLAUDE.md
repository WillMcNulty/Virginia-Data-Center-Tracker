# Data Centers Near You (repo: Virginia-Data-Center-Tracker)

A free, resident-first map of data centers built only from official public records: where they are, what stage
(planned, under construction, operating), and (coming) how residents can take part. Live at
https://willmcnulty.github.io/Virginia-Data-Center-Tracker/ ; moving to **datacentersnearyou.org** on Cloudflare
Pages once the owner has bought the domain and set up the account. Owner: William McNulty (UVA student).

Strategy and plans live in the owner's private `uva-knowledge` repo (`docs/plans/datacentersnearyou-growth-strategy.md`,
`data-center-tracker-launch.md`, `data-center-tracker-business-and-expansion.md`, `virginia-data-center-map*.md`).
The task backlog for parallel work is **`docs/BACKLOG.md`** in this repo.

## Rules (non-negotiable)

- **Never add a `Co-Authored-By: Claude` trailer** (or any Claude attribution) to commits or PR descriptions. The
  owner had it scrubbed from all history.
- **Every fact must trace to an official record**, with a link. Label estimates and our own classifications as such.
- **Neutral and procedural.** The site informs; it never argues for or against data centers or tells people what
  to think or whom to vote for.
- **No personal data:** no landowner names from filings, no county staff names/emails (LOLA's AssignedTo fields
  are deliberately not fetched). Searches run in the browser. Owner-authorized Cloudflare Web Analytics
  provides cookieless usage/performance reports; do not add search-event or map-pin tracking. Keep the
  privacy page accurate. The public beacon token appears in pages.py and the map index.html.
- **Don't scrape pages that block bots.** DEQ's issued-permits web page (Akamai 403) is updated by hand as a dated
  snapshot in `data/`. Use official APIs/ArcGIS REST services.
- **Critical infrastructure:** don't publish precise fiber routes or combine detailed infrastructure layers into a
  targeting map; keep to already-public, coarse data within each source's terms.
- The build must **refuse to publish broken data** (see `check()` in `build.py`); keep and extend those guards.

## Layout

```
build.py                 fetch sources -> checks -> site/virginia/data/*.json -> generated pages
pipeline/sources.py      source fetchers (ArcGIS REST, Census, NCES), standard library only
pipeline/geo.py          haversine miles, point-in-polygon (site/geo.js mirrors miles; tests check they agree)
pipeline/pages.py        static pages: front door, /virginia/{places,zip,schools,data-centers,new,browse}, about,
                         privacy, sitemap, legacy forwarders (generated, gitignored)
pipeline/cards.py        link-preview images (og:image) per page, Pillow; also the 1080x1350 Instagram variant
pipeline/changes.py      change log (site/virginia/data/changes.json, committed) -> "New this week" + RSS
pipeline/filings.py      county filings (Loudoun LOLA so far): NOT YET WIRED INTO build.py / the map (backlog T1)
site/virginia/index.html + app.js   the map app (MapLibre from site/vendor, OpenFreeMap tiles)
site/geo.js, theme.js, pages.css    shared by all pages; theme.js = Auto/Light/Dark switcher shared across the owner's sites
data/                    site_config.json (site_url, hidden support_url), DEQ permit snapshot, school aliases, sources.md
tests/                   test_build.py (python -m unittest discover tests), geo.test.mjs (node tests/geo.test.mjs)
```

## Commands

```bash
python build.py            # live build (~1 min); writes data + pages
python build.py --offline  # rebuild from .cache/ (never touches the change log)
python -m unittest discover tests
node tests/geo.test.mjs
python -m http.server 8140 --bind 127.0.0.1 --directory site   # preview
```

Push (HTTPS via gh credentials): `git -c credential.helper= -c "credential.helper=!C:/PROGRA~1/GITHUB~1/gh.exe auth git-credential" push origin main`.
CI (`.github/workflows/refresh.yml`) runs daily and on push: live build, both test suites, commits data only when
it changed (bot commits), deploys `site/` to GitHub Pages. **Pull before pushing**: the bot commits daily.

## Data sources and gotchas

- DEQ Air Sites layer: `apps.deq.virginia.gov/.../EDMA/MapServer/294`, `PLA_DATA_CENTER_YN='Y'` (~198 sites), daily.
  Needs a browser-like User-Agent. DEQ county boundaries: layer 157.
- Three sites on the Manassas city line: boundary map says Prince William County, DEQ's list says Manassas City;
  both are shown (`listed_locality`).
- A few DEQ records lack a street address or ZIP; pages say "not listed by DEQ".
- NCES calls schools by short official names ("Carson Middle"); `data/landmark_aliases.json` adds common names;
  pages lead with the common name.
- Loudoun LOLA: `logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0`; the server is sometimes down
  (returns an HTML error page), so treat it as optional with a health check, never fail the whole build on it.
- Agendas: Fairfax (`video.fairfaxcounty.gov` view 7), Loudoun (`loudoun.granicus.com` view 89), Prince William
  (`pwcgov.granicus.com` view 23) publish Granicus RSS (`ViewPublisherRSS.php?view_id=N&mode=agendas`) with
  searchable agenda HTML. The Legistar client `pwcgov` is NOT Prince William County.
- Design: portfolio design language (UVA Blue #232d4b / Orange #e57200, system fonts); chart/marker colors were
  validated for colorblind separation (see comments in site/virginia/index.html); light/dark via tokens.
