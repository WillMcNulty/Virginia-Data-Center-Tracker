"""Tests for the pipeline and the built data. Run: python -m unittest discover tests"""
import codecs
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import build  # noqa: E402
import geo  # noqa: E402

DATA = os.path.join(ROOT, "site", "virginia", "data")


def dt_ms(y, m, d):
    """An ArcGIS date: milliseconds since 1970, UTC."""
    import datetime
    return int(datetime.datetime(y, m, d, 12, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def load(name):
    return json.load(open(os.path.join(DATA, f"{name}.json"), encoding="utf-8"))


class Helpers(unittest.TestCase):
    def test_parse_date_handles_deq_typo(self):
        self.assertEqual(build.parse_date("07/31/2026"), "2026-07-31")
        self.assertEqual(build.parse_date("03/26-2026"), "2026-03-26")
        self.assertIsNone(build.parse_date("TBD"))

    def test_locality_label(self):
        self.assertEqual(build.locality_label("Fairfax", "059"), "Fairfax County")
        self.assertEqual(build.locality_label("Fairfax", "600"), "Fairfax City")
        self.assertEqual(build.locality_label("Richmond", "159"), "Richmond County")

    def test_point_in_polygon_with_hole(self):
        outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]  # like an independent city inside a county
        self.assertTrue(geo.in_esri_polygon(2, 2, [outer, hole]))
        self.assertFalse(geo.in_esri_polygon(5, 5, [outer, hole]))
        self.assertFalse(geo.in_esri_polygon(11, 5, [outer, hole]))

    def test_miles(self):
        # Carson Middle (NCES) to Herndon Technology Partners, 13775 McLearen Road (DEQ): 0.28 miles
        self.assertAlmostEqual(geo.miles(38.927278, -77.419005, 38.927049, -77.424213), 0.28, delta=0.01)
        self.assertEqual(geo.miles(37.5, -77.4, 37.5, -77.4), 0)

    def test_permit_snapshot_matches_deq_page(self):
        # When a newer snapshot is saved, add its row and facility counts from DEQ's page here.
        expected = {"2026-09-21": (194, 183)}
        permits, snap = build.load_permits()
        self.assertIn(snap, expected, "add the new snapshot's counts to this test")
        rows, facilities = expected[snap]
        self.assertEqual(sum(len(v) for v in permits.values()), rows)
        self.assertEqual(len(permits), facilities)

    def test_check_refuses_a_broken_source(self):
        with self.assertRaises(SystemExit):
            build.check([], [], {}, {})


class BuiltData(unittest.TestCase):
    """The committed site data is sane and every record can be traced to its source."""

    @classmethod
    def setUpClass(cls):
        cls.fac, cls.meta = load("facilities"), load("meta")

    def test_every_facility_is_located_and_staged(self):
        for f in self.fac:
            self.assertTrue(36.5 <= f["lat"] <= 39.5 and -83.7 <= f["lon"] <= -75.2, f["name"])
            self.assertIn(f["stage"], build.STAGES.values(), f["name"])
            self.assertTrue(f["locality"], f["name"])
            self.assertTrue(f["id"] and f["name"] and f["city"], f)
        # DEQ leaves the street address blank on a few records (2 of 198 in Sept 2026); the page says so.
        # Many blanks at once would mean the source changed shape.
        self.assertLessEqual(sum(1 for f in self.fac if not f["address"]), 10)

    def test_meta_counts_match(self):
        self.assertEqual(self.meta["facilities"], len(self.fac))
        self.assertEqual(sum(self.meta["stages"].values()), len(self.fac))

    def test_permit_dates_are_iso(self):
        for f in self.fac:
            for p in f["permits"]:
                self.assertRegex(p["issued"] or "", r"^\d{4}-\d{2}-\d{2}$|^$")


class ChangeLog(unittest.TestCase):
    def test_diff_finds_each_kind_of_change(self):
        import changes
        a = [{"id": 1, "name": "A", "stage": "planned", "latest_permit": None, "locality": "X"},
             {"id": 2, "name": "B", "stage": "operating", "latest_permit": "2025-01-01", "locality": "X"},
             {"id": 3, "name": "C", "stage": "operating", "latest_permit": None, "locality": "X"}]
        b = [{"id": 1, "name": "A", "stage": "construction", "latest_permit": "2026-09-01", "locality": "X"},
             {"id": 2, "name": "B2", "stage": "operating", "latest_permit": "2025-01-01", "locality": "X"},
             {"id": 4, "name": "D", "stage": "planned", "latest_permit": None, "locality": "Y"}]
        kinds = sorted((e["type"], e["id"]) for e in changes.diff(a, b, "2026-10-01"))
        self.assertEqual(kinds, [("new", 4), ("permit", 1), ("removed", 3), ("renamed", 2), ("stage", 1)])

    def test_same_change_is_not_logged_twice_and_offline_adds_nothing(self):
        import tempfile
        import changes
        a = [{"id": 1, "name": "A", "stage": "planned"}]
        b = [{"id": 1, "name": "A", "stage": "operating"}]
        path = os.path.join(tempfile.mkdtemp(), "changes.json")
        log, added = changes.update(path, a, b, "2026-10-01")
        json.dump(log, open(path, "w"))
        log2, added2 = changes.update(path, a, b, "2026-10-01")
        self.assertEqual((len(added), len(added2), len(log2["events"])), (1, 0, 1))
        self.assertEqual(changes.update(path, None, b, "2026-10-02")[1], [])  # no previous list (offline): nothing

    def test_committed_log_is_valid(self):
        log = load("changes")
        self.assertRegex(log["since"], r"^\d{4}-\d{2}-\d{2}$")
        ids = {f["id"] for f in load("facilities")} | {f["id"] for f in load("filings")}
        for ev in log["events"]:
            self.assertIn(ev["type"], {"new", "stage", "permit", "renamed", "removed", "filing-new", "filing-status"})
            if ev["type"] != "removed":
                self.assertIn(ev["id"], ids)


def lola(number, plan_type="Engineering Plan", status="In Review", when=None, name="Test Center",
         desc="Two data center buildings.", ring=None):
    """A raw LOLA feature, as the ArcGIS service returns it."""
    ring = ring or [[-77.50, 39.00], [-77.49, 39.00], [-77.49, 39.01], [-77.50, 39.01], [-77.50, 39.00]]
    return {"attributes": {"PlanNumber": number, "PlanApplicationDate": when or dt_ms(2026, 9, 1), "PlanType": plan_type,
                           "PlanStatus": status, "PlanName": name, "PlanDescription": desc},
            "geometry": {"rings": [ring]}}


class Filings(unittest.TestCase):
    """County filings (pipeline/filings.py) and how the build publishes them."""

    def test_scrub_removes_staff_initials_and_review_sessions(self):
        import filings
        self.assertEqual(filings.scrub("TWO BUILDINGS IN THE (PDIP) ZONING DISTRICT. AM"),
                         "TWO BUILDINGS IN THE (PDIP) ZONING DISTRICT.")
        self.assertEqual(filings.scrub("ZONING DISTRICT. JAB STMP-2022-0006."), "ZONING DISTRICT. STMP-2022-0006.")
        self.assertEqual(filings.scrub("IN THE PDIP ZONING DISTRICT ZDF"), "IN THE PDIP ZONING DISTRICT")
        self.assertEqual(filings.scrub("PARK (PDIP) SDM"), "PARK (PDIP)")
        self.assertEqual(filings.scrub("A data center. (Bluebeam Session# 640-079-749)"), "A data center.")
        # ordinary words and planning codes stay
        self.assertEqual(filings.scrub("(PDIP) AND SINGLE FAMILY"), "(PDIP) AND SINGLE FAMILY")
        self.assertEqual(filings.scrub("uses at a 0.86 FAR."), "uses at a 0.86 FAR.")
        self.assertEqual(filings.scrub("revise Bldg VA7. (SPAM)"), "revise Bldg VA7. (SPAM)")

    def test_people_are_not_published(self):
        import filings
        out = filings.loudoun([
            lola("STPL-2026-0001", name="ARCOLA LAKHVINDER PROPERTY", desc="ARCOLA LAKHVINDER PROPERTY : A SITE PLAN"),
            lola("EPLAN-2026-0002", desc="Jane Doe, Esq. of Some Firm LLC, on behalf of the owner, requests a data center"),
        ])
        by = {f["id"]: f for f in out}
        self.assertEqual(by["STPL-2026-0001"]["name"], "Site plan STPL-2026-0001")
        self.assertNotIn("LAKHVINDER", json.dumps(out).upper())
        self.assertNotIn("Jane", json.dumps(out))
        self.assertEqual(filings.problems(out), [])

    def test_loudoun_adapter(self):
        import filings
        raw = [lola("LEGI-2026-0019", "Legislative Application"),
               lola("SPEX-2026-0037", "Special Exception", desc="SEE LEGI-2026-0019 FOR DOCUMENTS"),
               lola("EPLAN-2026-0140", status="Approved", when=dt_ms(2026, 9, 2)),
               lola("BOND-2026-0001", "Bond"),  # paperwork: left out
               lola("EPLAN-2019-0001", status="Approved", when=dt_ms(2019, 5, 1)),  # decided long ago: left out
               lola("EPLAN-2018-0002", when=dt_ms(2018, 5, 1))]  # old but still in review: kept
        out = filings.loudoun(raw)
        self.assertEqual([f["id"] for f in out], ["EPLAN-2026-0140", "LEGI-2026-0019", "EPLAN-2018-0002"])
        legi = out[1]
        self.assertEqual(legi["related"], ["Special exception SPEX-2026-0037"])
        self.assertEqual((legi["kind"], legi["status"], legi["label"]),
                         ("land-use", "in-review", "Proposed: in county review"))
        self.assertEqual(out[0]["label"], "Site plan approved")
        for f in out:
            self.assertEqual(set(f), set(filings.FIELDS))
            self.assertAlmostEqual(f["lat"], 39.005, places=3)
            self.assertAlmostEqual(f["lon"], -77.495, places=3)
            self.assertIn(f["id"], f["source"])

    def test_problems_catch_broken_data(self):
        import filings
        good = filings.loudoun([lola(f"EPLAN-2026-{i:04d}") for i in range(1, 21)])
        self.assertEqual(filings.problems(good, good, lambda c, lon, lat: True), [])
        self.assertTrue(filings.problems(good[:10], good))  # fell by half
        self.assertTrue(filings.problems([]))
        self.assertTrue(filings.problems(good, None, lambda c, lon, lat: False))  # all outside the county
        first = good[0]["id"]
        self.assertEqual(filings.problems(good, None, lambda c, lon, lat: True), [])
        one_off = [dict(f, lat=37.0) if f["id"] == first else f for f in good]  # one parcel over the line: tolerated
        self.assertEqual(filings.problems(one_off, None, lambda c, lon, lat: lat > 38), [])
        self.assertTrue(filings.problems(good + good[:1]))  # duplicate id
        self.assertTrue(filings.problems([dict(good[0], date="09/01/2026")]))
        self.assertTrue(filings.problems([dict(good[0], description="Call (703) 555-0100")]))

    def test_diff_logs_new_filings_and_status_changes(self):
        import filings
        a = filings.loudoun([lola("EPLAN-2026-0001"), lola("EPLAN-2026-0002")])
        b = filings.loudoun([lola("EPLAN-2026-0001", status="Approved"), lola("EPLAN-2026-0002"),
                             lola("EPLAN-2026-0003")])
        ev = {(e["type"], e["id"]): e for e in filings.diff(a, b, "2026-10-01")}
        self.assertEqual(set(ev), {("filing-status", "EPLAN-2026-0001"), ("filing-new", "EPLAN-2026-0003")})
        changed = ev[("filing-status", "EPLAN-2026-0001")]
        self.assertEqual((changed["from"], changed["to"]), ("Site plan in review", "Site plan approved"))

    def test_build_keeps_yesterdays_filings_when_the_source_fails(self):
        import tempfile
        from unittest import mock
        import filings
        d = tempfile.mkdtemp()
        county = [[-77.6, 38.9], [-77.4, 38.9], [-77.4, 39.1], [-77.6, 39.1], [-77.6, 38.9]]
        with open(os.path.join(d, "deq_counties.json"), "w") as fh:
            json.dump([{"attributes": {"NAME": "Loudoun", "FIPS": "107"}, "geometry": {"rings": [county]}}], fh)
        prev = filings.loudoun([lola(f"EPLAN-2026-{i:04d}") for i in range(1, 11)])
        with open(os.path.join(d, "filings.json"), "w") as fh:
            json.dump(prev, fh)

        def run(fetch):
            src = [("Loudoun County", "lola.json", fetch, filings.loudoun)]
            with mock.patch.object(build, "CACHE", d), mock.patch.object(build, "FILING_SOURCES", src), \
                    mock.patch.object(build, "FILINGS", os.path.join(d, "filings.json")):
                return build.build_filings()

        def down():
            raise ValueError("LOLA returned an HTML error page")
        out, before, status = run(down)
        self.assertEqual((out, before, status["Loudoun County"]["updated"]), (prev, prev, False))
        out, _, status = run(lambda: [lola("EPLAN-2026-0001")])  # 1 filing instead of 10: looks broken
        self.assertEqual((len(out), status["Loudoun County"]["updated"]), (10, False))
        far = [[-80.0, 37.0], [-79.9, 37.0], [-79.9, 37.1], [-80.0, 37.0]]
        out, _, status = run(lambda: [lola(f"EPLAN-2026-{i:04d}", ring=far) for i in range(1, 11)])  # not in Loudoun
        self.assertEqual((out, status["Loudoun County"]["updated"]), (prev, False))
        out, _, status = run(lambda: [lola(f"EPLAN-2026-{i:04d}") for i in range(1, 12)])  # one new: published
        self.assertEqual((len(out), status["Loudoun County"]["updated"]), (11, True))


class CommittedFilings(unittest.TestCase):
    """site/virginia/data/filings.json: well formed, in Loudoun, sourced, and free of personal data."""

    def test_committed_filings(self):
        import re
        import filings
        fil = load("filings")
        self.assertGreater(len(fil), 50)
        self.assertEqual(len({f["id"] for f in fil}), len(fil))
        for f in fil:
            self.assertEqual(set(f), set(filings.FIELDS), f["id"])
            self.assertIn(f["kind"], {"land-use", "site-plan"})
            self.assertTrue(38.8 <= f["lat"] <= 39.35 and -77.97 <= f["lon"] <= -77.32, f["id"])  # Loudoun's extent
            self.assertTrue(f["source"].startswith("https://logis.loudoun.gov/") and f["id"] in f["source"], f["id"])
            text = f["name"] + " " + f["description"]
            self.assertIsNone(filings.PERSONAL_HINTS.search(text), f["id"])
            for w in filings.WITHHELD_NAME_WORDS:
                self.assertNotIn(w.lower(), text.lower(), f["id"])
            self.assertIsNone(re.search(r"DISTRI?C?T\.?\s+[A-Z]{2,3}$", f["description"]), f["id"])  # no initials
        self.assertEqual(filings.problems(fil), [])


class GeneratedPages(unittest.TestCase):
    """The static pages for search engines: built into a temporary folder from the committed data."""

    @classmethod
    def setUpClass(cls):
        import re
        import shutil
        import tempfile
        import pages
        cls.re = re
        cls.dir = tempfile.mkdtemp()
        for f in ("pages.css", "theme.js", "geo.js"):
            shutil.copy(os.path.join(ROOT, "site", f), cls.dir)
        shutil.copytree(os.path.join(ROOT, "site", "vendor"), os.path.join(cls.dir, "vendor"))
        shutil.copytree(os.path.join(ROOT, "site", "virginia"), os.path.join(cls.dir, "virginia"),
                        ignore=shutil.ignore_patterns("places", "zip", "schools", "data-centers", "new", "browse"))
        cfg = json.load(open(os.path.join(ROOT, "data", "site_config.json"), encoding="utf-8"))
        cls.cfg = cfg
        cls.counts = pages.build_pages(cls.dir, "virginia", load("facilities"), load("schools"), load("zips"),
                                       load("meta"), load("changes"), cfg, filings=load("filings"))
        cls.html = {}
        for root, _, files in os.walk(cls.dir):
            for f in files:
                if f == "index.html":
                    rel = os.path.relpath(root, cls.dir).replace(os.sep, "/")
                    cls.html["" if rel == "." else rel + "/"] = open(os.path.join(root, f), encoding="utf-8").read()
        cls.forwarders = {p for p, h in cls.html.items() if 'http-equiv="refresh"' in h}
        cls.pages = {p: h for p, h in cls.html.items() if p not in cls.forwarders and p != "virginia/"}

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.dir)

    def test_carson_page(self):
        page = self.html["virginia/schools/rachel-carson-middle-school-herndon/"]
        self.assertIn("<h1>Data centers near Rachel Carson Middle School</h1>", page)
        self.assertIn("<b>4 data centers</b> within 2 miles: 2 planned, 2 operating", page)
        self.assertIn('href="../../../virginia/#school=510126001756&amp;r=2"', page)

    def test_analytics_on_map_and_generated_pages_only_once(self):
        from html.parser import HTMLParser
        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__()
                self.beacons = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "script" and attrs.get("src") == "https://static.cloudflareinsights.com/beacon.min.js":
                    self.beacons.append(attrs)
        for path, html in self.html.items():
            parser = Scripts()
            parser.feed(html)
            with self.subTest(path=path):
                self.assertEqual(len(parser.beacons), 0 if path in self.forwarders else 1)
                if parser.beacons:
                    self.assertEqual(json.loads(parser.beacons[0]["data-cf-beacon"])["token"],
                                     "a6c6e47a18a143f28f11aff1ab47154b")
        self.assertIn("Cloudflare Web Analytics", self.html["privacy/"])
        self.assertNotIn("Nothing about you", self.html["privacy/"])

    def test_old_carson_address_forwards_to_the_new_one(self):
        self.assertIn("url=../../virginia/schools/rachel-carson-middle-school-herndon/",
                      self.html["schools/carson-middle-herndon/"])

    def test_data_center_page(self):
        page = self.html["virginia/data-centers/74332-herndon-technology-partners-llc/"]
        self.assertIn("<h1>Herndon Technology Partners LLC</h1>", page)
        self.assertIn("rachel-carson-middle-school-herndon/", page)  # nearby school, linked
        self.assertIn("74332-2, issued Jul 31, 2026", page)
        self.assertEqual(self.counts["facilities"], len(load("facilities")))

    def test_new_this_week_and_feed(self):
        page = self.html["virginia/new/"]
        feed = open(os.path.join(self.dir, "virginia", "new", "feed.xml"), encoding="utf-8").read()
        for ev in load("changes")["events"][:3]:
            self.assertIn(html_escape(ev["name"]), page)
            self.assertIn(f"{ev['date']}-{ev['type']}-{ev['id']}", feed)

    def test_every_page_has_one_h1_a_canonical_and_is_in_the_sitemap(self):
        sitemap = open(os.path.join(self.dir, "sitemap.xml"), encoding="utf-8").read()
        for path, page in self.pages.items():
            self.assertEqual(page.count("<h1>"), 1, path)
            self.assertIn(f'<link rel="canonical" href="{self.cfg["site_url"]}/{path}">', page)
            self.assertIn(f"<loc>{self.cfg['site_url']}/{path}</loc>", sitemap, path)
        for path in self.forwarders:
            self.assertNotIn(f"<loc>{self.cfg['site_url']}/{path}</loc>", sitemap)
        self.assertEqual(sitemap.count("<loc>"), self.counts["total"] + 1)  # + the Virginia map

    def test_internal_links_resolve(self):
        for path, page in self.html.items():
            for href in self.re.findall(r'href="([^"]+)"', page):
                if href.startswith(("http", "#", "mailto:")):
                    continue
                target = os.path.normpath(os.path.join(self.dir, path, href.split("#")[0]))
                self.assertTrue(os.path.exists(target), f"{path}: broken link {href}")

    def test_county_filings_on_pages(self):
        import pages
        loudoun = self.html["virginia/places/loudoun-county/"]
        for f in load("filings"):  # the county page lists every filing, each linked to its county record
            self.assertIn(html_escape(f["source"]), loudoun)
        self.assertIn("None in the county filings this site tracks",
                      self.html["virginia/schools/rachel-carson-middle-school-herndon/"])
        self.assertIn("are not included yet", self.html["virginia/places/fairfax-county/"])
        with_filings = [p for p, h in self.pages.items() if "that mention a data center, from" in h]
        for kind in ("schools", "zip", "data-centers"):
            self.assertTrue(any(p.startswith(f"virginia/{kind}/") for p in with_filings), kind)
        # a school gets a page when a filing is within 2 miles even if no DEQ-listed data center is
        for path, page in self.pages.items():
            if path.startswith("virginia/schools/") and "show no data centers within" in page:
                self.assertIn(f"County filings within {pages.FILING_RADIUS} miles", page)

    def test_filing_events_on_new_this_week(self):
        import tempfile
        import pages
        f = load("filings")[0]
        log = {"since": "2026-09-28", "events": [
            {"date": "2026-10-01", "type": "filing-status", "id": f["id"], "name": f["name"], "locality": f["county"],
             "kind": f["kind"], "filing_type": f["type"], "label": f["label"], "from": "Site plan in review",
             "to": "Site plan approved"}]}
        ctx = {"out": tempfile.mkdtemp(), "state": "virginia", "facilities": [], "filings": [f], "log": log,
               "cfg": self.cfg, "urls": []}
        pages.new_page(ctx)
        with open(os.path.join(ctx["out"], "virginia", "new", "index.html"), encoding="utf-8") as fh:
            page = fh.read()
        with open(os.path.join(ctx["out"], "virginia", "new", "feed.xml"), encoding="utf-8") as fh:
            feed = fh.read()
        self.assertIn(html_escape(f["source"]), page)
        self.assertIn(html_escape("County filing changed from “Site plan in review” to “Site plan approved”"), page)
        self.assertIn(f"2026-10-01-filing-status-{f['id']}", feed)

    def test_csv_downloads_match_the_json(self):
        import downloads
        expected = {"data-centers": load("facilities"), "changes": load("changes")["events"],
                    "county-filings": load("filings")}
        for key, items in expected.items():
            table = downloads.read(os.path.join(self.dir, "data", downloads.FILES[key].format(state="virginia")))
            with self.subTest(key=key):
                self.assertEqual(table[0], [c for c, _ in downloads.COLUMNS[key]])
                self.assertEqual(len(table) - 1, len(items))
                for c in table[0]:  # no personal-data fields (LOLA's AssignedTo, emails, phones, owners)
                    self.assertNotRegex(c, downloads.PERSONAL_COLUMN)
        dcs = downloads.read(os.path.join(self.dir, "data", "virginia-data-centers.csv"))
        hdr = dcs[0]
        carson_dc = next(r for r in dcs[1:] if r[0] == "74332")
        self.assertEqual(carson_dc[hdr.index("latest_air_permit_date")], "2026-07-31")
        self.assertIn("74332-2 (2026-07-31", carson_dc[hdr.index("air_permits")])
        self.assertTrue(all(r[hdr.index("deq_record_url")].startswith(
            "https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294/query?where=PLA_REG_NUM%3D")
            for r in dcs[1:]))
        fil = downloads.read(os.path.join(self.dir, "data", "virginia-county-filings.csv"))
        by_id = {f["id"]: f for f in load("filings")}
        for r in fil[1:]:  # descriptions and sources exactly as published in filings.json (already scrubbed)
            row = dict(zip(fil[0], r))
            self.assertEqual(row["description"], by_id[row["id"]]["description"])
            self.assertEqual(row["source"], by_id[row["id"]]["source"])
        # bytes on disk: UTF-8 with one byte-order mark (so Excel reads it as UTF-8), CRLF rows (RFC 4180)
        for name in ("virginia-data-centers.csv", "virginia-changes.csv", "virginia-county-filings.csv"):
            raw = open(os.path.join(self.dir, "data", name), "rb").read()
            self.assertTrue(raw.startswith(codecs.BOM_UTF8) and not raw.startswith(codecs.BOM_UTF8 * 2), name)
            self.assertIn(b"\r\n", raw)
            raw.decode("utf-8-sig")
        raw = open(os.path.join(self.dir, "data", "virginia-data-centers.csv"), "rb").read()
        self.assertTrue(raw.startswith(codecs.BOM_UTF8 + b"deq_registration_number,"))

    def test_data_and_methodology_pages_are_linked(self):
        sitemap = open(os.path.join(self.dir, "sitemap.xml"), encoding="utf-8").read()
        for path in ("data/", "methodology/"):
            self.assertIn(f"<loc>{self.cfg['site_url']}/{path}</loc>", sitemap)
        data, meth = self.html["data/"], self.html["methodology/"]
        for name in ("virginia-data-centers.csv", "virginia-changes.csv", "virginia-county-filings.csv"):
            self.assertIn(f'href="{name}"', data)
        self.assertIn("with attribution", data)
        self.assertIn('id="embedform"', data)
        self.assertIn(f'data-base="{self.cfg["site_url"]}/virginia/"', data)
        for page in (self.html["about/"],):
            self.assertIn('href="../data/"', page)
            self.assertIn('href="../methodology/"', page)
        for path, page in self.pages.items():  # footer on every generated page
            up = "../" * path.count("/")
            self.assertIn(f'<a href="{up}data/">Data</a>', page, path)
            self.assertIn(f'<a href="{up}methodology/">Methodology</a>', page, path)
        for text in ("Manassas", "74118", "haversine", "robots.txt", "In Review", "Loudoun only so far",
                     "issued-air-permits-for-data-centers", "MapServer/294", "LOLA_DATA"):
            self.assertIn(text, meth)

    def test_support_link_hidden_until_configured(self):
        if not self.cfg.get("support_url"):
            self.assertNotIn(self.cfg["support_label"], self.html["about/"])

    def test_every_page_has_a_preview_image(self):
        import cards
        base = self.cfg["site_url"].rstrip("/") + "/"
        own = 0
        for path, page in self.pages.items():
            url = self.re.search(r'<meta property="og:image" content="([^"]+)">', page).group(1)
            self.assertTrue(url.startswith(base), f"{path}: og:image must be absolute: {url}")
            self.assertIn('<meta property="og:image:width" content="1200">', page, path)
            self.assertIn('<meta property="og:image:height" content="630">', page, path)
            self.assertRegex(page, r'<meta property="og:image:alt" content="[^"]{20,}">', path)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">', page, path)
            rel = url[len(base):]
            if rel == cards.DEFAULT_CARD:
                file = os.path.join(ROOT, "site", rel)  # the committed generic card
            else:
                own += 1
                file = os.path.join(self.dir, rel)
            self.assertEqual(png_info(file)[:2], (1200, 630), f"{path}: {rel}")
        if cards.available():
            # every data page (county, ZIP, school, data center) and the front door has its own card
            self.assertEqual(own, sum(self.counts[k] for k in ("localities", "zips", "schools", "facilities")) + 1)
            self.assertEqual(self.counts["cards"]["cards"], own)
        else:
            self.assertEqual(own, 0)

    def test_carson_card(self):
        import cards
        page = self.html["virginia/schools/rachel-carson-middle-school-herndon/"]
        self.assertIn('content="4 data centers within 1 mile of Rachel Carson Middle School. Herndon, Virginia. '
                      'On Virginia DEQ records: 2 planned, 2 operating."', page)
        if cards.available():
            self.assertIn(f'content="{self.cfg["site_url"]}/cards/virginia/schools/rachel-carson-middle-school-herndon.png"', page)

    def test_cards_are_small_palette_pngs(self):
        import cards
        if not cards.available():
            self.skipTest("Pillow not installed")
        files = [os.path.join(r, f) for r, _, fs in os.walk(os.path.join(self.dir, "cards")) for f in fs]
        self.assertEqual(len(files), self.counts["cards"]["cards"])
        sizes = [os.path.getsize(f) for f in files]
        self.assertLess(max(sizes), 30_000)  # about 15 KB each in Sept 2026
        self.assertLess(sum(sizes) / len(sizes), 20_000)
        for f in files[:25]:
            self.assertEqual(png_info(f), (1200, 630, 3), f)  # color type 3: palette


class Downloads(unittest.TestCase):
    """The CSV writer refuses files that don't match the JSON or that carry personal data."""

    def setUp(self):
        import tempfile
        import downloads
        self.d = downloads
        self.dir = tempfile.mkdtemp()
        self.fac = load("facilities")[:5]
        self.fil = load("filings")[:5]
        self.log = {"since": "2026-09-28", "events": [
            {"date": "2026-10-01", "type": "filing-new", "id": self.fil[0]["id"], "name": self.fil[0]["name"],
             "locality": "Loudoun County", "kind": "site-plan", "filing_type": "Site plan", "label": "Site plan in review"}]}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def test_writes_rows_with_sources(self):
        files = self.d.write(self.dir, "virginia", self.fac, self.log, self.fil)
        self.assertEqual({k: n for k, (_, n) in files.items()}, {"data-centers": 5, "changes": 1, "county-filings": 5})
        rows = self.d.read(os.path.join(self.dir, "virginia-changes.csv"))
        self.assertEqual(rows[1][2], "county-filing")
        self.assertEqual(rows[1][-1], self.fil[0]["source"])

    def test_refuses_personal_data(self):
        bad = [dict(self.fil[0], description="Call the planner at jane.doe@loudoun.gov")]
        with self.assertRaises(SystemExit):
            self.d.write(self.dir, "virginia", self.fac, self.log, bad)

    def test_refuses_a_row_count_mismatch(self):
        files = self.d.write(self.dir, "virginia", self.fac, self.log, self.fil)
        with self.assertRaises(SystemExit):
            self.d.check(self.dir, files, {"data-centers": 6, "changes": 1, "county-filings": 5})


class Cards(unittest.TestCase):
    """Link-preview images (pipeline/cards.py)."""

    def setUp(self):
        import cards
        self.cards = cards

    def test_committed_default_card(self):
        path = os.path.join(ROOT, "site", self.cards.DEFAULT_CARD)
        self.assertEqual(png_info(path), (1200, 630, 3))
        self.assertLess(os.path.getsize(path), 30_000)

    def test_card_paths(self):
        self.assertEqual(self.cards.card_file(""), "cards/home.png")
        self.assertEqual(self.cards.card_file("virginia/zip/20171/"), "cards/virginia/zip/20171.png")

    def test_link_and_instagram_cards(self):
        import tempfile
        if not self.cards.available():
            self.skipTest("Pillow not installed")
        d = tempfile.mkdtemp()
        link = self.cards.render("4 data centers within 1 mile of Rachel Carson Middle School",
                                 "Herndon, Virginia. On Virginia DEQ records: 2 planned, 2 operating.", footer="example.org")
        insta = self.cards.instagram_card("4 data centers within 1 mile of Rachel Carson Middle School",
                                          "Herndon, Virginia. On Virginia DEQ records: 2 planned, 2 operating.")
        self.assertEqual((link.size, insta.size), ((1200, 630), (1080, 1350)))
        for name, img, dims in (("link", link, (1200, 630)), ("insta", insta, (1080, 1350))):
            path = os.path.join(d, f"{name}.png")
            n = self.cards.save(img, path)
            self.assertEqual(png_info(path), dims + (3,))
            self.assertLess(n, 40_000)
            self.assertEqual(n, os.path.getsize(path))
        # images with other colors: adaptive palette
        self.assertGreater(self.cards.save(link, os.path.join(d, "adaptive.png"), colors=8), 0)

    def test_long_headlines_wrap_and_shrink_to_fit(self):
        if not self.cards.available():
            self.skipTest("Pillow not installed")
        c = self.cards
        long_name = ("2 data centers within 2 miles of Thomas Jefferson High School for Science and Technology "
                     "Regional Governor's School Academy of the Arts and Sciences Annex")
        size, lines, line_h = c.fit(long_name, c.FONT_BOLD, 1000, 260, 72, 38, 4)
        self.assertLess(size, 72)  # shrank
        self.assertLessEqual(len(lines), 4)
        self.assertLessEqual(len(lines) * line_h, 260)
        font = c._font(c.FONT_BOLD, size)
        for line in lines:
            self.assertLessEqual(font.getlength(line), 1000, line)
        # an unbreakable run of characters is split, never drawn past the edge
        for line in c.wrap("X" * 200, c._font(c.FONT_BOLD, 60), 1000):
            self.assertLessEqual(c._font(c.FONT_BOLD, 60).getlength(line), 1000)
        # far too much text: cut with an ellipsis at the smallest size
        size, lines, line_h = c.fit("word " * 400, c.FONT_BOLD, 1000, 260, 72, 38, 4)
        self.assertEqual(size, 38)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertLessEqual(len(lines) * line_h, 260)
        c.render(long_name * 3, long_name * 3, footer="example.org")  # draws without error

    def test_without_pillow_pages_use_the_default_card(self):
        import tempfile
        from unittest import mock
        import pages
        cfg = {"site_url": "https://example.org/x", "contact_url": "https://example.org/c"}
        d = tempfile.mkdtemp()
        with mock.patch.object(self.cards, "Image", None), mock.patch.dict(os.environ):
            os.environ.pop("CI", None)
            self.assertFalse(self.cards.available())
            self.cards.reset()
            page = pages.shell("virginia/zip/20171/", "t", "d", "<h1>x</h1>", cfg,
                               card={"headline": "3 data centers within 5 miles of ZIP code 20171"})
            self.assertIn('<meta property="og:image" content="https://example.org/x/card-default.png">', page)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">', page)
            stats = self.cards.render_queued(d)
            self.assertEqual((stats["cards"], stats["skipped"]), (0, 1))
            self.assertFalse(os.path.exists(os.path.join(d, "cards")))
            # in CI (GitHub sets CI=true), a missing Pillow stops the build instead
            os.environ["CI"] = "true"
            with self.assertRaises(SystemExit):
                self.cards.render_queued(d)

    def test_with_pillow_a_page_points_to_its_own_card(self):
        import tempfile
        import pages
        if not self.cards.available():
            self.skipTest("Pillow not installed")
        cfg = {"site_url": "https://example.org/x/", "contact_url": "https://example.org/c"}
        d = tempfile.mkdtemp()
        self.cards.reset()
        page = pages.shell("virginia/zip/20171/", "t", "d", "<h1>x</h1>", cfg,
                           card={"headline": "3 data centers within 5 miles of ZIP code 20171", "sub": "Stage & more"})
        self.assertIn('<meta property="og:image" content="https://example.org/x/cards/virginia/zip/20171.png">', page)
        self.assertIn('content="3 data centers within 5 miles of ZIP code 20171. Stage &amp; more"', page)
        stats = self.cards.render_queued(d)
        self.assertEqual(stats["cards"], 1)
        self.assertEqual(png_info(os.path.join(d, "cards", "virginia", "zip", "20171.png")), (1200, 630, 3))


def png_info(path):
    """(width, height, color type) from a PNG's header, without Pillow."""
    import struct
    with open(path, "rb") as fh:
        head = fh.read(26)
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path
    w, h = struct.unpack(">II", head[16:24])
    return w, h, head[25]


def html_escape(s):
    import html
    return html.escape(s)


if __name__ == "__main__":
    unittest.main()
