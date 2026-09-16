"""In-app Modrinth browser: search, pick a version, install into an instance.

Handles both mods (installed into mods/, with dependency resolution) and
resource packs (dropped into resourcepacks/), selected via project_type.
"""
import os
import threading

import customtkinter as ctk

from .. import paths
from ..core import modrinth
from ..core import instance_content
from . import theme
from . import imagedesk
from .widgets import Card, accent_button, ghost_button, scroll_frame

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

_ICON_CACHE = os.path.join(paths.DATA_DIR, "cache", "mod_icons")

SORTS = [("Relevance", "relevance"), ("Downloads", "downloads"),
         ("Followers", "follows"), ("Newest", "newest"), ("Updated", "updated")]

# Per-project-type presentation and behaviour.
_KINDS = {
    "mod": {
        "noun": "mods",
        "title": "Browse mods",
        "placeholder": "Search mods (e.g. sodium, jei, shaders)...",
        "empty": "No mods found. Try a different search.",
    },
    "resourcepack": {
        "noun": "resource packs",
        "title": "Browse resource packs",
        "placeholder": "Search resource packs (e.g. faithful, bare bones)...",
        "empty": "No resource packs found. Try a different search.",
    },
}


def _human(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    for unit, div in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)


class ModBrowser(ctk.CTkToplevel):
    def __init__(self, app, instance, on_close=None, project_type="mod"):
        super().__init__(app)
        self.app = app
        self.instance = instance
        self.project_type = project_type if project_type in _KINDS else "mod"
        self.kind = _KINDS[self.project_type]
        self._on_close_cb = on_close
        self._loading = False
        self._offset = 0
        self._query = ""
        self._sort = "relevance"
        self._icon_refs = []
        # every search bumps this; a reply for an older one is thrown away, so
        # typing fast (or hitting Search twice) can never interleave two pages
        self._gen = 0
        self._debounce = None
        self._dead = False
        self._queue = []
        self._hits = []
        self._base_row = 0
        self._total = 0
        self._more_btns = []
        self._queue = []
        self._base_row = 0
        self._total = 0

        self.title("Add " + self.kind["noun"] + " \u2014 " + instance.name)
        theme.auto_pin(self)   # dialogs are not pages: nothing else walks them
        self.geometry("780x660")
        self.minsize(620, 520)
        self.configure(fg_color=theme.COL["bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.after(200, self._apply_icon)

        self._build_header()
        self._build_toolbar()

        self.results = scroll_frame(self)
        self.results.grid(row=2, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.results.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="", font=theme.font(12),
                                   text_color=theme.COL["text_dim"])
        self.status.grid(row=3, column=0, sticky="w", padx=20, pady=(0, 10))

        self._run_search(reset=True)
        self.protocol("WM_DELETE_WINDOW", self._closed)

    def _apply_icon(self):
        try:
            import tkinter as tk
            png = paths.resource_path(os.path.join("assets", "emblem.png"))
            if os.path.exists(png):
                self.iconphoto(False, tk.PhotoImage(file=png))
        except Exception:
            pass

    def _closed(self):
        self._dead = True
        self._gen += 1              # drop any reply that is on its way
        if self._on_close_cb:
            try:
                self._on_close_cb()
            except Exception:
                pass
        self.destroy()

    # ---- header / toolbar ---------------------------------------
    def _build_header(self):
        head = ctk.CTkFrame(self)
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=self.kind["title"], font=theme.title_font(23),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w")
        loader = "Fabric" if self.instance.loader == "fabric" else self.instance.loader
        meta = "From Modrinth  \u2022  Minecraft " + self.instance.mc_version
        if self.project_type == "mod":
            meta += "  \u2022  " + loader
        ctk.CTkLabel(head, text=meta, font=theme.font(12),
                     text_color=theme.COL["accent"]
                     ).grid(row=1, column=0, sticky="w", pady=(3, 0))

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 2))
        bar.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(bar, height=42, font=theme.font(14),
                                         fg_color=theme.COL["bg3"], border_color=theme.COL["border"],
                                         placeholder_text=self.kind["placeholder"])
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self._run_search(reset=True))
        # type and it searches - but only once you stop typing, otherwise every
        # keystroke fired a request and the list flashed half-typed words
        self.search_entry.bind("<KeyRelease>", self._on_type)

        self.sort_menu = ctk.CTkOptionMenu(
            bar, values=[s[0] for s in SORTS], width=140, height=42,
            font=theme.font(13), fg_color=theme.COL["bg3"], button_color=theme.COL["bg_hover"],
            button_hover_color=theme.COL["accent"], dropdown_fg_color=theme.COL["bg3"],
            dropdown_hover_color=theme.COL["bg_hover"], command=self._on_sort)
        self.sort_menu.grid(row=0, column=1, padx=(0, 8))
        accent_button(bar, "Search", lambda: self._run_search(reset=True),
                      width=110, height=42).grid(row=0, column=2)

    def _on_type(self, _event=None):
        if self._debounce is not None:
            try:
                self.after_cancel(self._debounce)
            except Exception:
                pass
        try:
            self._debounce = self.after(320, lambda: self._run_search(reset=True))
        except Exception:
            pass

    def _on_sort(self, label):
        for name, key in SORTS:
            if name == label:
                self._sort = key
        self._run_search(reset=True)

    # ---- search --------------------------------------------------
    def _loader(self):
        if self.project_type != "mod":
            return None
        return self.instance.loader if self.instance.loader in ("fabric", "forge", "quilt", "neoforge") else "fabric"

    def _run_search(self, reset=False):
        if not reset and self._loading:
            return                      # "Load more" waits for the page before it
        if reset:
            self._offset = 0
            for w in self.results.winfo_children():
                w.destroy()
            self._icon_refs.clear()
        # drop the "Load more" button before counting rows for the next page,
        # otherwise it is counted as a result row and page 2 starts one row too low
        for old in self._more_btns:
            try:
                old.destroy()
            except Exception:
                pass
        self._more_btns = []
        self._query = self.search_entry.get().strip()
        self._loading = True
        self._gen += 1
        self.status.configure(text="Searching Modrinth...", text_color=theme.COL["text_dim"])
        threading.Thread(target=self._search_worker, args=(self._gen,), daemon=True).start()

    def _search_worker(self, gen):
        # read the UI state here, once, so a later keystroke cannot change it
        # under us while the request is in flight
        query, sort, offset = self._query, self._sort, self._offset
        try:
            hits, total = modrinth.search(
                query, mc_version=self.instance.mc_version, loader=self._loader(),
                index=sort, limit=20, offset=offset, project_type=self.project_type)
            self._post(lambda: self._render_hits(gen, hits, total))
        except Exception as e:
            msg = str(e)
            self._post(lambda: self._search_error(gen, msg))

    def _post(self, fn):
        """Run fn on the UI thread, if this window is still around."""
        try:
            if self._dead or not self.winfo_exists():
                return
            self.after(0, fn)
        except Exception:
            pass

    def _search_error(self, gen, msg):
        if gen != self._gen:
            return
        self._loading = False
        self.status.configure(text="Search failed: " + msg[:100] + " - check your "
                              "connection, then press Search again",
                              text_color=theme.COL["danger"])

    def _render_hits(self, gen, hits, total):
        if gen != self._gen or self._dead:
            return
        self._loading = False
        base_row = len(self.results.winfo_children())
        self._hits = hits
        self._queue = list(enumerate(hits))
        self._base_row = base_row
        self._total = total
        self._paint_chunk(gen)

    def _paint_chunk(self, gen):
        """Build a few cards per frame.

        Twenty cards is 20 frames' worth of Tk work in one go, which reads as a
        stutter on a slower machine; in batches of six the window keeps painting.
        """
        if gen != self._gen or self._dead:
            return
        chunk = self._queue[:6]
        del self._queue[:6]
        for i, hit in chunk:
            self._result_card(hit, self._base_row + i)
        if self._queue:
            self.after(1, lambda: self._paint_chunk(gen))
            return
        hits = self._hits
        total = self._total
        if self._base_row == 0 and not hits:
            ctk.CTkLabel(self.results, text=self.kind["empty"],
                         font=theme.font(14), text_color=theme.COL["text_faint"]
                         ).grid(row=0, column=0, sticky="w", padx=10, pady=20)
            self.status.configure(text="")
            return
        self._offset += len(hits)
        self.status.configure(
            text="Showing %d of %s results" % (self._offset, total or "?"),
            text_color=theme.COL["text_dim"])
        if self._offset and total and self._offset < total:
            more = ghost_button(self.results, "Load more",
                                lambda: self._run_search(reset=False), height=38)
            more.grid(row=self._base_row + len(hits), column=0, sticky="ew",
                      padx=6, pady=8)
            self._more_btns.append(more)

    def _result_card(self, hit, row):
        card = Card(self.results, fg_color=theme.COL["bg2"])
        card.grid(row=row, column=0, sticky="ew", padx=6, pady=5)
        card.grid_columnconfigure(1, weight=1)

        # letter tile immediately; the real icon is fetched and decoded off the
        # UI thread by the shared image desk (see ui/imagedesk.py)
        icon = ctk.CTkLabel(card, text=(hit["title"][:1] or "?").upper(), width=54, height=54,
                            corner_radius=12, font=theme.font(20, "bold"),
                            text_color="#04121a", fg_color=theme.COL["accent"])
        icon.grid(row=0, column=0, rowspan=3, padx=(14, 12), pady=14)
        url = hit.get("icon_url")
        if url:
            imagedesk.DESK.show(icon, url, url=url, size=(54, 54))

        ctk.CTkLabel(card, text=hit["title"], font=theme.font(15, "bold"),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=1, sticky="w", pady=(12, 0))
        desc = hit["description"] or ""
        if len(desc) > 92:
            desc = desc[:92] + "\u2026"
        ctk.CTkLabel(card, text=desc, font=theme.font(11),
                     text_color=theme.COL["text_dim"], anchor="w", justify="left",
                     wraplength=430).grid(row=1, column=1, sticky="w", pady=(0, 4))
        meta = "\u2b07 " + _human(hit["downloads"]) + "   \u2022   by " + (hit["author"] or "?")
        ctk.CTkLabel(card, text=meta, font=theme.font(10),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=2, column=1, sticky="w", pady=(0, 12))

        accent_button(card, "Install", lambda h=hit: self._open_install(h),
                      width=104, height=42).grid(row=0, column=2, rowspan=3, padx=14)

    def _load_icon(self, url):
        """Kept for callers outside this file; use imagedesk.DESK.show instead."""
        if not (_HAS_PIL and url):
            return None
        try:
            path = modrinth.icon_path(url, _ICON_CACHE)
            return path if os.path.exists(path) else None
        except Exception:
            return None

    # ---- install dialog -----------------------------------------
    def _open_install(self, hit):
        InstallDialog(self, hit)


class InstallDialog(ctk.CTkToplevel):
    def __init__(self, browser, hit):
        super().__init__(browser)
        self.browser = browser
        self.instance = browser.instance
        self.project_type = browser.project_type
        self.hit = hit
        self._versions = []
        self._installing = False

        self.title("Install " + hit["title"])
        self.geometry("560x480")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(browser)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text=hit["title"], font=theme.title_font(20),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w",
                                                        padx=22, pady=(20, 2))
        if self.project_type == "resourcepack":
            note = ("Choose a version for Minecraft " + self.instance.mc_version
                    + ". The pack is added to this instance; enable it in-game under "
                    "Options \u2192 Resource Packs.")
        else:
            note = ("Choose a version for Minecraft " + self.instance.mc_version
                    + ". Required dependencies install automatically.")
        ctk.CTkLabel(self, text=note, font=theme.font(12),
                     text_color=theme.COL["text_dim"], wraplength=500, justify="left"
                     ).grid(row=1, column=0, sticky="w", padx=22)

        self.vlist = scroll_frame(self, fg_color=theme.COL["bg"])
        self.vlist.grid(row=2, column=0, sticky="nsew", padx=18, pady=12)
        self.vlist.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="Loading versions...", font=theme.font(12),
                                   text_color=theme.COL["accent"])
        self.status.grid(row=3, column=0, sticky="w", padx=22, pady=(0, 6))

        row = ctk.CTkFrame(self)
        row.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 16))
        row.grid_columnconfigure(0, weight=1)
        ghost_button(row, "Close", self.destroy, width=110).grid(row=0, column=1)

        threading.Thread(target=self._load_versions, daemon=True).start()

    def _load_versions(self):
        try:
            vs = modrinth.get_versions(self.hit["slug"] or self.hit["project_id"],
                                       self.instance.mc_version, self.browser._loader())
            self.after(0, lambda: self._render_versions(vs))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.status.configure(
                text="Could not load versions: " + msg[:80], text_color=theme.COL["danger"]))

    def _render_versions(self, versions):
        self._versions = versions
        for w in self.vlist.winfo_children():
            w.destroy()
        if not versions:
            self.status.configure(
                text="No versions available for MC " + self.instance.mc_version + ".",
                text_color=theme.COL["warn"])
            return
        self.status.configure(text=str(len(versions)) + " versions available",
                              text_color=theme.COL["text_dim"])
        for i, v in enumerate(versions):
            self._version_row(v, i)

    def _version_row(self, v, i):
        card = Card(self.vlist, fg_color=theme.COL["bg3"])
        card.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)

        colours = {"release": theme.COL["good"], "beta": theme.COL["warn"], "alpha": theme.COL["danger"]}
        tag = v["version_type"]
        ctk.CTkLabel(card, text=v["version_number"], font=theme.font(13, "bold"),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        sub = tag.upper() + "   \u2022   " + (v["date_published"][:10] if v["date_published"] else "")
        if self.project_type == "mod" and v["dependencies"]:
            req = sum(1 for d in v["dependencies"] if d.get("dependency_type") == "required")
            if req:
                sub += "   \u2022   +" + str(req) + " dependency"
        ctk.CTkLabel(card, text=sub, font=theme.font(10),
                     text_color=colours.get(tag, theme.COL["text_faint"]), anchor="w"
                     ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        accent_button(card, "Install", lambda ver=v: self._install(ver),
                      width=96, height=36).grid(row=0, column=1, rowspan=2, padx=12)

    def _install(self, version):
        if self._installing:
            return
        self._installing = True
        self.status.configure(text="Installing " + version["filename"] + "...",
                              text_color=theme.COL["accent"])
        threading.Thread(target=self._install_worker, args=(version,), daemon=True).start()

    def _install_worker(self, version):
        def prog(text, frac):
            if text:
                self.after(0, lambda: self.status.configure(text=text, text_color=theme.COL["accent"]))

        try:
            if self.project_type == "resourcepack":
                target = instance_content.resource_packs_dir(self.instance.game_dir)
                name = modrinth.install_file(
                    version, target,
                    progress=lambda f: prog(None, f))
                msg = "\u2713 Added " + version["filename"] if name else \
                    "\u2713 Already installed"
                self.after(0, lambda: self.status.configure(text=msg, text_color=theme.COL["good"]))
            else:
                mods_dir = os.path.join(self.instance.game_dir, "mods")
                installed, skipped = modrinth.install_with_dependencies(
                    version, mods_dir, self.instance.mc_version, self.browser._loader(),
                    progress=prog)
                msg = "\u2713 Installed " + str(len(installed)) + " file(s)"
                if skipped:
                    msg += ", " + str(len(skipped)) + " failed"
                self.after(0, lambda: self.status.configure(text=msg, text_color=theme.COL["good"]))
        except Exception as e:
            emsg = str(e)
            self.after(0, lambda: self.status.configure(text="Failed: " + emsg[:80],
                                                        text_color=theme.COL["danger"]))
        finally:
            self._installing = False
