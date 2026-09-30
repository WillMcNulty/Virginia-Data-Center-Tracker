"""Link-preview images ("cards"): the picture a page shows when its link is shared (og:image, Twitter/X large card).

Each generated page can pass a card (a headline built from the page's own numbers, plus a short line under it) to
pages.shell(); shell() puts the og:image tags in the page and queues the card; build_pages() then calls
render_queued(), which draws every queued card to site/cards/<page path>.png (generated, gitignored).

Pillow is needed to draw cards. CI installs it and refuses to build without it (the environment variable CI is set
there). A local build without Pillow still works: it prints a warning, draws nothing, and every page points to the
committed generic card, site/card-default.png. Regenerate that file with `python pipeline/cards.py`.

The fonts are DejaVu Sans and DejaVu Sans Bold (license in pipeline/fonts/LICENSE_DEJAVU), subset to Latin
characters, so cards look the same on Windows and on CI. Cards are saved as small palette PNGs.

For other uses (T9's social drafts): render(headline, sub, size=...) returns a Pillow image, instagram_card() draws
the 1080x1350 portrait variant, and save() writes any of them as an optimized palette PNG.
"""
import functools
import html
import os
import sys
import time

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # optional locally; see the module docstring
    Image = ImageDraw = ImageFont = None

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(HERE, "fonts", "DejaVuSans-Bold.ttf")
FONT_REGULAR = os.path.join(HERE, "fonts", "DejaVuSans.ttf")

LINK_SIZE = (1200, 630)        # link previews (Facebook, X, Bluesky, LinkedIn, iMessage, Slack)
INSTAGRAM_SIZE = (1080, 1350)  # Instagram's 4:5 portrait post
NAVY, ORANGE = (0x23, 0x2D, 0x4B), (0xE5, 0x72, 0x00)  # UVA Blue and UVA Orange, as on the site
WHITE, MUTED = (0xFF, 0xFF, 0xFF), (0xC6, 0xCF, 0xE8)  # the header band's text colors (pages.css --band-muted)


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# Cards use four flat colors, so antialiased text only needs the steps between the background and each text color:
# a fixed 16-color palette. Mapping to it is several times faster than an adaptive quantize and gives smaller files.
CARD_PALETTE = ([NAVY] + [_mix(NAVY, WHITE, i / 9) for i in range(1, 10)] + [_mix(NAVY, MUTED, i / 5) for i in range(1, 6)]
                + [ORANGE])

SITE_NAME = "Data Centers Near You"
CARD_DIR = "cards"                   # site/cards/..., generated
DEFAULT_CARD = "card-default.png"    # site/card-default.png, committed; used when a page has no card of its own
DEFAULT_HEADLINE = "Data centers planned, being built and running near you"
DEFAULT_SUB = "Search by ZIP code or school. Built from official state records."

_queue = []  # (card path relative to site/, headline, sub, footer) waiting for render_queued()


def available():
    """True when Pillow is installed, so cards can be drawn."""
    return Image is not None


# ---- drawing ------------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _font(path, size):
    return ImageFont.truetype(path, size)


def wrap(text, font, max_width):
    """Greedy word wrap; a single word wider than the line (rare, e.g. a long run-together name) is hyphen-split."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}" if cur else word
        if font.getlength(trial) <= max_width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        while font.getlength(word) > max_width:
            i = len(word) - 1
            while i > 1 and font.getlength(word[:i] + "-") > max_width:
                i -= 1
            lines.append(word[:i] + "-")
            word = word[i:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def _ellipsize(lines, font, max_width, max_lines):
    if len(lines) <= max_lines:
        return lines
    last = " ".join(lines[max_lines - 1:])
    while last and font.getlength(last + "…") > max_width:
        last = last[:-1].rstrip()
    return lines[:max_lines - 1] + [last + "…"]


def fit(text, font_path, max_width, max_height, max_size, min_size, max_lines, leading=1.15):
    """Largest font size (stepping down by 2) at which `text` wraps into at most max_lines lines within the box.
    Returns (size, lines, line_height). At min_size it gives up shrinking and cuts the text with an ellipsis."""
    size = max_size
    while True:
        font = _font(font_path, size)
        lines = wrap(text, font, max_width)
        line_h = round(size * leading)
        if (len(lines) <= max_lines and len(lines) * line_h <= max_height) or size <= min_size:
            fitting = max(1, min(max_lines, max_height // line_h))
            return size, _ellipsize(lines, font, max_width, fitting), line_h
        size -= 2


def render(headline, sub=None, *, size=LINK_SIZE, kicker=SITE_NAME, footer=None):
    """Draw a card: navy background, the site name, an orange rule, the headline (shrunk and wrapped to fit), an
    optional line under it, an optional footer (e.g. the site's address) and an orange bar along the bottom.
    Works for any size; LINK_SIZE and INSTAGRAM_SIZE are the two in use. Returns a Pillow RGB image."""
    if not available():
        raise RuntimeError("Pillow is not installed (pip install Pillow)")
    W, H = size
    portrait = H > W
    m = round(W * 0.07)
    img = Image.new("RGB", size, NAVY)
    d = ImageDraw.Draw(img)
    text_w = W - 2 * m

    # site name, orange rule
    k_size = round(W * (0.034 if portrait else 0.027))
    y = m
    d.text((m, y), kicker, font=_font(FONT_BOLD, k_size), fill=WHITE)
    y += round(k_size * 1.25) + round(m * 0.25)
    rule_h = max(6, round(W * 0.007))
    d.rectangle((m, y, m + round(W * 0.11), y + rule_h - 1), fill=ORANGE)
    top = y + rule_h + round(m * 0.55)

    # bottom bar and footer
    bar_h = max(8, round(H * (0.012 if portrait else 0.02)))
    d.rectangle((0, H - bar_h, W, H), fill=ORANGE)
    bottom = H - bar_h - round(m * 0.6)
    if footer:
        f_font = _font(FONT_REGULAR, round(W * (0.03 if portrait else 0.022)))
        f_text = _ellipsize(wrap(footer, f_font, text_w), f_font, text_w, 1)[0]
        f_h = f_font.getbbox("Ag")[3]
        d.text((m, bottom - f_h), f_text, font=f_font, fill=MUTED)
        bottom -= f_h + round(m * 0.45)

    # the line under the headline (fixed size, up to a few lines)
    sub_lines, sub_line_h, s_font = [], 0, None
    if sub:
        s_size = round(W * (0.037 if portrait else 0.026))
        s_font = _font(FONT_REGULAR, s_size)
        sub_line_h = round(s_size * 1.3)
        sub_lines = _ellipsize(wrap(sub, s_font, text_w), s_font, text_w, 6 if portrait else 3)
    sub_h = len(sub_lines) * sub_line_h
    gap = round(m * 0.4) if sub_lines else 0

    # headline: as large as fits in what's left
    h_max = round(W * (0.085 if portrait else 0.06))
    h_min = round(W * (0.042 if portrait else 0.032))
    h_size, h_lines, h_line_h = fit(headline, FONT_BOLD, text_w, bottom - top - sub_h - gap,
                                    h_max, h_min, 7 if portrait else 4)
    h_font = _font(FONT_BOLD, h_size)

    # center the headline and line under it in the space between the rule and the footer
    block = len(h_lines) * h_line_h + gap + sub_h
    y = top + max(0, (bottom - top - block) // 2)
    for line in h_lines:
        d.text((m, y), line, font=h_font, fill=WHITE)
        y += h_line_h
    y += gap
    for line in sub_lines:
        d.text((m, y), line, font=s_font, fill=MUTED)
        y += sub_line_h
    return img


def instagram_card(headline, sub=None, *, kicker=SITE_NAME, footer=None):
    """The 1080x1350 (4:5 portrait) Instagram variant of a card."""
    return render(headline, sub, size=INSTAGRAM_SIZE, kicker=kicker, footer=footer)


def save(img, path, colors=None):
    """Save as an optimized palette PNG and return its size in bytes. By default the image is mapped to the cards'
    fixed palette (right for anything render() draws); pass colors=N for an adaptive N-color palette instead (for
    images with other colors). No dithering: it only adds noise and bytes."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if colors:
        img = img.quantize(colors=colors, dither=Image.Dither.NONE)
    else:
        img = img.quantize(palette=_palette_image(), dither=Image.Dither.NONE)
    img.save(path, optimize=True)
    return os.path.getsize(path)


@functools.lru_cache(maxsize=None)
def _palette_image():
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in CARD_PALETTE for c in rgb]
    pal.putpalette(flat + flat[:3] * (256 - len(CARD_PALETTE)))
    return pal


# ---- pages ----------------------------------------------------------------------------------------------------------

def card_file(page_path):
    """Where a page's card goes, relative to site/: "" -> cards/home.png, "virginia/zip/20171/" -> cards/virginia/zip/20171.png."""
    return f"{CARD_DIR}/{page_path.strip('/') or 'home'}.png"


def host(cfg):
    return cfg["site_url"].split("://", 1)[-1].rstrip("/")


def for_page(cfg, page_path, card=None):
    """The og:image for a page: {url (absolute), width, height, alt}. `card` is {"headline": ..., "sub": ...} (sub
    optional) or None for the generic card. A page's own card is queued for render_queued(); without Pillow every
    page gets the generic card."""
    base = cfg["site_url"].rstrip("/")
    if card:
        rel = card_file(page_path)
        sub = card.get("sub")
        _queue.append((rel, card["headline"], sub, card.get("footer", host(cfg))))
    if not card or not available():
        return {"url": f"{base}/{DEFAULT_CARD}", "width": LINK_SIZE[0], "height": LINK_SIZE[1],
                "alt": f"{SITE_NAME}: {DEFAULT_HEADLINE}. {DEFAULT_SUB}"}
    return {"url": f"{base}/{rel}", "width": LINK_SIZE[0], "height": LINK_SIZE[1],
            "alt": f"{card['headline']}." + (f" {sub}" if sub else "")}


def meta_tags(cfg, page_path, card=None):
    """The <head> tags for a page's preview image (Open Graph and Twitter/X), one per line."""
    img = for_page(cfg, page_path, card)
    esc = html.escape
    return "\n".join([
        f'<meta property="og:image" content="{esc(img["url"])}">',
        '<meta property="og:image:type" content="image/png">',
        f'<meta property="og:image:width" content="{img["width"]}">',
        f'<meta property="og:image:height" content="{img["height"]}">',
        f'<meta property="og:image:alt" content="{esc(img["alt"])}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:image:alt" content="{esc(img["alt"])}">',
    ])


def reset():
    _queue.clear()


def render_queued(site_dir):
    """Draw every queued card into site_dir/cards/ (emptied first). Returns counts, bytes and seconds."""
    import shutil
    out = os.path.join(site_dir, CARD_DIR)
    if os.path.isdir(out):
        shutil.rmtree(out)
    jobs = list(dict.fromkeys(_queue))
    _queue.clear()
    if not available():
        if os.environ.get("CI"):
            raise SystemExit("Pillow is not installed, so link-preview images can't be drawn; refusing to publish "
                             "pages whose og:image would be missing (pip install Pillow)")
        print(f"warning: Pillow is not installed; skipped {len(jobs)} link-preview image(s); pages use site/card-default.png "
              "(pip install Pillow to draw them)", file=sys.stderr)
        return {"cards": 0, "bytes": 0, "seconds": 0.0, "skipped": len(jobs)}
    t0, total, largest = time.perf_counter(), 0, 0
    for rel, headline, sub, footer in jobs:
        n = save(render(headline, sub, footer=footer), os.path.join(site_dir, rel))
        total, largest = total + n, max(largest, n)
    secs = time.perf_counter() - t0
    if jobs:
        print(f"cards: {len(jobs)} link-preview image(s), {total / 1e6:.1f} MB (average {total / len(jobs) / 1e3:.0f} KB, "
              f"largest {largest / 1e3:.0f} KB) in {secs:.1f} s")
    return {"cards": len(jobs), "bytes": total, "largest": largest, "seconds": secs, "skipped": 0}


def write_default(site_dir):
    """Draw the generic card that pages fall back to (committed as site/card-default.png)."""
    return save(render(DEFAULT_HEADLINE, DEFAULT_SUB), os.path.join(site_dir, DEFAULT_CARD))


if __name__ == "__main__":
    site = os.path.join(os.path.dirname(HERE), "site")
    print(f"wrote {os.path.join(site, DEFAULT_CARD)} ({write_default(site)} bytes)")
