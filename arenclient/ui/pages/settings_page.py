"""Settings page: RAM, resolution, Java, JVM args, performance pack. Saves to disk."""
import shutil
import threading

import customtkinter as ctk

from ...core import endpoints
from ...core import system_info
from .. import theme
from ..widgets import flow_label
from ..widgets import (Card, PageFrame, accent_button, fixed_label, ghost_button,
                 scroll_frame, section_label)


class SettingsPage(PageFrame):
    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self.cfg = app.config_store
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Row 0 is deliberately empty. It used to hold a "Saved" label that was blank until the
        # moment after you stopped looking at it, which left a strip of background at the top of
        # every visit to the page - and a `CTkFrame` left in that row with nothing in it is worse,
        # because its default height is 200 px. Confirmations go to the window's status line
        # instead, which is what it is for and which does not move the cards when it speaks.

        scroll = scroll_frame(self)
        # 10 px above, not 0: the scroll area now starts at the top of the page, and a card
        # whose first line is level with the header's hairline reads as though it is being cut
        # in half by it.
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(10, 14))
        scroll.grid_columnconfigure(0, weight=1)

        # ---- Appearance ------------------------------------------
        look = Card(scroll)
        look.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 8))
        look.grid_columnconfigure(0, weight=1)
        section_label(look, "APPEARANCE", glyph="ui_picture").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 2))
        flow_label(look, text="The background behind the panels, and the wash on the "
                               "sidebar. It applies as you pick it - nothing to save, "
                               "nothing restarts, and your instances are untouched.",
                     font=theme.font(11), text_color=theme.COL["text_dim"], anchor="w",
                     justify="left").grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        # background_names() is (key, label, note); the row wants the keys, and the labels it
        # can show a person. Mixing those up is what printed a Python tuple on a button.
        self._style_keys = [k for k, _label, _note in theme.background_names()]
        self._style_names = [theme.background_label(k) for k in self._style_keys]
        self._name_to_key = dict(zip(self._style_names, self._style_keys))
        self._key_to_name = dict(zip(self._style_keys, self._style_names))
        self.style_btn = ctk.CTkSegmentedButton(
            look, values=self._style_names, command=self._on_style,
            font=theme.font(12, "bold"), height=34, corner_radius=10,
            fg_color=theme.COL["bg3"], selected_color=theme.COL["accent"],
            selected_hover_color=theme.COL["accent_hi"],
            unselected_color=theme.COL["bg3"], unselected_hover_color=theme.COL["bg_hover"],
            text_color=theme.COL["text"])
        self.style_btn.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 16))
        try:
            cur_key = self.cfg.get("ui_background", theme.DEFAULT_BACKGROUND)
            self.style_btn.set(self._key_to_name.get(cur_key, self._style_names[0]))
        except Exception:
            pass

        # ---- Memory ----------------------------------------------
        mem = Card(scroll)
        mem.grid(row=1, column=0, sticky="ew", padx=6, pady=8)
        mem.grid_columnconfigure(0, weight=1)
        section_label(mem, "MEMORY", glyph="ui_memory").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 2))
        # A fixed width, because this label changes text on every pixel of the slider: as an
        # autosizing label it re-requests its geometry ~60 times a second, which drags the
        # card, the scroll frame and the window through a re-layout - the "glitch when I move
        # a slider" report, reproduced from its source.
        self.ram_value_lbl = fixed_label(mem, text="", px=170, font=theme.font(15, "bold"),
                                         text_color=theme.COL["accent"])
        self.ram_value_lbl.grid(row=0, column=0, sticky="e", padx=18, pady=(16, 2))
        max_ram = system_info.recommended_max_ram_mb()
        self.ram_slider = ctk.CTkSlider(mem, from_=1024, to=max(max_ram, 2048),
                                        number_of_steps=max(1, (max(max_ram, 2048) - 1024) // 512),
                                        progress_color=theme.COL["accent"],
                                        button_color=theme.COL["accent"],
                                        button_hover_color=theme.COL["accent_hi"],
                                        command=self._on_ram)
        self.ram_slider.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 4))
        ctk.CTkLabel(mem, text=f"Detected system RAM: {system_info.total_ram_mb()} MB",
                     font=theme.font(11), text_color=theme.COL["text_faint"]
                     ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 16))

        # ---- Window ----------------------------------------------
        win = Card(scroll)
        win.grid(row=2, column=0, sticky="ew", padx=6, pady=8)
        win.grid_columnconfigure(1, weight=1)
        section_label(win, "GAME WINDOW", glyph="ui_window").grid(row=0, column=0, columnspan=4, sticky="w",
                                               padx=18, pady=(16, 6))
        ctk.CTkLabel(win, text="Width", font=theme.font(12),
                     text_color=theme.COL["text_dim"]).grid(row=1, column=0, padx=(18, 6), pady=4)
        self.width_entry = ctk.CTkEntry(win, width=90, height=34, fg_color=theme.COL["bg3"],
                                        border_color=theme.COL["border"])
        self.width_entry.grid(row=1, column=1, sticky="w", pady=4)
        ctk.CTkLabel(win, text="Height", font=theme.font(12),
                     text_color=theme.COL["text_dim"]).grid(row=1, column=2, padx=(18, 6), pady=4)
        self.height_entry = ctk.CTkEntry(win, width=90, height=34, fg_color=theme.COL["bg3"],
                                         border_color=theme.COL["border"])
        self.height_entry.grid(row=1, column=3, sticky="w", padx=(0, 18), pady=4)
        # Same shape as every other checkbox in the launcher: the box at 18 px, the accent for
        # "on". Extra border and hover colours here turn the whole row into a filled bar.
        self.fullscreen_chk = ctk.CTkCheckBox(win, text="Launch fullscreen",
                                              font=theme.font(13), checkbox_width=18,
                                              checkbox_height=18,
                                              fg_color=theme.COL["accent"])
        self.fullscreen_chk.grid(row=2, column=0, columnspan=4, sticky="w", padx=18, pady=(6, 16))

        # ---- Java ------------------------------------------------
        java = Card(scroll)
        java.grid(row=3, column=0, sticky="ew", padx=6, pady=8)
        java.grid_columnconfigure(0, weight=1)
        section_label(java, "JAVA", glyph="ui_java").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(java, text="Leave empty and Divine downloads the correct Java for you (from Adoptium).",
                     font=theme.font(11), text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=1, column=0, sticky="w", padx=18)
        jrow = ctk.CTkFrame(java)
        jrow.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 8))
        jrow.grid_columnconfigure(0, weight=1)
        self.java_entry = ctk.CTkEntry(jrow, height=36, fg_color=theme.COL["bg3"],
                                       border_color=theme.COL["border"],
                                       placeholder_text="(auto) path to java executable")
        self.java_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ghost_button(jrow, "Browse", self._browse_java, width=90, height=36).grid(row=0, column=1)

        # Repair Java - wipes the managed runtimes so the next launch pulls a
        # fresh, complete copy. This is the one-click fix for the jli.dll error.
        repair_row = ctk.CTkFrame(java)
        repair_row.grid(row=3, column=0, sticky="ew", padx=18, pady=(2, 2))
        repair_row.grid_columnconfigure(1, weight=1)
        self.repair_btn = ghost_button(repair_row, "Repair Java", self._repair_java,
                                       width=140, height=36)
        self.repair_btn.grid(row=0, column=0, sticky="w")
        self.repair_status = ctk.CTkLabel(repair_row, text="Fixes \u201cjli.dll not found\u201d "
                                          "and other broken-Java errors.",
                                          font=theme.font(11), text_color=theme.COL["text_faint"],
                                          anchor="w")
        self.repair_status.grid(row=0, column=1, sticky="w", padx=(12, 0))

        section_label(java, "JVM ARGUMENTS", glyph="ui_gauge").grid(row=4, column=0, sticky="w", padx=18, pady=(10, 2))
        self.jvm_entry = ctk.CTkEntry(java, height=36, fg_color=theme.COL["bg3"],
                                      border_color=theme.COL["border"])
        self.jvm_entry.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 16))

        # ---- Behaviour -------------------------------------------
        beh = Card(scroll)
        beh.grid(row=4, column=0, sticky="ew", padx=6, pady=8)
        beh.grid_columnconfigure(0, weight=1)
        section_label(beh, "LAUNCHER", glyph="ui_settings").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        self.perf_chk = ctk.CTkCheckBox(
            beh, text="Auto-install the Divine performance pack (Fabric instances and hosted servers)",
            font=theme.font(13), fg_color=theme.COL["accent2"])
        self.perf_chk.grid(row=1, column=0, sticky="w", padx=18, pady=6)
        self.close_chk = ctk.CTkCheckBox(beh, text="Close launcher after the game starts",
                                         font=theme.font(13), fg_color=theme.COL["accent"])
        self.close_chk.grid(row=2, column=0, sticky="w", padx=18, pady=(6, 12))

        # ---- Updates & unfinished tabs ------------------------------
        upd = Card(scroll)
        upd.grid(row=5, column=0, sticky="ew", padx=6, pady=8)
        upd.grid_columnconfigure(0, weight=1)
        section_label(upd, "UPDATES", glyph="ui_download").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        flow_label(upd, text="Divine Client asks the site which version is current. When it "
                               "is not, the new build is downloaded in the background and "
                               "verified, and nothing changes on disk until you restart - "
                               "so an update can never get between you and a game.",
                     font=theme.font(11), text_color=theme.COL["text_dim"],
                     anchor="w", justify="left"
                     ).grid(row=1, column=0, sticky="ew", padx=18)
        self.auto_update_chk = ctk.CTkCheckBox(upd, text="Check and download updates automatically",
                                               font=theme.font(13), checkbox_width=18,
                                               checkbox_height=18, fg_color=theme.COL["accent"])
        self.auto_update_chk.grid(row=2, column=0, sticky="w", padx=18, pady=(10, 6))
        urow = ctk.CTkFrame(upd)
        urow.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 4))
        urow.grid_columnconfigure(3, weight=1)
        self.update_now_btn = ghost_button(urow, "Check now", self._check_update_now,
                                           width=120, height=34)
        self.update_now_btn.grid(row=0, column=0)
        self.restart_update_btn = accent_button(urow, "Restart to update",
                                                self._restart_to_update, width=170,
                                                height=34)
        self.restart_update_btn.grid(row=0, column=1, padx=(8, 0))
        self.update_status = ctk.CTkLabel(urow, text="", font=theme.font(11),
                                         text_color=theme.COL["text_faint"])
        self.update_status.grid(row=0, column=2, sticky="w", padx=(12, 0))
        section_label(upd, "UNFINISHED TABS", glyph="ui_clock").grid(row=4, column=0, sticky="w", padx=18,
                                                   pady=(12, 6))
        self.servers_unlock_chk = ctk.CTkCheckBox(
            upd, text="Show the Servers tab (work in progress)", font=theme.font(13),
            checkbox_width=18, checkbox_height=18, fg_color=theme.COL["warn"],
            command=self._apply_servers_unlock)
        self.servers_unlock_chk.grid(row=5, column=0, sticky="w", padx=18, pady=(2, 2))
        flow_label(upd, text="Turning it off puts the tab back behind the allowance code; "
                               "turning it on asks for that code, so it cannot be enabled by "
                               "accident.",
                     font=theme.font(11), text_color=theme.COL["text_faint"],
                     anchor="w", justify="left"
                     ).grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 16))

        # ---- Discord ---------------------------------------------
        # ---- Windows Defender --------------------------------------
        sec = Card(scroll)
        sec.grid(row=6, column=0, sticky="ew", padx=6, pady=8)
        sec.grid_columnconfigure(0, weight=1)
        section_label(sec, "WINDOWS DEFENDER", glyph="ui_shield").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        flow_label(sec, text="This launcher is unsigned, so Defender can flag DivineClient.exe "
                     "for downloading a Java runtime and running the game. One exclusion for the "
                     "Divine folders stops that. It never turns real-time protection off, never "
                     "excludes a whole drive, and changes nothing else on the machine.",
                     font=theme.font(11), text_color=theme.COL["text_faint"],
                     anchor="w", justify="left"
                     ).grid(row=1, column=0, sticky="ew", padx=18)
        drow = ctk.CTkFrame(sec)
        drow.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 2))
        drow.grid_columnconfigure(1, weight=1)
        from ..widgets import pill, danger_button
        self.defender_pill = pill(drow, "checking\u2026")
        self.defender_pill.grid(row=0, column=0, sticky="w")
        self.defender_label = ctk.CTkLabel(drow, text="", font=theme.font(11),
                                           text_color=theme.COL["text_dim"], anchor="w")
        self.defender_label.grid(row=0, column=1, sticky="w", padx=(10, 8))
        self.defender_btn = accent_button(drow, "Add for me", self._defender_add,
                                          width=130, height=36)
        self.defender_btn.grid(row=0, column=2)
        self.defender_remove = danger_button(drow, "Remove", self._defender_remove, width=100)
        self.defender_remove.grid(row=0, column=3, padx=(8, 0))
        self.defender_paths = flow_label(sec, text="", font=theme.font(10), anchor="w",
                                           justify="left",
                                           text_color=theme.COL["text_faint"])
        self.defender_paths.grid(row=3, column=0, sticky="w", padx=18, pady=(2, 2))
        self.defender_auto_chk = ctk.CTkCheckBox(
            sec, text="If the exclusion disappears, add it back without asking me",
            font=theme.font(11), checkbox_width=18, checkbox_height=18,
            fg_color=theme.COL["accent"], hover_color=theme.COL["accent_hi"],
            border_color=theme.COL["border"], text_color=theme.COL["text_dim"],
            command=self._defender_auto_toggle)
        self.defender_auto_chk.grid(row=4, column=0, sticky="w", padx=18, pady=(4, 6))
        ghost_button(sec, "Ask me again on next launch", self._defender_unask,
                     width=210, height=32).grid(row=5, column=0, sticky="w", padx=18, pady=(0, 16))

        dis = Card(scroll)
        dis.grid(row=7, column=0, sticky="ew", padx=6, pady=8)
        dis.grid_columnconfigure(0, weight=1)
        section_label(dis, "DISCORD", glyph="ui_discord").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        self.discord_chk = ctk.CTkCheckBox(dis, text="Show my activity on Discord (Rich Presence)",
                                           font=theme.font(13), fg_color=theme.COL["accent2"])
        self.discord_chk.grid(row=1, column=0, sticky="w", padx=18, pady=6)
        flow_label(dis, text="Displays \u201cPlaying Divine Client\u201d with your version and instance. "
                     "Needs the Discord desktop app open.",
                     font=theme.font(11), text_color=theme.COL["text_faint"],
                     anchor="w", justify="left"
                     ).grid(row=2, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(dis, text="Custom Discord Application ID (optional \u2013 leave blank to use the built-in one)",
                     font=theme.font(11), text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=3, column=0, sticky="w", padx=18, pady=(10, 2))
        self.discord_id_entry = ctk.CTkEntry(dis, height=36, fg_color=theme.COL["bg3"],
                                             border_color=theme.COL["border"],
                                             placeholder_text="(built-in) your own app id from discord.com/developers")
        self.discord_id_entry.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 10))

        ctk.CTkLabel(dis, text="Friends server (for Connect Discord + friends)",
                     font=theme.font(11), text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=5, column=0, sticky="w", padx=18, pady=(6, 2))
        self.friends_api_entry = ctk.CTkEntry(dis, height=36, fg_color=theme.COL["bg3"],
                                              border_color=theme.COL["border"],
                                              text_color=theme.COL["text"],
                                              placeholder_text=endpoints.SITE)
        self.friends_api_entry.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 16))

        # ---- Game files ------------------------------------------
        loc = Card(scroll)
        loc.grid(row=8, column=0, sticky="ew", padx=6, pady=8)
        loc.grid_columnconfigure(0, weight=1)
        section_label(loc, "GAME FILES", glyph="ui_folder").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 2))
        flow_label(loc, text="Where the shared Minecraft downloads and Java live "
                     "(versions, libraries, assets). Point this at a bigger drive if "
                     "you are short on space.",
                     font=theme.font(11), text_color=theme.COL["text_faint"],
                     anchor="w", justify="left"
                     ).grid(row=1, column=0, sticky="ew", padx=18)
        locrow = ctk.CTkFrame(loc)
        locrow.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 6))
        locrow.grid_columnconfigure(0, weight=1)
        self.gamedir_entry = ctk.CTkEntry(locrow, height=36, fg_color=theme.COL["bg3"],
                                          border_color=theme.COL["border"],
                                          text_color=theme.COL["text"])
        self.gamedir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.gamedir_entry.configure(state="disabled")
        ghost_button(locrow, "Change", self._change_game_dir, width=90, height=36).grid(row=0, column=1)
        self.gamedir_status = ctk.CTkLabel(loc, text="", font=theme.font(11),
                                           text_color=theme.COL["text_faint"], anchor="w")
        self.gamedir_status.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 10))

        # instances & saves location (separate so worlds can live elsewhere)
        section_label(loc, "INSTANCES & SAVES", glyph="ui_instance").grid(row=4, column=0, sticky="w", padx=18, pady=(6, 2))
        flow_label(loc, text="Where instances are created and their worlds, mods and "
                     "options are kept. New instances are made here.",
                     font=theme.font(11), text_color=theme.COL["text_faint"],
                     anchor="w", justify="left"
                     ).grid(row=5, column=0, sticky="ew", padx=18)
        instrow = ctk.CTkFrame(loc)
        instrow.grid(row=6, column=0, sticky="ew", padx=18, pady=(8, 6))
        instrow.grid_columnconfigure(0, weight=1)
        self.instdir_entry = ctk.CTkEntry(instrow, height=36, fg_color=theme.COL["bg3"],
                                          border_color=theme.COL["border"],
                                          text_color=theme.COL["text"])
        self.instdir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.instdir_entry.configure(state="disabled")
        ghost_button(instrow, "Change", self._change_instances_dir, width=90, height=36).grid(row=0, column=1)
        self.instdir_status = ctk.CTkLabel(loc, text="", font=theme.font(11),
                                           text_color=theme.COL["text_faint"], anchor="w")
        self.instdir_status.grid(row=7, column=0, sticky="w", padx=18, pady=(0, 16))

        # ---- Save bar --------------------------------------------
        bar = ctk.CTkFrame(self)
        bar.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 16))
        bar.grid_columnconfigure(0, weight=1)
        ghost_button(bar, "Reset to defaults", self._reset, width=170).grid(row=0, column=0, sticky="w")
        accent_button(bar, "Save settings", self._save, width=170, height=44).grid(row=0, column=1, sticky="e")

    def on_show(self):
        self._load_into_widgets()
        self._show_update_state()
        self.refresh_defender()

    def _load_into_widgets(self):
        c = self.cfg
        self.ram_slider.set(c.get("ram_mb"))
        self._on_ram(c.get("ram_mb"))
        self.width_entry.delete(0, "end"); self.width_entry.insert(0, str(c.get("resolution_width")))
        self.height_entry.delete(0, "end"); self.height_entry.insert(0, str(c.get("resolution_height")))
        self._set_chk(self.fullscreen_chk, c.get("fullscreen"))
        self.java_entry.delete(0, "end"); self.java_entry.insert(0, c.get("custom_java_path", ""))
        self.jvm_entry.delete(0, "end"); self.jvm_entry.insert(0, c.get("jvm_args", ""))
        self._set_chk(self.perf_chk, c.get("auto_performance_mods"))
        self._set_chk(self.close_chk, c.get("close_on_launch"))
        self._set_chk(self.auto_update_chk, c.get("auto_update", True))
        self._set_chk(self.servers_unlock_chk, c.get("servers_unlocked", False))
        self._set_chk(self.discord_chk, c.get("discord_rpc"))
        self.discord_id_entry.delete(0, "end")
        self.discord_id_entry.insert(0, c.get("discord_app_id", ""))
        self.friends_api_entry.delete(0, "end")
        self.friends_api_entry.insert(0, c.get("friends_api_base", ""))
        from ... import paths
        self.gamedir_entry.configure(state="normal")
        self.gamedir_entry.delete(0, "end")
        self.gamedir_entry.insert(0, paths.get_game_dir())
        self.gamedir_entry.configure(state="disabled")
        self.instdir_entry.configure(state="normal")
        self.instdir_entry.delete(0, "end")
        self.instdir_entry.insert(0, paths.get_instances_dir())
        self.instdir_entry.configure(state="disabled")

    def _set_chk(self, chk, val):
        chk.select() if val else chk.deselect()

    def _on_ram(self, value):
        mb = int(float(value))
        self.ram_value_lbl.configure(text=f"{mb} MB  ({mb/1024:.1f} GB)")

    def _saved(self, text, ms=1800):
        """Say it in the window's status line, then clear it if nobody typed over it."""
        try:
            self.app.set_status(text, theme.COL["good"])
            if text and ms:
                self.after(ms, lambda: self._clear_saved(text))
        except Exception:
            pass

    def _clear_saved(self, which):
        try:
            if str(self.app.status_lbl.cget("text")) == which:
                self.app.set_status("")
        except Exception:
            pass

    def _on_style(self, label):
        """Pick a background. Applies now, and is remembered now.

        A preview you have to save first is a preview you do not use, and there is nothing
        here that can go wrong - the palette is a dict and the wash is repainted from it.
        """
        key = self._name_to_key.get(label)
        if not key:
            return
        try:
            if self.cfg.get("ui_background") != key:
                self.cfg.set("ui_background", key)
        except Exception:
            pass
        try:
            self.app.set_background(key)
        except Exception as exc:
            self.app.set_status("Could not apply that background: %s" % str(exc)[:80])
            return
        try:
            self._saved("\u2713 look saved", 1800)
        except Exception:
            pass

    def _repair_java(self):
        self.repair_btn.configure(state="disabled", text="Repairing...")
        self.repair_status.configure(text="Removing the current Java so a clean copy "
                                     "downloads on next launch...",
                                     text_color=theme.COL["accent"])
        threading.Thread(target=self._repair_worker, daemon=True).start()

    def _repair_worker(self):
        from ...core import adoptium
        from ... import paths
        import os
        removed = 0
        # Wipe both the Adoptium runtimes and Mojang's runtime folder.
        for d in (adoptium.adoptium_dir(), os.path.join(paths.MINECRAFT_DIR, "runtime")):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        self.after(0, self._repair_done, removed)

    def _repair_done(self, removed):
        self.repair_btn.configure(state="normal", text="Repair Java")
        if removed:
            self.repair_status.configure(
                text="\u2713 Done. Java will re-download cleanly the next time you play.",
                text_color=theme.COL["good"])
        else:
            self.repair_status.configure(
                text="Nothing to repair yet \u2014 Java installs on your first launch.",
                text_color=theme.COL["text_faint"])
        self.after(4000, lambda: self.repair_status.configure(
            text="Fixes \u201cjli.dll not found\u201d and other broken-Java errors.",
            text_color=theme.COL["text_faint"]))

    def _change_game_dir(self):
        from tkinter import filedialog, messagebox
        from ... import paths
        import os

        chosen = filedialog.askdirectory(title="Choose where to keep game files")
        if not chosen:
            return
        chosen = os.path.abspath(chosen)
        current = paths.get_game_dir()
        if os.path.normpath(chosen) == os.path.normpath(current):
            return

        # What has to come along regardless of the answer is handled by
        # paths.relocate_subdirs; this question is only about the user's own folders -
        # the instances and the hosted server worlds - because those are the big ones
        # and the only ones where "start fresh over there" is a reasonable thing to want.
        current_has_files = os.path.isdir(os.path.join(current, "instances")) or \
            os.path.isdir(os.path.join(current, "servers"))
        move = False
        if current_has_files:
            move = messagebox.askyesno(
                "Move your instances and server worlds?",
                "The launcher's own files - the downloaded versions, the libraries, "
                "Java and the tunnel program - always move with the location. That is "
                "not a choice: without them the new folder re-downloads everything and a "
                "hosted server loses its address.\n\n"
                "Yes  \u2013  also move your instances and your hosted server worlds.\n"
                "No  \u2013  leave them where they are. They keep working, because the "
                "launcher stores where each one lives; new instances and new servers will "
                "be created in the new folder.")

        if self.app.total_running():
            messagebox.showinfo("Close your games first",
                                "Please close any running games before moving game files.")
            return

        self.gamedir_status.configure(text="Applying...", text_color=theme.COL["accent"])
        threading.Thread(target=self._apply_game_dir_worker,
                         args=(current, chosen, move), daemon=True).start()

    def _apply_game_dir_worker(self, current, chosen, move):
        import os
        from ... import paths
        # Only relocate the "instances" folder together with game files when the
        # instances directory is still following game_dir (not set separately).
        move_instances = paths.is_default_instances_dir()
        try:
            os.makedirs(chosen, exist_ok=True)
            # minecraft + tunnel always; the user's own folders only when they said yes
            notes = paths.relocate_subdirs(
                current, chosen,
                include_user_data=bool(move),
                # a separately-configured instances folder is not under either root, so
                # touching the one that happens to be lying around here would be wrong
                skip=() if move_instances else ("instances",),
                progress=lambda msg: self.after(0, lambda m=msg: self.gamedir_status.configure(
                    text=m[:90], text_color=theme.COL["accent"])))
            paths.set_game_dir(chosen)
            try:
                self.app.instances.load()
            except Exception:
                pass
            self.after(0, self._game_dir_done, chosen, move, None, notes)
        except Exception as e:
            self.after(0, self._game_dir_done, chosen, move, str(e), {})

    def _game_dir_done(self, chosen, move, err, notes=None):
        from ... import paths
        self.gamedir_entry.configure(state="normal")
        self.gamedir_entry.delete(0, "end")
        self.gamedir_entry.insert(0, paths.get_game_dir())
        self.gamedir_entry.configure(state="disabled")
        # game_dir change may also move the default instances folder
        self.instdir_entry.configure(state="normal")
        self.instdir_entry.delete(0, "end")
        self.instdir_entry.insert(0, paths.get_instances_dir())
        self.instdir_entry.configure(state="disabled")
        if err:
            self.gamedir_status.configure(text="Could not switch: " + err[:90],
                                          text_color=theme.COL["danger"])
            return
        moved = ", ".join(sorted(k for k, v in (notes or {}).items() if v == "moved"))
        merged = ", ".join(sorted(k for k, v in (notes or {}).items() if v == "merged"))
        bits = ["\u2713 Game files now stored here."]
        if moved:
            bits.append("moved " + moved)
        if merged:
            bits.append("merged into an existing " + merged)
        if not move:
            bits.append("instances and server worlds left where they were")
        msg = "  \u00b7  ".join(bits)
        self.gamedir_status.configure(text=msg, text_color=theme.COL["good"])
        try:
            self.app.refresh_all()
        except Exception:
            pass
        self.after(6000, lambda: self.gamedir_status.configure(text=""))

    # ---- instances & saves location -----------------------------
    def _change_instances_dir(self):
        from tkinter import filedialog, messagebox
        from ... import paths
        import os

        chosen = filedialog.askdirectory(title="Choose where to keep instances and saves")
        if not chosen:
            return
        chosen = os.path.abspath(chosen)
        current = paths.get_instances_dir()
        if os.path.normpath(chosen) == os.path.normpath(current):
            return

        if self.app.total_running():
            messagebox.showinfo("Close your games first",
                                "Please close any running games before moving instances.")
            return

        move = False
        if os.path.isdir(current) and os.listdir(current):
            move = messagebox.askyesno(
                "Move existing instances?",
                "Move your existing instances (worlds, mods, saves) to the new "
                "location?\n\nYes  \u2013  move them now (recommended).\n"
                "No  \u2013  start fresh there (existing instances stay where they are).")

        self.instdir_status.configure(text="Applying...", text_color=theme.COL["accent"])
        threading.Thread(target=self._apply_instances_dir_worker,
                         args=(current, chosen, move), daemon=True).start()

    def _apply_instances_dir_worker(self, current, chosen, move):
        import os
        from ... import paths
        try:
            os.makedirs(chosen, exist_ok=True)
            if move and os.path.isdir(current):
                for name in os.listdir(current):
                    src = os.path.join(current, name)
                    dst = os.path.join(chosen, name)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst, ignore_errors=True)
                        else:
                            os.remove(dst)
                    shutil.move(src, dst)
            paths.set_instances_dir(chosen)
            try:
                self.app.instances.load()
            except Exception:
                pass
            self.after(0, self._instances_dir_done, move, None)
        except Exception as e:
            self.after(0, self._instances_dir_done, move, str(e))

    def _instances_dir_done(self, move, err):
        from ... import paths
        self.instdir_entry.configure(state="normal")
        self.instdir_entry.delete(0, "end")
        self.instdir_entry.insert(0, paths.get_instances_dir())
        self.instdir_entry.configure(state="disabled")
        if err:
            self.instdir_status.configure(text="Could not switch: " + err[:90],
                                          text_color=theme.COL["danger"])
            return
        msg = "\u2713 Instances now stored here." if move else \
            "\u2713 New location set. New instances will be created here."
        self.instdir_status.configure(text=msg, text_color=theme.COL["good"])
        try:
            self.app.refresh_all()
            self.app.pages["home"].refresh_instances()
        except Exception:
            pass
        self.after(6000, lambda: self.instdir_status.configure(text=""))

    def _browse_java(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Select java executable")
        if path:
            self.java_entry.delete(0, "end")
            self.java_entry.insert(0, path)

    def _save(self):
        c = self.cfg
        c.set("ram_mb", int(self.ram_slider.get()))
        try:
            c.set("resolution_width", max(320, int(self.width_entry.get())))
            c.set("resolution_height", max(240, int(self.height_entry.get())))
        except ValueError:
            pass
        c.set("fullscreen", bool(self.fullscreen_chk.get()))
        c.set("custom_java_path", self.java_entry.get().strip())
        c.set("jvm_args", self.jvm_entry.get().strip())
        c.set("auto_performance_mods", bool(self.perf_chk.get()))
        c.set("close_on_launch", bool(self.close_chk.get()))
        c.set("discord_rpc", bool(self.discord_chk.get()))
        c.set("discord_app_id", self.discord_id_entry.get().strip())
        c.set("friends_api_base", self.friends_api_entry.get().strip())
        c.set("auto_update", bool(self.auto_update_chk.get()))
        c.save()
        # Apply the Discord change live.
        try:
            self.app.discord.set_app_id(c.get("discord_app_id", ""))
            self.app.discord.set_enabled(bool(self.discord_chk.get()))
            self.app.refresh_discord()
        except Exception:
            pass
        self._saved("\u2713 Saved", 1800)

    # ---- the update controls ------------------------------------------
    def _apply_servers_unlock(self):
        """The checkbox can put the tab away; only the code can take it back out."""
        if self.servers_unlock_chk.get():
            return
        try:
            self.app.lock_servers()
        except Exception:
            pass

    def _check_update_now(self):
        self.update_status.configure(text="asking the site\u2026",
                                     text_color=theme.COL["accent"])
        try:
            # through the app, so the answer lands in the sidebar pill as well as here
            self.app.check_for_updates_now()
        except Exception:
            pass
        self.after(1500, self._show_update_state)
        self.after(6000, self._show_update_state)

    def _show_update_state(self):
        try:
            state = getattr(self.app, "_update_state", None) or {}
        except Exception:
            state = {}
        kind = state.get("state", "")
        text = {"current": "This is the newest version.",
                "available": "Version %s is downloading now." % state.get("remote", ""),
                "downloading": state.get("detail") or "downloading\u2026",
                "staged": "Version %s is ready and will install on restart."
                          % state.get("remote", ""),
                "downloaded": "Version %s is ready and will install on restart."
                              % state.get("remote", ""),
                "unreachable": "Could not reach the site to check.",
                "failed": "Update failed: %s" % (state.get("detail") or "unknown"),
                "no-download": "The site has not published a download for %s yet."
                               % state.get("remote", "")}.get(kind, "Not checked yet.")
        try:
            self.update_status.configure(
                text=text,
                text_color=theme.COL["good"] if kind in ("current", "staged",
                                                          "downloaded") else (
                    theme.COL["danger"] if kind in ("failed",) else
                    theme.COL["text_faint"]))
            self.restart_update_btn.configure(
                state=("normal" if kind in ("staged", "downloaded") else "disabled"))
        except Exception:
            pass

    def _restart_to_update(self):
        try:
            self.app.update_action()
        except Exception:
            pass

    def _reset(self):
        from ...core.config import DEFAULTS
        for k, v in DEFAULTS.items():
            self.cfg.set(k, v)
        self.cfg.save()
        self._load_into_widgets()
        self._saved("\u2713 Reset", 1800)

    # ------------------------------------------------------- Windows Defender
    def refresh_defender(self):
        """Ask the Defender module what the state is - off this thread.

        ``status()`` may run PowerShell to read the exclusion list, and that can take the
        best part of its timeout. The card starts at "checking" and fills in when the answer
        arrives, so the page is never frozen on the way to it.
        """
        try:
            self.defender_pill.configure(text="checking\u2026",
                                         fg_color=theme.COL["bg3"])
            self.defender_label.configure(text="reading the Defender settings\u2026")
        except Exception:
            pass
        self._defender_busy = getattr(self, "_defender_busy", False)
        if getattr(self, "_defender_reading", False):
            return
        self._defender_reading = True

        def work():
            from ...core import defender
            try:
                info = defender.status(self.cfg)
            except Exception as exc:
                info = {"state": "ready", "paths": [], "detail": "%s: %s" % (type(exc).__name__, exc),
                        "can_remove": False, "script": ""}
            self._defender_reading = False
            try:
                self.after(0, lambda: self._show_defender(info))
            except Exception:
                pass

        threading.Thread(target=work, name="divine-defender-status", daemon=True).start()

    def _show_defender(self, info):
        from ...core import defender
        info = info or {}
        state = str(info.get("state") or "ready")
        tone = {"already": theme.COL["good"], "done": theme.COL["good"],
                "no-script": theme.COL["warn"], "unsupported": theme.COL["bg3"]}.get(
            state, theme.COL["warn"])
        label = {"already": "on the list", "done": "added", "ready": "not added",
                 "no-script": "helper missing", "unsupported": "windows only",
                 "asked": "not added", "declined": "not added"}.get(state, "not added")
        try:
            self.defender_pill.configure(text=label, fg_color=tone)
            self.defender_label.configure(text=defender.describe(info))
            paths = info.get("paths") or []
            detail = info.get("detail") or ""
            if paths:
                detail = "%s\n%s" % ("\n".join("  %s" % p for p in paths), detail)
            note = str(getattr(self, "_defender_note", "") or "")
            if note:
                # kept here rather than in a label of its own, because the refresh below
                # rewrites this line and a report that vanished in half a second is useless
                detail = "%s\n%s" % (detail, note)
            self.defender_paths.configure(text=detail)
            can = state in ("ready", "done", "asked", "declined") and bool(info.get("script"))
            self.defender_btn.configure(state=("normal" if can else "disabled"),
                                        text="Add for me" if state != "already" else "Nothing to add")
            self.defender_remove.grid_forget()
            if info.get("can_remove"):
                self.defender_remove.grid(row=0, column=3, padx=(8, 0))
            self._set_chk(self.defender_auto_chk, bool(defender.auto_run(self.cfg)))
        except Exception:
            pass

    def _defender_add(self):
        self._defender_busy = True
        self._defender_note = ""
        try:
            self.defender_btn.configure(state="disabled", text="waiting on Windows\u2026")
        except Exception:
            pass
        from ...core import defender
        defender.apply_async(config=self.cfg, on_done=self._defender_done)

    def _defender_remove(self):
        self._defender_busy = True
        self._defender_note = ""
        try:
            self.defender_remove.configure(state="disabled", text="removing\u2026")
        except Exception:
            pass
        from ...core import defender
        defender.apply_async(config=self.cfg, remove=True, on_done=self._defender_done)

    def _defender_done(self, report):
        """What the elevated helper came back with, kept until the next attempt.

        ``refresh_defender`` runs straight after this and rebuilds the whole line, so the
        note has to go through ``_show_defender`` with it - a label written here would be
        overwritten before it could be read.
        """
        self._defender_busy = False
        report = report or {}
        if report.get("ok"):
            self._defender_note = (
                "last run: Defender did not confirm it yet - check Windows Security"
                if report.get("verified") is False else
                "last run: done, Defender leaves these folders alone")
        else:
            self._defender_note = "last run: %s" % (report.get("reason") or "Windows said no")
        try:
            self.defender_btn.configure(text="Add for me")
            self.defender_remove.configure(text="Remove")
        except Exception:
            pass
        self.refresh_defender()

    def _defender_auto_toggle(self):
        from ...core import defender
        try:
            defender.set_auto(self.cfg, bool(self.defender_auto_chk.get()))
        except Exception:
            pass

    def _defender_unask(self):
        """Put the first-open offer back, for someone who said no and changed their mind."""
        try:
            self.cfg.set("defender_asked", False)
            self.cfg.set("defender_state", "")
            self.cfg.save()
            self._saved("\u2713 will ask on next launch", 2200)
        except Exception:
            pass

