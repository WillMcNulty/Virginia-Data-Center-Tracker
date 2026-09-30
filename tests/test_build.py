"""Tests for the pipeline and the built data. Run: python -m unittest discover tests"""
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
        ids = {f["id"] for f in load("facilities")}
        for ev in log["events"]:
            self.assertIn(ev["type"], {"new", "stage", "permit", "renamed", "removed"})
            if ev["type"] != "removed":
                self.assertIn(ev["id"], ids)


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
                                       load("meta"), load("changes"), cfg)
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

    def test_support_link_hidden_until_configured(self):
        if not self.cfg.get("support_url"):
            self.assertNotIn(self.cfg["support_label"], self.html["about/"])


def html_escape(s):
    import html
    return html.escape(s)


if __name__ == "__main__":
    unittest.main()
