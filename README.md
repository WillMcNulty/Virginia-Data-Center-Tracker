# Virginia Data Center Tracker

Every data center Virginia's Department of Environmental Quality (DEQ) has on record, planned, under construction
or operating, on one map. Search around a ZIP code, a school, or any spot you pick on the map, within 1 to 30
miles. An independent project; not affiliated with DEQ, any locality, or any company shown.

## Why this exists

This started with my mom. My little brother goes to Rachel Carson Middle School in Herndon, and over about six
months, three data centers went up within a mile of his school. She found it disturbing, and what bothered her most
was that our family had no idea any of them were coming until they were there.

She texted me asking for something simple: a map showing where data centers are planned, what stage of
construction they're in, and how much they cost, where you could type in where you live and a distance (10 miles,
30 miles) and see what's around you. She'd seen a similar effort, but it relied on people submitting what they'd
heard, so it wasn't pulling from the best data.

So this map uses only official records. As of September 2026, Virginia DEQ's records show **four data centers
within a mile of my brother's school: two planned and two operating.** It answers the same question for any place
in Virginia in one step, and every dot links back to the state record it came from.

## What it shows

| | |
|---|---|
| **Sites** | Every site DEQ flags as a data center (`PLA_DATA_CENTER_YN = 'Y'`) in its daily **Air Sites** GIS layer: 198 as of September 2026. Data centers need a DEQ air permit for their backup diesel generators, so a project appears once it applies for one. |
| **Stage** | DEQ's own operating status: Planned, Under construction, Operating, Temporarily shut down. |
| **Permit dates** | From DEQ's **issued air permits for data centers** list (194 permits for 183 facilities as of September 21, 2026). |
| **Locality** | The county or independent city each site falls in, from DEQ's county boundary layer. Where DEQ's permit list names a different locality (three sites on the Manassas city line), both are shown. |
| **Search** | ZIP code (Census ZIP centers), school (all 2,159 Virginia public schools, from NCES), or a pin on the map, with a 1 to 30 mile radius. |

**Not yet shown** (planned next): earlier-stage proposals such as rezonings and special exceptions filed with a
county before any air permit; cost and size from county building permits; and, by ZIP code, the upcoming
hearings, comment periods and elections where residents can weigh in. See [`data/sources.md`](data/sources.md) for
every source and its limits.

## Privacy

- **Searches run in the browser.** ZIP centers, schools and data centers ship with the page; the distance math
  runs locally. There's no address box and no geocoding service.
- **Shareable links** keep the search in the URL fragment (`#school=...&r=1`), which browsers don't send to servers.
- **Cookieless analytics.** Cloudflare Web Analytics reports visits, page views, referrals and performance.
  We do not add search-event or map-pin tracking. See the site's Privacy page for details.
  The public beacon token is in `pipeline/pages.py` (generated pages) and `site/virginia/index.html` (map).
  Update both if replacing it. The map library is served from this site. External requests also fetch
  map tiles, from [OpenFreeMap](https://openfreemap.org/), which therefore sees which area of the map is being viewed.

## How it works

```
DEQ Air Sites layer (daily) ─┐
DEQ county boundaries ───────┤
DEQ permit list (snapshot) ──┼─> build.py ─> checks ─> site/virginia/data/*.json ─> static page (MapLibre + OpenFreeMap)
NCES school locations ───────┤
Census ZIP centers ──────────┘
```

- `pipeline/sources.py` fetches each source through its public API (ArcGIS REST, Census files). Nothing scrapes an
  HTML page. DEQ's permit list page blocks automated access, so its data is saved by hand as a dated snapshot in
  `data/` instead.
- `build.py` joins the sources, assigns each site's locality by point-in-polygon, attaches permit dates, and
  **refuses to publish** if the data looks broken: too few sites, a drop of more than 25% since the last build,
  points outside Virginia, sites with no locality, or too few schools or ZIP codes.
- `pipeline/pages.py` generates a static page for every county or city, ZIP code (data center within 5 miles)
  and public school (within 2 miles) with a data center nearby, plus Browse, About and Privacy pages and a
  sitemap, so search engines and link previews can read the content. Leading with the name people use: "Rachel
  Carson Middle School" rather than the federal "Carson Middle". Site settings (address, the hidden donate link)
  live in `data/site_config.json`.
- **Layout for more states** (the site becomes Data Centers Near You at `datacentersnearyou.org`): a national front
  page at `/`, and everything Virginia under `/virginia/`: the map, its data (`site/virginia/data/`), and the
  generated pages, including **one page per data center** (`/virginia/data-centers/<id>-<name>/`, with nearby
  schools and neighboring sites). The first version's addresses forward to the new ones.
- `pipeline/changes.py` keeps a **change log** (`site/virginia/data/changes.json`, committed): each daily build
  compares DEQ's records with the previous day's and records new sites, stage changes, new permits, renames and
  removals. It feeds `/virginia/new/` ("New this week") and an RSS feed. Offline rebuilds, which use cached data,
  never add to it.
- `pipeline/cards.py` draws each generated page's **link-preview image** (1200x630, `og:image`): the page's own
  numbers as a headline, e.g. "4 data centers within 1 mile of Rachel Carson Middle School", in DejaVu Sans
  (bundled in `pipeline/fonts/`), saved as a small palette PNG (about 15 KB) under `site/cards/` (generated). It
  also draws a 1080x1350 Instagram variant on request. Needs Pillow: CI installs it and refuses to build without
  it; a local build without it skips the images and points every page to the committed `site/card-default.png`.
- `site/geo.js` holds the search logic (distances, radius, school name matching, shareable links), shared by the
  page and the tests.
- **GitHub Actions** rebuilds from the live sources every morning, runs the tests, commits the data only when it
  changed, and deploys to GitHub Pages.

## Tests

```bash
python -m unittest discover tests     # pipeline helpers and the built data
node tests/geo.test.mjs               # the in-browser search, against the built data
```

Among other things, the tests check that the JavaScript and Python distance formulas agree to a millionth of a
mile, that "Rachel Carson", "rachel carson middle school" and "Carson" all find the school (its official name is
"Carson Middle"), and that the Carson Middle case returns its four sites nearest first.

## Run it locally

Python 3.10+ (standard library, plus Pillow for the link-preview images: `pip install Pillow`; optional locally)
and Node 18+ for the search tests.

```bash
python build.py                                   # fetch live data (about 40 seconds)
python -m http.server 8000 --directory site       # then open http://localhost:8000
```

`python build.py --offline` rebuilds from the raw files cached in `.cache/` by the last online build.

## Updating the permit dates

DEQ's issued-permits page can't be fetched by a script. To refresh it: open the page, show all rows, and save the
table as `data/deq_issued_permits_YYYY-MM-DD.tsv` with the same columns. The newest file is used automatically. Add
its row and facility counts to `test_permit_snapshot_matches_deq_page`.

## Related work

- The Piedmont Environmental Council's [Existing and Proposed Data Centers](https://www.pecva.org/region/culpeper/existing-and-proposed-data-centers-a-web-map/)
  map, which also includes proposals compiled from county filings and news.
- [Brockovich Data Center Reporting](https://brockovichdatacenter.com/), a national map of community reports.

## Credits

Data: Virginia Department of Environmental Quality; National Center for Education Statistics; U.S. Census Bureau.
Map: [MapLibre GL JS](https://maplibre.org/) (BSD-3-Clause, license in `site/vendor/LICENSE`),
[OpenFreeMap](https://openfreemap.org/), © OpenMapTiles, data © OpenStreetMap contributors.
