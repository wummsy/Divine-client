"""Generate the Divine Client partnership promo art (Discord + web sizes).

Everything here is drawn from the launcher's own palette and logo assets - no
AI-generated artwork, no stock photos, and no text baked in by a model that
might spell things wrong. Edit INVITE / the copy block below and re-run:

    python tools/make_promo.py

This is posting material for Discord, not website content: the site has no partner
page any more, so nothing here is served by it and the copy does not promise one.
Output goes next to this script, in tools/promo/:

    wide.png     1600x600   the pitch image - banner slot, X/Twitter card, email header
    square.png    800x800   Discord embed thumbnail, phone feeds
    banner.png    960x540   Discord server banner, Reddit post image
    wide.svg                 the wide banner as vectors, if you want it crisp

It also draws the one image the website does use - the link-preview card - straight
into server/static/og.png, because a shared link should look like the launcher.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(HERE, "promo")
# the site's social card; /assets/logo.png is the fallback if this is missing
SITE_OG = os.path.join(ROOT, "server", "static", "og.png")

# ---- palette (ui/theme.py) -------------------------------------------------
BG = (10, 12, 18)          # #0a0c12
BG2 = (17, 20, 29)         # #11141d
PANEL = (24, 28, 40)        # #181c28
HAIR = (32, 38, 58)         # #20263a
TEXT = (243, 246, 252)      # #f3f6fc
DIM = (144, 152, 180)       # #9098b4
FAINT = (90, 98, 128)       # #5a6280
CYAN = (56, 225, 208)       # #38e1d0
CYAN_HI = (110, 244, 230)
VIOLET = (155, 123, 255)    # #9b7bff
GOOD = (75, 224, 138)       # #4be08a
ON_ACCENT = (4, 18, 26)

INVITE = "discord.gg/ER2haQtach"          # keep in step with DISCORD_INVITE_URL
SITE = "divineclient.wispbyte.org"
# the site's own link-preview card (server/static/og.png)
SITE_HEAD = "A Minecraft launcher that keeps your instances apart"
SITE_SUB = ("Separate folders per version, Fabric with a performance pack and "
            "Modrinth search inside the app, so a 1.16.5 pack can never break your "
            "1.21.4 one.")
SITE_FEATURES = ("per-version instances", "Modrinth inside the app",
                 "Fabric + performance pack")
HEADLINE = "Partner with Divine Client"
SUBHEAD = ("We feature your community to Minecraft players who already use the "
           "launcher. You put Divine in front of your members.")

# Only perks the launcher can actually deliver today - nothing about a website page,
# because there is no partner page to link to.
PERKS = [
    "An announcement in the launcher news feed, read by every install",
    "A co-branded instance preset: your mods, packs and server, one click",
    "Divine listed in your events channel graphic, our side too",
    "Early builds and a direct line to the dev team for your staff",
]

ASKS = [
    "An active Minecraft community (roughly 300+ members is where it pays off)",
    "One Divine mention a month in your announcements channel, no spam",
    "Use the logo as shipped - do not recolour or stretch it",
]


def fonts(scale=1.0):
    def load(name, size):
        for cand in (name, name.replace("-Bold", ""), "DejaVuSans-Bold.ttf",
                     "DejaVuSans.ttf"):
            path = os.path.join("/usr/share/fonts/truetype/dejavu", cand)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, int(size * scale))
                except OSError:
                    continue
        return ImageFont.load_default()

    return {
        "huge": load("DejaVuSans-Bold.ttf", 60),
        "mid": load("DejaVuSans-Bold.ttf", 25),
        "body": load("DejaVuSans.ttf", 21),
        "small": load("DejaVuSans.ttf", 17),
        "mono": load("DejaVuSansMono-Bold.ttf", 19),
        "ribbon": load("DejaVuSans-Bold.ttf", 15),
        "card_title": load("DejaVuSans-Bold.ttf", 23),
        "card_sub": load("DejaVuSans.ttf", 15),
        "card_stat": load("DejaVuSans-Bold.ttf", 24),
    }


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def background(w, h, glow=((0.18, 0.0, CYAN), (0.92, 0.25, VIOLET))):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    for y in range(h):                                   # vertical gradient
        d.line([(0, y), (w, y)], fill=_lerp(BG, (13, 17, 28), y / max(1, h)))
    # faint block grid, a nod to the cube in the logo
    step = max(28, w // 48)
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, w + step, step):
        gd.line([(x, 0), (x, h)], fill=(255, 255, 255, 7))
    for y in range(0, h + step, step):
        gd.line([(0, y), (w, y)], fill=(255, 255, 255, 7))
    img = Image.alpha_composite(img.convert("RGBA"), grid)
    for fx, fy, color in glow:                            # soft corner glows
        blob = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(blob).ellipse([fx * w - w * 0.35, fy * h - h * 0.9,
                                      fx * w + w * 0.35, fy * h + h * 0.9],
                                     fill=color + (58,))
        img = Image.alpha_composite(img, blob.filter(ImageFilter.GaussianBlur(90)))
    return img.convert("RGB")


def panel(d, box, radius=18, fill=PANEL, outline=HAIR, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(d, xy, s, font, fill=TEXT, anchor=None, spacing=4):
    d.text(xy, s, font=font, fill=fill, anchor=anchor, spacing=spacing)


def wrap(d, s, font, max_w):
    words, lines, cur = s.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def wordmark(base, d, x, y, height):
    """The launcher's own wordmark (assets/logo.png already carries the mark)."""
    path = os.path.join(ASSETS, "logo.png")
    if not os.path.exists(path):
        return 0
    lg = Image.open(path).convert("RGBA")
    w = int(lg.width * (height / lg.height))
    base.alpha_composite(lg.resize((w, height), Image.LANCZOS), (x, y))
    return w


def server_card(base, d, x, y, w, h, f, scale):
    """A mock of the launcher's server window: the product, inside the ad."""
    panel(d, [x, y, x + w, y + h], radius=int(18 * scale), fill=(16, 19, 28),
          outline=HAIR)
    d.rounded_rectangle([x, y + 16, x + 5 * scale, y + h - 16],
                        radius=int(3 * scale), fill=VIOLET)
    pad = int(24 * scale)
    emb = Image.open(os.path.join(ASSETS, "emblem.png")).convert("RGBA")
    box = int(46 * scale)
    base.alpha_composite(emb.resize((box, box), Image.LANCZOS), (x + pad, y + pad))
    tx = x + pad + box + int(14 * scale)
    text(d, (tx, y + pad + int(2 * scale)), "Divine Partner Server", f["card_title"], TEXT)
    text(d, (tx, y + pad + int(30 * scale)), "fabric 1.21.4  \u2022  128 mods",
         f["card_sub"], DIM)

    strip_y = y + pad + int(62 * scale)
    strip_h = int(34 * scale)
    panel(d, [x + pad, strip_y, x + w - pad, strip_y + strip_h],
          radius=int(9 * scale), fill=(11, 14, 21), outline=(38, 46, 70))
    text(d, (x + pad + int(12 * scale), strip_y + strip_h // 2), "bore.pub:54294",
         f["mono"], GOOD, anchor="lm")
    text(d, (x + w - pad - int(12 * scale), strip_y + strip_h // 2),
         "no port forwarding", f["card_sub"], FAINT, anchor="rm")

    stats = [("632 MB", "of 1024 MB allocated"), ("24%", "of 8 cores"),
             ("17", "players online"), ("3h 12m", "since start")]
    top = strip_y + strip_h + int(20 * scale)
    col_w = (w - 2 * pad) // 2
    for i, (val, sub) in enumerate(stats):
        cx = x + pad + (i % 2) * col_w
        cy = top + (i // 2) * int(56 * scale)
        text(d, (cx, cy), val, f["card_stat"], CYAN)
        text(d, (cx, cy + int(26 * scale)), sub, f["card_sub"], FAINT)


def compose(kind):
    """kind: wide | square | banner | og - one layout, scaled."""
    sizes = {"wide": (1600, 600), "square": (800, 800), "banner": (960, 540),
             "og": (1200, 630)}
    w, h = sizes[kind]
    # one scale factor drives every dimension, so the layouts cannot disagree
    scale = w / 1600.0 if kind != "square" else w / 1000.0
    f = fonts(scale)
    base = background(w, h).convert("RGBA")
    d = ImageDraw.Draw(base)

    m = int(56 * scale)                       # outer margin
    card_w = int(540 * scale) if kind in ("wide", "og") else 0
    text_w = w - 2 * m - (card_w + int(48 * scale) if card_w else 0)

    wordmark(base, d, m, m, int(52 * scale))

    y = m + int(92 * scale)
    ribbon_h = int(34 * scale)
    ribbon_w = int(232 * scale)
    d.rounded_rectangle([m, y, m + ribbon_w, y + ribbon_h], radius=int(9 * scale),
                        fill=VIOLET)
    text(d, (m + int(15 * scale), y + ribbon_h // 2), "DISCORD PARTNERSHIPS",
         f["ribbon"], (11, 7, 32), anchor="lm")
    y += ribbon_h + int(26 * scale)

    text(d, (m, y), HEADLINE, f["huge"], TEXT)
    y += int(70 * scale)

    for ln in wrap(d, SUBHEAD, f["body"], text_w):
        text(d, (m, y), ln, f["body"], DIM)
        y += int(29 * scale)
    y += int(22 * scale)

    for perk in PERKS:
        dot = int(11 * scale)
        d.ellipse([m, y + int(5 * scale), m + dot, y + int(5 * scale) + dot],
                  fill=CYAN)
        line = perk.replace("SITE", SITE)
        if d.textlength(line, font=f["body"]) > text_w - dot:
            line = wrap(d, line, f["body"], text_w - dot)[0]
        text(d, (m + dot + int(14 * scale), y), line, f["body"], TEXT)
        y += int(33 * scale)

    if card_w:
        server_card(base, d, w - m - card_w, int(h * 0.26), card_w,
                    int(h * 0.47), f, scale)
    elif kind == "square":
        # the square is tall enough that text alone leaves half the art empty
        server_card(base, d, m, y + int(30 * scale), w - 2 * m, int(h * 0.33),
                    f, scale)

    foot_h = int(64 * scale)
    d.rectangle([0, h - foot_h, w, h], fill=(8, 10, 15))
    d.line([0, h - foot_h, w, h - foot_h], fill=HAIR, width=max(1, int(2 * scale)))
    fy = h - foot_h // 2
    text(d, (m, fy), "Apply: " + INVITE, f["mid"], CYAN_HI, anchor="lm")
    text(d, (w - m, fy), "info: %s" % SITE, f["small"], FAINT, anchor="rm")

    os.makedirs(OUT, exist_ok=True)
    name = {"square": "square.png", "banner": "banner.png",
            "wide": "wide.png"}[kind]
    path = os.path.join(OUT, name)
    base.convert("RGB").save(path, optimize=True)
    print("wrote %s (%dx%d)" % (os.path.relpath(path, ROOT), w, h))
    return path


def site_card(path, w=1200, h=630):
    """The site's own link-preview card (what Discord shows for a bare URL).

    Not part of the ad - it is the one image here that the website uses, so it sells
    the launcher rather than a program and says nothing the landing page does not
    already say. The text block is laid out from the footer upwards, so a longer
    headline grows up instead of running off the right edge.
    """
    scale = w / 1600.0
    f = fonts(scale)
    base = background(w, h, glow=((0.16, -0.05, CYAN), (0.86, 0.35, VIOLET))).convert("RGBA")
    d = ImageDraw.Draw(base)
    m = int(72 * scale)
    text_w = w - 2 * m

    wordmark(base, d, m, m, int(76 * scale))

    # a row of short labels fills the band between the wordmark and the headline
    row_y = m + int(150 * scale)
    step = text_w // max(1, len(SITE_FEATURES))
    for i, item in enumerate(SITE_FEATURES):
        x = m + i * step
        dot = int(10 * scale)
        d.ellipse([x, row_y - dot // 2, x + dot, row_y + dot - dot // 2], fill=CYAN)
        text(d, (x + dot + int(12 * scale), row_y), item, f["small"], DIM, anchor="lm")

    head = wrap(d, SITE_HEAD, f["huge"], text_w)
    sub = wrap(d, SITE_SUB, f["body"], text_w)
    head_lead = int(62 * scale)
    sub_lead = int(30 * scale)
    foot_h = int(64 * scale)
    block = len(head) * head_lead + int(18 * scale) + len(sub) * sub_lead
    y = h - foot_h - int(30 * scale) - block
    for ln in head:
        text(d, (m, y), ln, f["huge"], TEXT)
        y += head_lead
    y += int(18 * scale)
    for ln in sub:
        text(d, (m, y), ln, f["body"], DIM)
        y += sub_lead

    d.rectangle([0, h - foot_h, w, h], fill=(8, 10, 15))
    d.line([0, h - foot_h, w, h - foot_h], fill=HAIR, width=max(1, int(2 * scale)))
    fy = h - foot_h // 2
    text(d, (m, fy), SITE, f["mid"], CYAN_HI, anchor="lm")
    text(d, (w - m, fy), "free for Windows 10 & 11", f["small"], FAINT, anchor="rm")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    base.convert("RGB").save(path, optimize=True)
    print("wrote %s (%dx%d, headline in %d lines)" % (
        os.path.relpath(path, ROOT), w, h, len(head)))
    return path


def svg_wide(path):
    """A vector copy of the wide banner for the site (crisp on any display)."""
    perks = "".join(
        '<circle cx="60" cy="%d" r="6" fill="#38e1d0"/>'
        '<text x="80" y="%d" fill="#f3f6fc" font-family="Segoe UI,Arial" '
        'font-size="20">%s</text>' % (300 + i * 46, 307 + i * 46, p.replace("&", "&amp;"))
        for i, p in enumerate(PERKS))
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="600" viewBox="0 0 1600 600">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0a0c12"/><stop offset="1" stop-color="#0d111c"/>
  </linearGradient>
  <radialGradient id="glow" cx="0.2" cy="0" r="0.9">
    <stop offset="0" stop-color="#38e1d0" stop-opacity="0.30"/>
    <stop offset="1" stop-color="#38e1d0" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="glow2" cx="0.95" cy="0.3" r="0.7">
    <stop offset="0" stop-color="#9b7bff" stop-opacity="0.26"/>
    <stop offset="1" stop-color="#9b7bff" stop-opacity="0"/>
  </radialGradient>
</defs>
<rect width="1600" height="600" fill="url(#bg)"/>
<rect width="1600" height="600" fill="url(#glow)"/>
<rect width="1600" height="600" fill="url(#glow2)"/>
<g opacity="0.05" stroke="#ffffff"><path d="M0 40H1600M0 80H1600M0 120H1600M0 160H1600M0 200H1600M0 240H1600M0 280H1600M0 320H1600M0 360H1600M0 400H1600M0 440H1600M0 480H1600M40 0V600M80 0V600M120 0V600M160 0V600M200 0V600M240 0V600M280 0V600M320 0V600M360 0V600M400 0V600M440 0V600M480 0V600M520 0V600M560 0V600M600 0V600M640 0V600M680 0V600M720 0V600M760 0V600M800 0V600M840 0V600M880 0V600M920 0V600M960 0V600M1000 0V600M1040 0V600M1080 0V600M1120 0V600M1160 0V600M1200 0V600M1240 0V600M1280 0V600M1320 0V600M1360 0V600M1400 0V600M1440 0V600M1480 0V600M1520 0V600M1560 0V600"/></g>
<g transform="translate(56 44) scale(0.98)">
  <rect width="118" height="118" rx="26" fill="#141a2b" stroke="#242c44" stroke-width="2"/>
  <polygon points="59,26 92,44 59,62 26,44" fill="#4be6d6"/>
  <polygon points="26,44 59,62 59,96 26,78" fill="#8f6dff"/>
  <polygon points="92,44 92,78 59,96 59,62" fill="#22b6a8"/>
</g>
<text x="200" y="108" fill="#f3f6fc" font-family="Segoe UI,Arial" font-size="52" font-weight="700" letter-spacing="1">DIVINE</text>
<text x="316" y="108" fill="#9098b4" font-family="Segoe UI,Arial" font-size="52" letter-spacing="1">CLIENT</text>
<rect x="56" y="196" width="252" height="38" rx="10" fill="#9b7bff"/>
<text x="72" y="222" fill="#0b0720" font-family="Segoe UI,Arial" font-size="17" font-weight="700" letter-spacing="2">DISCORD PARTNERSHIPS</text>
<text x="56" y="300" fill="#f3f6fc" font-family="Segoe UI,Arial" font-size="62" font-weight="700">Partner with Divine Client</text>
<text x="56" y="346" fill="#9098b4" font-family="Segoe UI,Arial" font-size="22">We feature your community to Minecraft players who already use the launcher.</text>
%s
<rect x="56" y="526" width="1488" height="1" fill="#20263a"/>
<text x="56" y="570" fill="#6ff4e6" font-family="Segoe UI,Arial" font-size="26" font-weight="700">Apply: %s</text>
<text x="1544" y="570" fill="#5a6280" font-family="Segoe UI,Arial" font-size="18" text-anchor="end">info: %s</text>
</svg>""" % (perks, INVITE, SITE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote %s" % os.path.relpath(path, ROOT))


def copy_file():
    """The text to paste into Discord, plus the terms, next to the images."""
    asks = "\n".join("- %s" % a for a in ASKS)
    perks = "\n".join("- %s" % p for p in PERKS)
    txt = """# Divine Client - Discord partnership promo

Images in this folder, ready to attach:

| File | Size | Use it for |
| --- | --- | --- |
| `wide.png` | 1600x600 | the site hero, X/Twitter card, newsletter header |
| `banner.png` | 960x540 | Discord server banner, Reddit post image |
| `square.png` | 800x800 | Discord embed thumbnail, phone-first feeds |
| `wide.svg` | vector | the wide banner again, for anything that takes SVG |

Everything is redrawn by `python tools/make_promo.py` - change `INVITE` or the
copy in that file and re-run; nothing is baked in by a model. The same run also
refreshes the site's own link-preview card (`server/static/og.png`), which is the
only image here the website uses; that one advertises the launcher, not this
program, and it never mentions a partner page - the site has none.

---

## Short (announcement / status, ~230 chars)

> **Partner with Divine Client** - a clean Minecraft launcher with multi-instance
> support, a built-in Modrinth browser, one-click server hosting and a public
> address with no port forwarding. We feature your Discord to our players, you
> mention us to yours: `%%(invite)s`

## Medium (an embed description)

> **Divine Client is looking for partner Discord servers.**
>
> Divine Client is a free Minecraft launcher: separate instances per version,
> Fabric with a performance pack, a Modrinth mod and resource-pack browser inside
> the app, Microsoft sign-in, and hosted servers that keep running while you do
> other things - with a `bore.pub` address so friends can join without you
> touching your router.
>
> Partners get a page for their community on `%%(site)s`, an announcement in the
> launcher's news feed, a co-branded instance preset their members can install in
> one click, and early builds for their staff. In return we ask for roughly
> %%(min_members)s active members and one Divine mention a month in your
> announcements channel - no spam, no ping roles.
>
> Apply at %%(invite)s, or reply to this post.

## Long (forum / Reddit / Discord post)

> **We're starting a Discord partnership program for Divine Client**
>
> Divine Client is a free, open Minecraft launcher we build for people who run
> several modded instances. It handles versions, Java, Fabric, mods and resource
> packs per instance, signs in with Microsoft, and can host a dedicated server
> for any instance in its own window - that window can be closed without stopping
> the server, it shows live memory/CPU/player meters, and a built-in tunnel hands
> you a public address (`bore.pub:port`) so friends join without port forwarding.
>
> What partners get:
%(perks)s
>
> What we ask:
%(asks)s
>
> Site and download: %%(site)s
> Apply: %%(invite)s

---

Placeholders to fill in before posting: `%%(invite)s` = your Discord invite,
`%%(min_members)s` = the number in `ASKS`. Defaults live at the top of
`tools/make_promo.py`. The website has no partner page, so this is the only place
the program is written down - keep `INVITE` above and `DISCORD_INVITE_URL` on the
server the same, or the art and the site will
drift apart.
""" % {"site": SITE, "perks": perks, "asks": asks}
    pass


def main():
    os.makedirs(OUT, exist_ok=True)
    for kind in ("wide", "square", "banner"):
        compose(kind)
    svg_wide(os.path.join(OUT, "wide.svg"))
    site_card(SITE_OG)
    copy_file()


if __name__ == "__main__":
    main()
