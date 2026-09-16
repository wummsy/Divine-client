"""Instance editor: a tabbed window to edit an instance's details and to browse
its worlds, resource packs and multiplayer servers.
"""
import os
import threading
import webbrowser

import customtkinter as ctk

from .. import paths
from ..core import instance_content
from ..core import mod_manager
from ..core import content_meta
from . import theme
from . import imagedesk
from .scrollsync import Gate
from .widgets import (Card, section_label, accent_button, ghost_button,
                      danger_button, load_image_file, scroll_frame)


def _clip(text, n):
    """Shorten with an ellipsis, ending on a word boundary where possible."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    cut = text[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:.-") + "\u2026"


class InstanceEditor(ctk.CTkToplevel):
    """Edit one instance.

    Layout: an identity strip on top, a section rail down the left (with live
    counts) and one section at a time on the right. Each section carries its own
    accent colour, which is echoed in its header, its rail entry and the count
    chips on the Details page - so pressing a chip is a shortcut to that section.
    """

    def __init__(self, app, instance, on_change=None):
        super().__init__(app)
        self.app = app
        self.instance = instance
        self._on_change = on_change
        self._icon_refs = []
        # one generation per *list* per rebuild: a worker that finishes after its
        # own section was refreshed (or the window closed) must not touch rows
        # that no longer exist. Per-list on purpose - a shared counter meant that
        # building the Packs section cancelled the Mods worker, so mod names and
        # icons never arrived at all.
        self._gens = {}
        # Which list a table belongs to, so cosmetic row updates can wait for that
        # list to stop scrolling (see ui/scrollsync.py and the glitch it fixes).
        self._gate_lists = {"_rows_by_path": "mods_list",
                            "_world_rows": "worlds_list",
                            "_pack_rows": "packs_list"}
        self._gates = {}
        self._world_rows = {}
        self._rows_by_path = {}
        self._pack_rows = {}
        self._pages = {}
        self._rail_btns = {}
        self._stat_tiles = {}
        self._section = "details"

        self.title("Edit \u2014 " + instance.name)
        theme.auto_pin(self)   # dialogs are not pages: nothing else walks them
        self.geometry("1000x740")
        self.minsize(820, 600)
        self.configure(fg_color=theme.EDITOR["canvas"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.after(200, self._apply_icon)

        self._build_header()
        self._build_body()
        self._build_section_header()
        self.page_host = ctk.CTkFrame(self.content)
        self.page_host.grid(row=1, column=0, sticky="nsew")
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.grid_rowconfigure(0, weight=1)

        self._build_details_tab()
        self._build_mods_tab()
        self._build_worlds_tab()
        self._build_packs_tab()
        self._build_servers_tab()
        self._show_section("details")

    def _apply_icon(self):
        try:
            import tkinter as tk
            png = paths.resource_path(os.path.join("assets", "emblem.png"))
            if os.path.exists(png):
                self.iconphoto(False, tk.PhotoImage(file=png))
        except Exception:
            pass

    # ------------------------------------------------------------------ header
    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color=theme.EDITOR["header"], corner_radius=0,
                            border_width=0)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(2, weight=1)

        accent = theme.section_accent("details")
        loader = self.instance.loader
        badge_col = theme.section_accent("mods") if loader == "fabric" else accent
        self.head_badge = ctk.CTkLabel(head, text=("F" if loader == "fabric" else "V"),
                                       width=52, height=52, corner_radius=14,
                                       font=theme.font(22, "bold"),
                                       text_color="#061019", fg_color=badge_col)
        self.head_badge.grid(row=0, column=0, rowspan=2, padx=(20, 14), pady=16)

        self.head_title = ctk.CTkLabel(head, text=self.instance.name,
                                       font=theme.title_font(23),
                                       text_color=theme.EDITOR["ink"], anchor="w")
        self.head_title.grid(row=0, column=1, sticky="sw", pady=(16, 0))
        loader_txt = "Fabric" if loader == "fabric" else "Vanilla"
        self.head_sub = ctk.CTkLabel(head, text="Minecraft " + self.instance.mc_version
                                     + "  \u2022  " + loader_txt,
                                     font=theme.font(12),
                                     text_color=theme.EDITOR["ink_dim"], anchor="w")
        self.head_sub.grid(row=1, column=1, sticky="nw", pady=(2, 16))

        right = ctk.CTkFrame(head)
        right.grid(row=0, column=3, rowspan=2, sticky="e", padx=(10, 20))
        self.save_status = ctk.CTkLabel(right, text="", font=theme.font(12),
                                        text_color=theme.COL["good"])
        self.save_status.pack(side="left", padx=(0, 12))
        ghost_button(right, "Open folder", self._open_folder, width=116, height=38
                     ).pack(side="left", padx=(0, 8))
        accent_button(right, "Save changes", self._save_details, width=132, height=38
                      ).pack(side="left")

    # -------------------------------------------------------------------- body
    def _build_body(self):
        body = ctk.CTkFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(14, 16))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        rail = ctk.CTkFrame(body, width=214, corner_radius=16,
                            fg_color=theme.EDITOR["rail"], border_width=1,
                            border_color=theme.EDITOR["hairline"])
        rail.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        rail.grid_propagate(False)
        rail.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(rail, text="SECTION", font=theme.font(10, "bold"),
                     text_color=theme.EDITOR["ink_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))

        for i, key in enumerate(("details", "mods", "worlds", "packs", "servers"), start=1):
            meta = theme.SECTION[key]
            btn = ctk.CTkButton(
                rail, text="   %s   %s" % (meta["icon"], meta["short"]), anchor="w",
                font=theme.font(14, "bold"), height=44, corner_radius=10,
                fg_color="transparent", hover_color=theme.COL["bg_hover"],
                text_color=theme.EDITOR["ink_dim"],
                command=lambda k=key: self._show_section(k))
            btn.grid(row=i, column=0, sticky="ew", padx=10, pady=3)
            # count chip over the right end of the rail button; transparent
            # background when empty so it never shows as a stray grey box
            count = ctk.CTkLabel(rail, text="", font=theme.font(10, "bold"),
                                 text_color=meta["accent"],
                                 width=0)
            count.place(in_=btn, relx=1.0, rely=0.5, anchor="e", x=-14)
            self._rail_btns[key] = {"btn": btn, "count": count}

        ctk.CTkFrame(rail, fg_color=theme.EDITOR["hairline"], height=1
                     ).grid(row=6, column=0, sticky="ew", padx=14, pady=(12, 8))
        ctk.CTkLabel(rail, text="Instance folder\n%s" % self.instance.game_dir,
                     font=theme.font(10), text_color=theme.EDITOR["ink_faint"],
                     anchor="w", justify="left", wraplength=180
                     ).grid(row=7, column=0, sticky="nw", padx=16, pady=(0, 14))

        self.content = ctk.CTkFrame(body, fg_color=theme.EDITOR["surface"],
                                    corner_radius=16, border_width=1,
                                    border_color=theme.EDITOR["hairline"])
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=0)
        self.content.grid_rowconfigure(1, weight=1)

    def _build_section_header(self):
        """Title + one-line description, with the section's colour as a rule."""
        head = ctk.CTkFrame(self.content)
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        self.content.grid_rowconfigure(1, weight=1)
        head.grid_columnconfigure(0, weight=1)
        self.section_title = ctk.CTkLabel(head, text="Details", font=theme.title_font(17),
                                          text_color=theme.EDITOR["ink"], anchor="w")
        self.section_title.grid(row=0, column=0, sticky="w")
        self.section_blurb = ctk.CTkLabel(head, text="", font=theme.font(11),
                                          text_color=theme.EDITOR["ink_dim"], anchor="w",
                                          justify="left", wraplength=520)
        self.section_blurb.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.section_bar = ctk.CTkFrame(head, height=2, corner_radius=1,
                                        fg_color=theme.section_accent("details"),
                                        border_width=0)
        self.section_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        return head

    def _page(self, key):
        """The frame a section builds itself into (one at a time, stacked)."""
        frame = ctk.CTkFrame(self.page_host)
        self._pages[key] = frame
        return frame

    def _show_section(self, key):
        self._section = key
        for k, page in self._pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew")
                page.tkraise()
            else:
                page.grid_remove()
        accent = theme.section_accent(key)
        for k, widgets in self._rail_btns.items():
            on = (k == key)
            widgets["btn"].configure(
                fg_color=(theme.EDITOR["rail_sel"] if on else "transparent"),
                text_color=(accent if on else theme.EDITOR["ink_dim"]),
                hover_color=theme.COL["bg_hover"])
        # a tab switch ends any scroll, so anything queued for these rows goes on
        # screen now instead of a beat later
        self._flush_gates()
        try:
            self.section_title.configure(text=theme.SECTION[key]["label"])
            self.section_blurb.configure(text=theme.SECTION[key]["blurb"])
            self.section_bar.configure(fg_color=accent)
        except Exception:
            pass
        self._refresh_stats()

    def _set_section_count(self, key, value):
        w = self._rail_btns.get(key)
        if w:
            try:
                if value:
                    w["count"].configure(text=str(value))
                    w["count"].place(in_=w["btn"], relx=1.0, rely=0.5, anchor="e", x=-14)
                else:
                    # nothing to show - take the label off entirely so an empty
                    # widget never flashes as a stray box on the active row
                    w["count"].place_forget()
            except Exception:
                pass

    # ================= Details =================
    def _build_details_tab(self):
        t = self._page("details")
        t.grid_columnconfigure(0, weight=1)
        t.grid_columnconfigure(1, weight=1)
        t.grid_rowconfigure(1, weight=0)

        # --- name / folder card
        ident = Card(t, fg_color=theme.EDITOR["surface_hi"], corner_radius=14,
                     border_color=theme.EDITOR["hairline"])
        ident.grid(row=0, column=0, sticky="nsew", padx=(20, 8), pady=(14, 10))
        ident.grid_columnconfigure(0, weight=1)
        ident.grid_rowconfigure(2, weight=1)
        self._left_edge(ident, theme.section_accent("details"))
        ctk.CTkLabel(ident, text="INSTANCE NAME", font=theme.font(10, "bold"),
                     text_color=theme.EDITOR["ink_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=(20, 0), pady=(18, 2))
        self.name_entry = ctk.CTkEntry(ident, height=42, font=theme.font(15, "bold"),
                                       fg_color=theme.COL["bg3"],
                                       border_color=theme.EDITOR["hairline"],
                                       text_color=theme.EDITOR["ink"])
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=20)
        self.name_entry.insert(0, self.instance.name)
        ctk.CTkLabel(ident, text="ID (folder name)  \u00b7  %s" % self.instance.id,
                     font=theme.font(11), text_color=theme.EDITOR["ink_faint"], anchor="w"
                     ).grid(row=3, column=0, sticky="sw", padx=(20, 0), pady=(10, 16))

        # --- version / loader card
        target = Card(t, fg_color=theme.EDITOR["surface_hi"], corner_radius=14,
                      border_color=theme.EDITOR["hairline"])
        target.grid(row=0, column=1, sticky="nsew", padx=(8, 20), pady=(14, 10))
        target.grid_columnconfigure(0, weight=1)
        target.grid_rowconfigure(5, weight=1)
        self._left_edge(target, theme.section_accent("mods"))
        ctk.CTkLabel(target, text="MINECRAFT VERSION", font=theme.font(10, "bold"),
                     text_color=theme.EDITOR["ink_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=(20, 0), pady=(18, 2))
        self.version_menu = ctk.CTkOptionMenu(
            target, values=[self.instance.mc_version], height=42, font=theme.font(15, "bold"),
            fg_color=theme.COL["bg3"], button_color=theme.COL["bg_hover"],
            button_hover_color=theme.COL["accent"], dropdown_fg_color=theme.COL["bg3"],
            dropdown_hover_color=theme.COL["bg_hover"], command=self._on_version_change)
        self.version_menu.grid(row=1, column=0, sticky="ew", padx=20)
        self.version_menu.set(self.instance.mc_version)

        ctk.CTkLabel(target, text="MOD LOADER", font=theme.font(10, "bold"),
                     text_color=theme.EDITOR["ink_faint"], anchor="w"
                     ).grid(row=2, column=0, sticky="w", padx=(20, 0), pady=(16, 4))
        self.loader_var = ctk.StringVar(value=self.instance.loader)
        lrow = ctk.CTkFrame(target)
        lrow.grid(row=3, column=0, sticky="w", padx=18)
        ctk.CTkRadioButton(lrow, text="Vanilla", variable=self.loader_var, value="vanilla",
                           font=theme.font(13), text_color=theme.EDITOR["ink"],
                           fg_color=theme.section_accent("details"),
                           hover_color=theme.COL["bg_hover"]
                           ).pack(side="left", padx=(2, 22))
        self.fabric_radio = ctk.CTkRadioButton(lrow, text="Fabric + Divine performance pack",
                                                variable=self.loader_var, value="fabric",
                                                font=theme.font(13),
                                                text_color=theme.EDITOR["ink"],
                                                fg_color=theme.section_accent("mods"),
                                                hover_color=theme.COL["bg_hover"])
        self.fabric_radio.pack(side="left")
        self.detail_hint = ctk.CTkLabel(target, text="", font=theme.font(11),
                                        text_color=theme.COL["warn"], anchor="w",
                                        wraplength=380, justify="left")
        self.detail_hint.grid(row=4, column=0, sticky="w", padx=20, pady=(10, 0))

        # --- count chips: clicking one jumps to that section
        strip = ctk.CTkFrame(t)
        strip.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(4, 4))
        for c in range(4):
            strip.grid_columnconfigure(c, weight=1, uniform="chips")
        for c, key in enumerate(("mods", "worlds", "packs", "servers")):
            meta = theme.SECTION[key]
            chip = Card(strip, fg_color=theme.EDITOR["surface_hi"], corner_radius=14,
                        border_color=theme.EDITOR["hairline"])
            chip.grid(row=0, column=c, sticky="ew", padx=(0 if c == 0 else 8))
            chip.grid_columnconfigure(0, weight=1)
            self._left_edge(chip, meta["accent"], radius=14)
            val = ctk.CTkLabel(chip, text="\u2014", font=theme.font(24, "bold"),
                               text_color=meta["accent"])
            val.grid(row=0, column=0, pady=(14, 0))
            ctk.CTkLabel(chip, text="%s   \u203a" % meta["label"], font=theme.font(11),
                         text_color=theme.EDITOR["ink_dim"]).grid(row=1, column=0,
                                                                   pady=(0, 12))
            self._stat_tiles[key] = val
            for wdg in (chip, val):
                wdg.bind("<Button-1>", lambda e, k=key: self._show_section(k), add="+")
                wdg.configure(cursor="hand2")

        note = ctk.CTkLabel(t, text="Renaming or changing version never deletes your "
                            "saves. Files for a new version download on next launch.",
                            font=theme.font(11), text_color=theme.EDITOR["ink_faint"],
                            anchor="w", justify="left", wraplength=760)
        note.grid(row=2, column=0, columnspan=2, sticky="sw", padx=2, pady=(0, 14))

        threading.Thread(target=self._load_versions, daemon=True).start()
        self._refresh_stats()

    @staticmethod
    def _left_edge(card, color, radius=3):
        """A thin accent bar down the left edge of a card - the section signature.

        Placed (not gridded) on purpose: as a grid child with a rowspan it made
        every card stretch to an absurd height.
        """
        bar = ctk.CTkFrame(card, width=4, corner_radius=radius, fg_color=color,
                           border_width=0)
        bar.place(relx=0.0, rely=0.10, relheight=0.80, anchor="w")
        return bar

    def _refresh_stats(self):
        """Update the quick-stats tiles from the instance contents.

        Counting only. The old version opened every mod jar and every world's
        region folder through list_*(), on the UI thread, on every section switch
        - which is why clicking between Mods and Worlds felt sticky.
        """
        try:
            gd = self.instance.game_dir
            counts = {
                "mods": mod_manager.count_mods(os.path.join(gd, "mods")),
                "worlds": instance_content.count_worlds(gd),
                "packs": instance_content.count_resource_packs(gd),
                "servers": len(instance_content.list_servers(gd)),
            }
            for key, val in counts.items():
                if key in self._stat_tiles:
                    self._stat_tiles[key].configure(text=str(val))
                self._set_section_count(key, val)
        except Exception:
            pass

    def _load_versions(self):
        try:
            versions = self.app.get_versions()
            ids = [v["id"] for v in versions if v.get("type") == "release"]
            # keep the current version present even if it's a snapshot
            if self.instance.mc_version not in ids:
                ids = [self.instance.mc_version] + ids
            ids = ids[:400]
            self.after(0, lambda: self._set_versions(ids))
        except Exception:
            pass

    def _set_versions(self, ids):
        self.version_menu.configure(values=ids)
        self.version_menu.set(self.instance.mc_version)
        self._on_version_change(self.instance.mc_version)

    def _on_version_change(self, version):
        try:
            fabric_ok = version in self.app.get_fabric_versions()
        except Exception:
            fabric_ok = True
        if fabric_ok:
            self.fabric_radio.configure(state="normal")
            self.detail_hint.configure(text="")
        else:
            if self.loader_var.get() == "fabric":
                self.loader_var.set("vanilla")
            self.fabric_radio.configure(state="disabled")
            self.detail_hint.configure(
                text="Fabric is not available for this version \u2014 vanilla only.")

    def _save_details(self):
        name = self.name_entry.get().strip() or self.instance.name
        version = self.version_menu.get().strip()
        loader = self.loader_var.get()
        version_changed = version != self.instance.mc_version
        loader_changed = loader != self.instance.loader
        self.app.instances.update(self.instance.id, name=name, mc_version=version,
                                  loader=loader)
        # refresh header
        self.head_title.configure(text=name)
        loader_txt = "Fabric" if loader == "fabric" else "Vanilla"
        self.head_sub.configure(text="Minecraft " + version + "  \u2022  " + loader_txt)
        msg = "\u2713 Saved"
        if version_changed or loader_changed:
            msg += " \u2014 files download on next launch"
        self.save_status.configure(text=msg)
        self.after(4000, lambda: self.save_status.configure(text=""))
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    # ================= Mods =================
    def _build_mods_tab(self):
        t = self._page("mods")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(t)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 4))
        bar.grid_columnconfigure(0, weight=1)
        self.mods_note = ctk.CTkLabel(
            bar, text="Toggle mods on or off. Changes apply next launch.",
            font=theme.font(12), text_color=theme.COL["text_dim"], anchor="w")
        self.mods_note.grid(row=0, column=0, sticky="w", padx=6)
        accent_button(bar, "Get mods", self._browse_mods, width=104, height=34
                      ).grid(row=0, column=1, padx=(4, 2))
        ghost_button(bar, "Add .jar", self._add_mod, width=88, height=34
                     ).grid(row=0, column=2, padx=2)
        ghost_button(bar, "Refresh", self._refresh_mods, width=84, height=34
                     ).grid(row=0, column=3, padx=(2, 6))
        self.mods_list = scroll_frame(t)
        self.mods_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 8))
        self.mods_list.grid_columnconfigure(0, weight=1)
        self._refresh_mods()

    def _mods_dir(self):
        return os.path.join(self.instance.game_dir, "mods")

    def _refresh_mods(self):
        gate = self._gates.get("_rows_by_path")
        if gate:
            gate.clear()
        for w in self.mods_list.winfo_children():
            w.destroy()
        self._icon_refs.clear()
        self._rows_by_path.clear()
        # filenames only: opening every jar to find the real mod name is what the
        # worker below does, so the list can be on screen immediately
        mods = mod_manager.list_mods(self._mods_dir(), with_meta=False)
        if not mods:
            self._empty(self.mods_list,
                        "No mods in this instance.\nUse \u201cGet mods\u201d to browse "
                        "Modrinth, or \u201cAdd .jar\u201d for your own.")
            self._refresh_stats()
            return
        on = sum(1 for m in mods if m["enabled"])
        word = "mod" if len(mods) == 1 else "mods"
        self.mods_note.configure(
            text=f"{len(mods)} {word} \u2022 {on} enabled. Changes apply next launch.",
            text_color=theme.COL["text_dim"])
        for i, mod in enumerate(mods):
            self._mod_row(mod, i)
        self._refresh_stats()
        self._start_content_worker("_rows_by_path",
                                   [(m["path"], lambda m=m: self._mod_updates(m))
                                    for m in mods])

    def _mod_row(self, mod, i):
        card = Card(self.mods_list, fg_color=theme.EDITOR["surface_hi"], corner_radius=13,
               border_color=theme.EDITOR["hairline"])
        card.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
        card.grid_columnconfigure(2, weight=1)

        var = ctk.BooleanVar(value=mod["enabled"])
        ctk.CTkSwitch(card, text="", variable=var, width=44,
                      progress_color=theme.COL["good"],
                      command=lambda m=mod, v=var: self._toggle_mod(m, v)
                      ).grid(row=0, column=0, rowspan=2, padx=(14, 6), pady=14)

        # icon: letter tile immediately, jar/Modrinth icon when the desk has it
        icon_lbl = self._icon_label(card, mod["name"])
        icon_lbl.grid(row=0, column=1, rowspan=2, padx=(2, 12), pady=12)

        title = mod["name"] + ("  " + mod["version"] if mod["version"] else "")
        # width + height are pinned on the text labels: the real mod name arrives a
        # moment later from the jar, and an unbounded label would widen column 2 for
        # every row in the list (they share the grid) exactly while it is being
        # scrolled. Long names are clipped to the same box instead.
        title_lbl = ctk.CTkLabel(card, text=_clip(title, 44), font=theme.font(14, "bold"),
                                 text_color=theme.COL["text"] if mod["enabled"] else theme.COL["text_faint"],
                                 anchor="w", width=380, height=22)
        title_lbl.grid(row=0, column=2, sticky="w", pady=(11, 0))
        sub = _clip(mod["description"] or mod["filename"], 88)
        desc_lbl = ctk.CTkLabel(card, text=sub, font=theme.font(11),
                                text_color=theme.COL["text_dim"], anchor="nw",
                                justify="left", wraplength=360, width=380, height=30)
        desc_lbl.grid(row=1, column=2, sticky="w", pady=(0, 11))

        # Modrinth link: placed now (empty), filled in later - see _apply_row
        link = ctk.CTkLabel(card, text="", font=theme.font(11, "bold"),
                            text_color=theme.COL["accent"], cursor="hand2",
                            width=380, height=18, anchor="w")
        link.grid(row=2, column=2, sticky="w", pady=(0, 11))
        ctk.CTkLabel(card, text="On" if mod["enabled"] else "Off",
                     font=theme.font(12, "bold"),
                     text_color=theme.COL["good"] if mod["enabled"] else theme.COL["text_faint"]
                     ).grid(row=0, column=3, rowspan=2, padx=(6, 6))
        danger_button(card, "Delete", lambda m=mod: self._delete_mod(m),
                      width=80, height=34).grid(row=0, column=4, rowspan=2, padx=(2, 12))

        self._rows_by_path[mod["path"]] = {
            "card": card, "icon": icon_lbl, "desc": desc_lbl, "link": link,
            "title": title_lbl}

    def _mod_updates(self, mod):
        """Everything slow about one mod row, run off the UI thread."""
        path = mod["path"]
        up = {}
        meta = mod_manager.read_meta(path)
        if meta and meta.get("name"):
            up["title"] = meta["name"] + ("  " + meta["version"] if meta.get("version") else "")
            if meta.get("description"):
                up["desc"] = _clip(meta["description"], 88)
        icon = content_meta.extract_mod_icon(path)
        if icon:
            up["icon_path"] = icon
        info = content_meta.modrinth_for_file(path)
        if info:
            if info.get("description"):
                up["desc"] = _clip(info["description"], 100)
            if info.get("icon_url"):
                up["icon_url"] = info["icon_url"]
                up.pop("icon_path", None)
            if info.get("url"):
                up["url"] = info["url"]
                up["link_row"], up["link_col"] = 2, 2
        return up

    # ------------------------------------------------- off-thread row details
    def _start_content_worker(self, table_attr, jobs):
        """Run `jobs` (list of (row_key, fn)) off the UI thread, apply in one go.

        Each fn does the slow part - opening a jar, hashing a file, asking
        Modrinth, walking a folder - and returns a dict of things to put on the
        row. Results arrive in a single callback instead of one `after` per row.
        """
        gen = self._gens.get(table_attr, 0) + 1
        self._gens[table_attr] = gen

        def stale():
            return self._gens.get(table_attr) != gen

        def run():
            out = []

            def flush():
                if not out:
                    return
                batch = list(out)
                del out[:]
                try:
                    # post() happens on the UI thread; a destroyed window must not
                    # make a daemon thread throw
                    self.after(0, lambda b=batch: self._apply_updates(gen, table_attr, b))
                except Exception:
                    pass

            for key, fn in jobs:
                if stale():
                    return                      # list was rebuilt or we closed
                try:
                    up = fn()
                except Exception:
                    up = None
                if up:
                    out.append((key, up))
                # a few rows at a time: waiting for all 40 before the first icon
                # appears looks exactly like a hang, even though nothing is stuck
                if len(out) >= 4:
                    flush()
            flush()
            try:
                content_meta.flush_hash_cache()
            except Exception:
                pass

        if jobs:
            threading.Thread(target=run, daemon=True).start()

    def _apply_updates(self, gen, table_attr, updates):
        if self._gens.get(table_attr) != gen:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        table = getattr(self, table_attr, {})
        gate = self._gate_for(table_attr)
        for key, up in updates:
            row = table.get(key)
            if row is None:
                continue
            # one repaint per row, and only once the list has stopped moving:
            # applying text/images mid-scroll is what made the rows jump around
            gate.submit((table_attr, key),
                        lambda r=row, u=dict(up): self._apply_row(r, u))

    def _apply_row(self, row, up):
        if not row:
            return
        try:
            if not row["card"].winfo_exists():
                return
        except Exception:
            return
        if "title" in up and row.get("title") is not None:
            row["title"].configure(text=_clip(up["title"], 44))
        if "desc" in up and row.get("desc") is not None:
            row["desc"].configure(text=_clip(up["desc"], 88))
        if "extra" in up and row.get("extra") is not None:
            row["extra"].configure(text=up["extra"])
        # a remote icon wins over the one baked into the jar
        icon = up.get("icon_url") or up.get("icon_path")
        if icon and row.get("icon") is not None:
            imagedesk.DESK.show(row["icon"], icon, path=up.get("icon_path"),
                                url=up.get("icon_url"), size=(46, 46))
        if up.get("url") and row.get("link") is not None:
            url = up["url"]
            # The link label was gridded when the row was built, empty, so its row
            # is already reserved: filling it in cannot change the card's height.
            # (Adding it here instead - the old way - inserted a third grid row into
            # a card the user might be scrolling past, and every row below it moved.)
            row["link"].configure(text="View on Modrinth \u2197")
            row["link"].bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

    def _toggle_mod(self, mod, var):
        new_name = mod_manager.set_enabled(self._mods_dir(), mod["filename"], var.get())
        if new_name is None:
            var.set(mod["enabled"])
            return
        self._refresh_mods()

    def _delete_mod(self, mod):
        if mod_manager.delete_mod(self._mods_dir(), mod["filename"]):
            self._refresh_mods()

    def _add_mod(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Choose a mod .jar",
                                          filetypes=[("Mod jar", "*.jar"), ("All files", "*.*")])
        if path:
            mod_manager.add_mod(self._mods_dir(), path)
            self._refresh_mods()

    def _browse_mods(self):
        from .mod_browser import ModBrowser
        win = ModBrowser(self.app, self.instance, on_close=self._refresh_mods)
        win.after(120, win.lift)
        win.after(160, win.focus_force)

    # ================= Worlds =================
    def _build_worlds_tab(self):
        t = self._page("worlds")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(t)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 4))
        bar.grid_columnconfigure(0, weight=1)
        self.worlds_note = ctk.CTkLabel(bar, text="Singleplayer worlds saved in this instance.",
                                        font=theme.font(12), text_color=theme.COL["text_dim"])
        self.worlds_note.grid(row=0, column=0, sticky="w", padx=6)
        ghost_button(bar, "Refresh", self._refresh_worlds, width=90, height=34
                     ).grid(row=0, column=1, padx=(4, 6))
        self.worlds_list = scroll_frame(t)
        self.worlds_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 8))
        self.worlds_list.grid_columnconfigure(0, weight=1)
        self._refresh_worlds()

    def _refresh_worlds(self):
        gate = self._gates.get("_world_rows")
        if gate:
            gate.clear()
        for w in self.worlds_list.winfo_children():
            w.destroy()
        self._world_rows = {}
        # with_sizes=False: sizing a world means walking every region file, which
        # is the slowest thing this window could do before showing something
        worlds = instance_content.list_worlds(self.instance.game_dir, with_sizes=False)
        if not worlds:
            self._empty(self.worlds_list, "No worlds yet.\nCreate one in-game and it will show up here.")
            self._refresh_stats()
            return
        for i, world in enumerate(worlds):
            self._world_row(world, i)
        self._refresh_stats()
        self._start_content_worker("_world_rows",
                                   [(w["path"], lambda w=w: self._world_updates(w))
                                    for w in worlds])

    def _world_row(self, world, i):
        card = Card(self.worlds_list, fg_color=theme.EDITOR["surface_hi"], corner_radius=13,
               border_color=theme.EDITOR["hairline"])
        card.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="\u25A3", width=42, height=42, corner_radius=10,
                     font=theme.font(18, "bold"), text_color="#04121a",
                     fg_color=theme.COL["good"]).grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=12)
        ctk.CTkLabel(card, text=_clip(world["name"], 44), font=theme.font(14, "bold"),
                     text_color=theme.COL["text"], anchor="w", width=380, height=22
                     ).grid(row=0, column=1, sticky="w", pady=(12, 0))
        bits = []
        if world["game_mode"]:
            bits.append(world["game_mode"])
        bits.append("played " + instance_content.format_last_played(world["last_played"]))
        if world.get("size_mb"):
            bits.append(str(world["size_mb"]) + " MB")
        else:
            bits.append("sizing\u2026")
        extra_lbl = ctk.CTkLabel(card, text="   \u2022   ".join(bits), font=theme.font(11),
                                 text_color=theme.COL["text_dim"], anchor="w")
        extra_lbl.grid(row=1, column=1, sticky="w", pady=(0, 12))
        self._world_rows[world["path"]] = {"card": card, "extra": extra_lbl}
        danger_button(card, "Delete", lambda w=world: self._delete_world(w),
                      width=90, height=36).grid(row=0, column=2, rowspan=2, padx=12)

    def _world_updates(self, world):
        """Just the size: walking a world folder is the whole cost here."""
        size = instance_content.folder_size_mb(world["path"])
        if not size:
            return None
        bits = []
        if world.get("game_mode"):
            bits.append(world["game_mode"])
        bits.append("played " + instance_content.format_last_played(world.get("last_played")))
        bits.append("%s MB" % size)
        return {"extra": "   \u2022   ".join(bits)}

    def _delete_world(self, world):
        from .pages.instances_page import ConfirmDialog
        dlg = ConfirmDialog(self, "Delete world \u201c" + world["name"] + "\u201d?",
                            "This permanently removes the world folder. This cannot be undone.")
        self.wait_window(dlg)
        if dlg.result:
            instance_content.delete_world(self.instance.game_dir, world["folder"])
            self._refresh_worlds()

    # ================= Resource packs =================
    def _build_packs_tab(self):
        t = self._page("packs")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(t)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 4))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Packs in this instance.",
                     font=theme.font(12), text_color=theme.COL["text_dim"]
                     ).grid(row=0, column=0, sticky="w", padx=6)
        accent_button(bar, "Get packs", self._browse_packs, width=110, height=34
                      ).grid(row=0, column=1, padx=(4, 2))
        ghost_button(bar, "Add .zip", self._add_pack, width=90, height=34
                     ).grid(row=0, column=2, padx=2)
        ghost_button(bar, "Refresh", self._refresh_packs, width=90, height=34
                     ).grid(row=0, column=3, padx=(2, 6))
        self.packs_list = scroll_frame(t)
        self.packs_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 8))
        self.packs_list.grid_columnconfigure(0, weight=1)
        self._refresh_packs()

    def _refresh_packs(self):
        gate = self._gates.get("_pack_rows")
        if gate:
            gate.clear()
        for w in self.packs_list.winfo_children():
            w.destroy()
        self._pack_rows = {}
        # with_sizes=False: sizing every extracted pack means walking thousands of
        # files, which is fine in a worker and not fine before a click responds
        packs = instance_content.list_resource_packs(self.instance.game_dir,
                                                      with_sizes=False)
        if not packs:
            self._empty(self.packs_list,
                        "No resource packs yet.\nUse \u201cGet packs\u201d to browse Modrinth, "
                        "or \u201cAdd .zip\u201d for your own.")
            self._refresh_stats()
            return
        for i, pack in enumerate(packs):
            self._pack_row(pack, i)
        self._refresh_stats()
        self._start_content_worker("_pack_rows",
                                   [(p["path"], lambda p=p: self._pack_updates(p))
                                    for p in packs])

    def _pack_row(self, pack, i):
        card = Card(self.packs_list, fg_color=theme.EDITOR["surface_hi"], corner_radius=13,
               border_color=theme.EDITOR["hairline"])
        card.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
        card.grid_columnconfigure(1, weight=1)

        icon_lbl = self._icon_label(card, pack["filename"],
                                    fallback_color=theme.COL["accent2"])
        icon_lbl.grid(row=0, column=0, rowspan=3, padx=(14, 12), pady=12)

        ctk.CTkLabel(card, text=_clip(pack["filename"], 44), font=theme.font(14, "bold"),
                     text_color=theme.COL["text"], anchor="w", width=400, height=22
                     ).grid(row=0, column=1, sticky="w", pady=(11, 0))
        # fixed box: a real pack.mcmeta description is longer than "" and would
        # otherwise wrap into a second line and grow the card mid-scroll
        desc_lbl = ctk.CTkLabel(card, text="", font=theme.font(11),
                                text_color=theme.COL["text_dim"], anchor="nw",
                                justify="left", wraplength=380, width=400, height=30)
        state = "Enabled" if pack["enabled"] else "Not enabled in-game"
        state_col = theme.COL["good"] if pack["enabled"] else theme.COL["text_faint"]
        size = ("   \u2022   %s MB" % pack["size_mb"]) if pack.get("size_mb") else ""
        extra_lbl = ctk.CTkLabel(card, text=state + size, font=theme.font(11),
                                 text_color=state_col, anchor="w"
                                 ).grid(row=2, column=1, sticky="w", pady=(0, 11))
        # reserved now, filled in later (see _apply_row): gridding this only once
        # the Modrinth match arrives added a row to the card while it was on screen
        link = ctk.CTkLabel(card, text="", font=theme.font(11, "bold"),
                            text_color=theme.COL["accent"], cursor="hand2",
                            width=400, height=18, anchor="w")
        link.grid(row=3, column=1, sticky="w", pady=(0, 11))
        danger_button(card, "Delete", lambda p=pack: self._delete_pack(p),
                      width=90, height=36).grid(row=0, column=2, rowspan=3, padx=12)

        self._pack_rows[pack["path"]] = {"card": card, "icon": icon_lbl,
                                         "desc": desc_lbl, "link": link,
                                         "extra": extra_lbl, "pack": pack}

    def _pack_updates(self, pack):
        """pack.png / pack.mcmeta, size, and a Modrinth match - off-thread."""
        path = pack["path"]
        up = {}
        meta = content_meta.extract_pack_meta(path)
        if meta.get("icon"):
            up["icon_path"] = meta["icon"]
        if meta.get("description"):
            up["desc"] = _clip(meta["description"], 88)
        size = instance_content.folder_size_mb(path) if os.path.isdir(path) \
            else pack.get("size_mb")
        state = "Enabled" if pack["enabled"] else "Not enabled in-game"
        if size:
            up["extra"] = "%s   \u2022   %s MB" % (state, size)
        else:
            up["extra"] = state
        if not os.path.isdir(path):
            # folders cannot be hashed to a single file; only match zip packs
            info = content_meta.modrinth_for_file(path)
            if info:
                if info.get("icon_url"):
                    up["icon_url"] = info["icon_url"]
                    up.pop("icon_path", None)
                if not up.get("desc") and info.get("description"):
                    up["desc"] = _clip(info["description"], 100)
                if info.get("url"):
                    up["url"] = info["url"]
                    up["link_row"], up["link_col"] = 3, 1
        return up

    def _delete_pack(self, pack):
        instance_content.delete_resource_pack(self.instance.game_dir, pack["filename"])
        self._refresh_packs()

    def _add_pack(self):
        from tkinter import filedialog
        import shutil
        path = filedialog.askopenfilename(title="Select a resource pack (.zip)",
                                          filetypes=[("Resource pack", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        dest_dir = instance_content.resource_packs_dir(self.instance.game_dir)
        try:
            shutil.copy2(path, os.path.join(dest_dir, os.path.basename(path)))
        except OSError:
            pass
        self._refresh_packs()

    def _browse_packs(self):
        from .mod_browser import ModBrowser
        win = ModBrowser(self.app, self.instance, on_close=self._refresh_packs,
                         project_type="resourcepack")
        win.after(120, win.lift)
        win.after(160, win.focus_force)

    # ================= Servers =================
    def _build_servers_tab(self):
        t = self._page("servers")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(t)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 4))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Multiplayer servers saved in this instance.",
                     font=theme.font(12), text_color=theme.COL["text_dim"]
                     ).grid(row=0, column=0, sticky="w", padx=6)
        ghost_button(bar, "Refresh", self._refresh_servers, width=90, height=34
                     ).grid(row=0, column=1, padx=(4, 6))
        self.servers_list = scroll_frame(t)
        self.servers_list.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 8))
        self.servers_list.grid_columnconfigure(0, weight=1)
        self._refresh_servers()

    def _refresh_servers(self):
        for w in self.servers_list.winfo_children():
            w.destroy()
        servers = instance_content.list_servers(self.instance.game_dir)
        if not servers:
            self._empty(self.servers_list,
                        "No servers saved.\nAdd servers in-game and they appear here.")
            return
        for i, srv in enumerate(servers):
            self._server_row(srv, i)

    def _server_row(self, srv, i):
        card = Card(self.servers_list, fg_color=theme.EDITOR["surface_hi"], corner_radius=13,
               border_color=theme.EDITOR["hairline"])
        card.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="\u25C9", width=42, height=42, corner_radius=10,
                     font=theme.font(18, "bold"), text_color="#04121a",
                     fg_color=theme.COL["accent"]).grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=12)
        ctk.CTkLabel(card, text=srv["name"], font=theme.font(14, "bold"),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=1, sticky="w", pady=(12, 0))
        ctk.CTkLabel(card, text=srv["ip"] or "(no address)", font=theme.font(11),
                     text_color=theme.COL["text_dim"], anchor="w"
                     ).grid(row=1, column=1, sticky="w", pady=(0, 12))

    # ================= helpers =================
    def _gate_for(self, table_attr):
        """The scroll gate for the list a table is drawn in (created on demand).

        CustomTkinter keeps the scrollable canvas in a private attribute; without it
        there is nothing to watch, and a Gate with no canvas applies work
        immediately - i.e. exactly the old behaviour, never a hang.
        """
        gate = self._gates.get(table_attr)
        if gate is not None:
            return gate
        frame = getattr(self, self._gate_lists.get(table_attr, ""), None)
        # CustomTkinter's name for the scrolled canvas moved between releases; the
        # view is the only thing worth watching, so try both and let the Gate fall
        # back to applying work immediately if neither exists.
        canvas = (getattr(frame, "_parent_canvas", None)
                  or getattr(frame, "_canvas", None))
        gate = Gate(self, canvas)
        self._gates[table_attr] = gate
        return gate

    def _flush_gates(self):
        for gate in self._gates.values():
            gate.apply_now()

    def destroy(self):
        for gate in list(self._gates.values()):
            gate.close()
        self._gates.clear()
        try:
            super().destroy()
        except Exception:
            pass

    def _icon_label(self, card, name, path=None, url=None, fallback_color=None):
        """A 46px icon tile: always a letter immediately, image when we have one.

        `path`/`url` are handed to the shared image desk, which decodes (and
        downloads) off the UI thread. Nothing in here touches the network or
        opens a jar - that was the freeze.
        """
        letter = (name[:1] or "?").upper()
        lbl = ctk.CTkLabel(card, text=letter, width=46, height=46, corner_radius=11,
                           font=theme.font(18, "bold"), text_color="#04121a",
                           fg_color=fallback_color or theme.COL["accent2"])
        key = url or path
        if key:
            imagedesk.DESK.show(lbl, key, path=path, url=url, size=(46, 46))
        return lbl

    def _empty(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=theme.font(14),
                     text_color=theme.COL["text_faint"], justify="left"
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=24)

    def _open_folder(self):
        import subprocess, sys
        path = self.instance.game_dir
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
