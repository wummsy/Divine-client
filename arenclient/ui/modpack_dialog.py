"""Install a Modrinth modpack as a new instance.

The dialog is a search box, a list, and one button per row. Everything that touches the
network runs on a worker thread and hands its result back through ``ui.post``, because a
window that freezes for a second per keystroke feels broken in a way a slow search does not.

Nothing here can block a launch, and nothing here invents a version: the pack's own
manifest decides the Minecraft version and the loader, and if a pack cannot be understood
the row simply reports why instead of making a half-built instance.
"""
import os
import threading

import customtkinter as ctk

from ..core import modpacks
from . import theme
from .post import post
from .imagedesk import DESK
from .widgets import (accent_button, danger_button, ghost_button, load_image_file,
                 row, scroll_frame, set_tile)

PAGE = 12


class ModpackDialog(ctk.CTkToplevel):
    def __init__(self, master, app, on_done=None):
        super().__init__(master)
        self.app = app
        self.on_done = on_done
        self._offset = 0
        self._rows = []
        self._gen = 0                      # ignore answers to a search already replaced
        self._busy = False
        self.title("Install a modpack")
        self.geometry("740x560")
        self.minsize(620, 420)
        self.configure(fg_color=theme.COL["bg"])
        try:
            self.transient(master)
            self.grab_set()
        except Exception:
            pass

        self._build()
        theme.pin_surfaces(self)     # a dialog is not a page: nobody else walks it
        self._search()

    # ------------------------------------------------------------------ build
    def _build(self):
        head = ctk.CTkFrame(self, fg_color=theme.COL["bg2"], corner_radius=0)
        head.pack(fill="x")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="Modpacks", font=theme.title_font(18),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=0, columnspan=3, sticky="ew",
                            padx=18, pady=(14, 0))
        ctk.CTkLabel(head, text="A pack becomes an ordinary instance: its own mods, "
                               "saves and settings, and everything else in this launcher "
                               "keeps working on it.",
                     font=theme.font(11), text_color=theme.COL["text_dim"], anchor="w",
                     justify="left", wraplength=660
                     ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=18,
                            pady=(2, 10))

        row = ctk.CTkFrame(head)
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))
        row.grid_columnconfigure(0, weight=1)
        self.query = ctk.CTkEntry(row, height=34, corner_radius=10,
                                  fg_color=theme.COL["bg3"], border_width=1,
                                  border_color=theme.COL["border"],
                                  placeholder_text="Search packs, or leave it empty for the "
                                                   "popular ones\u2026",
                                  font=theme.font(12), text_color=theme.COL["text"])
        self.query.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.query.bind("<Return>", lambda e: self._search())
        accent_button(row, "Search", lambda: self._search(), width=96, height=34
                      ).grid(row=0, column=1, padx=(0, 6))
        ghost_button(row, "Close", self._close, width=80, height=34
                     ).grid(row=0, column=2)

        self.list_frame = scroll_frame(self,
                                                 scrollbar_button_color="#1b4a58",
                                                 scrollbar_button_hover_color="#2ee6e0")
        self.list_frame.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        self.list_frame.grid_columnconfigure(0, weight=1)

        foot = ctk.CTkFrame(self, fg_color=theme.COL["bg2"], corner_radius=0)
        foot.pack(fill="x")
        foot.grid_columnconfigure(1, weight=1)
        self.status = ctk.CTkLabel(foot, text="", anchor="w", font=theme.font(11),
                                   text_color=theme.COL["text_dim"], justify="left")
        self.status.grid(row=0, column=0, sticky="w", padx=18, pady=(10, 2))
        self.bar = ctk.CTkProgressBar(foot, height=8, corner_radius=4,
                                      progress_color=theme.COL["accent"],
                                      fg_color=theme.COL["bg3"])
        self.bar.grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 4))
        self.bar.set(0.0)
        nav = ctk.CTkFrame(foot)
        nav.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 12))
        nav.grid_columnconfigure(2, weight=1)
        ghost_button(nav, "\u2190  Earlier", self._prev, width=104, height=30
                     ).grid(row=0, column=0, padx=(0, 6))
        ghost_button(nav, "Later  \u2192", self._next, width=104, height=30
                     ).grid(row=0, column=1)
        self.page_lbl = ctk.CTkLabel(nav, text="", font=theme.font(10),
                                     text_color=theme.COL["text_faint"])
        self.page_lbl.grid(row=0, column=2, sticky="e")

    # ----------------------------------------------------------------- search
    def _say(self, text, frac=None):
        def do():
            try:
                self.status.configure(text=text or "")
                if frac is not None:
                    self.bar.set(max(0.0, min(1.0, frac)))
            except Exception:
                pass
        post(do)

    def _search(self, offset=None):
        if self._busy:
            return
        if offset is not None:
            self._offset = max(0, int(offset))
        self._busy = True
        self._gen += 1
        gen = self._gen
        text = (self.query.get() or "").strip()
        self._say("Searching Modrinth\u2026")

        def work():
            try:
                hits, total = modpacks.search(text, limit=PAGE, offset=self._offset)
            except Exception as e:
                self._busy = False
                self._say("Could not reach Modrinth: %s" % str(e)[:90])
                return
            self._busy = False
            if gen != self._gen:
                return                       # a newer search is already on screen
            post(lambda: self._paint(hits, total))
        threading.Thread(target=work, daemon=True).start()

    def _paint(self, hits, total):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._rows = []
        if not hits:
            ctk.CTkLabel(self.list_frame, text="Nothing matched that.",
                         font=theme.font(12), text_color=theme.COL["text_dim"]
                         ).grid(row=0, column=0, sticky="w", padx=12, pady=24)
        for i, hit in enumerate(hits):
            self._pack_row(hit, i)
        try:
            self.page_lbl.configure(text="packs %s\u2013%s of %s"
                                    % (self._offset + 1, self._offset + len(hits), total))
        except Exception:
            pass
        self._say("")

    def _pack_row(self, hit, idx):
        card = row(self.list_frame, theme.COL["bg3"], corner_radius=12)
        card.grid(row=idx, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(1, weight=1)
        name = str(hit.get("title") or "Modpack")

        # The tile is painted before anything is asked of the network, and it is painted from
        # the pack's own name: a search where Modrinth is slow, or a pack that simply has no
        # picture, used to show an empty square, which reads as a broken launcher. When the
        # icon does arrive the desk overwrites this one in place.
        mark = ctk.CTkLabel(card, text="?", width=46, height=46, corner_radius=10,
                            fg_color=theme.COL["bg2"], compound="none",
                            font=theme.font(16, "bold"), text_color=theme.COL["text_dim"])
        set_tile(mark, name, size=(44, 44))
        mark.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=10)
        self._load_icon(mark, hit)

        ctk.CTkLabel(card, text=name[:60], anchor="w", wraplength=340,
                     font=theme.font(14, "bold"), text_color=theme.COL["text"]
                     ).grid(row=0, column=1, sticky="w", pady=(10, 0))
        sub = "%s  \u00b7  %s downloads" % (hit.get("author") or "unknown",
                                            format(int(hit.get("downloads") or 0), ","))
        ctk.CTkLabel(card, text=sub, anchor="w", font=theme.font(10),
                     text_color=theme.COL["text_faint"]
                     ).grid(row=1, column=1, sticky="w", pady=(1, 0))
        accent_button(card, "Install", lambda h=hit: self._install(h), width=104,
                      height=32).grid(row=0, column=2, rowspan=2, padx=12, pady=10)

    def _load_icon(self, mark, hit):
        """Fetch the pack's picture into the tile, off the UI thread, and swap it in."""
        url = str(hit.get("icon_url") or "")
        if not url:
            return
        key = "pack:%s:%s" % (hit.get("project_id") or hit.get("slug") or url, 44)
        try:
            from .. import paths
            from ..core import modrinth
            path = modrinth.icon_path(url, os.path.join(paths.DATA_DIR, "cache", "packs"))
        except Exception:
            path = None
        try:
            DESK.show(mark, key, path=path, url=url, size=(44, 44))
        except Exception:
            pass

    def _icon_path(self, hit):
        """Cached project icon, if it is already on disk. Never fetched from this thread."""
        url = str(hit.get("icon_url") or "")
        if not url:
            return ""
        try:
            from ..core import modrinth, paths
            return modrinth.icon_path(url, os.path.join(paths.DATA_DIR, "cache", "packs"))
        except Exception:
            return ""

    # ---------------------------------------------------------------- install
    def _install(self, hit):
        if self._busy:
            self._say("One install at a time.")
            return
        self._busy = True
        slug = hit.get("slug") or hit.get("project_id")
        name = str(hit.get("title") or "Modpack")
        self._say("Looking for a build of %s that this launcher can install\u2026" % name, 0.0)

        def work():
            try:
                versions = modpacks.mrpack_versions(slug)
                if not versions:
                    raise RuntimeError("that pack has no downloadable version")
                version = versions[0]
                mrpack = modpacks.download_mrpack(version)
                if not mrpack:
                    raise RuntimeError("the pack archive could not be downloaded")

                def prog(done, total, text):
                    frac = (done / float(total)) if total else 0.0
                    self._say("%s  \u00b7  %s" % (name, text), 0.15 + 0.8 * frac)

                self._say("Unpacking %s\u2026" % name, 0.1)
                inst, report = modpacks.install(mrpack, self.app.instances,
                                                name=name, progress=prog)
                note = ("Installed %s: %d of %d files, %d extra overrides%s"
                        % (inst.name, report.get("installed", 0),
                           report.get("total_files", 0), report.get("overrides", 0),
                           "" if not report.get("failed") else
                           " (%d failed)" % len(report["failed"])))
                post(lambda: self._finish(inst, note, bool(report.get("failed"))))
            except Exception as e:
                self._busy = False
                post(lambda: self._say("Could not install %s: %s"
                                       % (name, str(e)[:140]), 0.0))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, inst, note, had_failures):
        self._busy = False
        self._say(note, 1.0)
        try:
            self.status.configure(text_color=theme.COL["warn"] if had_failures
                                  else theme.COL["good"])
        except Exception:
            pass
        try:
            self.app.pages["instances"].refresh()
        except Exception:
            pass
        if self.on_done:
            try:
                self.on_done(inst)
            except Exception:
                pass

    # ------------------------------------------------------------------ pages
    def _prev(self):
        self._search(max(0, self._offset - PAGE))

    def _next(self):
        self._search(self._offset + PAGE)

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

