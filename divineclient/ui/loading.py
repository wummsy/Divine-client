"""A plain loading window: what the launcher is doing, and how far it got.

Phase 9 shipped a self-drawing canvas version (animated cube, gradient, staged fade-outs,
a ticking bar that crept toward each stage's ceiling). It was the nicest thing in the app
and the least useful: the crawl meant a stalled step still looked like progress, the fade
left a black frame on slow displays, and the whole thing needed a Tk timer running while
the main thread was busy importing Java runtime code - so exactly when the user wanted to
see it, it froze.

This version draws once per event. ``stage(key)`` sets the bar and the checklist, nothing
repeats on a timer, and ``finish()`` destroys the window instead of animating it out. The
stage weights are kept, because they are the one genuinely good idea in the old file: a
stage can only fill the bar up to its own ceiling, so a launcher stuck at "versions" can
never show 100%.
"""
import tkinter as tk

import customtkinter as ctk

from .. import paths
from . import theme

#: (key, weight, label). Weights sum to 1.0 and a stage may not pass its own ceiling.
STAGES = [
    ("boot", 0.10, "Starting"),
    ("java", 0.22, "Java runtime"),
    ("versions", 0.24, "Versions"),
    ("manifest", 0.26, "Version manifests"),
    ("mods", 0.12, "Mods"),
    ("ready", 0.06, "Ready"),
]

_LABELS = {name: (weight, label) for name, weight, label in STAGES}


class Loading(ctk.CTkToplevel):
    """A small, flat, non-animating splash window."""

    def __init__(self, master, width=470, height=212):
        super().__init__(master)
        self._width = width
        self._height = height
        self._done_stages = set()
        self.title("Divine Client")
        try:
            self.overrideredirect(True)
        except tk.TclError:
            pass
        for attr in ("-topmost",):
            try:
                self.attributes(attr, True)
            except tk.TclError:
                pass
        self.configure(fg_color=theme.COL["bg"])
        self._place_center()
        self._build()
        self._icon()
        self.update_idletasks()

    # ------------------------------------------------------------------ setup
    def _place_center(self):
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            sw, sh = 1280, 800
        x = max(0, (sw - self._width) // 2)
        y = max(0, (sh - self._height) // 2 - 20)
        self.geometry("%dx%d+%d+%d" % (self._width, self._height, x, y))

    def _icon(self):
        try:
            ico = paths.resource_path("assets/icon.ico")
            if __import__("os").path.exists(ico):
                self.iconbitmap(default=ico)
        except Exception:
            pass

    def _build(self):
        pad = {"padx": 22}
        row = 0
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=row, column=0, sticky="ew", **pad, pady=(20, 0))
        head.grid_columnconfigure(1, weight=1)

        # the logo, not an icon plus the name typed out again
        from .widgets import load_ctk_image
        self.logo_lbl = ctk.CTkLabel(head, text="", height=44)
        img = load_ctk_image("assets/logo.png", (126, 44))
        if img is not None:
            self.logo_lbl.configure(image=img)
        else:
            self.logo_lbl.configure(text="DIVINE CLIENT", font=theme.font(17, "bold"),
                                    text_color=theme.COL["text"])
        self.logo_lbl.grid(row=0, column=0, sticky="w")
        try:
            from .. import CLIENT_VERSION
        except ImportError:
            CLIENT_VERSION = "?"
        ctk.CTkLabel(head, text="v%s" % CLIENT_VERSION, font=theme.font(11),
                     text_color=theme.COL["text_faint"]).grid(row=0, column=2, sticky="e")
        row += 1

        self.status_lbl = ctk.CTkLabel(self, text="Starting\u2026", anchor="w",
                                       font=theme.font(12),
                                       text_color=theme.COL["text_dim"])
        self.status_lbl.grid(row=row, column=0, sticky="ew", **pad, pady=(16, 4))
        row += 1

        self.bar = ctk.CTkProgressBar(self, height=10, corner_radius=5,
                                      progress_color=theme.COL["accent"],
                                      fg_color=theme.COL["bg3"])
        self.bar.grid(row=row, column=0, sticky="ew", **pad)
        self.bar.set(0.0)
        row += 1

        self.stages_lbl = ctk.CTkLabel(self, text=self._checklist(), anchor="w",
                                       justify="left", font=theme.font(10),
                                       text_color=theme.COL["text_faint"])
        self.stages_lbl.grid(row=row, column=0, sticky="ew", **pad, pady=(10, 14))

    # ------------------------------------------------------------------- draw
    def _checklist(self):
        parts = []
        for name, _weight, label in STAGES:
            mark = "\u2713" if name in self._done_stages else "\u00b7"
            parts.append("%s %s" % (mark, label))
        return "   ".join(parts)

    def stage(self, key, note=""):
        """Move to a stage. The bar may reach that stage's ceiling and no further."""
        index = next((i for i, (n, _w, _l) in enumerate(STAGES) if n == key), None)
        if index is None:
            self.set_status(note or key)
            return
        _name, weight, label = STAGES[index]
        self._done_stages = {n for n, _w, _l in STAGES[:index]}
        ceiling = sum(w for _n, w, _l in STAGES[:index + 1])
        self.set_status(label if not note else "%s \u2014 %s" % (label, note), ceiling)
        self._redraw_checklist()

    def set_status(self, text, frac=None):
        try:
            self.status_lbl.configure(text=text)
            if frac is not None:
                self.bar.set(max(0.0, min(1.0, float(frac))))
        except tk.TclError:
            pass

    def _redraw_checklist(self):
        try:
            self.stages_lbl.configure(text=self._checklist())
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ close
    def finish(self):
        """Called once the main window is mapped. No fade: it just goes away."""
        for name, _w, _l in STAGES:
            self._done_stages.add(name)
        try:
            self.bar.set(1.0)
            self.status_lbl.configure(text="Ready")
            self._redraw_checklist()
        except tk.TclError:
            pass
        self.destroy()

    def destroy(self):
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        super().destroy()
