"""Divine Client visual theme: palettes, washes, fonts, and small styled widgets.

Everything colour-related lives in ``BACKGROUNDS`` - one entry per choice in
Settings > Appearance. Each entry is a *complete* palette, not a tint of another one,
because a dark cyan UI and a black-grey UI need different panel colours to keep the same
contrast, and half-adjusted palettes are how you get cards that vanish into the
background. ``set_background()`` swaps the palette in place; the app then rebuilds its
widgets (see ``DivineApp.restyle``), which is also why no widget has to remember where its
colour came from.

Two rules the palettes are built around, both learned from "the UI glitches":

* every surface a widget sits on is a **solid colour** - nothing depends on a background
  showing through, because Tk only repaints what it knows is dirty;
* the wash is drawn as flat bands by a canvas (``widgets.Gradient``), never as an image,
  so a resize, a maximize or a restore from the taskbar can never show a stale one.
"""

# --- the palettes -------------------------------------------------------------
# ``wash`` is the gradient behind the shell, ``nav`` the one in the sidebar. A wash of
# (c, c, "flat") is a solid fill - that is the "no gradient" choice, and it still goes
# through the same painter so the rest of the code has one path.
BACKGROUNDS = {
    "divine": {
        "label": "Divine Obsidian",
        "note": "pure obsidian with luminous white accents",
        "wash": ("#0e1017", "#050608", "vertical"),
        "page": ("#0d1017", "#07080c", "vertical"),
        "nav": ("#10131d", "#08090f", "vertical"),
        "col": {
            "bg":          "#08090d",
            "bg2":         "#0e1017",
            "bg3":         "#161924",
            "bg_hover":    "#222738",
            "sidebar":     "#0c0e14",
            "accent":      "#ffffff",
            "accent2":     "#cbd5e1",
            "accent_hi":   "#ffffff",
            "text":        "#ffffff",
            "text_dim":    "#cbd5e1",
            "text_faint":  "#94a3b8",
            "good":        "#22c55e",
            "warn":        "#f59e0b",
            "danger":      "#ef4444",
            "border":      "#2a2f3e",
            "border_soft": "#191d29",
        },
    },
    "all-black": {
        "label": "AMOLED Void",
        "note": "pitch black void with high-contrast white",
        "wash": ("#050505", "#000000", "vertical"),
        "page": ("#050505", "#000000", "vertical"),
        "nav": ("#080808", "#000000", "vertical"),
        "col": {
            "bg":          "#000000",
            "bg2":         "#0a0a0c",
            "bg3":         "#141418",
            "bg_hover":    "#22222a",
            "sidebar":     "#050505",
            "accent":      "#ffffff",
            "accent2":     "#d4d4d8",
            "accent_hi":   "#ffffff",
            "text":        "#ffffff",
            "text_dim":    "#d4d4d8",
            "text_faint":  "#a1a1aa",
            "good":        "#22c55e",
            "warn":        "#f59e0b",
            "danger":      "#ef4444",
            "border":      "#27272a",
            "border_soft": "#18181b",
        },
    },
    "cyan-purple": {
        "label": "Cyan \u2192 purple",
        "note": "the bright one: cyan panels, violet in the corners",
        # kept dark on purpose: a wash bright enough to be a feature is a wash you read
        # instead of a wash you look through, and every panel on top of it has to fight it
        "wash": ("#10303a", "#221335", "diagonal"),
        "page": ("#0b1d26", "#0a141d", "diagonal"),
        "nav": ("#143a49", "#1a1130", "vertical"),
        "col": {
            "bg":          "#07141b",
            "bg2":         "#101f28",
            "bg3":         "#16303b",
            "bg_hover":    "#1e4557",
            "sidebar":     "#0b1c25",
            "accent":      "#2ee6e0",
            "accent2":     "#a98bff",
            "accent_hi":   "#6ff7f0",
            "text":        "#eafcff",
            "text_dim":    "#93bcc6",
            "text_faint":  "#5e8690",
            "good":        "#4be08a",
            "warn":        "#f5c563",
            "danger":      "#ff6183",
            "border":      "#22505f",
            "border_soft": "#173543",
        },
    },
    "black-grey": {
        "label": "Black \u2192 grey",
        "note": "neutral and quiet: no colour but the accent",
        "wash": ("#171b21", "#05070a", "vertical"),
        "page": ("#12151a", "#0a0c0f", "vertical"),
        "nav": ("#1c2127", "#090b0e", "vertical"),
        "col": {
            "bg":          "#0a0c0f",
            "bg2":         "#171a20",
            "bg3":         "#1f242c",
            "bg_hover":    "#2b323c",
            "sidebar":     "#0f1216",
            "accent":      "#2ee6e0",
            "accent2":     "#9aa6b4",
            "accent_hi":   "#6ff7f0",
            "text":        "#f1f4f7",
            "text_dim":    "#a3adb9",
            "text_faint":  "#6c7683",
            "good":        "#4be08a",
            "warn":        "#f5c563",
            "danger":      "#ff6183",
            "border":      "#333b46",
            "border_soft": "#232932",
        },
    },
    "cyan-wash": {
        "label": "Cyan wash",
        "note": "what the launcher shipped with: dark cyan, one hue",
        "wash": ("#0b2731", "#041319", "diagonal"),
        "page": ("#071c24", "#041119", "diagonal"),
        "nav": ("#0f3541", "#061b23", "vertical"),
        "col": {
            "bg":          "#04141b",
            "bg2":         "#0a2028",
            "bg3":         "#0f2b34",
            "bg_hover":    "#164050",
            "sidebar":     "#061a22",
            "accent":      "#2ee6e0",
            "accent2":     "#79f2e6",
            "accent_hi":    "#6ff7f0",
            "text":        "#eafcff",
            "text_dim":    "#8fb9c2",
            "text_faint":  "#5b838d",
            "good":        "#4be08a",
            "warn":        "#f5c563",
            "danger":      "#ff6183",
            "border":      "#16404c",
            "border_soft": "#0e2a33",
        },
    },
    "flat": {
        "label": "Flat (no gradient)",
        "note": "the least to paint; useful on a slow remote display",
        "wash": ("#0d1116", "#0d1116", "flat"),
        "page": ("#0d1116", "#0d1116", "flat"),
        "nav": ("#12161c", "#12161c", "flat"),
        "col": {
            "bg":          "#0d1116",
            "bg2":         "#161b22",
            "bg3":         "#1d242d",
            "bg_hover":    "#28313d",
            "sidebar":     "#11151b",
            "accent":      "#2ee6e0",
            "accent2":     "#8b98a8",
            "accent_hi":   "#6ff7f0",
            "text":        "#eef2f6",
            "text_dim":    "#9aa5b1",
            "text_faint":  "#69737f",
            "good":        "#4be08a",
            "warn":        "#f5c563",
            "danger":      "#ff6183",
            "border":      "#2c3540",
            "border_soft": "#202832",
        },
    },
}

DEFAULT_BACKGROUND = "divine"

#: the palette the running process is using. ``COL`` below is this dict - code that wants a
#: colour reads ``theme.COL[...]`` and never copies a value, so a restyle reaches everything.
COL = dict(BACKGROUNDS[DEFAULT_BACKGROUND]["col"])

#: The wash behind the shell, as (from, to, angle). Painted as bands at paint time, never
#: animated and never cached as an image - the point of the wash is that the window is not a
#: flat rectangle, not that it moves.
GRADIENT = {
    "from":     BACKGROUNDS[DEFAULT_BACKGROUND]["wash"][0],
    "to":       BACKGROUNDS[DEFAULT_BACKGROUND]["wash"][1],
    "angle":    BACKGROUNDS[DEFAULT_BACKGROUND]["wash"][2],
    "page_from": BACKGROUNDS[DEFAULT_BACKGROUND]["page"][0],
    "page_to": BACKGROUNDS[DEFAULT_BACKGROUND]["page"][1],
    "page_angle": BACKGROUNDS[DEFAULT_BACKGROUND]["page"][2],
    "nav_from": BACKGROUNDS[DEFAULT_BACKGROUND]["nav"][0],
    "nav_to":   BACKGROUNDS[DEFAULT_BACKGROUND]["nav"][1],
    "nav_angle": BACKGROUNDS[DEFAULT_BACKGROUND]["nav"][2],
}


_current_background = DEFAULT_BACKGROUND


_pin_gen = 0          # bumped whenever the palette moves, to retire the stamps below


def background_key() -> str:
    return _current_background



def background_label(key):
    """The name a person would read, for the settings row."""
    spec = BACKGROUNDS.get(key) or {}
    return spec.get("label") or str(key).replace("_", " ").title()


def background_note(key):
    spec = BACKGROUNDS.get(key) or {}
    return spec.get("note") or ""

def background_names():
    """[(key, label, note)] in the order the Settings row shows them."""
    return [(k, v["label"], v["note"]) for k, v in BACKGROUNDS.items()]


def set_background(key) -> bool:
    """Point the palette at one of ``BACKGROUNDS``. Returns False for an unknown key.

    In-place, because a hundred widgets hold ``theme.COL`` - but they resolved their own
    colour at build time, so this only takes effect for widgets built afterwards. That is
    what ``DivineApp.restyle`` is for: it rebuilds the shell, and a rebuild of a launcher
    window takes a couple of hundred milliseconds on a settings change a person makes once.
    """
    global _current_background, _pin_gen
    spec = BACKGROUNDS.get(key)
    if not spec:
        return False
    _current_background = key
    _pin_gen += 1        # every surface stamp was made from the old palette: retire them
    COL.clear()
    COL.update(spec["col"])
    GRADIENT.clear()
    GRADIENT.update({"from": spec["wash"][0], "to": spec["wash"][1], "angle": spec["wash"][2],
                     "nav_from": spec["nav"][0], "nav_to": spec["nav"][1],
                     "nav_angle": spec["nav"][2],
                     "page_from": spec["page"][0], "page_to": spec["page"][1],
                     "page_angle": spec["page"][2]})
    return True


def gradient_colors(kind="main"):
    """(from, to) for one of the three washes: the shell, the sidebar, the pages.

    A page gets its own, darker pair. The shell wash is bright enough to be seen *as* a
    wash; the same colours behind a column of cards read as a purple flood in the margins and
    make every panel look like it is floating, so the page wash is the same hue two steps down.
    """
    if kind == "nav":
        return GRADIENT["nav_from"], GRADIENT["nav_to"]
    if kind == "page":
        return GRADIENT.get("page_from", GRADIENT["from"]), GRADIENT.get("page_to", GRADIENT["to"])
    return GRADIENT["from"], GRADIENT["to"]


def gradient_angle(kind="main"):
    if kind == "nav":
        return GRADIENT["nav_angle"]
    if kind == "page":
        return GRADIENT.get("page_angle", GRADIENT["angle"])
    return GRADIENT["angle"]


def wash_base(kind="main"):
    """The solid colour a surface falls back to: the wash's dark end.

    ``Gradient`` reports this as its own ``fg_color``, so anything that asks its parent for a
    colour - a rounded corner, a transparent label - gets the darkest part of the wash
    instead of a default grey or a stale pixel. That single value is what keeps a repaint
    miss from turning into visible garbage.
    """
    a, b = gradient_colors(kind)
    return b or "#000000"


FONT_FAMILY = "Segoe UI"      # falls back gracefully on other OSes
MONO_FAMILY = "Consolas"




def repaint_locked() -> int:
    """The generation counter the surface stamps are keyed on (for tests and restyle)."""
    return _pin_gen


def paint_surface(widget, color=None):
    """Tell a CustomTkinter widget what colour is behind it, instead of letting it guess.

    This is the whole story of the repaint glitch. A ``CTkFrame`` is a Tk canvas, and
    ``CTkFrame._draw`` finishes with::

        self._canvas.configure(bg=self._apply_appearance_mode(self._bg_color))

    ``_bg_color`` comes from ``bg_color="transparent"``, which means "ask my master" - and
    when the master is a plain Tk frame, or the widget was built before its master had a
    colour, CTk falls back to the *theme* default, a grey (``gray17``). The fill of the frame is
    a canvas item, and items are only redrawn when CTk notices the geometry or colours changed.
    Between the two - a maximize, a restore from the taskbar, a slider that grows a page - the
    canvas is showing its own background: grey. That is the smear.

    Pinning ``_bg_color`` and the canvas ``-background`` to the real colour makes the worst case
    a correct colour, at any size, at any moment, with no timer and no redraw trickery.
    """
    fill = resolve_color(color or COL.get("bg", "#0b0f18"), widget)
    # Idempotence, and it is not a micro-optimisation: the pin runs after every map and every
    # resize, and a configure of a CTk widget costs about as much as its whole redraw - 665
    # widgets, 115 ms, once per <Configure>. So each widget remembers the colour it was last
    # given at. The memory cannot go stale on its own: when CTk redraws a widget it re-stamps
    # its inner widgets from ``_bg_color``, which is exactly the value we set below, so the
    # grey never comes back by itself. It only goes stale when a colour is genuinely different
    # (a palette change, which bumps the generation) or when someone reconfigures ``fg_color``
    # behind our back (which changes ``_bg_color``, checked below).
    stamp = (_pin_gen, fill)
    if getattr(widget, "_divine_pin", None) == stamp and getattr(widget, "_bg_color", fill) == fill:
        return fill
    try:
        widget._bg_color = fill
    except Exception:
        pass
    # A CustomTkinter widget is usually several Tk widgets: a frame is a frame plus a canvas,
    # a label is a frame plus a Label, a button adds another. Each one has its own -background,
    # and every one of them that is left at the theme default will show as grey where the CTk
    # item does not cover it - which is why a label's text used to sit on a grey rectangle.
    nodes = [widget, getattr(widget, "_canvas", None), getattr(widget, "_text_label", None)]
    for node in nodes:
        if node is None:
            continue
        try:
            node.configure(bg=fill)
        except Exception:
            pass   # a plain Tk widget with no -bg, or one already torn down
    try:
        widget._divine_pin = stamp
    except Exception:
        pass
    return fill




def appearance_mode() -> str:
    """What CustomTkinter thinks the mode is, in lowercase.

    ``ThemeManager.appearance_mode`` looks like the obvious read and **does not exist** in
    customtkinter 6.0.0 - it raises ``AttributeError``, so any caller that wrapped it in a
    try/except was getting a silent default forever. ``customtkinter.get_appearance_mode()``
    is the real API.
    """
    try:
        import customtkinter
        return str(customtkinter.get_appearance_mode()).lower()
    except Exception:
        return "dark"


def _appearance_dark() -> bool:
    return appearance_mode() != "light"


def resolve_color(value, widget=None):
    """The colour a light/dark pair will actually show, as CustomTkinter would pick it.

    Every colour in this app is one of two values - a pair for the two appearance modes, or a
    theme default - and picking the wrong half of it is a bug with the same shape as the one
    this module exists to fix: a frame on the Instances header was pinned to ``gray81``, the
    *light* value of ``["gray81", "gray20"]``, while CustomTkinter painted ``gray20``, and the
    six pixels either side of the button in it showed that grey. So ask the widget itself,
    which knows the mode it was drawn in, and only fall back to the mode we are configured for.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    apply = getattr(widget, "_apply_appearance_mode", None)
    if apply is not None:
        try:
            out = apply(value)
        except Exception:
            out = None
        if isinstance(out, str) and out:
            return out
    if isinstance(value, (tuple, list)):
        return str(value[1] if _appearance_dark() and len(value) > 1 else value[0])
    return str(value)


_SURFACE_DEFAULTS = {}


def _theme_surface_defaults():
    """Every colour CustomTkinter would choose for a surface nobody coloured, as strings.

    Not just ``CTkFrame.fg_color``: a frame whose master is the window is given
    ``top_fg_color``, a scrollable frame and a label each have their own entry, and any of
    those left in place is another grey rectangle. Compared as the strings the theme holds, so
    a pair matches whether or not it has been resolved yet.

    Memoised on the theme object and the appearance mode, because this is asked once per
    container of the window during a pin: building the same set 250 times in a walk that is
    supposed to cost single digits of milliseconds is what turned a settled re-pin from 2.8 ms
    into 19 ms, and the settled re-pin is the one that runs on every resize.
    """
    try:
        from customtkinter import ThemeManager
        memo = (id(ThemeManager.theme), appearance_mode())
    except Exception:
        return set()
    hit = _SURFACE_DEFAULTS.get(memo)
    if hit is not None:
        return hit
    out = set()
    try:
        from customtkinter import ThemeManager
        theme = ThemeManager.theme
        for widget in ("CTkFrame", "CTkScrollableFrame", "CTkLabel", "CTk", "CTkToplevel"):
            try:
                entries = theme[widget]
            except Exception:
                continue
            for entry, val in list(entries.items()):
                if "fg_color" not in entry:   # fg_color, top_fg_color, label_fg_color
                    continue
                names = [val] if isinstance(val, str) else list(val)
                if any(str(v).lower() == "transparent" for v in names):
                    continue        # asked to show what is behind it: not a colour to replace
                out.add(str(val))
                out.add(str([str(v) for v in names]))
                for part in names:
                    out.add(str(part))
    except Exception:
        return set()            # a theme that cannot be read is no theme: nothing is cached
    if not out:
        # CustomTkinter fills `ThemeManager.theme` when the first window is made, and a pin can
        # run before that - the version of this function that cached the empty answer then told
        # every later pass that no colour was a theme default, which put theme grey back on
        # 86 canvases at once. An empty set is "not yet", never "nothing to avoid".
        return out
    if len(_SURFACE_DEFAULTS) > 8:            # a theme swapped under us a dozen times is noise
        _SURFACE_DEFAULTS.clear()
    _SURFACE_DEFAULTS[memo] = out
    return out


# Widgets whose ``fg_color`` is drawn content rather than a surface: a tick, a switch's thumb,
# a radio dot. Everything else in CustomTkinter uses ``fg_color`` for "the rectangle I sit in",
# which is why the pinner below reads that colour off the widget - but these three would be
# painted in their own accent if it were.
_INDICATOR = ("CTkCheckBox", "CTkSwitch", "CTkRadioButton")


def pin_surfaces(widget, fill=None, _depth=0, _defaults=None):
    """Recursively give every canvas in this subtree a background of the colour behind it.

    ``paint_surface`` for one widget, this for a whole page. It walks the tree, keeps the
    colour it resolved for each parent, and does two things with it: any frame that never
    asked for a colour of its own takes its parent's (CustomTkinter would otherwise paint the
    theme's grey there), and every surface that has a canvas has that canvas' background set
    and is then redrawn, so the fill item is repainted from the colour we just agreed on.

    Called after the shell is built, after a page switch, after a palette change and on every
    map and resize of a window - a maximise or a restore from the taskbar included, which is
    where the grey used to show. It is therefore built to be repeated: a widget that already
    carries the colour it would be given is skipped outright, so a second pass over a settled
    window is a walk and nothing else (single-digit milliseconds) rather than 665 redraws, and
    only widgets that are new or genuinely off-colour are repainted.
    """
    if _depth > 24 or widget is None:
        return 0
    try:
        kids = widget.winfo_children()
    except Exception:
        return 0
    frame_default = _theme_surface_defaults() if _defaults is None else _defaults
    painted = 0
    for child in kids:
        own = None
        if type(child).__name__ in _INDICATOR:
            # A tick box's ``fg_color`` *is* the box - it is not the colour of anything behind
            # the widget. Reading it as the surface painted the checkbox's whole 138x24 strip
            # in the accent, which is why every "Launch fullscreen" looked like a highlighted
            # bar. Its background is whatever the card behind it is, so that is what it gets.
            color = fill
        elif hasattr(child, "_bg_color"):      # a CustomTkinter widget; Tk ones have no such thing
            try:
                own = child.cget("fg_color")
            except Exception:
                own = None
            if own is not None and str(own) in frame_default:
                # Nothing of ours chose this colour, the theme did - so the colour behind the
                # widget is the one that should be showing.
                try:
                    child.configure(fg_color=fill or COL["bg"])
                    own = fill or COL["bg"]
                except Exception:
                    pass
        color = resolve_color(own, child)
        if color is not None and str(color) in frame_default:
            color = fill or COL["bg"]
        color = color if (color and str(color) != "transparent") else fill
        if color is not None and (hasattr(child, "_canvas") or hasattr(child, "_text_label")):
            have = getattr(child, "_divine_pin", None)
            bg = resolve_color(getattr(child, "_bg_color", color), child)
            if have != (_pin_gen, color) or bg != color:
                # Either it is new, or its colour is not what this subtree should show. The
                # explicit ``_draw`` is for the first case: CTk skips re-applying its own
                # colours when it believes nothing changed, and "nothing changed" is exactly
                # what used to leave the theme grey sitting there.
                paint_surface(child, color)
                try:
                    child._draw()
                    painted += 1
                except Exception:
                    pass
        painted += pin_surfaces(child, color, _depth + 1, frame_default)
    return painted


def auto_pin(widget):
    """Keep a window's surfaces pinned for as long as it lives, not only when it is built.

    ``pin_surfaces`` once at construction covers the first paint and nothing else: a page that
    refreshes itself, a dialog that grows a row, a window that is maximised, all make or move
    widgets afterwards. So the pin is repeated on every map and resize, coalesced to one call per
    idle - the same shape as the hero's cover repaint. A paint of the palette onto ~300 widgets is
    a couple of milliseconds, and it only ever runs when the geometry actually changed.
    """
    state = {"job": None}

    def _soon(_event=None):
        if state["job"] is not None:
            return
        try:
            state["job"] = widget.after_idle(_run)
        except Exception:
            state["job"] = None

    def _run():
        state["job"] = None
        try:
            pin_surfaces(widget)
        except Exception:
            pass

    try:
        widget.bind("<Map>", _soon, add="+")
        widget.bind("<Configure>", _soon, add="+")
    except Exception:
        pass      # a widget that cannot be bound to is a widget that was already destroyed
    _soon()
    return widget


def font(size=13, weight="normal"):
    return (FONT_FAMILY, size, weight)


def title_font(size=22):
    return (FONT_FAMILY, size, "bold")


# --- instance editor palette -------------------------------------------------
# The editor is a dense, multi-section surface, so it uses a slightly lifted
# layer stack and one accent colour per section. That way you always know which
# part of the instance you are looking at, and the counts read as part of it.
EDITOR = {
    "canvas":    "#04161e",   # window behind everything
    "header":    "#0b2934",   # identity strip at the top
    "rail":      "#071f27",   # section list
    "rail_sel":  "#123a47",   # active section
    "surface":   "#0d2932",   # cards
    "surface_hi":"#10333f",   # rows inside cards
    "hairline":  "#1b4a58",
    "ink":       "#eafcff",
    "ink_dim":   "#8fb9c2",
    "ink_faint": "#5b838d",
}

# one accent per section - teal / violet / green / amber / blue
SECTION = {
    "details": {"label": "Details", "short": "Details", "icon": "\u2699",
                "accent": "#38e1d0",
                "blurb": "Name, Minecraft version and loader for this instance."},
    "mods":    {"label": "Mods", "short": "Mods", "icon": "\u2637",
                "accent": "#79f2e6",
                "blurb": "The .jar files this instance loads. Toggle them off "
                         "instead of deleting them."},
    "worlds":  {"label": "Worlds", "short": "Worlds", "icon": "\u25A3",
                "accent": "#4be08a",
                "blurb": "Singleplayer saves that live in this instance only."},
    "packs":   {"label": "Resource packs", "short": "Packs", "icon": "\u25C7",
                "accent": "#f5c563",
                "blurb": "Texture and resource packs shipped with the instance."},
    "servers": {"label": "Servers", "short": "Servers", "icon": "\u2609",
                "accent": "#7aa2ff",
                "blurb": "Multiplayer servers added from this instance."},
}


def section_accent(key, default=None):
    return (SECTION.get(key) or {}).get("accent", default or COL["accent"])

# --- the side panel -----------------------------------------------------------
# The gradient and the slide timings that used to be here went with the sliding
# rails (phase 9b): the sidebar in ui.nav is a flat column of the theme's own
# colours, and the friends panel is a Card. What is left is the friend palette,
# which is a product decision rather than a styling one.

# Who is who in the friend list, exactly as specified: bright green when they are in
# Minecraft right now, orange when they are around but idle, and offline names recede.
FRIEND = {
    "playing":  "#2bff88",
    "idle":     "#ff9f2e",
    "offline":  "#171a22",   # near black; the row keeps a dim handle so it is findable
    "offline_text": "#5b6480",
    "dot_playing": "#2bff88",
    "dot_idle":    "#ff9f2e",
    "dot_offline": "#2a2f3d",
}


def friend_color(state):
    """(name colour, dot colour) for one of the three friend states."""
    if state == "playing":
        return FRIEND["playing"], FRIEND["dot_playing"]
    if state == "idle":
        return FRIEND["idle"], FRIEND["dot_idle"]
    return FRIEND["offline_text"], FRIEND["dot_offline"]
