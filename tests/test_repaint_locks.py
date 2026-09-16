#!/usr/bin/env python3
"""Phase 13: the two repaint glitches, one instance at a time, and tiles for the rest.

The reports were specific - "when I minimise or maximise the screen the client UI glitches
and when any slider on anything changes it glitches" - so the checks are specific back. Both
turn out to have the same kind of cause, which is a widget whose colour is decided by
CustomTkinter's theme rather than by us, or a widget whose size is decided by its own text.
Neither can be caught by looking at a finished frame: you have to look at the *invariant*
that makes the frame right, which is what most of this file does.

Run under a headless display to get the GUI half:

    xvfb-run -a python3 tests/test_repaint_locks.py

Without one, the GUI checks are skipped and the rest still run.
"""
import inspect
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="divine-repaint-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")
os.environ.setdefault("DIVINE_NO_SERVER_DOWNLOAD", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

RESULTS = []
HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))


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


def _app():
    """One live window for the whole file, built the way main() builds it."""
    global _APP
    if "_APP" in globals():
        return _APP
    import customtkinter as ctk
    from arenclient.ui.app import DivineApp
    ctk.set_appearance_mode("dark")
    _APP = DivineApp()
    _APP._reveal()
    _APP._download_update = lambda i: None        # no network during a test
    _APP.geometry("1180x740+20+20")
    for _ in range(24):
        _APP.update_idletasks()
        _APP.update()
    return _APP


def _every_widget(w):
    yield w
    for k in w.winfo_children():
        for sub in _every_widget(k):
            yield sub


# ------------------------------------------------------------------ the grey, at the source
# Everything CustomTkinter can hand out for a surface nobody coloured, in both modes: the
# CTkFrame fg_color pair, its top_fg_color pair (the one a header frame got in phase 13), and
# the label/scrollable-frame entries. Any of these on a canvas is the theme painting over us.
THEME_GREYS = {"gray14", "gray17", "grey14", "grey17", "#242424", "#2b2b2b",
               "#3b3942", "#d3d3d3", "gray92", "gray95",
               "gray20", "#333333", "gray81", "#cfd0d2", "gray86", "#d9d9d9",
               "gray23", "#3b3b3b", "gray78", "#c7c7c7", "gray28", "#484848"}


@check("no canvas in the app is left holding the theme's grey")
def _no_theme_grey():
    """The invariant behind the minimize/maximize glitch.

    A CTkFrame is a Tk canvas, and CTk paints the frame's fill as an *item* on it - but only
    when it thinks the geometry or the colours changed. Any pixel it has not repainted yet is
    the canvas' own ``-background``, and CustomTkinter defaults that to a theme grey. So the
    fix is not a redraw timer: it is that no canvas in this app may have a background the theme
    chose. That is exactly what a strip of grey after a maximize is made of.
    """
    app = _app()
    seen = [0]

    def walk(w):
        try:
            kids = w.winfo_children()
        except Exception:
            return
        for child in kids:
            # Every Tk window a CTk widget is built out of, not just its canvas. A label's
            # text lives in an inner tkinter.Label that keeps the theme's -bg until someone
            # says otherwise, and a widget drawn over artwork showed that as the instance
            # name sitting on a grey rectangle.
            for node in (getattr(child, "_canvas", None), getattr(child, "_text_label", None)):
                if node is None:
                    continue
                try:
                    bg = str(node.cget("bg")).strip().lower()
                    seen[0] += 1
                except Exception:
                    bg = ""
                assert bg not in THEME_GREYS, "%s %s is still %s" % (
                    type(child).__name__,
                    "canvas" if node is not getattr(child, "_text_label", None) else "label", bg)
                pinned = getattr(child, "_bg_color", None)
                if pinned and isinstance(pinned, str):
                    assert bg == pinned.strip().lower(), (
                        "%s was pinned to %s but its %s says %s"
                        % (type(child).__name__, pinned,
                           "canvas" if node is not getattr(child, "_text_label", None)
                           else "label", bg))
            walk(child)

    walk(app)
    assert seen[0] > 40, "only %d surfaces walked: the tree is not what this test expects" % seen[0]


@check("a settled window costs a walk to re-pin, not a repaint")
def _pin_is_idempotent():
    """The resize path must be free, because this is what runs on every minimize and maximize.

    The pin is repeated on map and resize so that widgets made after the page was shown cannot
    slip through with a theme-grey canvas - which means a whole-window pin has to be close to
    nothing, or the fix for one glitch buys a stutter on every resize. A window of ~650 widgets
    took 115 ms per pass while every widget was configured and redrawn each time, whether or not
    it needed it; it now carries a stamp of what it was last given. So two things are checked:
    that a settled second pass calls no ``_draw`` at all, and that it is an order of magnitude
    cheaper than a pass where the colours really did move.
    """
    import time
    import customtkinter as ctk
    from arenclient.ui import theme
    app = _app()
    assert theme.pin_surfaces(app) >= 0            # settle it
    counted = []
    reals = {}
    for name in ("CTkFrame", "CTkLabel"):
        klass = getattr(ctk, name)
        reals[name] = klass._draw

        def counting(self, _n=name):
            counted.append(_n)
            return reals[_n](self)

        klass._draw = counting
    try:
        theme.pin_surfaces(app)
    finally:
        for name, fn in reals.items():
            getattr(ctk, name)._draw = fn
    assert not counted, "a repeat pin redrew %d widgets: the stamps are not holding" % len(counted)

    def forget(root):
        def walk(w):
            try:
                del w._divine_pin
            except Exception:
                pass
            for child in w.winfo_children():
                walk(child)
        walk(root)

    forget(app)
    t0 = time.perf_counter(); theme.pin_surfaces(app); forced = time.perf_counter() - t0
    t0 = time.perf_counter(); theme.pin_surfaces(app); repeat = time.perf_counter() - t0
    assert repeat < forced / 8.0, "a settled pin is %.1f ms against a repaint of %.1f ms" % (
        repeat * 1000, forced * 1000)
    # and moving the palette retires every stamp, so a background switch still repaints
    key = theme.background_key()
    gen = theme.repaint_locked()
    assert theme.set_background("flat" if key != "flat" else "black-grey")
    assert theme.repaint_locked() != gen, "a palette change must retire the surface stamps"
    try:
        assert theme.pin_surfaces(app) > 0, "nothing repainted after the palette moved"
    finally:
        theme.set_background(key)
        theme.pin_surfaces(app)


@check("the shell's containers are plain Tk frames, not painted CTk frames")
def _containers_are_plain():
    """A CTkFrame's fill canvas is `place`d, and a placed window stacks above grid-managed
    children - so a container that only has to be a colour should not be one."""
    import tkinter as tk
    import customtkinter as ctk
    app = _app()
    for name in ("content", "pages_host"):
        w = getattr(app, name)
        assert isinstance(w, tk.Frame), "%s is a %s" % (name, type(w).__name__)
        assert not isinstance(w, ctk.CTkFrame), "%s must not be a CTkFrame" % name
        assert str(w.cget("bg")).lower() != "#2b2b2b"


@check("the wash is painted from geometry, with no image and no timer")
def _wash_is_items():
    from arenclient.ui import widgets
    src = inspect.getsource(widgets.Gradient._draw)
    assert "create_polygon" in src or "create_rectangle" in src, \
        "the wash has to be canvas items"
    assert "CTkImage(" not in src and "resize(" not in src, (
        "a wash made from a resized image is the wrong size for one frame out of every "
        "resize, which is the maximize glitch")
    whole = inspect.getsource(widgets)
    assert "after(" not in src and "after_idle" not in src, "no repaint timer in _draw"
    assert not hasattr(widgets, "gradient_pil"), "the old image wash should be gone"
    app = _app()
    page = app.pages["home"]
    assert getattr(page, "_wash_on", False) is False, "pages are flat; the wash is the shell's"
    assert hasattr(app.nav, "_wash_on"), "the sidebar is the wash"


@check("moving the RAM slider moves nothing but its own number")
def _slider_does_not_reflow():
    """The other half of the report: a slider that redraws the whole page.

    The value readout is what did it - an autosizing label, one card up from a scroll frame.
    So the test is not "does it look nice while dragging", it is "did any geometry in that card
    change while the number did", which is the thing that used to cascade.
    """
    app = _app()
    page = app.pages["settings"]
    app.show_page("settings")
    for _ in range(10):
        app.update_idletasks()
        app.update()
    slider = page.ram_slider
    card = slider.master
    label = page.ram_value_lbl

    def snapshot():
        return [w.winfo_geometry() for w in (card, slider, label, label.master)]

    start = int(slider.get())
    slider.set(start + 512)
    for _ in range(8):
        app.update()
    moved = snapshot()
    label_text = str(label.cget("text"))
    assert "MB" in label_text, "the readout did not even update: %r" % label_text
    slider.set(start + 1024)
    for _ in range(8):
        app.update()
    after = snapshot()
    assert moved == after, "a slider tick re-laid out the card: %s -> %s" % (moved, after)
    assert int(label.cget("width")) >= 100, "the readout is not a fixed width"
    slider.set(start)
    app.update()


@check("the hero paints its cover as a canvas item, once per idle")
def _hero_cover_is_an_item():
    app = _app()
    home = app.pages["home"]
    banner = home.banner
    assert not hasattr(banner, "img_lbl"), "the banner's label image is back"
    src = inspect.getsource(type(banner)._paint)
    assert "itemconfig" in src and "PhotoImage" in src
    assert "CTkImage" not in src, "a CTkImage scales itself to its widget; that is the stretch"
    conf = inspect.getsource(type(banner)._on_configure)
    assert "after_idle" in conf and "after(140" not in conf, \
        "the cover must coalesce to the next idle, not to a timer a resize can outrun"
    # and the item exists on the real banner
    found = banner._canvas.find_withtag("divinecover")
    assert found, "no cover item on the hero canvas"


# --------------------------------------------------------------------------- the palette
@check("the four backgrounds are real palettes, and switching one repaints the app")
def _backgrounds():
    from arenclient.ui import theme
    names = [k for k, _l, _n in theme.background_names()]
    assert len(names) >= 3, names
    assert "cyan-purple" in names and "black-grey" in names, "the user asked for these two"
    original = theme.background_key()
    for key in names:
        assert theme.set_background(key) is True, key
        assert theme.COL.get("bg") and theme.COL.get("accent"), key
        assert theme.gradient_colors("main")[0] != theme.gradient_colors("main")[1] \
            or theme.gradient_angle("main") == "flat", key
        for kind in ("main", "nav", "page"):
            pair = theme.gradient_colors(kind)
            assert isinstance(pair, tuple) and len(pair) == 2, (kind, pair)
    theme.set_background("cyan-purple")
    app = _app()
    app.set_background("black-grey")
    app.update_idletasks()
    app.update()
    assert theme.COL["bg"], "the palette went empty"
    assert str(app.content.cget("bg")).lower() == str(theme.COL["bg"]).lower(), \
        "the shell did not take the new colour"
    app.set_background("cyan-purple")
    for _ in range(8):
        app.update()
    assert str(app.content.cget("bg")).lower() == str(theme.COL["bg"]).lower()
    if original:
        theme.set_background(original)


@check("the chosen background is what opens next time")
def _background_is_saved():
    app = _app()
    from arenclient.ui import theme as _t
    allowed = [k for k, _l, _n in _t.background_names()]
    key = app.config_store.get("ui_background")
    assert key in allowed, "unknown background in the config: %r (want one of %s)" % (key, allowed)


@check("requirements pin the CustomTkinter the repaint fix was written against")
def _pinned_ctk():
    path = os.path.join(ROOT, "requirements.txt")
    lines = [ln.strip() for ln in open(path, encoding="utf-8").read().split("\n") if ln.strip()]
    pin = [ln for ln in lines if ln.lower().startswith("customtkinter")]
    assert pin, "customtkinter is not in requirements.txt at all"
    assert "==" in pin[0], (
        "the wash is painted by overriding CTkFrame._draw; against another version of the "
        "library that method may not be the one Tk calls, so the version is pinned: %s" % pin[0])
    import customtkinter as ctk
    want = pin[0].split("==")[1].strip()
    assert ctk.__version__ == want, "installed %s, pinned %s" % (ctk.__version__, want)


# ------------------------------------------------------------------- one instance at a time
class _FakeProc:
    """Something that looks, to ``live_games()``, like a game that is up."""

    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


@check("a second instance cannot be launched, and says so")
def _one_instance():
    app = _app()
    mgr = app.instances
    names = ["Probe One", "Probe Two"]
    made = []
    for nm in names:
        inst = None
        for existing in list(mgr.instances or []):
            if existing.name == nm:
                inst = existing
                break
        if inst is None:
            inst = mgr.create(nm, "1.20.4", loader="fabric")
        assert inst is not None, "test could not make an instance"
        made.append(inst)
    first, second = made[0], made[1]

    app.running_procs = {first.id: [_FakeProc()]}
    try:
        assert len(app.live_games()) == 1, "live_games() does not see the running game"
        flow = app.flow
        others = flow.others_running(second)
        assert others and first.name in others, (
            "the flow does not know the other instance is up: %r" % (others,))
        assert flow.locked_for(second) is True
        assert flow.others_running(first) == [], "the running instance may not be locked"
        assert flow.locked_for(first) is False, (
            "the open game must still be stoppable from its own card")

        flow.select(second)
        for _ in range(6):
            app.update()
        started = []
        real_worker = flow._worker

        def spy(inst, *a, **kw):
            started.append(inst)

        flow._worker = spy
        try:
            flow.launch()
            for _ in range(8):
                app.update()
            assert not started, "a launch thread was started while another game was open"
            assert flow.busy is False, "the flow went busy on a launch it refused"
        finally:
            flow._worker = real_worker
        status = str(app.pages["home"].status.cget("text"))
        assert "one instance" in status.lower() or "still open" in status.lower(), (
            "the refusal is not explained on the page: %r" % status)
    finally:
        app.running_procs = {}
        for inst in made:
            try:
                mgr.delete(inst.id)
            except Exception:
                pass
        flow.select(None)
        app.update()


@check("the other cards grey their Launch and the open one says Running")
def _cards_show_the_lock():
    app = _app()
    mgr = app.instances
    inst = None
    for existing in list(mgr.instances or []):
        if existing.name == "Probe Card":
            inst = existing
            break
    if inst is None:
        inst = mgr.create("Probe Card", "1.20.4", loader="fabric")
    other = None
    for existing in list(mgr.instances or []):
        if existing.name != inst.name:
            other = existing
            break
    if other is None:
        other = mgr.create("Probe Other", "1.20.4", loader="vanilla")
    try:
        page = app.pages["instances"]
        app.show_page("instances")
        for _ in range(12):
            app.update_idletasks()
            app.update()
        page.refresh()
        for _ in range(10):
            app.update()
        assert inst.id in page._cards, "the page did not build a card for the instance"
        card = page._cards[inst.id]
        assert card.locked is False, "a fresh card starts locked?"

        app.running_procs = {other.id: [_FakeProc()]}
        page.refresh_locks()
        for _ in range(8):
            app.update()
        assert card.locked is True, "the card did not lock while another game is up"
        states = []
        for widget in _every_widget(card):
            if type(widget).__name__ != "CTkButton":
                continue                      # the inner label is not the control
            try:
                if "Launch" in str(widget.cget("text")):
                    states.append(str(widget.cget("state")))
            except Exception:
                continue
        assert states and all(s == "disabled" for s in states), (
            "Launch is still clickable somewhere on a locked card: %r" % (states,))

        app.running_procs = {inst.id: [_FakeProc()]}
        page.refresh_locks()
        for _ in range(8):
            app.update()
        assert card.running == 1, "the open instance's own card does not know it is running"
        assert "Running" in str(card.state_lbl.cget("text")), (
            "no Running marker on the live card: %r" % card.state_lbl.cget("text"))
        assert card.locked is False
    finally:
        app.running_procs = {}
        for gone in (inst, other):
            try:
                mgr.delete(gone.id)
            except Exception:
                pass
    app.update()


@check("the instances grid changes columns with the window, without rebuilding")
def _grid_is_responsive():
    app = _app()
    page = app.pages["instances"]
    app.geometry("1500x820+10+10")
    for _ in range(14):
        app.update_idletasks()
        app.update()
    wide = page._cols
    app.geometry("820x620+10+10")
    for _ in range(14):
        app.update_idletasks()
        app.update()
    narrow = page._cols
    assert wide >= narrow, "the grid never got wider"
    src = inspect.getsource(type(page)._reflow)
    assert "destroy" not in src, "a reflow must move the same cards, not rebuild them"
    assert "winfo_width()" not in inspect.getsource(type(page).on_show)


# ---------------------------------------------------------------------- tiles for the rest
@check("a pack with no picture still gets a tile, and the tile is ours")
def _letter_tiles():
    from arenclient.ui import widgets
    app = _app()
    label = __import__("customtkinter").CTkLabel(app)
    assert widgets.set_tile(label, "Sky Factory 4", size=(44, 44)) is True or not \
        __import__("arenclient.ui.widgets", fromlist=["_HAS_PIL"])._HAS_PIL
    img = widgets.letter_tile_image("Minecraft", (44, 44))
    if __import__("arenclient.ui.widgets", fromlist=["_HAS_PIL"])._HAS_PIL:
        assert img is not None, "Pillow is installed and the tile came back empty"
        again = widgets.letter_tile_image("Minecraft", (44, 44))
        assert again is img, "the tile is rebuilt for the same letter every time"
        other = widgets.letter_tile_image("Minecraft", (60, 60))
        assert other is not img, "the cache ignores the size"
    label.destroy()


@check("the modpack rows put a tile on before anything is asked of the network")
def _modpack_row():
    from arenclient.ui.modpack_dialog import ModpackDialog
    app = _app()
    dlg = ModpackDialog(app, app)
    try:
        hit = {"title": "Better Pack Ever", "author": "someone", "downloads": 12345,
               "icon_url": "", "project_id": "probe-1"}
        dlg._paint([hit], 1)
        for _ in range(8):
            app.update_idletasks()
            app.update()
        cards = [w for w in dlg.list_frame.winfo_children()]
        assert cards, "no row was built"
        marks = [w for w in _every_widget(cards[0])
                 if type(w).__name__ == "CTkLabel" and int(w.cget("width") or 0) >= 40]
        assert marks, "the row has no tile at all"
        mark = marks[0]
        has_pil = __import__("arenclient.ui.widgets", fromlist=["_HAS_PIL"])._HAS_PIL
        if has_pil:
            assert str(mark.cget("image")), "the tile is empty"
            assert not str(mark.cget("text")), "the tile still shows its fallback letter"
        src = inspect.getsource(type(dlg)._pack_row)
        assert "_load_icon" in src, "no picture is ever fetched for a pack"
        fetch = inspect.getsource(type(dlg)._load_icon)
        assert "DESK.show" in fetch, "the icon must come through the image desk, not the row"
        assert "requests" not in fetch and "urlopen" not in fetch, \
            "the row must not do its own downloading"
    finally:
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()
        app.update()


@check("the supplied marks are used, not just present")
def _glyphs_wired():
    from arenclient.ui import nav, theme, widgets
    from arenclient import paths
    names = [n[:-4] for n in os.listdir(os.path.join(ROOT, "assets"))
             if n.startswith("ui_") and n.endswith(".png")]
    assert len(names) >= 20, "only %d ui glyphs" % len(names)
    for item in list(getattr(nav, "MAIN_ITEMS", [])) + list(getattr(nav, "FOOT_ITEMS", [])):
        glyph = item[2]
        assert "ui_" in glyph, "a sidebar row without a mark: %r" % (item,)
        assert os.path.exists(os.path.join(ROOT, "assets", glyph + ".png")), \
            "the sidebar asks for %s, which is not in assets/" % glyph
    for supplied in ("ui_friends", "ui_account", "ui_new", "ui_discord"):
        assert supplied in names
        assert os.path.exists(paths.resource_path("assets/%s.png" % supplied))
    # and they are loaded, not merely listed
    imgs = [widgets.load_glyph("assets/ui_%s.png" % supplied, (20, 20))
            for supplied in ("friends", "account", "new", "discord")]
    if __import__("arenclient.ui.widgets", fromlist=["_HAS_PIL"])._HAS_PIL:
        assert all(i is not None for i in imgs), "a supplied mark would not load"
    src = inspect.getsource(widgets.load_glyph)
    assert "_GLYPHS" in src or "cache" in src.lower(), "every label re-decodes its glyph"


# --------------------------------------------------------------------- no dead code paths
@check("nothing anywhere configures an image inside a Configure handler")
def _no_resize_image_storms():
    """The pattern that caused both reports: a <Configure> handler that builds a new image."""
    import glob
    import re
    bad = []
    for path in glob.glob(os.path.join(ROOT, "arenclient", "ui", "**", "*.py"),
                          recursive=True):
        src = open(path, encoding="utf-8").read()
        if "<Configure>" not in src and "_on_configure" not in src:
            continue
        handler = re.search(r"def _on_configure\(self[^)]*\):(.*?)\n    def ", src, re.S)
        if not handler:
            continue
        body = handler.group(1)
        if "CTkImage" in body or "_cover(" in body or "_paint(" in body and "after(" in body:
            if "after_idle" not in body:
                bad.append(os.path.basename(path))
    assert not bad, "these repaint an image on a timer instead of on the next idle: %s" % bad


@check("a restyle rebuilds the shell and keeps the page the person was on")
def _restyle_keeps_state():
    app = _app()
    app.show_page("instances")
    for _ in range(10):
        app.update()
    app.set_background("black-grey")
    for _ in range(20):
        app.update_idletasks()
        app.update()
    assert app._current == "instances", "a palette change sent the person back to Home"
    assert "home" in app.pages and "settings" in app.pages, "not every page came back"
    # and the rebuilt shell is still clean
    for name in ("content", "pages_host"):
        w = getattr(app, name)
        assert str(w.cget("bg")).lower() not in THEME_GREYS
    for child in app.pages_host.winfo_children():
        if hasattr(child, "_canvas"):
            assert str(child._canvas.cget("bg")).lower() not in THEME_GREYS


@check("nothing in the shell runs on a timer")
def _no_animations():
    import glob
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "arenclient", "ui", "**", "*.py"),
                          recursive=True):
        src = open(path, encoding="utf-8").read()
        if "iconbitmap" in src:
            continue
        for i, line in enumerate(src.split("\n")):
            code = line.split("#")[0]
            if "after(" in code and "self.after(7000, self._reveal)" in code:
                continue
            if "self.after(" in code and "def " not in code:
                # one-shot scheduling is fine and everywhere; a *loop* is a timer that
                # repaints, and this launcher has none by design - so flag only recursion
                fn = None
                for j in range(i, 0, -1):
                    if src.split("\n")[j].startswith("    def "):
                        fn = src.split("\n")[j]
                        break
                if fn and any(k in fn for k in ("_animate", "_tick_ui", "_pulse", "_spin")):
                    offenders.append("%s:%d" % (os.path.basename(path), i + 1))
    assert not offenders, "animation timers are back: %s" % offenders


def main():
    ok = sum(1 for k, _ in RESULTS if k == "ok")
    bad = sum(1 for k, _ in RESULTS if k == "fail")
    print("\nphase 13 repaint and locks: %d ok, %d failed" % (ok, bad))
    if HAVE_DISPLAY:
        try:
            globals().get("_APP", None) and _APP.destroy()
        except Exception:
            pass
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
