#!/usr/bin/env python3
"""Draw the launcher's own glyph set, in the style of the four marks that were supplied.

The supplied artwork (assets/ui_friends.png, ui_account.png, ui_new.png, ui_discord.png) is a
512 px square, one solid near-black shape, thick strokes, generous rounding, no outlines and
no detail inside the silhouette. Every page needs more marks than those four, and mixing in a
thin-stroke icon family next to them looks like two launchers stitched together - so this
script draws the rest to match, and the four supplied files are left exactly as they are.

The shapes are built on a 512 grid with a 44 px margin and a 60 px stroke, which is what the
supplied ones measure. They are then *cut* rather than drawn where a mark needs a hole (the
inside of a gear, Discord's eyes), because the launcher tints them by replacing the RGB and
keeping alpha - holes must be transparent, not white, or a glyph turns into a blob at 20 px.

Run from the repo root:

    python3 tools/make_ui_glyphs.py            # writes assets/ui_*.png
    python3 tools/make_ui_glyphs.py -contact   # also writes assets/glyphs_contact.png
"""
import os
import sys

from PIL import Image, ImageDraw

SIZE = 512
PAD = 44
STROKE = 60
INK = (0, 0, 0, 255)          # solid; the app tints it at paint time
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")


def canvas():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def rrect(d, box, radius=None, fill=INK, width=0, outline=None):
    x0, y0, x1, y1 = box
    radius = radius if radius is not None else min(36, (y1 - y0) / 2, (x1 - x0) / 2)
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, width=width, outline=outline)


def dot(d, cx, cy, r, fill=INK):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def thick_line(d, points, width=STROKE, joint="round"):
    d.line(points, fill=INK, width=width, joint=joint)


def tri(d, points, fill=INK):
    d.polygon(list(points), fill=fill)


# --------------------------------------------------------------------- the marks
def home():
    img, d = canvas()
    # roof as a thick chevron, body as a rounded box under it - the two supplied "person"
    # marks read the same way, so this stays legible at 20 px
    thick_line(d, [(PAD + 6, 236), (SIZE / 2, PAD + 6), (SIZE - PAD - 6, 236)], width=STROKE + 6)
    rrect(d, [116, 232, SIZE - 116, SIZE - PAD], radius=30)
    d.rectangle([216, 336, 296, SIZE - PAD], fill=(0, 0, 0, 0))       # the doorway, cut out
    return img


def instances():
    img, d = canvas()
    gap = 26
    side = (SIZE - 2 * PAD - gap) / 2
    for i in range(2):
        for j in range(2):
            x0 = PAD + i * (side + gap)
            y0 = PAD + j * (side + gap)
            rrect(d, [x0, y0, x0 + side, y0 + side], radius=34)
    return img


def servers():
    img, d = canvas()
    for i, y in enumerate((PAD, 202, 364)):
        rrect(d, [PAD, y, SIZE - PAD, y + 104], radius=28)
        dot(d, PAD + 58, y + 52, 20, fill=(0, 0, 0, 0))               # the status lamp, cut
    return img


def settings():
    img, d = canvas()
    import math
    cx = cy = SIZE / 2
    d.ellipse([cx - 150, cy - 150, cx + 150, cy + 150], fill=INK)
    teeth = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(teeth).rounded_rectangle([10, 26, 110, 94], radius=22, fill=INK)
    for i in range(8):
        ang = math.radians(i * 45)
        t = teeth.rotate(-i * 45, resample=Image.BICUBIC, expand=True)
        px = cx + 168 * math.cos(ang) - t.width / 2
        py = cy + 168 * math.sin(ang) - t.height / 2
        img.alpha_composite(t, (int(px), int(py)))
    d = ImageDraw.Draw(img)
    dot(d, cx, cy, 62, fill=(0, 0, 0, 0))
    return img


def about():
    img, d = canvas()
    d.ellipse([PAD, PAD, SIZE - PAD, SIZE - PAD], outline=INK, width=STROKE)
    dot(d, SIZE / 2, 168, 34)
    rrect(d, [SIZE / 2 - 30, 224, SIZE / 2 + 30, SIZE - 128], radius=28)
    return img


def play():
    img, d = canvas()
    tri(d, [(140, 96), (140, SIZE - 96), (SIZE - 96, SIZE / 2)])
    # round the corners of the triangle by overdrawing the leading edge with a fat line
    thick_line(d, [(150, 110), (SIZE - 106, SIZE / 2)], width=STROKE - 8)
    return img


def stop():
    img, d = canvas()
    rrect(d, [PAD + 22, PAD + 22, SIZE - PAD - 22, SIZE - PAD - 22], radius=46)
    return img


def pause():
    img, d = canvas()
    rrect(d, [140, 118, 220, SIZE - 118], radius=34)
    rrect(d, [SIZE - 220, 118, SIZE - 140, SIZE - 118], radius=34)
    return img


def refresh():
    img, d = canvas()
    import math
    box = [PAD + 30, PAD + 30, SIZE - PAD - 30, SIZE - PAD - 30]
    d.arc(box, start=40, end=320, fill=INK, width=STROKE)
    a = math.radians(40)
    cx, cy = SIZE / 2, SIZE / 2
    r = (box[2] - box[0]) / 2
    x, y = cx + r * math.cos(a), cy + r * math.sin(a)
    tri(d, [(x - 12, y - 78), (x + 74, y - 6), (x - 34, y + 52)])
    return img


def search():
    img, d = canvas()
    d.ellipse([PAD, PAD, 348, 348], outline=INK, width=STROKE)
    thick_line(d, [(318, 318), (SIZE - 46, SIZE - 46)], width=STROKE + 6)
    return img


def download():
    img, d = canvas()
    thick_line(d, [(SIZE / 2, 92), (SIZE / 2, 316)], width=STROKE + 8)
    tri(d, [(152, 262), (SIZE - 152, 262), (SIZE / 2, 392)])
    rrect(d, [PAD, SIZE - 128, SIZE - PAD, SIZE - 68], radius=28)
    return img


def export():
    img, d = canvas()
    thick_line(d, [(SIZE / 2, SIZE - 96), (SIZE / 2, 150)], width=STROKE + 8)
    tri(d, [(152, 244), (SIZE - 152, 244), (SIZE / 2, 108)])
    rrect(d, [PAD + 24, SIZE - 132, SIZE - PAD - 24, SIZE - 60], radius=26)
    return img


def folder():
    img, d = canvas()
    rrect(d, [PAD, 150, SIZE - PAD, SIZE - 74], radius=34)
    rrect(d, [PAD, 92, 250, 190], radius=30)
    d.rectangle([PAD, 150, SIZE - PAD, 176], fill=INK)
    return img


def picture():
    img, d = canvas()
    rrect(d, [PAD, 118, SIZE - PAD, SIZE - 118], radius=34)
    dot(d, 170, 208, 40, fill=(0, 0, 0, 0))
    tri(d, [(110, SIZE - 150), (250, 250), (392, SIZE - 150)], fill=(0, 0, 0, 0))
    tri(d, [(280, SIZE - 150), (382, 282), (SIZE - 106, SIZE - 150)], fill=(0, 0, 0, 0))
    return img


def trash():
    img, d = canvas()
    rrect(d, [110, 92, SIZE - 110, 136], radius=20)
    rrect(d, [196, 62, 316, 100], radius=18)
    rrect(d, [128, 158, SIZE - 128, SIZE - 70], radius=28)
    for x in (196, 256, 316):
        rrect(d, [x - 14, 206, x + 14, SIZE - 118], radius=12, fill=(0, 0, 0, 0))
    return img


def copy():
    img, d = canvas()
    # back sheet as an outline, then a transparent halo where the front sheet goes, then the
    # front sheet solid. Two solid squares touching read as one blob at 20 px - the gap is
    # the whole icon.
    rrect(d, [148, 88, 424, 364], radius=30, width=46, outline=INK)
    rrect(d, [52, 140, 350, 438], radius=52, fill=(0, 0, 0, 0))
    rrect(d, [84, 172, 340, 444], radius=30)
    return img


def chevron_down():
    img, d = canvas()
    thick_line(d, [(128, 196), (SIZE / 2, 336), (SIZE - 128, 196)], width=STROKE + 10)
    return img


def chevron_right():
    img, d = canvas()
    thick_line(d, [(196, 128), (336, SIZE / 2), (196, SIZE - 128)], width=STROKE + 10)
    return img


def close():
    img, d = canvas()
    thick_line(d, [(140, 140), (SIZE - 140, SIZE - 140)], width=STROKE + 10)
    thick_line(d, [(SIZE - 140, 140), (140, SIZE - 140)], width=STROKE + 10)
    return img


def edit():
    img, d = canvas()
    d.polygon([(128, SIZE - 130), (356, 96), (432, 172), (204, SIZE - 96)], fill=INK)
    tri(d, [(110, SIZE - 92), (212, SIZE - 116), (150, SIZE - 214)])
    rrect(d, [330, 60, 470, 200], radius=40)
    return img


def link():
    img, d = canvas()
    import math
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([60, 176, 268, 336], radius=80, outline=INK, width=52)
    ld.rounded_rectangle([244, 176, 452, 336], radius=80, outline=INK, width=52)
    layer = layer.rotate(-40, resample=Image.BICUBIC, center=(SIZE / 2, SIZE / 2))
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    return img


def shield():
    img, d = canvas()
    d.polygon([(SIZE / 2, 56), (SIZE - 78, 130), (SIZE - 78, 272), (SIZE / 2, 456),
               (78, 272), (78, 130)], fill=INK)
    d.line([(172, 250), (238, 318), (350, 184)], fill=(0, 0, 0, 0), width=54,
           joint="round")
    return img


def clock():
    img, d = canvas()
    d.ellipse([PAD, PAD, SIZE - PAD, SIZE - PAD], outline=INK, width=STROKE)
    thick_line(d, [(SIZE / 2, 148), (SIZE / 2, 268), (352, 300)], width=46)
    return img


def gauge():
    img, d = canvas()
    box = [78, 128, SIZE - 78, SIZE + 128]
    d.pieslice(box, start=180, end=360, fill=INK)
    d.pieslice([150, 200, SIZE - 150, SIZE + 4], start=180, end=360, fill=(0, 0, 0, 0))
    d.pieslice([150, 200, SIZE - 150, SIZE + 4], start=200, end=340, fill=(0, 0, 0, 0))
    d.line([(SIZE / 2, 336), (338, 224)], fill=INK, width=44)
    dot(d, SIZE / 2, 336, 40)
    rrect(d, [78, 336, SIZE - 78, 400], radius=26)
    return img


def memory():
    img, d = canvas()
    rrect(d, [60, 150, SIZE - 60, SIZE - 150], radius=26)
    for x in (150, 236, 322, 408):
        rrect(d, [x - 26, 200, x + 26, 268], radius=12, fill=(0, 0, 0, 0))
    for x in (110, 200, 290, 380):
        rrect(d, [x, SIZE - 190, x + 44, SIZE - 150], radius=10, fill=INK)
    return img


def window():
    img, d = canvas()
    rrect(d, [60, 110, SIZE - 60, SIZE - 110], radius=30)
    d.rectangle([60, 110, SIZE - 60, 190], fill=(0, 0, 0, 0))
    rrect(d, [60, 110, SIZE - 60, 190], radius=30)
    dot(d, 118, 150, 18, fill=(0, 0, 0, 0))
    dot(d, 172, 150, 18, fill=(0, 0, 0, 0))
    d.rectangle([60, 176, SIZE - 60, 190], fill=(0, 0, 0, 0))
    d.rectangle([84, 214, SIZE - 84, SIZE - 134], fill=INK)
    return img


def java():
    img, d = canvas()
    rrect(d, [110, 208, 344, SIZE - 92], radius=34)
    rrect(d, [344, 256, 434, 346], radius=44, width=40, outline=INK)
    d.rectangle([300, 256, 400, 346], fill=INK)
    d.rectangle([340, 292, 400, 312], fill=(0, 0, 0, 0))
    rrect(d, [110, 208, 344, SIZE - 92], radius=34)
    for x in (186, 268):
        d.line([(x, 168), (x + 34, 124), (x, 78)], fill=INK, width=36, joint="round")
    return img


def news():
    img, d = canvas()
    rrect(d, [PAD, 110, SIZE - PAD, SIZE - 84], radius=28)
    for i, y in enumerate((180, 250, 320, 390)):
        w = 250 if i == 0 else (320 if i % 2 else 190)
        rrect(d, [110 if i else 110, y, 110 + w, y + 40], radius=14, fill=(0, 0, 0, 0))
    rrect(d, [SIZE - 220, 180, SIZE - 110, 330], radius=16, fill=(0, 0, 0, 0))
    return img


def globe():
    img, d = canvas()
    d.ellipse([PAD, PAD, SIZE - PAD, SIZE - PAD], outline=INK, width=STROKE - 6)
    d.ellipse([188, PAD, SIZE - 188, SIZE - PAD], outline=INK, width=STROKE - 20)
    d.rectangle([PAD + 20, SIZE / 2 - 26, SIZE - PAD - 20, SIZE / 2 + 26], fill=INK)
    return img


def key():
    img, d = canvas()
    d.ellipse([70, 156, 262, 348], outline=INK, width=STROKE)
    d.rectangle([238, 232, SIZE - 70, 276], fill=INK)
    d.rectangle([SIZE - 150, 276, SIZE - 106, 340], fill=INK)
    d.rectangle([SIZE - 216, 276, SIZE - 176, 322], fill=INK)
    d.ellipse([128, 214, 206, 290], fill=(0, 0, 0, 0))
    return img


def modpack():
    img, d = canvas()
    d.polygon([(SIZE / 2, 62), (SIZE - 76, 168), (SIZE / 2, 262), (76, 168)], fill=INK)
    d.polygon([(76, 232), (SIZE / 2, 330), (SIZE / 2, 452), (76, 352)], fill=INK)
    d.polygon([(SIZE - 76, 232), (SIZE / 2, 330), (SIZE / 2, 452), (SIZE - 76, 352)], fill=INK)
    return img


def instance():
    """One cube - the "a single instance" mark, for cards that are not a grid."""
    img, d = canvas()
    d.polygon([(SIZE / 2, 74), (SIZE - 70, 176), (SIZE / 2, 278), (70, 176)], fill=INK)
    d.polygon([(70, 218), (SIZE / 2, 318), (SIZE / 2, 444), (70, 344)], fill=INK)
    d.polygon([(SIZE - 70, 218), (SIZE / 2, 318), (SIZE / 2, 444),
               (SIZE - 70, 344)], fill=INK)
    return img


GLYPHS = {
    "home": home, "instances": instances, "servers": servers, "settings": settings,
    "about": about, "play": play, "stop": stop, "pause": pause, "refresh": refresh,
    "search": search, "download": download, "export": export, "folder": folder,
    "picture": picture, "trash": trash, "copy": copy, "chevron_down": chevron_down,
    "chevron_right": chevron_right, "close": close, "edit": edit, "link": link,
    "shield": shield, "clock": clock, "gauge": gauge, "memory": memory, "window": window,
    "java": java, "news": news, "globe": globe, "key": key, "modpack": modpack,
    "instance": instance,
}


def write(name, img, force=True):
    path = os.path.join(ASSETS, "ui_%s.png" % name)
    if os.path.exists(path) and not force:
        return path
    img.save(path)
    return path


def contact(names, out):
    cols = 6
    cell = 128
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 22)), (16, 31, 40))
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        img = GLYPHS[name]() if name in GLYPHS else Image.open(
            os.path.join(ASSETS, "ui_%s.png" % name)).convert("RGBA")
        tinted = Image.new("RGBA", img.size, (46, 230, 224, 0))
        tinted.putalpha(img.split()[3])
        tinted.thumbnail((cell - 24, cell - 24))
        x, y = (i % cols) * cell, (i // cols) * (cell + 22)
        sheet.paste(tinted, (x + (cell - tinted.width) // 2, y + (cell - 22 - tinted.height) // 2),
                    tinted)
        draw.text((x + 10, y + cell - 16), name, fill=(234, 252, 255))
    sheet.save(out)


def main():
    argv = sys.argv[1:]
    force = "-f" in argv
    names = [n for n in GLYPHS]
    made = 0
    for name in names:
        path = write(name, GLYPHS[name](), force=force)
        if path:
            made += 1
    print("%d glyphs in %s" % (made, ASSETS))
    for shipped in ("friends", "account", "new", "discord"):
        print("  kept as supplied: ui_%s.png %s" % (shipped, "present" if os.path.exists(
            os.path.join(ASSETS, "ui_%s.png" % shipped)) else "MISSING"))
    if "-contact" in argv:
        # the sheet is a dev look-over, not an asset: it goes next to the build scratch,
        # never into assets/, or it would ship in the exe
        out = os.path.join(os.path.dirname(HERE), "glyphs_contact.png")
        contact(sorted(names) + ["friends", "account", "new", "discord"], out)
        print("contact sheet:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
