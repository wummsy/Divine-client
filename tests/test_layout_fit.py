#!/usr/bin/env python3
"""Nothing in this UI is allowed to be cut off by its own box.

Phase 14 came from one screenshot: the header's instance name reduced to a single letter beside
its own Play button, and the Play button hanging past the bottom hairline of a bar whose height
had been written down as a number instead of being decided by what is inside it. Both are the
same mistake - a widget told how big its container is, rather than asked - and the second one is
why "make sure all text doesn't be on the corner of the box" needed a test rather than a fix:
long copy in this app carried a hand-picked ``wraplength`` chosen at whatever window size was open
the day it was written, so it clipped the moment the window, the card or the sidebar got smaller.

So: measure every label at three widths on every page. Run with a display:

    xvfb-run -a python3 tests/test_layout_fit.py
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="divine-fit-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")
os.environ.setdefault("DIVINE_NO_SERVER_DOWNLOAD", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

RESULTS = []
HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
PAGES = ("home", "instances", "servers", "accounts", "settings", "about")
WIDTHS = ("1240x780+30+30", "1100x720+30+30", "980x620+30+30")     # default .. minimum


def check(name, needs_display=False):
    def wrap(fn):
        if needs_display and not HAVE_DISPLAY:
            print("  skip  %s (no display)" % name)
            return fn
        try:
            fn()
            RESULTS.append(("ok", name))
            print("  ok    %s" % name)
        except Exception as err:                                   # noqa: BLE001
            import traceback
            traceback.print_exc()
            RESULTS.append(("fail", name))
            print("  FAIL  %s: %r" % (name, err))
        return fn
    return wrap


_APP = {}


def app():
    if "a" in _APP:
        return _APP["a"]
    import time
    import customtkinter as ctk
    from arenclient.ui.app import DivineApp
    ctk.set_appearance_mode("dark")
    a = DivineApp()
    a._reveal()
    a._download_update = lambda i: None
    for name, ver in (("Fabric 1.21.11", "1.21.11"),
                      ("An extremely long instance name to stress every box", "1.20.4")):
        try:
            a.instances.create(name, ver)
        except Exception:
            pass
    _APP["a"] = a
    return a


def pump(a, n=14):
    import time
    for _ in range(n):
        try:
            a.update_idletasks()
            a.update()
        except Exception:
            return
        time.sleep(0.008)


def labels_in(root, out=None, depth=0):
    """Every widget in this subtree that draws words."""
    if out is None:
        out = []
    if depth > 22:
        return out
    try:
        kids = root.winfo_children()
    except Exception:
        return out
    for c in kids:
        try:
            if str(c.cget("text")).strip():
                out.append(c)
        except Exception:
            pass
        labels_in(c, out, depth + 1)
    return out


def visible(w):
    try:
        return bool(w.winfo_ismapped()) and int(w.winfo_width()) > 1
    except Exception:
        return False


@check("no word anywhere is cut off by the space it was given", needs_display=True)
def _nothing_clips():
    """The invariant: a label's requested width never exceeds what its cell gives it.

    Clipping is invisible in a screenshot of the size you normally use, and it is invisible to a
    test that only looks at one window size, which is why it survived as long as it did. Three
    widths, six pages, every page that is actually shown - and the long-named instance above, so
    the header is measured with its worst-case content.
    """
    a = app()
    bad = []
    for size in WIDTHS:
        a.geometry(size)
        pump(a, 10)
        for key in PAGES:
            a.show_page(key)
            pump(a)
            for root in (a.pages.get(key), a._bar, a.nav):
                if root is None:
                    continue
                for w in labels_in(root):
                    if not visible(w):
                        continue
                    try:
                        req, have = int(w.winfo_reqwidth()), int(w.winfo_width())
                    except Exception:
                        continue
                    if req - have > 3:
                        bad.append("%s @%s: %s wants %d, has %d (%r)" % (
                            key, size.split("x")[0], type(w).__name__, req, have,
                            str(w.cget("text"))[:38]))
    assert not bad, "%d labels are clipped:\n    %s" % (len(bad), "\n    ".join(bad[:14]))


@check("words keep their distance from the edge of the panel they sit on", needs_display=True)
def _no_flush_text():
    """A sentence painted on a card has to be inside the card with room to read.

    Only labels, and only where the label is smaller than the panel it is on: a button in a row
    that hugs it, or a label in a container sized to fit it, has no "edge" to be flush with, and
    the nearest panel wider than the widget is the one a person actually sees. Buttons are left
    out on purpose - a button stretched across a row is a layout choice, a sentence touching the
    corner of a card is the mistake from the screenshot.
    """
    a = app()
    bad = []
    for size in WIDTHS[:2]:
        a.geometry(size)
        pump(a, 10)
        for key in PAGES:
            a.show_page(key)
            pump(a)
            page = a.pages.get(key)
            if page is None:
                continue
            # the shell too: the sidebar and the header hold as much text as a page does, and
            # both are narrow enough to be the place a label runs out of room.
            roots = [page, a.nav, a._bar]
            for w in labels_in(page) + labels_in(a.nav) + labels_in(a._bar):
                if not visible(w) or type(w).__name__ != "CTkLabel":
                    continue
                # the *outermost* panel the text is written on. A card is usually a frame
                # inside a frame, and the inner one is invisible - same colour, no border - so
                # measuring against it would call a perfectly padded label flush. The box a
                # person sees is the last one before the page itself.
                box, node = None, w.master
                for _ in range(10):
                    if node is None or node in roots or node is a:
                        break
                    box = node
                    node = node.master
                if box is None or box is w.master:
                    continue        # nothing but its own row above it: a hugging container
                try:
                    left = w.winfo_rootx() - box.winfo_rootx()
                    right = (box.winfo_rootx() + int(box.winfo_width())) - (
                        w.winfo_rootx() + width)
                    top = w.winfo_rooty() - box.winfo_rooty()
                except Exception:
                    continue
                if left < 6 or right < 6 or top < 5:
                    bad.append("%s @%s: %r  L%d R%d T%d inside %s" % (
                        key, size.split("x")[0], str(w.cget("text"))[:32], left, right, top,
                        type(box).__name__))
    assert not bad, "%d labels are flush with the edge of their panel:\n    %s" % (
        len(bad), "\n    ".join(bad[:14]))


@check("no box is so full that Tk hides part of it", needs_display=True)
def _nothing_is_over_subscribed():
    """The failure mode nobody sees: a container that cannot fit its children drops them.

    Tk's pack and grid give every child what it asked for and hand the leftovers to the one
    marked expand - and when there are no leftovers, the children that came last are simply not
    mapped. Not clipped, not scrolled: gone. That is how the friends panel lost its "add a
    friend" row at a short window, which no screenshot of the default size would ever show. So
    every container on every page is asked the same question at three window heights: does the
    height you gave out cover the height you were asked for? If not, something in you is hidden.
    """
    a = app()
    bad = []
    for size in WIDTHS:
        tall = int(size.split("+")[0].split("x")[1])
        a.geometry(size)
        pump(a, 10)
        for key in PAGES:
            a.show_page(key)
            pump(a)
            for root in (a.pages.get(key), a.nav, a._bar):
                if root is None:
                    continue
                stack = [root]
                while stack:
                    w = stack.pop()
                    try:
                        kids = w.winfo_children()
                    except Exception:
                        continue
                    stack.extend(kids)
                    if len(kids) < 2:
                        continue
                    try:
                        have = int(w.winfo_height())
                    except Exception:
                        continue
                    if have < 24:
                        continue
                    manager = ""
                    try:
                        manager = w.tk.call("winfo", "toplevel", w._w) and ""
                    except Exception:
                        pass
                    need = 0
                    packed = [k for k in kids if k.__class__.__name__ != "CTkCanvas"]
                    for c in packed:
                        try:
                            if c.winfo_manager() == "pack":
                                need += int(c.winfo_reqheight()) + 4
                        except Exception:
                            continue
                    if need and need > have + 6:
                        hidden = [type(c).__name__ for c in packed
                                  if c.winfo_manager() == "pack" and not c.winfo_ismapped()]
                        if hidden:
                            bad.append("%s @%dh: %s asked %d px and has %d -> hidden %s" % (
                                key, tall, str(w)[-22:], need, have, ",".join(hidden[:3])))
    assert not bad, "%d containers are over-full and are hiding children:\n    %s" % (
        len(bad), "\n    ".join(bad[:12]))


@check("the header is sized by what is in it, and everything fits", needs_display=True)
def _header_holds():
    """The bug in the screenshot, as a rule: no widget in the bar may reach its edge.

    The bar used to be `height=60` with `grid_propagate(False)`, so the Play button - 34 px in a
    bar whose two rows were already full - was drawn past the bottom hairline, and the instance
    name next to it was clipped by the button itself. The header is bigger now on purpose, so
    the check is that it is big enough for its contents: at least 84 px, every child inside it
    with a margin at the bottom, and the instance line above the buttons instead of beside them.
    """
    a = app()
    a.geometry(WIDTHS[0])
    pump(a, 12)
    bar = a._bar
    pump(a)
    h = int(bar.winfo_height())
    assert h >= 84, "the header is %d px: it is not bigger than the content it holds" % h
    top, bottom = bar.winfo_rooty(), bar.winfo_rooty() + h
    for name in ("overline_lbl", "title_lbl", "subtitle_lbl", "top_inst", "top_play",
                 "top_account"):
        w = getattr(a, name, None)
        if w is None or not visible(w):
            continue
        y0, y1 = w.winfo_rooty(), w.winfo_rooty() + int(w.winfo_height())
        assert y0 >= top and y1 <= bottom, (
            "%s runs from %d to %d inside a header of %d..%d: the bar is sized by a number "
            "again" % (name, y0, y1, top, bottom))
        assert bottom - y1 >= 6, "%s sits %d px from the header's bottom edge" % (name, bottom - y1)
    # the instance name and the button must not share a row, which is what cut the name
    inst, play = a.top_inst, a.top_play
    if visible(inst) and visible(play):
        assert inst.winfo_rooty() + inst.winfo_height() <= play.winfo_rooty() + 2, (
            "the instance line is level with the Play button again")
    # and it follows the launch flow, so the height is spent on something true
    a.set_state(True, False)
    pump(a, 4)
    assert "LAUNCH" in str(a.overline_lbl.cget("text")).upper(), str(
        a.overline_lbl.cget("text"))
    a.set_state(False, False)


@check("the friends rail is a rail: narrow, and it ends where its content ends",
       needs_display=True)
def _friends_rail():
    a = app()
    a.geometry(WIDTHS[0])
    a.show_page("home")
    pump(a, 16)
    panel = a.pages["home"].friends
    w, h = int(panel.winfo_width()), int(panel.winfo_height())
    assert w <= 320, "the friends panel is %d px wide; it was asked to be smaller" % w
    assert int(panel.winfo_reqwidth()) <= 320, (
        "the friends panel *wants* %d px: something in it is a single unwrapped line wider "
        "than the rail, which is how it used to push the rail out" % int(panel.winfo_reqwidth()))
    page_h = int(a.pages["home"].winfo_height())
    assert h <= page_h - 60, "the panel is %d px in a page of %d: it still fills the column" % (
        h, page_h)
    # It must be a rail on the right of the play card, with the news box stacked under it in
    # the same column: the layout the page used to have put the news under everything in the
    # left column, where a 780 px window left it below the bottom edge with nothing to scroll.
    page = a.pages["home"]
    assert panel.winfo_rootx() > page.play_card.winfo_rootx() + 320, \
        "the friends panel is not in a right-hand rail"
    news = getattr(page, "news_head", None)
    assert news is not None, "the page no longer names its news box, so nothing proves it is placed"
    assert abs(news.winfo_rootx() - panel.winfo_rootx()) < 8, \
        "the news box is not in the rail with the friends panel"
    assert news.winfo_rooty() >= panel.winfo_rooty() + int(panel.winfo_height()) - 4, \
        "the news box overlaps the friends panel instead of following it"

    # A scroll frame reports its own height as the little strip around its canvas, so the
    # number that matters is the canvas the friends are drawn on.
    inner = getattr(panel.list, "_parent_canvas", None) or panel.list
    assert int(inner.winfo_height()) >= 120, \
        "the friends list is only %d px of canvas: the panel is being squeezed, not sized" % int(
            inner.winfo_height())
    assert panel.foot.winfo_ismapped(), \
        "the add-a-friend row is not on screen at %s" % WIDTHS[0]
    assert int(panel.winfo_rooty()) + int(panel.winfo_height()) <= int(a.winfo_height()), \
        "the friends panel runs past the bottom of the window"


@check("the rail keeps the friends panel whole at the smallest window", needs_display=True)
def _rail_survives_minimum():
    a = app()
    a.geometry("980x620+40+30")
    a.show_page("home")
    pump(a, 18)
    page = a.pages["home"]
    panel = page.friends
    inner = getattr(panel.list, "_parent_canvas", None) or panel.list
    assert panel.winfo_ismapped(), "the friends panel is not shown at the minimum size"
    assert panel.foot.winfo_ismapped(), (
        "at 980x620 the footer is unmapped again - the panel has to be sized by what it holds, "
        "or Tk takes the shortfall out of the last row packed")
    assert int(inner.winfo_height()) >= 96, \
        "the friends list is %d px at the minimum size" % int(inner.winfo_height())
    assert int(panel.winfo_rooty()) + int(panel.winfo_height()) <= int(a.winfo_height()) + 2, \
        "the panel hangs off the bottom of a minimum-size window"
    news = page.news_head
    if news.winfo_manager():
        assert int(news.winfo_rooty()) + int(news.winfo_height()) <= int(a.winfo_height()) + 2, (
            "the news box is shown at a size where it cannot fit; the rail is supposed to hide "
            "it rather than let Tk cut it in half")


def cell_width(w):
    """How wide the space in front of this widget really is.

    ``winfo_width`` is no good here: a label gridded ``sticky="w"`` is given *its own* requested
    width, which for a wrapping label is the width of the text it already wrapped - so measuring
    "did it wrap when it did not have to" against it is circular and always says no. The grid
    knows the truth: ``grid bbox`` returns the cell, and a columnspan is a run of contiguous
    cells, so they are summed. A pack-managed flow label fills its master by construction
    (``flow_label`` asks for that), so its own width is the cell.
    """
    try:
        mgr = w.winfo_manager()
    except Exception:
        return 0
    if mgr == "pack":
        try:
            return int(w.winfo_width())
        except Exception:
            return 0
    if mgr != "grid":
        return 0
    try:
        info = w.grid_info()
        master, col, row = info["in"], int(info["column"]), int(info["row"])
        span = max(1, int(info.get("columnspan", 1)))
    except Exception:
        return 0
    total, seen = 0, 0
    for c in range(col, col + span):
        try:
            bbox = master.tk.call("grid", "bbox", master._w, c, row)
        except Exception:
            return 0
        if not bbox:
            return 0
        total += int(bbox[2]); seen += 1
    if not seen:
        return 0
    try:                                        # the label's own horizontal padding is not room
        padx = str(w.grid_info().get("padx", "0"))
        parts = [int(float(p)) for p in padx.replace(",", " ").split()]
        total -= (parts[0] if parts else 0) + (parts[-1] if len(parts) > 1 else (parts[0] if parts else 0))
    except Exception:
        pass
    return max(0, total)


@check("no flow label wraps a sentence its own cell had room for", needs_display=True)
def _no_early_wrap():
    """The other half of the clipping bug: text broken over lines it did not need.

    A label whose cell is wider than its text must be one line tall. The play card's title used
    to read "Fabric" over "1.21.11" in a 647 px cell: it was gridded ``sticky="w"``, so Tk handed
    it its own requested width, and a label that measures its own box to choose a wrap then
    measures the box its own text produced - the two decide each other and settle somewhere short
    of the truth. ``flow_label`` now claims the cell horizontally, and this is the check that
    keeps a future ``sticky="w"`` from putting the early wrap back.
    """
    from arenclient.ui import widgets
    a = app()
    bad, measured = [], 0
    for size in WIDTHS:
        a.geometry(size)
        pump(a, 10)
        for key in PAGES:
            a.show_page(key)
            pump(a)
            for root in (a.pages.get(key), a._bar, a.nav):
                if root is None:
                    continue
                for lbl in labels_in(root):
                    if getattr(lbl, "_fit_flow", None) is None or not visible(lbl):
                        continue
                    text = str(lbl.cget("text") or "")
                    if not text.strip() or "\n" in text:
                        continue
                    try:
                        f = widgets.face_for(lbl.cget("font"))
                        if f is None:
                            raise RuntimeError("no font face for %s" % type(lbl).__name__)
                        one, line_h = f.measure(text), f.metrics("linespace")
                        room = max(int(lbl.winfo_width()), cell_width(lbl))
                        height = int(lbl.winfo_reqheight())
                    except Exception as exc:
                        measured += 0
                        bad.append("%s @%s: the label could not be measured (%s), which would "
                                   "make this check pass without looking at anything" % (
                                       key, size.split("x")[0], exc))
                        continue
                    measured += 1
                    if one <= room - 6 and height >= 2 * line_h:
                        bad.append("%s @%s: %r is %d px of text in %d px, drawn %d px tall" % (
                            key, size.split("x")[0], text[:38], one, room, height))
    assert not bad, "%d label(s) wrap early:\n    %s" % (len(bad), "\n    ".join(bad[:10]))


@check("a flow label measures its own box instead of trusting a number", needs_display=False)
def _flow_label_is_self_correcting():
    """The helper is the fix, so the helper gets tested on its own, without a window."""
    import inspect
    from arenclient.ui import widgets
    src = inspect.getsource(widgets.flow_label)
    assert "winfo_width" in src and "wraplength" in src, "flow_label does not measure and set"
    assert "winfo_reqwidth" in src, "flow_label cannot tell a fit from a clip"
    sig = inspect.signature(widgets.flow_label)
    assert sig.parameters.get("text") is not None and sig.parameters.get("master") is not None


@check("the shipped copy has no fixed wraplength left on a long sentence", needs_display=False)
def _no_hand_picked_wraplengths():
    """Every ``wraplength=NNN`` in a page is a size assumption that outlives the day it was made.

    The ones that stayed are deliberate - a dialog with a fixed width, where the number is the
    width - so the rule is narrow: a *page* may not carry one on a label it also expects to
    shrink. Pages live inside a resizable window; dialogs do not.
    """
    import re
    import glob
    hits = []
    for path in glob.glob(os.path.join(ROOT, "arenclient", "ui", "pages", "*.py")):
        text = open(path, encoding="utf-8").read()
        for i, line in enumerate(text.splitlines(), 1):
            if "wraplength=" in line and "flow_label" not in line and "configure(" not in line:
                hits.append("%s:%d  %s" % (os.path.basename(path), i, line.strip()[:70]))
    assert not hits, "long copy in a page with a hand-picked width:\n    %s" % "\n    ".join(hits)


def main():
    ok = sum(1 for k, _ in RESULTS if k == "ok")
    bad = sum(1 for k, _ in RESULTS if k == "fail")
    print("\nlayout fit: %d ok, %d failed" % (ok, bad))
    if HAVE_DISPLAY:
        try:
            app().destroy()
        except Exception:
            pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
