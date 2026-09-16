"""Render the no-colour (mono) icon set: assets/icon_mono.png and assets/icon_mono.ico.

The mono mark exists for the places colour either is not available or is not wanted -
a printed sheet, a black-and-white listing, a system icon theme that renders the tile
on a light background. Same silhouette as the colour icon, one grey per facet instead
of teal and violet, so the cube still reads at 16 px.

Two ways to build it, chosen automatically:

* if ``cairosvg`` is importable, the vector art is re-rendered with the mono palette -
  the same source of truth as ``make_logo.py``, so the shapes cannot drift apart;
* otherwise the existing ``assets/emblem.png`` is recoloured: every pixel is matched to
  the nearest colour in the palette that ``make_logo.py`` declares, and swapped for that
  colour's grey. Flat vector art means the match is exact, not an approximation.

Run:  python3 tools/make_mono_icon.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
SOURCE = os.path.join(HERE, "make_logo.py")

# Each palette entry of make_logo.py, and the grey it becomes. Not luminance: the top
# face has to stay the brightest thing on the tile and the seams the darkest, which is
# what makes the cube read at icon sizes. Every value is a neutral grey on purpose - a
# blue-tinted "mono" still reads as coloured next to a black-and-white sheet.
MONO = {
    "FACE_TOP":     "#f5f5f5",
    "FACE_TOP_HI":  "#ffffff",
    "FACE_RIGHT":   "#c9c9c9",
    "FACE_LEFT":    "#8a8a8a",
    "TILE_TOP":     "#1c1c1c",
    "TILE_BOT":     "#121212",
    "TILE_EDGE":    "#303030",
    "EDGE":         "#060606",
    "TEXT":         "#f5f5f5",
    "SUBTEXT":      "#c9c9c9",
}
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def colour(name, default):
    """One ``NAME = "#rrggbb"`` line from make_logo.py, read as text.

    Reading the file instead of importing it keeps this tool working on a machine
    without cairo: the palette is the only thing worth sharing between the two scripts.
    """
    try:
        src = open(SOURCE, encoding="utf-8").read()
    except OSError:
        return default
    m = re.search(r'^%s\s*=\s*"(#[0-9a-fA-F]{6})"' % re.escape(name), src, re.M)
    return m.group(1) if m else default


def rgb(hexstr):
    hexstr = hexstr.lstrip("#")
    return tuple(int(hexstr[i:i + 2], 16) for i in (0, 2, 4))


def build_from_vector(png_path):
    """Preferred: re-render the same SVG with mono colours."""
    try:
        sys.path.insert(0, HERE)
        import make_logo as ml                                     # noqa: F401
    except Exception:
        return False
    try:
        for name, grey in MONO.items():
            if hasattr(ml, name):
                setattr(ml, name, grey)
        ml.render(ml.emblem_svg(600), png_path, 600, 600)
        return True
    except Exception as err:
        print("vector path failed (%s); falling back to recolouring emblem.png" % err)
        return False


def build_from_emblem(png_path):
    """Fallback: swap every emblem pixel for the grey of the palette colour it matches."""
    import numpy
    from PIL import Image
    src_path = os.path.join(ASSETS, "emblem.png")
    if not os.path.isfile(src_path):
        raise SystemExit("neither cairosvg nor assets/emblem.png is available")
    im = Image.open(src_path).convert("RGBA")
    arr = numpy.asarray(im).astype(numpy.int16)
    names = sorted(MONO)
    palette = numpy.array([rgb(colour(n, MONO[n])) for n in names], dtype=numpy.int16)
    greys = numpy.array([rgb(MONO[n]) for n in names], dtype=numpy.uint8)
    out = arr.copy()
    alpha = arr[..., 3] > 8
    rows = arr.shape[0]
    for y0 in range(0, rows, 128):                 # chunked: no 400 MB temporary
        sel = alpha[y0:y0 + 128]
        block = arr[y0:y0 + 128, ..., :3]
        if not sel.any():
            continue
        pix = block[sel]
        dist = ((pix[:, None, :].astype(numpy.int32) - palette[None, :, :]) ** 2).sum(-1)
        idx = dist.argmin(1)
        new = numpy.zeros((pix.shape[0], 4), dtype=numpy.uint8)
        new[:, :3] = greys[idx]
        new[:, 3] = arr[y0:y0 + 128][sel][:, 3]
        out_block = out[y0:y0 + 128]
        out_block[sel] = new
        out[y0:y0 + 128] = out_block
    Image.fromarray(out.astype(numpy.uint8), "RGBA").save(png_path)
    return True


def main():
    png = os.path.join(ASSETS, "icon_mono.png")
    ico = os.path.join(ASSETS, "icon_mono.ico")
    how = "vector"
    if not build_from_vector(png):
        how = "recoloured emblem"
        build_from_emblem(png)
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    # the .ico carries the same art at every size Windows asks for, so a taskbar
    # thumbnail never gets an upscaled 16 px version of the tile
    im.save(png)
    im.save(ico, format="ICO", sizes=ICO_SIZES, bitmap_format="rgba")
    print("wrote %s (%d px, %s palette) and %s (%d sizes)"
          % (os.path.basename(png), im.size[0], how, os.path.basename(ico), len(ICO_SIZES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
