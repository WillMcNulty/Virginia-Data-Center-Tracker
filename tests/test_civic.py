"""Tests for the civic layer (pipeline/civic.py and the meetings pages). Run: python -m unittest discover tests

Fixtures in tests/fixtures/civic/ are real Granicus pages saved on 2026-09-30, trimmed to a few items, with county
staff names replaced by placeholders (Alex Sample, Morgan Example, ...) so the repository carries no staff names.
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.robotparser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import civic  # noqa: E402
import pages  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "civic")
TODAY = dt.date(2026, 9, 30)
PLACEHOLDER_STAFF = ["Alex Sample", "Sam Example", "Jordan Placeholder", "Casey Fixture", "Riley Sample",
                     "Morgan Example", "Taylor Placeholder", "Jamie Fixture", "Drew Sample"]


def fixture(name, mode="r"):
    with open(os.path.join(FIX, name), mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        return fh.read()


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class FixtureFetcher:
    """Serves the saved fixtures as if they were the counties' pages; anything else is 'not available'."""
    FILES = {("fairfax-county", "feed.xml"): "fairfax_feed.xml",
             ("loudoun-county", "feed.xml"): "loudoun_feed.xml",
             ("loudoun-county", "clip-8247.html"): "loudoun_pc_work_session_2026-09-17.html",
             ("loudoun-county", "clip-8252.html"): "loudoun_pc_hearing_2026-09-22.html",
             ("prince-william-county", "feed.xml"): "pwc_feed.xml",
             ("prince-william-county", "event-3464.html"): "pwc_agenda_2026-10-06.html"}

    def __init__(self, broken=()):
        self.broken, self.calls = set(broken), []

    def __call__(self, county, name, url):
        self.calls.append((county["slug"], name))
        if county["slug"] in self.broken:
            raise civic.Skip("server returned an error page")
        f = self.FILES.get((county["slug"], name))
        if not f:
            raise civic.Skip(f"no saved copy of {url}")
        return fixture(f, "rb")


class Feed(unittest.TestCase):
    def test_fairfax_feed_drops_spanish_caption_copies_and_the_leading_date(self):
        ms = civic.parse_rss(fixture("fairfax_feed.xml", "rb"))
        self.assertEqual([(m["date"], m["name"]) for m in ms],
                         [("2026-09-29", "Board of Supervisors Meeting"), ("2026-09-15", "Board of Supervisors Meeting")])
        self.assertEqual(ms[0]["id"], "clip-4260")

    def test_prince_william_upcoming_meeting(self):
        ms = civic.parse_rss(fixture("pwc_feed.xml", "rb"))
        first = ms[0]
        self.assertEqual((first["id"], first["date"], first["name"], first["published"]),
                         ("event-3464", "2026-10-06", "Board of County Supervisors Meeting", True))
        self.assertTrue(all(not m["published"] for m in ms[1:]))  # the rest are archived
        # the meeting date comes from the title, not the feed's publication date (Sep 25 for the Sep 23 meeting)
        self.assertIn(("clip-3914", "2026-09-23"), [(m["id"], m["date"]) for m in ms])

    def test_date_falls_back_to_granicus_date_parts(self):
        xml = b"""<?xml version="1.0"?><rss version="2.0" xmlns:gran="https://www.granicus.com/schema/rss-supplements">
          <channel><item><title>Special Meeting</title><gran:pubDateParts yr='2026' mo='10' day='14' />
          <link>https://example.granicus.com/AgendaViewer.php?view_id=1&amp;event_id=9</link>
          <description>has been published</description></item></channel></rss>"""
        self.assertEqual(civic.parse_rss(xml), [{"id": "event-9", "date": "2026-10-14", "name": "Special Meeting",
                                                  "link": "https://example.granicus.com/AgendaViewer.php?view_id=1&event_id=9",
                                                  "published": True}])


class Agenda(unittest.TestCase):
    def test_prince_william_items_sections_and_no_staff_names(self):
        items = civic.agenda_items(fixture("pwc_agenda_2026-10-06.html"))
        by_num = {i["number"]: i for i in items}
        self.assertEqual(list(by_num), ["6.", "6.C.", "6.G.", "7.", "7.C.", "7.D.", "11.", "11.B."])
        self.assertEqual(by_num["7.D."]["section"], "Consent Agenda")
        self.assertEqual(by_num["7.D."]["text"],
                         "RES - Authorize the Execution of an Agreement for Iron Mountain Data Centers Virginia 6, LLC, "
                         "for the Maintenance of Sidewalks, Curb and Gutter, and Access Road in State-Maintained "
                         "Right-of-Way - Brentsville Magisterial District")
        text = " ".join(i["text"] for i in items)
        for name in PLACEHOLDER_STAFF:  # presenters ("Name, Department" and "Name / Name, Department") are dropped
            self.assertNotIn(name, text)
        self.assertNotIn("Mobility, Economic Growth", text)  # the italic strategic-plan goal is dropped
        self.assertIn("Chair Jefferson", by_num["6.G."]["text"])  # the elected sponsor stays
        self.assertTrue(by_num["6.C."]["text"].endswith("as Pedestrian Safety Month"))
        self.assertNotIn("Item 7-D", text)  # attachment links aren't items

    def test_loudoun_items_drop_project_managers_and_attachments(self):
        items = civic.agenda_items(fixture("loudoun_pc_hearing_2026-09-22.html"))
        self.assertEqual([i["number"] for i in items], ["I.", "VI.", "1.", "2.", "3.", "4.", "5.", "6.", "VIII."])
        five = items[6]
        self.assertEqual(five["section"], "Public Hearing Items")
        self.assertEqual(five["text"], "LEGI-2025-0053, Dulles North Technology Park: ZMAP-2024-0017, CMPT-2025-0009, "
                                       "SPEX-2025-0101, & SPEX-2025-0102 (Sterling)")
        text = " ".join(i["text"] for i in items)
        self.assertNotIn("Project Manager", text)
        for name in PLACEHOLDER_STAFF:
            self.assertNotIn(name, text)
        self.assertNotIn("Staff Presentation", text)

    def test_matching_finds_data_center_items_only(self):
        pwc = civic.match_items(civic.agenda_items(fixture("pwc_agenda_2026-10-06.html")))
        self.assertEqual([i["number"] for i in pwc], ["7.D."])
        ws = civic.match_items(civic.agenda_items(fixture("loudoun_pc_work_session_2026-09-17.html")))
        self.assertEqual([(i["section"], i["text"]) for i in ws], [("Administrative Items", "Data Center Open Houses")])
        # a technology park and a logistics center are not "data center" items unless a case number says so
        hearing = civic.agenda_items(fixture("loudoun_pc_hearing_2026-09-22.html"))
        self.assertEqual(civic.match_items(hearing), [])
        by_case = civic.match_items(hearing, frozenset({"ZMAP-2024-0017"}))
        self.assertEqual([i["number"] for i in by_case], ["5."])
        self.assertIn("ZMAP-2024-0017 is a data center filing", by_case[0]["why"])

    def test_data_center_wording(self):
        for yes in ["Data Center Opportunity Zone", "data centers", "Data-Center Uses", "DATACENTER", "data centre"]:
            self.assertTrue(civic.DC_RE.search(yes), yes)
        for no in ["Update Center", "metadata centers", "Data Collection Center", "data, center of town", "Datacentric"]:
            self.assertFalse(civic.DC_RE.search(no), no)


class County(unittest.TestCase):
    def test_read_county_keeps_the_window_and_marks_what_was_searched(self):
        pwc = civic.BY_LOCALITY["Prince William County"]
        block = civic.read_county(pwc, FixtureFetcher(), TODAY)
        self.assertEqual(block["checked"], "2026-09-30")
        # upcoming Oct 6, plus Sep 9-23 (21 days back); Sep 1 and July are outside the window
        self.assertEqual([m["id"] for m in block["meetings"]],
                         ["clip-3903", "clip-3906", "clip-3911", "clip-3914", "event-3464"])
        oct6 = block["meetings"][-1]
        self.assertTrue(oct6["searched"])
        self.assertEqual([i["number"] for i in oct6["items"]], ["7.D."])
        # agendas we couldn't read are "not searched", never "no data center items"
        sep22 = block["meetings"][2]
        self.assertFalse(sep22["searched"])
        self.assertIn("couldn't read", sep22["note"])

    def test_fairfax_agendas_are_listed_but_not_fetched(self):
        f = FixtureFetcher()
        block = civic.read_county(civic.BY_LOCALITY["Fairfax County"], f, TODAY)
        self.assertEqual(f.calls, [("fairfax-county", "feed.xml")])
        self.assertTrue(all(not m["searched"] and "PDF" in m["note"] for m in block["meetings"]))
        self.assertEqual(len(block["meetings"]), 2)

    def test_limit_on_agendas_per_county(self):
        old = civic.MAX_AGENDAS
        civic.MAX_AGENDAS = 2
        try:
            block = civic.read_county(civic.BY_LOCALITY["Prince William County"], FixtureFetcher(), TODAY)
        finally:
            civic.MAX_AGENDAS = old
        self.assertEqual(sum(1 for m in block["meetings"] if "limit" in (m.get("note") or "")), 3)


class Failures(unittest.TestCase):
    """Civic data is optional: a county that fails keeps its last good data, and nothing takes the build down."""

    def prev(self):
        return {"counties": {"Loudoun County": {"checked": "2026-09-01", "feed": "https://x", "meetings": []}}}

    def test_a_failing_county_keeps_its_last_good_data(self):
        data = civic.update(self.prev(), FixtureFetcher(broken={"loudoun-county"}), TODAY)
        self.assertEqual(data["counties"]["Loudoun County"]["checked"], "2026-09-01")
        self.assertEqual(data["counties"]["Prince William County"]["checked"], "2026-09-30")

    def test_broken_or_empty_feed_is_skipped(self):
        for body in [b"<html><body>Service unavailable</body></html>", b"<rss><channel></channel></rss>", b"not xml <"]:
            data = civic.update(self.prev(), lambda c, n, u, body=body: body, TODAY,
                                counties=[civic.BY_LOCALITY["Loudoun County"]])
            self.assertEqual(data["counties"]["Loudoun County"]["checked"], "2026-09-01", body)

    def test_robots_txt_is_obeyed(self):
        f = civic.LiveFetcher(tempfile.mkdtemp())
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(["User-agent: Googlebot", "Disallow: /JSON.php", "User-agent: *", "Disallow: /"])
        f.robots["https://loudoun.granicus.com"] = rp  # what the host answered in September 2026
        f._get = lambda url: self.fail(f"fetched {url} despite robots.txt")
        with self.assertRaises(civic.Skip) as cm:
            f(civic.BY_LOCALITY["Loudoun County"], "feed.xml", civic.feed_url(civic.BY_LOCALITY["Loudoun County"]))
        self.assertIn("robots.txt", str(cm.exception))
        # ...and a robots refusal while reading an agenda skips the whole county rather than listing it as empty
        with self.assertRaises(civic.Skip):
            def fetch(county, name, url):
                if name == "feed.xml":
                    return fixture("loudoun_feed.xml", "rb")
                raise civic.Skip("robots.txt on loudoun.granicus.com asks automated clients not to fetch it")
            civic.read_county(civic.BY_LOCALITY["Loudoun County"], fetch, TODAY)

    def test_too_many_matches_means_a_layout_change(self):
        html = "".join(f"<div>{n}.</div><div>Data center item {n}</div>" for n in range(1, 30))

        def fetch(county, name, url):
            return fixture("loudoun_feed.xml", "rb") if name == "feed.xml" else html.encode()
        with self.assertRaises(civic.Skip):
            civic.read_county(civic.BY_LOCALITY["Loudoun County"], fetch, TODAY)

    def test_check_refuses_staff_contacts_and_bad_dates(self):
        def data(text, date="2026-10-06"):
            return {"counties": {"Loudoun County": {"checked": "2026-09-30", "feed": "https://x", "meetings": [
                {"date": date, "name": "m", "agenda_url": "https://x", "items": [{"text": text, "number": "1."}]}]}}}
        civic.check(data("Data Center Open Houses"))
        for bad in [data("Data center rezoning Project Manager: Someone"), data("Contact someone@loudoun.gov"),
                    data("Data center", date="Oct 6")]:
            with self.assertRaises(ValueError):
                civic.check(bad)

    def test_refresh_never_raises_and_keeps_the_file(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "meetings.json")
        good = {"window_days_back": 21, "counties": self.prev()["counties"]}
        civic.write(out, good)
        before = _text(out)
        civic.refresh(out, os.path.join(d, "no-cache"), offline=True, today=TODAY)  # nothing saved: all skipped
        self.assertEqual(_text(out), before)
        civic.refresh(os.path.join(d, "missing", "meetings.json"), d, offline=True, today=TODAY)  # no previous file
        shutil.rmtree(d)

    def test_known_cases_from_filings(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "filings.json")
        with open(path, "w") as fh:
            json.dump([{"id": "LEGI-2023-0012", "related": ["Rezoning ZMAP-2023-0005", "Special exception SPEX-2023-0101"]},
                       {"id": "not a case"}], fh)
        self.assertEqual(civic.known_cases(path), {"LEGI-2023-0012", "ZMAP-2023-0005", "SPEX-2023-0101"})
        self.assertEqual(civic.known_cases(os.path.join(d, "none.json")), frozenset())
        shutil.rmtree(d)


class CommittedData(unittest.TestCase):
    def test_meetings_json_passes_the_check(self):
        path = os.path.join(ROOT, "site", "virginia", "data", "meetings.json")
        data = civic._read_json(path)
        civic.check(data)
        self.assertTrue(set(data["counties"]) <= set(civic.BY_LOCALITY))

    def test_participation_facts_are_sourced_dated_and_impersonal(self):
        data = civic._read_json(civic.PARTICIPATION)
        official = ("https://www.fairfaxcounty.gov/", "https://www.loudoun.gov/", "https://www.pwcva.gov/")
        for loc in civic.BY_LOCALITY:
            self.assertIn(loc, data)
            self.assertTrue(data[loc]["facts"], loc)
            for f in data[loc]["facts"]:
                self.assertTrue(f["source"].startswith(official), f["source"])
                self.assertRegex(f["checked"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertIsNone(civic.EMAIL_RE.search(f["text"]), f["text"])
            for link in data[loc].get("links", []):
                self.assertTrue(link["url"].startswith("https://"), link)


class MeetingsPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        meetings = civic.update({"counties": {}}, FixtureFetcher(), TODAY)
        participation = civic._read_json(civic.PARTICIPATION)
        cfg = civic._read_json(os.path.join(ROOT, "data", "site_config.json"))
        cls.ctx = {"out": cls.dir, "state": "virginia", "cfg": cfg, "urls": [], "today": TODAY,
                   "civic": {"meetings": meetings, "participation": participation}}
        pages.meetings_page(cls.ctx)
        cls.page = _text(os.path.join(cls.dir, "virginia", "meetings", "index.html"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_meetings_page(self):
        p = self.page
        self.assertEqual(p.count("<h1>"), 1)
        self.assertIn("<b>1 item</b>", p)  # one data center item on upcoming agendas (Prince William, Oct 6)
        self.assertIn("Iron Mountain Data Centers Virginia 6, LLC", p)
        self.assertIn("Data Center Open Houses", p)  # Loudoun, Sep 17: in the past three weeks
        self.assertIn('href="https://pwcgov.granicus.com/AgendaViewer.php?view_id=23&amp;event_id=3464">Official agenda', p)
        self.assertIn("confirm there", p)
        self.assertIn("Fairfax posts its Board agendas as a PDF", p)
        self.assertIn("Agendas last checked Sep 30, 2026", p)
        for name in PLACEHOLDER_STAFF:
            self.assertNotIn(name, p)
        self.assertEqual(self.ctx["urls"], ["virginia/meetings/"])  # so it lands in the sitemap

    def test_how_to_take_part_is_sourced(self):
        for loc in civic.BY_LOCALITY:
            self.assertIn(f"How to take part in {loc}", self.page)
        self.assertIn('href="https://www.fairfaxcounty.gov/clerkservices/ways-provide-public-hearing-testimony">source</a>, checked Sep 30, 2026',
                      self.page)

    def test_old_data_says_so(self):
        ctx = dict(self.ctx, today=TODAY + dt.timedelta(days=30), urls=[])
        section = pages.civic_section(ctx, "Loudoun County", "../../../")
        self.assertIn("That was 30 days ago", section)
        self.assertIn("<b>0</b> on upcoming agendas, 0 in the past 3 weeks", section)

    def test_county_page_section(self):
        section = pages.civic_section(self.ctx, "Prince William County", "../../../")
        self.assertIn("<h2>Public meetings</h2>", section)
        self.assertIn("<b>1</b> on upcoming agendas, 0 in the past 3 weeks", section)
        self.assertIn('href="../../../virginia/meetings/#prince-william-county"', section)
        self.assertEqual(pages.civic_section(self.ctx, "Henrico County", "../../../"), "")


if __name__ == "__main__":
    unittest.main()
