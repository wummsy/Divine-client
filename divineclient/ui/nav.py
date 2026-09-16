"""The launcher's sidebar: the mark, the pages, the account, and the update pill.

A fixed 208 px column - flat, always the same width, nothing that moves. Rows are a glyph
from ``assets/ui_*.png`` and a word; the four supplied marks (friends, account, new, Discord)
are used where they apply and the rest of the set is drawn to match them (see
``tools/make_ui_glyphs.py``). Text stays on every row even when the picture loaded, because a
20 px mark without a word is a scavenger hunt, and because a build without Pillow must look
plainer rather than broken.

What is deliberate:
* the row is one ``CTkButton`` and selection is one colour swap - no second frame to keep in
  sync, nothing that can be left half-painted when the window comes back from the taskbar;
* the account sits at the *top* and pressing it switches account. It is the only way to
  switch from the shell, because two ways to do one thing is how people end up signed out by
  accident;
* the Servers row carries a W.I.P. badge until the allowance code is entered;
* the update pill is at the bottom and wraps, because "Update 1.6 - downloading" is 24
  characters and a 208 px column is not.
"""
import tkinter as tk

import customtkinter as ctk

from .. import paths
from . import theme
from .widgets import Gradient, load_ctk_image, load_glyph

WIDTH = 208

#: (page key, label, glyph). Order is the order in the sidebar; ``settings`` and ``about``
#: sit at the bottom so the everyday pages are grouped together.
MAIN_ITEMS = [
    ("home", "Home", "ui_home"),
    ("instances", "Instances", "ui_instances"),
    ("servers", "Servers", "ui_servers"),
]

FOOT_ITEMS = [
    ("accounts", "Accounts", "ui_account"),
    ("settings", "Settings", "ui_settings"),
    ("about", "About", "ui_about"),
]

#: if Pillow is missing there is no PNG, so the row falls back to a text mark
FALLBACK = {
    "ui_home": "\u2302", "ui_instances": "\u25a6", "ui_servers": "\u2601",
    "ui_account": "\u263a", "ui_settings": "\u2699", "ui_about": "\u24d8",
}

ROW_HEIGHT = 42
GLYPH_PX = (20, 20)


class SideNav(Gradient):
    """Left column of the launcher, on the theme's wash."""

    WIDTH = WIDTH      # also exported at module level; the app reads it off the class

    def __init__(self, master, app):
        super().__init__(master, kind="nav", corner_radius=0,
                         border_width=1, border_color=theme.COL["border"])
        self.app = app
        self.buttons = {}
        self._icons = {}                       # key -> (dim image, accent image)
        self._titles = {key: label for key, label, _g in MAIN_ITEMS + FOOT_ITEMS}
        self._glyph_of = {key: glyph for key, _l, glyph in MAIN_ITEMS + FOOT_ITEMS}
        self._server_count = 0

        # head / account / pages / footer - one row each, so nothing can overlap. (An
        # earlier revision put the account row and the page list in the same cell, and the
        # account silently disappeared behind a transparent frame.)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_head()
        self._build_account()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=(2, 6))
        body.grid_columnconfigure(0, weight=1)
        r = 0
        for key, label, glyph in MAIN_ITEMS:
            self._make_button(body, r, key, label, glyph)
            r += 1
        r += 1
        for key, label, glyph in FOOT_ITEMS:
            self._make_button(body, r, key, label, glyph)
            r += 1

        self._build_foot()

    # ------------------------------------------------------------------ head
    def _build_head(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        head.grid_columnconfigure(0, weight=1)

        # The logo is the whole head: it carries the mark and the word, so the sidebar
        # does not repeat the word "CLIENT" a third time next to it.
        self.logo_lbl = ctk.CTkLabel(head, text="", height=56)
        img = load_ctk_image("assets/logo.png", (168, 58))
        if img is not None:
            self.logo_lbl.configure(image=img)
        else:
            self.logo_lbl.configure(text="DIVINE  CLIENT", font=theme.font(15, "bold"),
                                    text_color=theme.COL["text"])
        self.logo_lbl.grid(row=0, column=0, sticky="w", pady=(0, 2))

    # --------------------------------------------------------------- account row
    def _build_account(self):
        """The account you are playing as, at the top. Pressing it switches account."""
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 2))
        box.grid_columnconfigure(0, weight=1)
        self._glyph = load_glyph("assets/ui_account.png", GLYPH_PX)
        self.account_btn = ctk.CTkButton(
            box, text="  Not signed in", font=theme.font(12, "bold"), height=46,
            anchor="w", fg_color=theme.COL["bg3"], hover_color=theme.COL["bg_hover"],
            text_color=theme.COL["text"], corner_radius=10, compound="left",
            image=self._glyph or "", command=self._account_pressed)
        self.account_btn.grid(row=0, column=0, sticky="ew")
        self._account_sub = ctk.CTkLabel(
            box, text="Sign in to play online", font=theme.font(10),
            text_color=theme.COL["text_faint"])
        self._account_sub.grid(row=1, column=0, sticky="w", padx=(12, 0), pady=(3, 0))

    # ------------------------------------------------------------------ foot
    def _build_foot(self):
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 10))
        foot.grid_columnconfigure(0, weight=1)

        # wraps, and is allowed two or three lines: this text is the whole reason the pill
        # exists and a clipped "downloadi" tells you nothing
        self.pill = ctk.CTkLabel(foot, text="", font=theme.font(10, "bold"),
                                 fg_color=theme.COL["bg3"], text_color=theme.COL["text"],
                                 corner_radius=9, padx=10, pady=6, anchor="w",
                                 justify="left", wraplength=WIDTH - 46)
        self.pill.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.pill.grid_remove()
        self.pill.bind("<Button-1>", lambda e: self.app.update_action())

        self.version_lbl = ctk.CTkLabel(foot, text="", font=theme.font(10),
                                        text_color=theme.COL["text_faint"])
        self.version_lbl.grid(row=1, column=0, sticky="w")
        self.set_version_label()

    # ------------------------------------------------------------- make/config
    def _icons_for(self, key, glyph):
        """(unselected, selected) images for a row. Either may be None."""
        if key in self._icons:
            return self._icons[key]
        dim = load_glyph("assets/%s.png" % glyph, GLYPH_PX, color=theme.COL["text_dim"])
        hot = load_glyph("assets/%s.png" % glyph, GLYPH_PX, color=theme.COL["accent"])
        self._icons[key] = (dim, hot)
        return dim, hot

    def _make_button(self, parent, row, key, label, glyph):
        dim, hot = self._icons_for(key, glyph)
        text = ("  %s" % label) if dim is not None \
            else "%s   %s" % (FALLBACK.get(glyph, ""), label)
        btn = ctk.CTkButton(parent, text=text,
                            font=theme.font(13, "bold"), height=ROW_HEIGHT, anchor="w",
                            corner_radius=10, fg_color="transparent",
                            hover_color=theme.COL["bg3"],
                            text_color=theme.COL["text_dim"],
                            image=dim or "", compound="left",
                            command=lambda k=key: self.app.show_page(k))
        # CTk puts the image left of the text and indents neither, so the two leading spaces
        # are the gap. It looks fussy in source and correct on screen - and it keeps working
        # on CustomTkinter 5.2, which has no padding options on a button at all.
        btn.grid(row=row, column=0, sticky="ew", padx=2, pady=2)
        self.buttons[key] = btn

    def set_page(self, key):
        """Flat selection state: filled background, accent text and mark. No tween."""
        for k, btn in self.buttons.items():
            sel = (k == key)
            dim, hot = self._icons_for(k, self._glyph_of.get(k, ""))
            try:
                btn.configure(
                    fg_color=theme.COL["bg3"] if sel else "transparent",
                    text_color=theme.COL["accent"] if sel else theme.COL["text_dim"],
                    image=(hot if sel else dim) or btn.cget("image"))
            except tk.TclError:
                pass

    def set_version_label(self, extra=""):
        try:
            from .. import CLIENT_VERSION
        except ImportError:
            CLIENT_VERSION = "?"
        self.version_lbl.configure(
            text="v%s %s" % (CLIENT_VERSION, extra) if extra else "v%s" % CLIENT_VERSION)

    def set_server_badge(self, count):
        """Show how many local servers are live on the Servers button."""
        self._server_count = count
        btn = self.buttons.get("servers")
        if btn is None:
            return
        label = self._titles.get("servers", "Servers")
        if not str(btn.cget("image")):                  # no PIL: keep the text mark
            label = "%s   %s" % (FALLBACK.get(self._glyph_of.get("servers", ""), ""), label)
        try:
            btn.configure(text=label + ("  \u00b7  %d" % count if count else ""))
        except tk.TclError:
            pass

    def set_update_state(self, state, text):
        """Update pill from ``core.updater`` state names."""
        colors = {
            "info": (theme.COL["bg3"], theme.COL["text"]),
            "good": (theme.COL["accent"], "#04121a"),
            "warn": (theme.COL["warn"], "#1a1206"),
            "danger": (theme.COL["danger"], "#ffffff"),
        }
        if not text:
            self.pill.grid_remove()
            return
        fg, txt = colors.get(state, colors["info"])
        try:
            self.pill.configure(text=text, fg_color=fg, text_color=txt)
            self.pill.grid()
        except tk.TclError:
            pass

    # ------------------------------------------------------------- account
    # Accounts are plain dicts (`id`, `type`, `name`, `uuid`) - the store has never
    # carried objects, and reading attributes off a dict is how a UI ends up printing "?"
    # for a name that is right there.
    def refresh_account(self):
        acc = None
        try:
            acc = self.app.accounts.get_active()
        except Exception:
            acc = None
        if not acc:
            self.account_btn.configure(text="Not signed in",
                                       text_color=theme.COL["text_dim"])
            self._account_sub.configure(text="Sign in to play online")
            return
        kind = {"microsoft": "Microsoft", "offline": "Offline name"}.get(
            acc.get("type"), acc.get("type") or "account")
        self.account_btn.configure(text="  %s" % (acc.get("name") or "?"),
                                   text_color=theme.COL["text"])
        self._account_sub.configure(text=kind)

    def _account_pressed(self):
        """Switch account from the sidebar, or go add one if there is nothing to switch."""
        try:
            accounts = list(self.app.accounts.accounts or [])
        except Exception:
            accounts = []
        if len(accounts) < 2:
            self.app.show_page("accounts")
            return
        self._account_menu(accounts)

    def _account_menu(self, accounts):
        menu = tk.Toplevel(self)
        menu.title("Switch account")
        menu.configure(bg=theme.COL["bg2"])
        menu.overrideredirect(True)
        try:
            menu.attributes("-topmost", True)
        except tk.TclError:
            pass
        x = self.account_btn.winfo_rootx()
        y = self.account_btn.winfo_rooty() + self.account_btn.winfo_height() + 4
        menu.geometry("+%d+%d" % (x, y))
        menu.resizable(False, False)

        active = None
        try:
            active = self.app.accounts.active_id
        except Exception:
            pass
        for acc in accounts:
            kind = {"microsoft": "Microsoft", "offline": "offline"}.get(
                acc.get("type"), acc.get("type") or "")
            mark = "\u2713 " if acc.get("id") == active else "   "
            tk.Button(menu, text="%s%s  (%s)" % (mark, acc.get("name", "?"), kind),
                      anchor="w", bd=0, padx=14, pady=8,
                      bg=theme.COL["bg2"], fg=theme.COL["text"],
                      activebackground=theme.COL["bg_hover"],
                      activeforeground=theme.COL["text"], font=("Segoe UI", 10),
                      command=lambda a=acc: self._pick(a, menu)).pack(fill="x")
        tk.Frame(menu, bg=theme.COL["border"], height=1).pack(fill="x")
        tk.Button(menu, text="Manage accounts\u2026", anchor="w", bd=0, padx=14, pady=8,
                  bg=theme.COL["bg2"], fg=theme.COL["text_dim"],
                  activebackground=theme.COL["bg_hover"], activeforeground=theme.COL["text"],
                  font=("Segoe UI", 10),
                  command=lambda: (menu.destroy(), self.app.show_page("accounts"))).pack(fill="x")

        menu.bind("<FocusOut>", lambda e: menu.destroy())
        menu.bind("<Escape>", lambda e: menu.destroy())
        menu.after(30, menu.focus_force)
        self._menu = menu          # kept so a test (or a re-click) can find it

    def _pick(self, acc, menu):
        try:
            menu.destroy()
        except Exception:
            pass
        try:
            self.app.accounts.set_active(acc["id"])
        except Exception as exc:
            self.app.set_status("Could not switch account: %s" % exc)
        self.refresh_account()
        self.app.refresh_top_account()

    def destroy(self):
        try:
            getattr(self, "_menu", None) and self._menu.destroy()
        except Exception:
            pass
        super().destroy()
