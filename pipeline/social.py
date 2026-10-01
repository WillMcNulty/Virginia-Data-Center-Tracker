"""Social drafts: this week's Facebook, Bluesky and Instagram posts, drafted for the owner to check and post by hand.

    python pipeline/social.py                     # drafts for the 7 days ending today
    python pipeline/social.py --date 2026-10-07   # ... ending on another day
    python pipeline/social.py --out some/folder   # somewhere other than drafts/social/

Reads only the committed data (site/virginia/data/changes.json, facilities.json, schools.json, meta.json) and
data/site_config.json, and writes drafts/social/<YYYY-MM-DD>/ (generated, gitignored):

  README.md              what's in the folder, every number with the page to check it on, and a checklist
  facebook.txt           one post
  bluesky.txt            a post, or a short thread; each post fits Bluesky's 300 characters, links included
  instagram-caption.txt  the carousel's caption
  instagram-slides.txt   each slide's text and alt text
  instagram-NN.png       the slides, 1080x1350, drawn with cards.instagram_card() (needs Pillow; without it the
                         text drafts are still written and the README says the images weren't drawn)

When the change log has something from the last 7 days (new sites, stage changes, new air permits, and the rarer
renames and removals), the drafts report it. When it doesn't, they fall back to an evergreen "look up your school"
post with the current school numbers.

Rules the drafts follow (see CLAUDE.md): every number is computed from the data files; every post links to the
page on the site where it can be checked and names the source (Virginia DEQ records); the wording is neutral and
procedural (no calls to support or oppose anything, no hashtags that take sides); no personal names (sites are
called by DEQ's facility name, as on the site). This script never posts anything and makes no network calls.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cards  # noqa: E402
import geo  # noqa: E402
from pages import (SCHOOL_RADIUS, STAGE_LABEL, facility_path, fmt_date, plural, school_display, slug,  # noqa: E402
                   stage_summary)

STATE, STATE_NAME = "virginia", "Virginia"
DATA = os.path.join(ROOT, "site", STATE, "data")
CONFIG = os.path.join(ROOT, "data", "site_config.json")
OUT = os.path.join(ROOT, "drafts", "social")
BLUESKY_LIMIT = 300        # characters (graphemes) per post, links included
INSTAGRAM_CAPTION_LIMIT = 2200
MAX_EVENT_SLIDES = 8       # Instagram allows 20 slides; past this, one slide sends people to "New this week"
MAX_THREAD_REPLIES = 8
SOURCE = "Virginia DEQ records"
HOW = ("Open the map, type your school's name, ZIP code or pick a spot, and choose a distance from 1 to 30 miles. "
       "Every data center links to the DEQ record it came from.")
ORDER = {"new": 0, "stage": 1, "permit": 2, "removed": 3, "renamed": 4}
KIND = {"new": "New site", "stage": "Stage change", "permit": "New air permit", "removed": "No longer listed",
        "renamed": "Renamed"}
COUNT_WORD = {"new": ("new site", "new sites"), "stage": ("stage change", "stage changes"),
              "permit": ("new air permit", "new air permits"), "removed": ("site no longer listed", "sites no longer listed"),
              "renamed": ("rename", "renames")}


def load_inputs(data_dir=DATA, config=CONFIG):
    def rd(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return {"changes": rd(os.path.join(data_dir, "changes.json")), "facilities": rd(os.path.join(data_dir, "facilities.json")),
            "schools": rd(os.path.join(data_dir, "schools.json")), "meta": rd(os.path.join(data_dir, "meta.json")),
            "cfg": rd(config)}


# ---- numbers from the data -------------------------------------------------------------------------------------------

def week_events(log, end):
    """Change-log events dated in the 7 days ending on `end` (a date), most important kind first."""
    start = end - dt.timedelta(days=6)
    evs = [ev for ev in log.get("events", []) if start <= dt.date.fromisoformat(ev["date"]) <= end]
    return sorted(evs, key=lambda ev: (ORDER.get(ev["type"], 9), ev["date"], ev["name"]))


def school_numbers(facilities, schools, state=STATE):
    """For every school with a data center within SCHOOL_RADIUS miles: its page path (the same rule as
    pages.school_pages) and how many data centers are within 1 and 2 miles. Returns a list in schools.json order."""
    out, seen = [], {}
    for sc in schools:
        d = [geo.miles(sc["lat"], sc["lon"], f["lat"], f["lon"]) for f in facilities]
        within2 = sum(1 for x in d if x <= SCHOOL_RADIUS)
        if not within2:
            continue
        base = slug(f"{school_display(sc)} {sc['city']}")
        seen[base] = seen.get(base, 0) + 1
        path = f"{state}/schools/{base}{'' if seen[base] == 1 else '-' + sc['id'][-4:]}/"
        out.append({"school": sc, "path": path, "within1": sum(1 for x in d if x <= 1), "within2": within2})
    return out


def pick_school(rows, end):
    """The week's example school: rotates by ISO week through the schools with a data center within 1 mile (most
    first), so the example changes from week to week without anyone choosing it."""
    near = sorted((r for r in rows if r["within1"]), key=lambda r: (-r["within1"], school_display(r["school"])))
    return near[end.isocalendar()[1] % len(near)] if near else None


# ---- text helpers ------------------------------------------------------------------------------------------------------

def chars(text):
    """Characters as Bluesky counts them (graphemes). Code points are never fewer than graphemes, so this is safe."""
    return len(text)


def first_fitting(candidates, limit=BLUESKY_LIMIT):
    for c in candidates:
        if chars(c) <= limit:
            return c
    raise ValueError(f"no Bluesky draft fits in {limit} characters: {candidates[-1]!r}")


def date_range(end):
    start = end - dt.timedelta(days=6)
    first = fmt_date(start.isoformat())
    if start.year == end.year:
        first = first.rsplit(",", 1)[0]  # "Sep 24 to Sep 30, 2026"
    return f"{first} to {fmt_date(end.isoformat())}"


def stage(s):
    return STAGE_LABEL.get(s, s or "not given").lower()


def event_sentence(ev):
    """One neutral sentence about a change, without the site's name."""
    t = ev["type"]
    if t == "new":
        return f"New on Virginia DEQ's data center records, listed as {stage(ev.get('stage'))}."
    if t == "stage":
        return f"Stage on Virginia DEQ's records changed from {stage(ev.get('from'))} to {stage(ev.get('to'))}."
    if t == "permit":
        return f"Virginia DEQ issued an air permit dated {fmt_date(ev.get('to')) or 'without a date'}."
    if t == "removed":
        return "No longer on Virginia DEQ's data center records."
    if t == "renamed":
        return f"Renamed on Virginia DEQ's records (was “{ev.get('from')}”)."
    raise ValueError(f"unknown change type {t!r}")


def event_short(ev):
    t = ev["type"]
    return {"new": lambda: f"new, {stage(ev.get('stage'))}",
            "stage": lambda: f"{stage(ev.get('from'))} to {stage(ev.get('to'))}",
            "permit": lambda: f"air permit dated {fmt_date(ev.get('to')) or 'without a date'}",
            "removed": lambda: "no longer listed",
            "renamed": lambda: "renamed"}[t]()


def count_line(evs):
    counts = {}
    for ev in evs:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
    return ", ".join(f"{counts[t]} {COUNT_WORD[t][counts[t] != 1]}" for t in ORDER if counts.get(t))


def hashtags(localities):
    """Place-name hashtags only: nothing that takes a side."""
    tags = ["#Virginia", "#DataCenters"]
    for loc in localities:
        tag = "#" + "".join(w for w in loc.replace("-", " ").split() if w.isalnum())
        if tag not in tags:
            tags.append(tag)
    return " ".join(tags)


# ---- the drafts ---------------------------------------------------------------------------------------------------------

def build_drafts(inputs, end):
    """Everything for one week, as text and slide specs (nothing written). `end` is the last day of the week."""
    cfg, facilities, schools, meta = inputs["cfg"], inputs["facilities"], inputs["schools"], inputs["meta"]
    base = cfg["site_url"].rstrip("/")
    by_id = {f["id"]: f for f in facilities}
    urls = {"map": f"{base}/{STATE}/", "new": f"{base}/{STATE}/new/", "browse": f"{base}/{STATE}/browse/"}
    host = cards.host(cfg)
    as_of = fmt_date(meta["built_at"][:10])
    total = len(facilities)
    summary = stage_summary(facilities)
    facts = [(str(total), f"data centers on Virginia DEQ's records statewide, as of {as_of}", urls["browse"]),
             (summary, "statewide, by DEQ's stage", urls["browse"])]
    statewide_slide = {"kicker": cards.SITE_NAME, "headline": f"{total} data centers on Virginia DEQ's records",
                       "sub": f"Statewide, as of {as_of}: {summary}."}

    evs = week_events(inputs["changes"], end)
    week = date_range(end)
    if evs:
        d = _weekly(evs, by_id, urls, base, week)
        facts += d.pop("facts")
        slides = [d.pop("cover")] + d.pop("event_slides") + [statewide_slide, {
            "kicker": cards.SITE_NAME, "headline": "See what's near you", "sub": HOW + " Link in bio."}]
    else:
        d = _evergreen(facilities, schools, urls, base, end)
        facts += d.pop("facts")
        slides = d.pop("slides")
        slides.insert(len(slides) - 1, statewide_slide)
    for s in slides:
        s.setdefault("footer", host)
    d.update(kind="weekly" if evs else "evergreen", week=week, end=end.isoformat(), events=evs, slides=slides,
             facts=facts, urls=urls, as_of=as_of)
    return d


def _weekly(evs, by_id, urls, base, week):
    def link(ev):
        f = by_id.get(ev["id"])
        return f"{base}/{facility_path(STATE, f)}" if f and ev["type"] != "removed" else urls["new"]

    counts = count_line(evs)
    facts = [(counts, f"changes seen in the daily check of Virginia DEQ's records, {week}", urls["new"])]
    for ev in evs:
        facts.append((fmt_date(ev["date"]), f"{ev['name']}: {event_sentence(ev)} (the day the daily check saw it)", link(ev)))

    # Facebook: the whole list, each with its page
    lines = [f"What changed on Virginia's data center records this week ({week}): {counts}.", ""]
    for ev in evs:
        lines += [f"• {ev['name']} ({ev.get('locality') or 'locality not given'}), seen {fmt_date(ev['date'])}: "
                  f"{event_sentence(ev)}", f"  {link(ev)}"]
    lines += ["", f"These come from a daily check of {SOURCE} (air permits for data centers' backup generators). "
                  "Each page above links to the DEQ record it came from.",
              f"All changes, with an RSS feed: {urls['new']}"]
    facebook = "\n".join(lines)

    # Bluesky: one post naming the changes if they fit, else the counts; then one reply per change with its link
    single = len(evs) == 1
    main_link = link(evs[0]) if single else urls["new"]
    head = f"What changed on Virginia DEQ's data center records this week ({week}):"
    listed = "\n".join(f"• {ev['name']} ({ev.get('locality') or 'locality not given'}): {event_short(ev)}" for ev in evs)
    bluesky = [first_fitting([
        f"{head}\n{listed}\n\nSource: {SOURCE}. Details: {main_link}",
        f"{head} {counts}.\n\nSource: {SOURCE}. Details: {urls['new']}",
        f"{counts} on {SOURCE} this week. Details: {urls['new']}",
    ])]
    if not single:
        for ev in evs[:MAX_THREAD_REPLIES]:
            loc = ev.get("locality") or "locality not given"
            bluesky.append(first_fitting([
                f"{ev['name']} ({loc}), seen {fmt_date(ev['date'])}: {event_sentence(ev)} {link(ev)}",
                f"{ev['name']} ({loc}): {event_short(ev)}. {link(ev)}",
                f"{loc}: {event_short(ev)}. {link(ev)}",
            ]))
        if len(evs) > MAX_THREAD_REPLIES:
            bluesky.append(f"{plural(len(evs) - MAX_THREAD_REPLIES, 'more change')} this week: {urls['new']}")

    # Instagram: a cover, a slide per change (up to MAX_EVENT_SLIDES), then statewide totals (added by the caller)
    cover = {"kicker": cards.SITE_NAME, "headline": "What changed on Virginia's data center records this week",
             "sub": f"{week}: {counts}. From the daily check of {SOURCE}."}
    shown = evs if len(evs) <= MAX_EVENT_SLIDES else evs[:MAX_EVENT_SLIDES - 1]
    event_slides = [{"kicker": f"{cards.SITE_NAME} · {KIND[ev['type']]}", "headline": ev["name"],
                     "sub": f"{ev.get('locality') or 'Locality not given'}, {STATE_NAME}. {event_sentence(ev)} "
                            f"Seen in the daily check on {fmt_date(ev['date'])}."} for ev in shown]
    if len(shown) < len(evs):
        event_slides.append({"kicker": cards.SITE_NAME, "headline": f"{plural(len(evs) - len(shown), 'more change')} this week",
                             "sub": "The full list, with a page for each site, is on “New this week” (link in bio)."})
    localities = sorted({ev["locality"] for ev in evs if ev.get("locality")})
    caption = "\n".join([
        f"What changed on Virginia's data center records this week ({week}): {counts}.", "",
        *(f"• {ev['name']} ({ev.get('locality') or 'locality not given'}): {event_sentence(ev)}" for ev in evs), "",
        f"Source: {SOURCE}, checked every morning. Each site has its own page with a link to its DEQ record: "
        f"see “New this week” at {urls['new']} (link in bio).", "",
        hashtags(localities)])
    return {"facebook": facebook, "bluesky": bluesky, "caption": caption, "cover": cover,
            "event_slides": event_slides, "facts": facts}


def _evergreen(facilities, schools, urls, base, end):
    rows = school_numbers(facilities, schools)
    n2 = len(rows)
    n1 = sum(1 for r in rows if r["within1"])
    n_all = len(schools)
    ex = pick_school(rows, end)
    facts = [(f"{n2:,}", f"Virginia public schools with a data center within {SCHOOL_RADIUS} miles "
                         f"(of {n_all:,} public schools): count the Schools list on Browse", urls["browse"]),
             (f"{n1:,}", "Virginia public schools with a data center within 1 mile: the Schools list on Browse gives each one's count within 1 mile", urls["browse"])]
    intro = (f"{n2:,} of Virginia's {n_all:,} public schools have a data center within {SCHOOL_RADIUS} miles, "
             f"and {n1:,} have one within 1 mile.")
    slides = [{"kicker": cards.SITE_NAME, "headline": f"{n2:,} Virginia public schools have a data center within "
                                                        f"{SCHOOL_RADIUS} miles",
               "sub": f"{n1:,} of them within 1 mile. Straight-line distances, from {SOURCE} and federal "
                      "school locations (NCES)."}]
    example_fb = example_caption = ""
    if ex:
        sc, name = ex["school"], school_display(ex["school"])
        url = f"{base}/{ex['path']}"
        facts.append((f"{ex['within1']} / {ex['within2']}", f"data centers within 1 / {SCHOOL_RADIUS} miles of {name}, "
                                                             f"{sc['city']} (this week's example)", url))
        headline = f"{plural(ex['within1'], 'data center')} within 1 mile of {name}"
        slides.append({"kicker": f"{cards.SITE_NAME} · Example", "headline": headline,
                       "sub": f"{sc['city']}, {STATE_NAME}. {plural(ex['within2'], 'data center')} within "
                              f"{SCHOOL_RADIUS} miles on {SOURCE}."})
        example_fb = (f"\n\nOne example: {headline} in {sc['city']} ({plural(ex['within2'], 'data center')} within "
                      f"{SCHOOL_RADIUS} miles): {url}")
        example_caption = f"\n\nThis week's example: {headline} ({sc['city']})."
    how = HOW
    slides.append({"kicker": cards.SITE_NAME, "headline": "Look up your school", "sub": how + " Link in bio."})
    facebook = (f"Is there a data center near your school? {intro}{example_fb}\n\n"
                f"Look up any school: {urls['map']}\n{how}\n\n"
                f"Sources: {SOURCE} (data center locations and stages) and the National Center for Education "
                f"Statistics (school locations). Distances are straight-line. Every school with a data center within "
                f"{SCHOOL_RADIUS} miles has its own page: {urls['browse']}")
    bluesky = [first_fitting([
        f"Is there a data center near your school? {intro} Look up any school: {urls['map']}\n\n"
        f"Sources: {SOURCE}; NCES.",
        f"{intro} Look up any school: {urls['map']} Source: {SOURCE}.",
    ])]
    caption = (f"Is there a data center near your school? {intro}{example_caption}\n\n{how}\n\n"
               f"Sources: {SOURCE} and NCES school locations. Free map, link in bio ({urls['map']}).\n\n"
               + hashtags([]))
    return {"facebook": facebook, "bluesky": bluesky, "caption": caption, "slides": slides, "facts": facts}


# ---- writing -----------------------------------------------------------------------------------------------------------

def slide_file(i):
    return f"instagram-{i:02d}.png"


def write_drafts(d, out_dir):
    """Write the drafts into out_dir (created; earlier generated files there are replaced). Returns the file list
    and whether the slide images were drawn."""
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "instagram-*.png")):
        os.remove(old)

    def put(name, text):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text.rstrip("\n") + "\n")

    put("facebook.txt", d["facebook"])
    n = len(d["bluesky"])
    put("bluesky.txt", "\n\n".join(
        f"=== Post {i} of {n}{' (reply to the one above)' if i > 1 else ''}, {chars(p)} of {BLUESKY_LIMIT} characters ===\n{p}"
        for i, p in enumerate(d["bluesky"], 1)))
    put("instagram-caption.txt", d["caption"])
    put("instagram-slides.txt", "\n\n".join(
        f"=== Slide {i}: {slide_file(i)} ===\nTop line: {s['kicker']}\nHeadline: {s['headline']}\nUnder it: {s['sub']}\n"
        f"Footer: {s['footer']}\nAlt text: {s['headline']}. {s['sub']}" for i, s in enumerate(d["slides"], 1)))

    drawn = cards.available()
    if drawn:
        for i, s in enumerate(d["slides"], 1):
            img = cards.instagram_card(s["headline"], s["sub"], kicker=s["kicker"], footer=s["footer"])
            cards.save(img, os.path.join(out_dir, slide_file(i)))
    else:
        print("warning: Pillow is not installed, so the Instagram slide images weren't drawn (pip install Pillow); "
              "the text drafts, including each slide's text in instagram-slides.txt, were written", file=sys.stderr)
    put("README.md", manifest(d, drawn))
    files = ["README.md", "facebook.txt", "bluesky.txt", "instagram-caption.txt", "instagram-slides.txt"]
    return files + ([slide_file(i) for i in range(1, len(d["slides"]) + 1)] if drawn else []), drawn


def manifest(d, drawn):
    what = (f"this week's changes on the change log ({count_line(d['events'])})" if d["kind"] == "weekly" else
            "nothing changed on the change log this week, so these are the evergreen \"look up your school\" posts")
    n_slides = len(d["slides"])
    slides = (f"- `instagram-01.png` to `{slide_file(n_slides)}`: the carousel, {n_slides} slides, 1080x1350, in order"
              if drawn else "- Slide images: **not drawn, because Pillow is not installed** (`pip install Pillow`, then "
                            "run this again). The slide text is in `instagram-slides.txt`.")
    facts = "\n".join(f"| {v} | {what_} | {url} |" for v, what_, url in d["facts"])
    counts = ", ".join(f"post {i}: {chars(p)}" for i, p in enumerate(d["bluesky"], 1))
    return f"""# Social drafts: {d['week']}

Drafted by `python pipeline/social.py` from the committed data in `site/virginia/data/` (data as of {d['as_of']}):
{what}. **Nothing here has been posted, and the script never posts.** Check, edit and post by hand.

## Files

- `facebook.txt`: one post.
- `bluesky.txt`: {plural(len(d['bluesky']), 'post')}{' (a thread: post each as a reply to the one above)' if len(d['bluesky']) > 1 else ''}; characters, links included, out of {BLUESKY_LIMIT}: {counts}.
- `instagram-caption.txt`: the carousel's caption.
- `instagram-slides.txt`: each slide's text, with alt text to paste into Instagram's accessibility setting.
{slides}

## Numbers in these drafts, and where to check them

| Number | What it is | Check it on |
|---|---|---|
{facts}

## Before posting

- [ ] Verify each number against the linked page before posting. Pages rebuild every morning, so a number can
      change between drafting and posting; if it has, run `python pipeline/social.py` again after `git pull`.
- [ ] Open every link in the posts and make sure it loads and says the same thing.
- [ ] For each change, follow the site's page to its DEQ record and confirm it there.
- [ ] Read for tone: neutral and factual, no calls to support or oppose anything, no hashtags that take sides.
- [ ] No personal names (landowners, applicants, county staff): sites are called by DEQ's facility name only.
- [ ] Bluesky: each post is within {BLUESKY_LIMIT} characters including the link (counts above).
- [ ] Instagram: upload the slides in order and add each slide's alt text.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draft this week's social posts into drafts/social/<date>/ (never posts).")
    ap.add_argument("--date", help="last day of the week to cover, YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default=OUT, help="parent folder for the drafts (default: drafts/social)")
    ap.add_argument("--data", default=DATA, help=argparse.SUPPRESS)
    ap.add_argument("--config", default=CONFIG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    end = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    d = build_drafts(load_inputs(a.data, a.config), end)
    out_dir = os.path.join(a.out, end.isoformat())
    files, drawn = write_drafts(d, out_dir)
    print(f"social drafts ({d['kind']}, {d['week']}) in {out_dir}: {', '.join(files)}")
    print("Nothing was posted. Check every number against its linked page (README.md) before posting.")
    return out_dir


if __name__ == "__main__":
    main()
