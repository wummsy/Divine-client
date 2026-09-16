"""Generate the Divine Client logo assets as clean, hand-built vector art.

The mark is an isometric cube (a nod to Minecraft's block world): a bright teal
top face, a violet left face and a deep-teal right face, sitting on a rounded app
tile. Flat colours with a single crisp highlight edge - no neon bloom, no fake
circuit backdrop. Renders emblem.png, logo.png, logo_stacked.png and icon.ico.
"""
import os

import cairosvg
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# Palette (matches the app theme: teal-cyan primary, violet accent).
TILE_TOP = "#141a2b"     # tile background (top)
TILE_BOT = "#0e1220"     # tile background (bottom)
TILE_EDGE = "#242c44"
FACE_TOP = "#4be6d6"     # top face (bright teal, catches the light)
FACE_TOP_HI = "#6ff4e6"  # top-face inner highlight
FACE_LEFT = "#8f6dff"    # left face (violet, in shade)
FACE_RIGHT = "#22b6a8"   # right face (deep teal, in shade)
EDGE = "#0b1220"         # crisp seams between faces
TEXT = "#f3f6fc"
SUBTEXT = "#38e1d0"


def _cube_svg(cx, cy, r):
    """Isometric cube centred at (cx, cy). ``r`` is the half-width of the cube.

    Uses a 2:1 isometric projection. Three visible faces (top, left, right) meet
    at the centre; thin dark seams keep the facets crisp.
    """
    h = r * 0.5          # vertical offset of an isometric step
    # key points of the cube silhouette
    top = (cx, cy - r)              # top vertex
    right = (cx + r, cy - h / 1.0)  # upper-right
    left = (cx - r, cy - h / 1.0)   # upper-left
    mid = (cx, cy)                  # centre (where three faces meet at front)
    bl = (cx - r, cy + h)           # bottom-left
    br = (cx + r, cy + h)           # bottom-right
    bottom = (cx, cy + r)           # bottom vertex (front lower point)

    def pts(seq):
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in seq)

    top_face = [top, right, mid, left]
    left_face = [left, mid, bottom, bl]
    right_face = [right, br, bottom, mid]

    # a soft highlight wedge on the top face, near the top vertex
    hi = [top, ((top[0] + right[0]) / 2, (top[1] + right[1]) / 2),
          mid, ((top[0] + left[0]) / 2, (top[1] + left[1]) / 2)]

    return (
        f'<polygon points="{pts(top_face)}" fill="{FACE_TOP}"/>'
        f'<polygon points="{pts(hi)}" fill="{FACE_TOP_HI}" opacity="0.55"/>'
        f'<polygon points="{pts(left_face)}" fill="{FACE_LEFT}"/>'
        f'<polygon points="{pts(right_face)}" fill="{FACE_RIGHT}"/>'
        # seams
        f'<polyline points="{pts([top, mid])}" stroke="{EDGE}" stroke-width="{r*0.05:.2f}" fill="none"/>'
        f'<polyline points="{pts([left, mid])}" stroke="{EDGE}" stroke-width="{r*0.05:.2f}" fill="none"/>'
        f'<polyline points="{pts([right, mid])}" stroke="{EDGE}" stroke-width="{r*0.05:.2f}" fill="none"/>'
        f'<polyline points="{pts([mid, bottom])}" stroke="{EDGE}" stroke-width="{r*0.05:.2f}" fill="none"/>'
    )


def emblem_svg(size=600):
    """A rounded app tile containing the isometric cube."""
    tile_r = size * 0.22
    cx = size / 2.0
    cy = size / 2.0
    r = size * 0.30

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<defs>'
        f'<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{TILE_TOP}"/>'
        f'<stop offset="1" stop-color="{TILE_BOT}"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<rect x="2" y="2" width="{size-4}" height="{size-4}" rx="{tile_r:.1f}" '
        f'fill="url(#tile)" stroke="{TILE_EDGE}" stroke-width="4"/>'
        f'{_cube_svg(cx, cy, r)}'
        f'</svg>'
    )



def logo_svg(w=1200, h=420):
    """Emblem tile beside the DIVINE / CLIENT wordmark, transparent background."""
    em = 320
    em_x = 70
    em_y = (h - em) / 2.0
    emblem = emblem_svg(size=em)
    inner = emblem[emblem.index('>') + 1:emblem.rindex('</svg>')]
    tx = em_x + em + 60
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<g transform="translate({em_x},{em_y})">{inner}</g>'
        f'<text x="{tx}" y="{h/2 - 6}" text-anchor="start" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" '
        f'font-size="132" letter-spacing="6" fill="{TEXT}">DIVINE</text>'
        f'<text x="{tx + 6}" y="{h/2 + 78}" text-anchor="start" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" '
        f'font-size="52" letter-spacing="30" fill="{SUBTEXT}">CLIENT</text>'
        f'</svg>'
    )


def logo_stacked_svg(w=520, h=560):
    """Emblem above the DIVINE / CLIENT wordmark - used in the narrow sidebar."""
    em = 300
    em_x = (w - em) / 2.0
    em_y = 8
    emblem = emblem_svg(size=em)
    inner = emblem[emblem.index('>') + 1:emblem.rindex('</svg>')]
    divine_y = em_y + em + 110
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<g transform="translate({em_x},{em_y})">{inner}</g>'
        f'<text x="{w/2}" y="{divine_y}" text-anchor="middle" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" '
        f'font-size="118" letter-spacing="6" fill="{TEXT}">DIVINE</text>'
        f'<text x="{w/2 + 4}" y="{divine_y + 62}" text-anchor="middle" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" '
        f'font-size="46" letter-spacing="26" fill="{SUBTEXT}">CLIENT</text>'
        f'</svg>'
    )


def render(svg, path, w, h):
    cairosvg.svg2png(bytestring=svg.encode(), write_to=path,
                     output_width=w, output_height=h)


def main():
    render(emblem_svg(600), os.path.join(ASSETS, "emblem.png"), 600, 600)
    render(logo_svg(1200, 420), os.path.join(ASSETS, "logo.png"), 1200, 420)
    render(logo_stacked_svg(520, 560), os.path.join(ASSETS, "logo_stacked.png"), 520, 560)

    base = Image.open(os.path.join(ASSETS, "emblem.png")).convert("RGBA")
    base.save(os.path.join(ASSETS, "icon.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote emblem.png, logo.png, icon.ico")


if __name__ == "__main__":
    main()
