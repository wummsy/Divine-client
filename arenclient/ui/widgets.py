"""Reusable UI helpers and small widgets."""
import os

import customtkinter as ctk

from .. import paths
from . import theme

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def load_ctk_image(relative_path, size):
    """Load an image from assets as a CTkImage, or None if unavailable."""
    if not _HAS_PIL:
        return None
    full = paths.resource_path(relative_path)
    if not os.path.exists(full):
        return None
    try:
        img = Image.open(full).convert("RGBA")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None


def load_image_file(path, size):
    """Load any image from an absolute/relative path as a CTkImage, or None."""
    if not (_HAS_PIL and path and os.path.exists(path)):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize(size)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None


class Card(ctk.CTkFrame):
    """A rounded panel that groups content. Solid, always.

    The radius is small and the fill is the palette's own panel colour rather than
    "transparent with a border": a card that lets its background through is a card that has
    to be repainted by someone else, and on Windows nobody does.
    """
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", theme.COL["bg2"])
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", theme.COL["border_soft"])
        super().__init__(master, **kwargs)


def section_label(master, text, glyph=None):
    """A small caps heading. ``glyph`` is an ``assets/ui_*.png`` name, put left of the words.

    The mark is drawn in the same family as the supplied four, so a heading reads the same
    in the sidebar, on a card and in a dialog - and it stays a text label when there is no
    Pillow to load it with.
    """
    if glyph:
        img = load_glyph("assets/%s.png" % glyph if "/" not in glyph else glyph, (15, 15),
                         color=theme.COL["text_faint"])
        if img is not None:
            return ctk.CTkLabel(master, text="  %s" % text, image=img, compound="left",
                                font=theme.font(11, "bold"),
                                text_color=theme.COL["text_faint"])
    return ctk.CTkLabel(master, text=text, font=theme.font(11, "bold"),
                        text_color=theme.COL["text_faint"])


def pill(master, text, color=None, text_color="#04121a"):
    """A small rounded status/label chip."""
    return ctk.CTkLabel(master, text=text, font=theme.font(10, "bold"),
                        fg_color=color or theme.COL["bg3"],
                        text_color=text_color, corner_radius=8,
                        padx=8, pady=2)


def accent_button(master, text, command, **kwargs):
    kwargs.setdefault("font", theme.font(15, "bold"))
    kwargs.setdefault("height", 46)
    kwargs.setdefault("corner_radius", 12)
    kwargs.setdefault("fg_color", theme.COL["accent"])
    kwargs.setdefault("hover_color", theme.COL["accent_hi"])
    kwargs.setdefault("text_color", "#04121a")
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def ghost_button(master, text, command, **kwargs):
    kwargs.setdefault("font", theme.font(13, "bold"))
    kwargs.setdefault("height", 38)
    kwargs.setdefault("corner_radius", 10)
    kwargs.setdefault("fg_color", theme.COL["bg3"])
    kwargs.setdefault("hover_color", theme.COL["bg_hover"])
    kwargs.setdefault("text_color", theme.COL["text"])
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def danger_button(master, text, command, **kwargs):
    kwargs.setdefault("font", theme.font(13, "bold"))
    kwargs.setdefault("height", 38)
    kwargs.setdefault("corner_radius", 10)
    kwargs.setdefault("fg_color", "transparent")
    kwargs.setdefault("hover_color", "#3a1420")
    kwargs.setdefault("text_color", theme.COL["danger"])
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", theme.COL["danger"])
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


# --------------------------------------------------------------------- glyphs
def _rgb(color):
    """'#2ee6e0' -> (46, 230, 224). Anything unparsable comes back white."""
    text = str(color or "#ffffff").lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (255, 255, 255)


def tint_pil(img, color):
    """Recolour an alpha-cut glyph.

    The UI icons are black shapes on transparency, which on a dark theme means invisible.
    So the shape's own alpha becomes the mask and the colour fills it; the marks *inside*
    the shape (Discord's eyes, the gap under a head) are transparent holes and read as
    whatever panel they sit on, which is what the artwork asks for.
    """
    if not _HAS_PIL or img is None:
        return img
    src = img.convert("RGBA")
    r, g, b = _rgb(color)
    out = Image.new("RGBA", src.size, (r, g, b, 0))
    out.putalpha(src.split()[3])
    return out


_GLYPH_CACHE = {}
_GLYPH_MAX = 16


def load_glyph(relative_path, size, color=None):
    """A UI icon from ``assets/``, tinted for the theme. None if PIL or the file is absent.

    Every caller must already have a text fallback: on a machine without Pillow, or a
    partially installed build, a button that only ever had an icon would be blank.

    Cached by (file, size, colour) because these are built while pages are being painted -
    the sidebar, the friends header and the Instances toolbar all ask for one per widget, and
    opening and rescaling the same PNG twelve times a rebuild is exactly the kind of
    file-and-decode work that belongs off the UI thread. The image object is shared instead.
    """
    if not _HAS_PIL:
        return None
    key = (relative_path, tuple(size), color)
    hit = _GLYPH_CACHE.get(key)
    if hit is not None:
        return hit
    full = paths.resource_path(relative_path)
    if not os.path.exists(full):
        return None
    try:
        img = Image.open(full).convert("RGBA").resize((max(1, int(size[0])),
                                                       max(1, int(size[1]))))
        img = tint_pil(img, color or theme.COL["text_dim"])
        out = ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None
    if len(_GLYPH_CACHE) >= _GLYPH_MAX:
        _GLYPH_CACHE.clear()
    _GLYPH_CACHE[key] = out
    return out


# ------------------------------------------------------------------- the wash
def _mix(c1, c2, t):
    """Linear blend of two hex colours. ``t`` is clamped, and the result is a hex string."""
    a, b = _rgb(c1), _rgb(c2)
    t = 0.0 if t < 0 else (1.0 if t > 1 else float(t))
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _clip_corner(w, h, k):
    """The part of the box where ``x/w + y/h <= k``, as a point list.

    That half-plane is one band of a corner-to-corner wash, and clipping a rectangle against
    one line is the only geometry the painter needs: Sutherland-Hodgman on the four box
    corners, which stays correct at the ends (an empty list before the wash starts, the whole
    box after it) where the "triangle then quad" shortcut I tried first turned degenerate.
    """
    if k <= 0:
        return []
    if k >= 2:
        return [(0, 0), (w, 0), (w, h), (0, h)]
    box = [(0, 0), (w, 0), (w, h), (0, h)]
    out = []
    for i, (x0, y0) in enumerate(box):
        x1, y1 = box[(i + 1) % len(box)]
        s0 = x0 / w + y0 / h - k
        s1 = x1 / w + y1 / h - k
        if s0 <= 0:
            out.append((x0, y0))
        if (s0 < 0 < s1) or (s1 < 0 < s0):
            t = s0 / (s0 - s1)
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


class Gradient(ctk.CTkFrame):
    """A panel that paints a wash behind its children, on its own canvas.

    Why not an image: an image is a fixed rectangle of pixels, so it is only correct at the
    size it was made at. On a maximize, a restore from the taskbar, or a DPI change - all of
    which resize the window without repainting the image first - Tk shows the old pixels
    stretched or the gap beside them, and that is the smear people report as a glitch. Canvas
    *items* cannot do that: Tk redraws items from their geometry on every expose, so a
    repaint-free resize still comes out right, and repainting them costs microseconds.

    The bands are painted inside ``_draw``, which is what CustomTkinter calls after it has
    drawn its own background, so the wash is always on top of the frame fill and always under
    the children. No timer, no ticker, nothing to stop.
    """

    MAX_BANDS = 72
    MIN_BANDS = 18
    TAG = "divinewash"

    def __init__(self, master, kind="main", c1=None, c2=None, angle=None,
                 corner_radius=0, wash=True, **kwargs):
        # The frame's own colour is the dark end of the wash, not "transparent": a rounded
        # corner or a plain-Tk child asks its master for a colour, and it should get the
        # colour that is actually behind it.
        kwargs.setdefault("fg_color", theme.wash_base(kind))
        kwargs.setdefault("border_width", 0)
        # CustomTkinter paints from its own __init__, so every attribute _draw reads has to
        # exist before super() is called - not doing that is an AttributeError during the
        # first draw, which Tk reports as a broken window rather than a stack trace.
        self._kind = kind
        self._c1 = c1
        self._c2 = c2
        self._angle = angle
        self._wash_on = bool(wash)
        self._wash_size = (0, 0)
        super().__init__(master, corner_radius=corner_radius, **kwargs)
        self.bind("<Map>", self._on_map, add="+")

    # -- colours
    def colors(self):
        c1 = self._c1 or theme.gradient_colors(self._kind)[0]
        c2 = self._c2 or theme.gradient_colors(self._kind)[1]
        angle = self._angle or theme.gradient_angle(self._kind)
        return c1, c2, angle

    def set_style(self, kind=None, c1=None, c2=None, angle=None, wash=None):
        """Re-point the wash at another palette entry and repaint now."""
        if kind is not None:
            self._kind = kind
        if c1 is not None:
            self._c1 = c1
        if c2 is not None:
            self._c2 = c2
        if angle is not None:
            self._angle = angle
        if wash is not None:
            self._wash_on = bool(wash)
        self._wash_size = (0, 0)
        try:
            self.configure(fg_color=theme.wash_base(self._kind))
        except Exception:
            pass
        self._repaint()

    # -- painting
    def _on_map(self, _event=None):
        # Coming back from the taskbar: the size may not have changed at all, but if the
        # canvas was never painted (built while the window was withdrawn) this is the
        # first moment the real geometry exists.
        if self._wash_size[0] < 2 or self._wash_size[1] < 2:
            self._repaint()

    def _repaint(self):
        try:
            self._draw(no_color_updates=True)
        except Exception:
            pass

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        # Ask Tk how big we are rather than reading CustomTkinter's own size cache: the number
        # we have to paint is the window's, _current_width is the library's guess at it, and the
        # second one is not a documented member to depend on.
        try:
            w, h = int(self.winfo_width()), int(self.winfo_height())
        except Exception:
            w, h = 0, 0
        cv = getattr(self, "_canvas", None)
        if cv is None or not cv.winfo_exists():
            return
        if w < 2 or h < 2:
            return
        cv.delete(self.TAG)
        c1, c2, angle = self.colors()
        # the base colour goes down first, whatever happens: the wash is painted over it and a
        # surface of this widget's size can then never expose the theme grey, not even in the
        # frame between a resize and the item redraw
        cv.create_rectangle(0, 0, w + 1, h + 1, fill=c1, outline="", tags=self.TAG)
        if not getattr(self, "_wash_on", False):
            return
        if angle == "flat" or c1 == c2:
            cv.create_rectangle(0, 0, w + 1, h + 1, fill=c1, outline="", tags=self.TAG)
            return
        n = max(self.MIN_BANDS, min(self.MAX_BANDS, max(w, h) // 12))
        if angle == "vertical":
            for i in range(n):
                t0, t1 = i * h / n, (i + 1) * h / n + 1
                cv.create_rectangle(-1, t0 - 1, w + 1, t1,
                                    fill=_mix(c1, c2, (i + 0.5) / n), outline="", tags=self.TAG)
        elif angle == "horizontal":
            for i in range(n):
                t0, t1 = i * w / n, (i + 1) * w / n + 1
                cv.create_rectangle(t0 - 1, -1, t1, h + 1,
                                    fill=_mix(c1, c2, (i + 0.5) / n), outline="", tags=self.TAG)
        else:
            # corner to corner. Each band is the region between two cut lines, which is the
            # difference of two corner polygons - so paint the biggest corner first and each
            # smaller one over it: the last thing drawn on any pixel is its own band.
            for i in range(n, 0, -1):
                pts = _clip_corner(w, h, 2.0 * i / n)
                if len(pts) < 3:
                    continue
                flat = [v for pt in pts for v in pt]
                cv.create_polygon(*flat, fill=_mix(c1, c2, (i - 0.5) / n),
                                  outline="", smooth=False, tags=self.TAG)

    def destroy(self):
        try:
            cv = getattr(self, "_canvas", None)
            if cv is not None and cv.winfo_exists():
                cv.delete(self.TAG)
        except Exception:
            pass
        try:
            super().destroy()
        except Exception:
            pass


class PageFrame(Gradient):
    """What every page is built on: a solid panel with the theme's wash on its own canvas.

    Each page paints its own background instead of sharing a backdrop with the widgets on
    top of it. It looks the same, and it removes the whole class of "the old page is still
    under the new one": when a page is hidden and another shown, each one's canvas redraws
    its own items, so there is nothing to leave behind.
    """

    #: pages are flat by default. Their wash would only be visible in the few pixels of
    #: margin around a column of cards, where it reads as a border rather than as depth -
    #. and every pixel of wash inside a scroll frame is a seam. The palette swap in Settings
    #. > Appearance is what changes how a page looks, and it does so properly.
    wash_default = False

    def __init__(self, master, kind="page", wash=None, **kwargs):
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("border_width", 0)
        if wash is None:
            wash = self.wash_default
        if not wash:
            kwargs["fg_color"] = kwargs.get("fg_color") or theme.COL["bg"]
        super().__init__(master, kind=kind, wash=wash, **kwargs)


def surface_color(widget):
    """The colour actually behind ``widget``: its own, or the nearest ancestor that has one.

    A child that must not let the background through - a scroll frame's canvas, mostly -
    needs the colour of whatever it sits on. Asking up the chain is the only answer that
    stays right when a card moves into a dialog or a page's base changes with the palette,
    and it is the reason this UI can keep transparent rows without them smearing.
    """
    node = widget
    for _i in range(12):
        if node is None:
            break
        try:
            val = node.cget("fg_color")
        except Exception:
            val = None
        if isinstance(val, (tuple, list)):
            val = val[0]
        if val and str(val) != "transparent":
            return val
        node = getattr(node, "master", None)
    return theme.COL["bg"]


def scroll_frame(master, fg=None, **kwargs):
    """A ``CTkScrollableFrame`` that states the colour it is sitting on.

    A scroll frame is the one widget whose inside cannot be "transparent" and stay correct:
    it is a canvas, and a canvas that paints nothing leaves the previous scroll position
    behind while you drag. So it asks ``surface_color`` for the parent's own colour and paints
    that - same look, no smear, and it follows the palette if the page underneath changes.
    """
    kwargs.setdefault("fg_color", fg or surface_color(master))
    kwargs.setdefault("border_width", 0)
    kwargs.setdefault("scrollbar_button_color", theme.COL["bg3"])
    kwargs.setdefault("scrollbar_button_hover_color", theme.COL["bg_hover"])
    kwargs.setdefault("scrollbar_button_clicked_color", theme.COL["accent"])
    try:
        return ctk.CTkScrollableFrame(master, **kwargs)
    except TypeError:
        # an older CustomTkinter has no scrollbar colour arguments at all; the bar is then
        # whatever the theme says, which is a plainer look and not a crash
        for key in ("scrollbar_button_color", "scrollbar_button_hover_color",
                    "scrollbar_button_clicked_color"):
            kwargs.pop(key, None)
        return ctk.CTkScrollableFrame(master, **kwargs)


# ---------------------------------------------------------------- letter tiles
def letter_tile(text, size=(46, 46), bg=None, fg=None, radius=None, font=None):
    """A tile with one letter on it, for anything that has no picture.

    Modpacks, mods without a thumbnail, friends with no avatar and instances with no
    screenshot all need *something* square in the same slot, and a blank square reads as a
    broken download. This is generated locally, so it is instant and works offline; the real
    picture replaces it when (if) one arrives.
    """
    if not _HAS_PIL:
        return None
    try:
        from PIL import ImageDraw, ImageFont
    except Exception:
        return None
    w, h = max(8, int(size[0])), max(8, int(size[1]))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(radius if radius is not None else max(4, min(w, h) // 5))
    try:
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=_rgb(bg or theme.COL["bg3"]))
    except Exception:                                  # older Pillow: no rounded_rectangle
        draw.rectangle([0, 0, w - 1, h - 1], fill=_rgb(bg or theme.COL["bg3"]))
    ch = (str(text or "?").strip() or "?")[0].upper()
    px = int(h * 0.62)
    picked = None
    for cand in (font, "DejaVuSans-Bold", "Helvetica", "Arial"):
        if not cand:
            continue
        try:
            picked = ImageFont.truetype(cand, px)
            break
        except Exception:
            continue
    if picked is None:
        picked = ImageFont.load_default()
    try:
        box = draw.textbbox((0, 0), ch, font=picked)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text(((w - tw) / 2 - box[0], (h - th) / 2 - box[1]), ch, font=picked,
                  fill=_rgb(fg or theme.COL["accent"]))
    except Exception:
        pass
    return img


_TILES = {}


def letter_tile_image(text, size=(46, 46), bg=None, fg=None):
    """``letter_tile`` as a ``CTkImage``, cached by (letter, size) - pages reuse them."""
    if not _HAS_PIL:
        return None
    key = ((str(text or "?").strip() or "?")[0].upper(), int(size[0]), int(size[1]),
            bg or "", fg or "")
    hit = _TILES.get(key)
    if hit is not None:
        return hit
    img = letter_tile(text, size, bg=bg, fg=fg)
    if img is None:
        return None
    out = ctk.CTkImage(light_image=img, dark_image=img, size=(int(size[0]), int(size[1])))
    if len(_TILES) > 220:
        _TILES.clear()
    _TILES[key] = out
    return out


def set_tile(label, name, size=(46, 46), bg=None, fg=None):
    """Put the letter tile on ``label`` right now. Returns True if it did."""
    img = letter_tile_image(name, size, bg=bg, fg=fg)
    if img is None:
        return False
    try:
        label.configure(image=img, text="")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- small helpers
def fixed_label(master, text="", px=120, **kwargs):
    """A readout whose requested width does not depend on its text. ``px`` is pixels.

    A value label that grows by two pixels every time the number changes drags the card, the
    scroll frame and the window through a re-layout on each slider tick - sixty times a second
    while the button is under the pointer. That reflow storm, not a repaint bug, is what
    "it glitches when I move a slider" is: the readout is the widest thing in the row and the
    row is inside a canvas, so re-laying it out means scrolling the canvas a little.

    A fixed pixel width means the text changes and nothing else moves. The number is chosen
    for the widest value it will ever hold, so it never clips.
    """
    kwargs.setdefault("anchor", "e")
    kwargs.setdefault("width", int(px))
    return ctk.CTkLabel(master, text=text, **kwargs)


# ---------------------------------------------------------------- text fitting
_FONTS = {}


def face_for(font):
    """A ``tkfont`` for a ``CTkFont``, so text can be measured before it is drawn.

    Cached, because ``tkfont.Font`` registers a new named font on every call and a resize asks
    for the same two or three faces over and over.
    """
    try:
        import tkinter.font as tkfont
        if hasattr(font, "cget"):
            key = (str(font.cget("family")), int(font.cget("size")),
                   str(font.cget("weight") or "normal"))
        else:
            # `theme.title_font()` hands back a plain Tk font tuple, which is what a canvas
            # item is given; reading `.cget` off it raises, and a swallowed AttributeError here
            # once meant every measurement returned 0 and every "does it fit" said yes.
            seq = list(font) + ["normal"]
            fam = str(seq[0]) if seq and seq[0] else ""
            if not fam or fam.lstrip("-").isdigit():      # ("", 26, "bold") means the default face
                fam = tkfont.nametofont("TkDefaultFont").cget("family")
            key = (fam, int(seq[1] or 12), str(seq[2] or "normal"))
        face = _FONTS.get(key)
        if face is None:
            face = tkfont.Font(family=key[0], size=key[1], weight=key[2])
            _FONTS[key] = face
        return face
    except Exception:
        return None


def text_width(text, font):
    face = face_for(font)
    if face is None:
        return 0
    try:
        return face.measure(text)
    except Exception:
        return 0


def clip_to_width(text, font, room):
    """Shorten `text` with an ellipsis until it is `room` pixels wide.

    Needed wherever text cannot wrap: a canvas item (the hero caption is painted on the art and
    a canvas *clips* rather than wraps) and a header line with a fixed height. In both cases the
    alternative is what those used to be - "An extremely long instance nam" ending mid-letter at
    the edge of the card, which is the same defect as a clipped label with a nicer name.
    """
    if not text or room <= 0 or text_width(text, font) <= room:
        return text
    cut = text
    while cut and text_width(cut + "\u2026", font) > room:
        cut = cut[:-1]
    return (cut.rstrip() + "\u2026") if cut else "\u2026"


def flow_label(master, text="", min_px=120, band=24, tries=400, wrap=None,
               max_lines=None, **kwargs):
    """A sentence that wraps to the box it is really in, instead of being cut off by it.

    Every long piece of copy in this UI used to carry a hand-picked ``wraplength`` - 380, 560,
    720 pixels - chosen by eye at the window size that happened to be open that day. Shrink the
    window, or put the same label in a narrower card, and the cell ends up smaller than the
    wrap: Tk paints the lines it has room for and throws the rest away, which is how a
    description became "A clean multi-instance Minecraft l" and how the header's instance name
    became one letter beside its own Play button.

    So the label measures its own allocation and re-wraps to fit it. Fitting is the invariant
    rather than a guess, and the label then never asks for more than the cell can give.

    Measuring in a feedback loop needs three brakes, and they are not decoration: wrapping onto
    two lines makes the content taller, a scroll frame answers by showing a scrollbar, the
    scrollbar takes about 16 px off the viewport, and a naive "re-wrap when the width changed"
    then walks the label back and forth for as long as the window exists - it does not settle, it
    spins, and the whole UI stops with it. The brakes: a re-wrap needs a change of ``band`` pixels
    (wider than any scrollbar), the wrap is always a margin *inside* the box rather than "unlimited
    when it fits", and ``tries`` is a runaway fuse rather than a plan.
    """
    kwargs.setdefault("justify", "left")
    kwargs.setdefault("anchor", "w")
    if wrap:
        # A starting wrap for the case where nothing else bounds the label: a row inside a card
        # that hugs its children takes its width from the widest thing in it, so an unwrapped
        # sentence there sets the width of the whole panel and then never needs to wrap. Given a
        # first line length to work to, the panel stays narrow and this still re-measures itself.
        kwargs["wraplength"] = int(wrap)
    lbl = ctk.CTkLabel(master, text=text, **kwargs)
    state = {"have": -1, "wrap": int(wrap or 0), "busy": False, "tries": tries,
             "claim": False, "text": text, "internal": False}

    def _claim_cell():
        """Ask for the whole cell, once, if the call site asked for less.

        A label gridded with ``sticky="w"`` is given *its own* requested width, not the cell's -
        so a label that measures its own box to decide where to wrap measures a box that only
        ever shrinks. Home's play title did exactly that at full size: "Fabric" on one line and
        "1.21.11" under it in a card 700 px wide, because the label first asked for 160 px, got
        160 px, wrapped to 152 and stopped. Filling the cell horizontally is the only shape in
        which self-measuring works, and no call site that wants a wrapping paragraph wants a
        narrower one, so this is done here rather than at sixty places of ``sticky``.
        """
        state["claim"] = True
        try:
            mgr = lbl.winfo_manager()
            if mgr == "grid":
                st = str(lbl.grid_info().get("sticky", "")).lower()
                if "e" not in st or "w" not in st:
                    lbl.grid_configure(sticky=(st + "ew").lstrip())
            elif mgr == "pack":
                if str(lbl.pack_info().get("fill", "none")).lower() not in ("x", "both"):
                    lbl.pack_configure(fill="x")
        except Exception:
            pass

    def _lines(want):
        """Put the text back on the number of lines the box can hold.

        A label with `max_lines` is a *line*, not a paragraph: the header's instance name sits in
        a row that is one line tall, and letting Tk break it across three lines makes the strip
        grow by two rows' height and the text run under the Play button. So the wrap is set, and
        whatever the wrap cannot hold becomes an ellipsis.
        """
        if not max_lines:
            return
        full = state["text"]
        if not full:
            return
        room = max(24, int(want)) * max(1, int(max_lines))
        shown = clip_to_width(full, lbl.cget("font"), room) if want else full
        if shown != str(lbl.cget("text")):
            state["internal"] = True
            try:
                lbl.configure(text=shown)
            finally:
                state["internal"] = False

    def _fit(_event=None):
        if state["busy"]:
            return
        state["busy"] = True
        try:
            if not state["claim"]:
                _claim_cell()
            if not lbl.winfo_ismapped() or state["tries"] <= 0:
                return
            have, req = int(lbl.winfo_width()), int(lbl.winfo_reqwidth())
            if have < 40 or abs(have - state["have"]) < band:
                return
            state["have"] = have
            # The wrap always follows the box, in both directions, and never goes wider than
            # it. That is what makes this settle: a label wrapped to its own width minus a
            # margin cannot ask for more than the cell holds, so there is nothing for the
            # geometry manager to react to. The old habit of "unwrap it when there is room"
            # is what made it spin - setting a huge wraplength to say "it fits" makes the
            # label's *requested* width the whole sentence, the card then grows to match, and
            # a scroll frame answers by showing or hiding its scrollbar, which is 16 px off
            # the viewport, which brings the label back to not fitting. Round and round.
            want = max(min_px, have - 8)
            if abs(want - state["wrap"]) < band:
                return
            state["wrap"] = want
            state["tries"] -= 1
            _lines(want)
            lbl.configure(wraplength=want)
        except Exception:
            return                      # mid-rebuild; the next Configure measures it again
        finally:
            state["busy"] = False

    lbl.bind("<Configure>", _fit, add="+")

    def set_flow_text(value):
        """The copy the label is *supposed* to show; the fitting runs again from it.

        Call this instead of ``configure(text=...)`` on a flow label whose text changes at run
        time, or an ellipsis added earlier survives and the new sentence arrives already cut.
        """
        state["text"] = value or ""
        state["have"] = -1
        state["tries"] = tries
        lbl.configure(text=value or "")
        _lines(state["wrap"] or (wrap or 0))

    lbl.set_flow_text = set_flow_text

    # Any write of new copy goes through here, because an ellipsis the label added itself must
    # not become the text it remembers: a run-time `configure(text=...)` on a capped label
    # otherwise kept the *previous* sentence's tail forever.
    _configure = lbl.configure

    def _configure_tracked(cnfig=None, **kw):
        if not state["internal"]:
            value = kw.get("text", cnfig.get("text") if isinstance(cnfig, dict) else None)
            if isinstance(value, str) and value != state["text"]:
                state["text"] = value
                state["have"] = -1
                state["tries"] = tries
        if cnfig is None:
            return _configure(**kw)
        if kw:
            merged = dict(cnfig)
            merged.update(kw)
            return _configure(merged)
        return _configure(cnfig)

    lbl.configure = _configure_tracked
    lbl.after_idle(_fit)
    lbl._fit_flow = _fit
    return lbl


def row(master, fg=None, **kwargs):
    """A strip inside a card. Solid, never "transparent", on purpose.

    Transparent containers are the other half of the reflow storm: a widget inside one
    repaints itself and the container paints nothing, so whatever was there before stays.
    Saying the colour out loud costs one dict lookup per row and removes the class of bug.
    """
    kwargs.setdefault("fg_color", fg or theme.COL["bg2"])
    kwargs.setdefault("border_width", 0)
    kwargs.setdefault("corner_radius", 0)
    return ctk.CTkFrame(master, **kwargs)


def icon_button(master, text, command, glyph=None, **kwargs):
    """A quiet button with one of the UI marks on it, and its words as the fallback."""
    kwargs.setdefault("font", theme.font(13, "bold"))
    kwargs.setdefault("height", 38)
    kwargs.setdefault("corner_radius", 10)
    kwargs.setdefault("fg_color", theme.COL["bg3"])
    kwargs.setdefault("hover_color", theme.COL["bg_hover"])
    kwargs.setdefault("text_color", theme.COL["text"])
    kwargs.setdefault("compound", "left")
    img = load_glyph(glyph, (20, 20)) if isinstance(glyph, str) else glyph
    if img is not None:
        kwargs.setdefault("image", img)
        text = "  " + text
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def glyph_label(master, glyph, size=(20, 20), color=None):
    """A mark with no words, or nothing at all when PIL is missing.

    Callers pair it with a text label rather than relying on it: ``grid`` handles an absent
    sibling badly, and a build without Pillow should look plainer, not broken.
    """
    img = load_glyph(glyph, size, color=color) if isinstance(glyph, str) else glyph
    if img is None:
        return None
    return ctk.CTkLabel(master, text="", image=img, width=size[0])
