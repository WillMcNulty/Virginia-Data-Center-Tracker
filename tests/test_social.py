"""Tests for the social drafts generator (pipeline/social.py). Run: python -m unittest discover tests"""
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import socket
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import cards  # noqa: E402
import geo  # noqa: E402
import social  # noqa: E402

DATA = os.path.join(ROOT, "site", "virginia", "data")
END = dt.date(2026, 10, 7)  # a fixed "today" for the synthetic weeks below


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def png_info(path):
    with open(path, "rb") as fh:
        head = fh.read(26)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def synthetic_log(facilities, end=END):
    """A busy week built from real facilities (the longest names, to stress the length limits), plus one event
    from the week before, which must be left out."""
    longest = sorted(facilities, key=lambda f: -len(f["name"]))
    evs = []
    kinds = ["new", "stage", "permit", "stage", "new", "permit", "removed", "renamed", "stage", "new", "permit"]
    for i, (kind, f) in enumerate(zip(kinds, longest)):
        ev = {"date": (end - dt.timedelta(days=i % 7)).isoformat(), "type": kind, "id": f["id"], "name": f["name"],
              "locality": f["locality"], "stage": f["stage"]}
        if kind == "stage":
            ev.update({"from": "planned", "to": "construction"})
        if kind == "permit":
            ev.update({"from": None, "to": (end - dt.timedelta(days=3)).isoformat()})
        if kind == "renamed":
            ev.update({"from": "An earlier name", "to": f["name"]})
        evs.append(ev)
    old = dict(evs[0], date=(end - dt.timedelta(days=7)).isoformat(), type="new", id=longest[20]["id"],
               name=longest[20]["name"])
    return {"since": "2026-09-28", "events": evs + [old]}


def all_text(d):
    slides = [f"{s['kicker']} {s['headline']} {s['sub']} {s['footer']}" for s in d["slides"]]
    return [d["facebook"], d["caption"], *d["bluesky"], *slides]


class SocialDrafts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = social.load_inputs()
        cls.facilities, cls.schools = cls.inputs["facilities"], cls.inputs["schools"]
        cls.cfg = cls.inputs["cfg"]
        cls.base = cls.cfg["site_url"].rstrip("/")
        busy = dict(cls.inputs, changes=synthetic_log(cls.facilities))
        empty = dict(cls.inputs, changes={"since": "2026-09-28", "events": []})
        cls.weekly = social.build_drafts(busy, END)
        cls.evergreen = social.build_drafts(empty, END)
        log = cls.inputs["changes"]
        latest = max((dt.date.fromisoformat(e["date"]) for e in log["events"]), default=END)
        cls.committed = social.build_drafts(cls.inputs, latest)  # whatever the committed log has
        # schools with a data center within 1 and 2 miles, counted here independently of social.py
        cls.n1 = cls.n2 = 0
        for sc in cls.schools:
            d = min(geo.miles(sc["lat"], sc["lon"], f["lat"], f["lon"]) for f in cls.facilities)
            cls.n2 += d <= 2
            cls.n1 += d <= 1

    def drafts(self):
        return (self.weekly, self.evergreen, self.committed)

    # ---- the week's changes, and the fallback ----

    def test_week_is_the_last_seven_days(self):
        evs = self.weekly["events"]
        self.assertEqual(self.weekly["kind"], "weekly")
        self.assertEqual(len(evs), 11)  # the event from 7 days earlier is left out
        self.assertTrue(all(END - dt.timedelta(days=6) <= dt.date.fromisoformat(e["date"]) <= END for e in evs))
        self.assertEqual(self.weekly["week"], "Oct 1 to Oct 7, 2026")

    def test_empty_week_gives_the_evergreen_school_post(self):
        d = self.evergreen
        self.assertEqual((d["kind"], d["events"]), ("evergreen", []))
        self.assertIn("near your school", d["facebook"])
        self.assertIn("Look up your school", [s["headline"] for s in d["slides"]])
        with tempfile.TemporaryDirectory() as tmp:  # an empty (or brand-new) change log still writes every file
            data = os.path.join(tmp, "data")
            shutil.copytree(DATA, data)
            with open(os.path.join(data, "changes.json"), "w", encoding="utf-8") as fh:
                json.dump({"since": "2026-10-07", "events": []}, fh)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                out = social.main(["--date", "2026-10-07", "--out", tmp, "--data", data])
            self.assertEqual(out, os.path.join(tmp, "2026-10-07"))
            for f in ("README.md", "facebook.txt", "bluesky.txt", "instagram-caption.txt", "instagram-slides.txt"):
                self.assertTrue(os.path.getsize(os.path.join(out, f)) > 0, f)
            self.assertIn("evergreen", read(os.path.join(out, "README.md")))

    # ---- limits ----

    def test_bluesky_posts_fit_in_300_characters_counting_the_link(self):
        for d in self.drafts():
            for post in d["bluesky"]:
                self.assertLessEqual(len(post), 300, post)
                self.assertIn("https://", post)
        self.assertEqual(len(self.weekly["bluesky"]), 1 + social.MAX_THREAD_REPLIES + 1)  # post, replies, "more"
        with self.assertRaises(ValueError):
            social.first_fitting(["x" * 301])

    def test_instagram_caption_and_slide_count(self):
        for d in self.drafts():
            self.assertLessEqual(len(d["caption"]), social.INSTAGRAM_CAPTION_LIMIT)
            self.assertLessEqual(len(d["slides"]), 20)
        # busy week: cover, 7 changes, "4 more changes", statewide, look-up
        self.assertEqual(len(self.weekly["slides"]), 1 + social.MAX_EVENT_SLIDES + 2)
        self.assertEqual(self.weekly["slides"][social.MAX_EVENT_SLIDES]["headline"], "4 more changes this week")

    # ---- sources, links, wording ----

    def test_every_post_links_to_the_site_and_names_the_source(self):
        for d in self.drafts():
            for text in (d["facebook"], d["caption"], d["bluesky"][0]):
                self.assertIn(self.base + "/virginia/", text)
                self.assertIn("Virginia DEQ", text)
            for reply in d["bluesky"][1:]:
                self.assertIn(self.base + "/virginia/", reply)

    def test_links_follow_the_page_conventions(self):
        import pages
        by_id = {f["id"]: f for f in self.facilities}
        for ev in self.weekly["events"]:
            if ev["type"] != "removed":
                self.assertIn(f"{self.base}/{pages.facility_path('virginia', by_id[ev['id']])}", self.weekly["facebook"])
        # school page addresses match the ones pages.py generates (built here into a temporary folder)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = {"out": tmp, "state": "virginia", "facilities": self.facilities, "schools": self.schools,
                   "cfg": self.cfg, "urls": [], "meta": self.inputs["meta"], "zips": {}}
            pages.school_pages(ctx)
            cards.reset()
        mine = {r["school"]["id"]: r["path"] for r in social.school_numbers(self.facilities, self.schools)}
        self.assertEqual(mine, ctx["school_path"])
        for url in re.findall(r"https://\S+", self.evergreen["facebook"]):
            path = url[len(self.base) + 1:].rstrip(").,")
            self.assertTrue(path in ("virginia/", "virginia/browse/") or path in ctx["school_path"].values(), url)

    def test_neutral_wording_and_hashtags(self):
        taking_sides = re.compile(r"\b(oppose|opposition|support|stop|ban|fight|protest|say no|keep out|"
                                  r"protect|threat|danger|alarming|shocking|urgent|act now|contact your|vote|"
                                  r"sign the|petition)\b", re.I)
        for d in self.drafts():
            for text in all_text(d):
                self.assertIsNone(taking_sides.search(text), text)
                for tag in re.findall(r"#\w+", text):
                    self.assertTrue(tag in ("#Virginia", "#DataCenters") or
                                    any(tag == "#" + f["locality"].replace(" ", "") for f in self.facilities), tag)

    # ---- numbers ----

    def test_school_numbers_match_the_data(self):
        text = self.evergreen["facebook"]
        self.assertIn(f"{self.n2:,} of Virginia's {len(self.schools):,} public schools have a data center within 2 miles",
                      text)
        self.assertIn(f"{self.n1:,} have one within 1 mile", text)
        self.assertEqual(self.inputs["meta"]["schools"], len(self.schools))
        ex = next(s for s in self.evergreen["slides"] if s["kicker"].endswith("Example"))
        name = ex["headline"].split(" within 1 mile of ", 1)[1]
        sc = next(s for s in self.schools if (s["aka"][0] if s.get("aka") else s["name"]) == name
                  and ex["sub"].startswith(s["city"] + ","))
        d = [geo.miles(sc["lat"], sc["lon"], f["lat"], f["lon"]) for f in self.facilities]
        n = sum(x <= 1 for x in d)
        self.assertTrue(ex["headline"].startswith(f"{n} data center"))
        self.assertIn(f"{sum(x <= 2 for x in d)} data center", ex["sub"])

    def test_statewide_numbers_match_the_data(self):
        stages = {}
        for f in self.facilities:
            stages[f["stage"]] = stages.get(f["stage"], 0) + 1
        meta = self.inputs["meta"]
        self.assertEqual(meta["facilities"], len(self.facilities))
        self.assertEqual({k: v for k, v in meta["stages"].items() if v}, stages)
        slide = next(s for d in self.drafts() for s in d["slides"] if "data centers on Virginia DEQ" in s["headline"])
        self.assertEqual(slide["headline"], f"{len(self.facilities)} data centers on Virginia DEQ's records")
        for stage, n in stages.items():
            self.assertIn(f"{n} {social.STAGE_LABEL[stage].lower()}", slide["sub"])

    def test_change_counts_match_the_log(self):
        self.assertIn("3 new sites, 3 stage changes, 3 new air permits, 1 site no longer listed, 1 rename",
                      self.weekly["facebook"])
        for d in (self.weekly, self.committed):
            for ev in d["events"]:
                self.assertIn(ev["name"], d["facebook"])

    def test_every_number_comes_from_the_data(self):
        """Any number in any draft is a count computed here, a date, a facility name's own digits, or one of the
        fixed distances the site uses (1, 2, 30 miles)."""
        stages = {}
        for f in self.facilities:
            stages[f["stage"]] = stages.get(f["stage"], 0) + 1
        allowed = {1, 2, 30, len(self.facilities), len(self.schools), self.n1, self.n2, *stages.values()}
        for d in self.drafts():
            for ev in d["events"]:
                day = dt.date.fromisoformat(ev["date"])
                allowed |= {day.day, day.year}
                allowed |= {int(x) for x in re.findall(r"\d+", ev["name"] + str(ev.get("from")) + str(ev.get("to")))}
            for evs_type in ("new", "stage", "permit", "removed", "renamed"):
                allowed.add(sum(1 for ev in d["events"] if ev["type"] == evs_type))
            end = dt.date.fromisoformat(d["end"])
            start = end - dt.timedelta(days=6)
            allowed |= {start.day, end.day, start.year, end.year, len(d["events"]) - len(d["slides"]) + 4,
                        len(d["events"]) - social.MAX_THREAD_REPLIES, len(d["events"]) - social.MAX_EVENT_SLIDES + 1}
            built = dt.date.fromisoformat(self.inputs["meta"]["built_at"][:10])
            allowed |= {built.day, built.year}
            ex = next((s for s in d["slides"] if s["kicker"].endswith("Example")), None)
            if ex:
                allowed |= {int(x) for x in re.findall(r"\d+", ex["headline"] + ex["sub"])}  # checked above
            for text in all_text(d):
                text = re.sub(r"https?://\S+|\S+\.github\.io\S*", "", text)
                for num in re.findall(r"(?<![\w.])\d[\d,]*", text):
                    self.assertIn(int(num.replace(",", "")), allowed, f"{num!r} in {text!r}")

    # ---- output, safety ----

    def test_writes_the_folder_with_1080x1350_slides(self):
        if not cards.available():
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "2026-10-07")
            with contextlib.redirect_stderr(io.StringIO()):
                files, drawn = social.write_drafts(self.weekly, out)
            self.assertTrue(drawn)
            pngs = sorted(f for f in os.listdir(out) if f.endswith(".png"))
            self.assertEqual(len(pngs), len(self.weekly["slides"]))
            self.assertEqual(sorted(f for f in files if f.endswith(".png")), pngs)
            for f in pngs:
                self.assertEqual(png_info(os.path.join(out, f)), (1080, 1350), f)
            readme = read(os.path.join(out, "README.md"))
            self.assertIn("Verify each number against the linked page before posting", readme)
            for f in files:
                if not f.endswith(".png"):
                    self.assertIn(f, readme + "README.md")
            bluesky = read(os.path.join(out, "bluesky.txt"))
            posts = re.split(r"=== Post \d+ of \d+[^\n]*===\n", bluesky)[1:]
            self.assertEqual([p.strip() for p in posts], [p.strip() for p in self.weekly["bluesky"]])

    def test_without_pillow_the_text_drafts_are_still_written(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cards, "Image", None):
            self.assertFalse(cards.available())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                files, drawn = social.write_drafts(self.evergreen, tmp)
            self.assertFalse(drawn)
            self.assertIn("Pillow is not installed", err.getvalue())
            self.assertEqual(sorted(files), sorted(os.listdir(tmp)))
            self.assertFalse([f for f in os.listdir(tmp) if f.endswith(".png")])
            self.assertIn("not drawn, because Pillow is not installed",
                          read(os.path.join(tmp, "README.md")))
            self.assertIn("Look up your school", read(os.path.join(tmp, "instagram-slides.txt")))

    def test_never_posts_and_makes_no_network_calls(self):
        src = read(os.path.join(ROOT, "pipeline", "social.py"))
        for mod in ("urllib", "http", "socket", "requests", "smtplib", "ssl", "subprocess", "webbrowser"):
            self.assertIsNone(re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), mod)

        def refuse(*a, **k):
            raise AssertionError("social.py tried to use the network")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(socket, "socket", refuse), mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            social.main(["--date", END.isoformat(), "--out", tmp])
            self.assertIn("Nothing was posted", out.getvalue())


if __name__ == "__main__":
    unittest.main()
