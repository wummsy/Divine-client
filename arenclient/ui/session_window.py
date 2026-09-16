"""A per-launch window that opens when a game starts.

Shows the instance details, a live status/log view, and a Mods tab where the
player can enable or disable the mods in that instance. Closing the game (or the
window's Stop button) is wired back to the main app's process tracking.
"""
import os
import threading

import customtkinter as ctk

from ..core import mod_manager
from . import theme
from .scrollsync import Gate
from .widgets import Card, accent_button, danger_button, ghost_button, scroll_frame


def _shorten(text, n):
    """Clip to a fixed box so a longer real name cannot widen every row.

    Rows in these lists share one grid column, so an unbounded label growing by a
    few characters re-flows the whole list - which is what reads as a glitch while
    the list is being scrolled.
    """
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    cut = text[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:.-") + "\u2026"


class SessionWindow(ctk.CTkToplevel):
    def __init__(self, app, instance, proc, log_path):
        super().__init__(app)
        self.app = app
        self.instance = instance
        self.proc = proc
        self.log_path = log_path
        self._log_pos = 0

        self.title("Divine Client \u2014 " + instance.name)
        theme.auto_pin(self)   # dialogs are not pages: nothing else walks them
        self.geometry("640x560")
        self.minsize(520, 460)
        self.configure(fg_color=theme.COL["bg"])
        try:
            self.after(200, self._apply_icon)
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_tabs()

        self._poll()

    def _apply_icon(self):
        try:
            from .. import paths
            import tkinter as tk
            png = paths.resource_path(os.path.join("assets", "emblem.png"))
            if os.path.exists(png):
                self.iconphoto(False, tk.PhotoImage(file=png))
        except Exception:
            pass

    # ---- header --------------------------------------------------
    def _build_header(self):
        head = Card(self)
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        head.grid_columnconfigure(1, weight=1)

        badge = "F" if self.instance.loader == "fabric" else "V"
        col = theme.COL["accent2"] if self.instance.loader == "fabric" else theme.COL["accent"]
        ctk.CTkLabel(head, text=badge, width=52, height=52, corner_radius=12,
                     font=theme.font(22, "bold"), text_color="#04121a", fg_color=col
                     ).grid(row=0, column=0, rowspan=2, padx=(16, 14), pady=16)

        ctk.CTkLabel(head, text=self.instance.name, font=theme.font(18, "bold"),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=1, sticky="w", pady=(16, 0))
        loader = "Fabric" if self.instance.loader == "fabric" else "Vanilla"
        self.status_dot = ctk.CTkLabel(
            head, text="\u25CF Running   \u2022   Minecraft " + self.instance.mc_version
                       + "   \u2022   " + loader,
            font=theme.font(12), text_color=theme.COL["good"], anchor="w")
        self.status_dot.grid(row=1, column=1, sticky="w", pady=(0, 16))

        self.stop_btn = danger_button(head, "\u25A0  Stop game", self._stop,
                                      width=130, height=42)
        self.stop_btn.grid(row=0, column=2, rowspan=2, padx=16)

    # ---- tabs ----------------------------------------------------
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.COL["bg2"],
            segmented_button_fg_color=theme.COL["bg3"],
            segmented_button_selected_color=theme.COL["accent"],
            segmented_button_selected_hover_color=theme.COL["accent_hi"],
            segmented_button_unselected_color=theme.COL["bg3"],
            text_color=theme.COL["text"],
        )
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=16, pady=(6, 16))
        self.tab_mods = self.tabs.add("Mods")
        self.tab_details = self.tabs.add("Details")
        self.tab_log = self.tabs.add("Log")

        self._build_mods_tab()
        self._build_details_tab()
        self._build_log_tab()

    # ---- mods tab ------------------------------------------------
    def _build_mods_tab(self):
        self.tab_mods.grid_columnconfigure(0, weight=1)
        self.tab_mods.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self.tab_mods)
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 4))
        bar.grid_columnconfigure(0, weight=1)
        self.mods_note = ctk.CTkLabel(
            bar, text="Toggle mods below. Changes apply the next time you launch.",
            font=theme.font(11), text_color=theme.COL["text_faint"], anchor="w")
        self.mods_note.grid(row=0, column=0, sticky="w", padx=6)
        accent_button(bar, "Get mods", self._open_browser, width=110, height=32).grid(row=0, column=1, padx=(4, 2))
        ghost_button(bar, "Add .jar", self._add_mod, width=90, height=32).grid(row=0, column=2, padx=2)
        ghost_button(bar, "Refresh", self._refresh_mods, width=90, height=32).grid(row=0, column=3, padx=2)
        ghost_button(bar, "Open folder", self._open_mods_folder, width=110, height=32).grid(row=0, column=4, padx=(2, 6))

        self.mods_list = scroll_frame(self.tab_mods)
        self.mods_list.grid(row=1, column=0, sticky="nsew", padx=2, pady=(2, 6))
        self.mods_list.grid_columnconfigure(0, weight=1)
        # mod metadata arrives while this tab may be being scrolled; see
        # ui/scrollsync.py - same reason as in the instance editor
        self._mods_gate = Gate(self, getattr(self.mods_list, "_parent_canvas", None))

        self._refresh_mods()

    def _mods_dir(self):
        return os.path.join(self.instance.game_dir, "mods")

    def _refresh_mods(self):
        gate = getattr(self, "_mods_gate", None)
        if gate:
            gate.clear()
        for w in self.mods_list.winfo_children():
            w.destroy()
        self._mod_rows = {}
        # names from filenames first: opening every jar in the instance to read
        # fabric.mod.json used to hold up the whole game window on this tab
        mods = mod_manager.list_mods(self._mods_dir(), with_meta=False)
        if not mods:
            ctk.CTkLabel(self.mods_list,
                         text="No mods in this instance.\n"
                              "Vanilla instances have none; Fabric ones get the "
                              "Divine pack.\nUse \u201cAdd .jar\u201d to add your own.",
                         font=theme.font(13), text_color=theme.COL["text_faint"],
                         justify="left").grid(row=0, column=0, sticky="w", padx=10, pady=20)
            return
        for idx, mod in enumerate(mods):
            self._mod_row(mod, idx)
        self._read_mod_meta(mods)

    def _mod_row(self, mod, idx):
        row = Card(self.mods_list, fg_color=theme.COL["bg3"])
        row.grid(row=idx, column=0, sticky="ew", padx=4, pady=4)
        row.grid_columnconfigure(1, weight=1)

        var = ctk.BooleanVar(value=mod["enabled"])
        sw = ctk.CTkSwitch(row, text="", variable=var, width=44,
                           progress_color=theme.COL["good"],
                           command=lambda m=mod, v=var: self._toggle(m, v))
        sw.grid(row=0, column=0, rowspan=2, padx=(14, 8), pady=12)

        title = mod["name"] + ("  " + mod["version"] if mod["version"] else "")
        # width/height pinned: the real name from fabric.mod.json is usually longer
        # than the filename it is replaced by, and an unbounded label would widen
        # this column for every row in the list while the user is scrolling it
        title_lbl = ctk.CTkLabel(row, text=_shorten(title, 44),
                                   font=theme.font(14, "bold"),
                                   text_color=theme.COL["text"] if mod["enabled"] else theme.COL["text_faint"],
                                   anchor="w", width=340, height=22)
        title_lbl.grid(row=0, column=1, sticky="w", pady=(10, 0))
        sub = _shorten(mod["description"] or mod["filename"], 70)
        desc_lbl = ctk.CTkLabel(row, text=sub, font=theme.font(11),
                                text_color=theme.COL["text_faint"], anchor="w",
                                width=340, height=18)
        desc_lbl.grid(row=1, column=1, sticky="w", pady=(0, 10))
        self._mod_rows[mod["path"]] = (title_lbl, desc_lbl)

    def _read_mod_meta(self, mods):
        """Fill each row's real name/version/description off the UI thread."""
        self._meta_gen = getattr(self, "_meta_gen", 0) + 1
        gen = self._meta_gen

        def run():
            out = []
            for mod in mods:
                meta = mod_manager.read_meta(mod["path"])
                if meta and meta.get("name"):
                    out.append((mod["path"], meta))
            try:
                self.after(0, lambda: self._apply_mod_meta(gen, out))
            except Exception:
                pass

        if mods:
            threading.Thread(target=run, daemon=True).start()

    def _apply_mod_meta(self, gen, updates):
        """Put worker results on their rows - but not while the list is scrolling."""
        if gen != getattr(self, "_meta_gen", 0):
            return
        gate = getattr(self, "_mods_gate", None)
        for path, meta in updates:
            pair = self._mod_rows.get(path)
            if not pair:
                continue
            if gate is None:
                self._apply_mod_pair(pair, meta)
            else:
                gate.submit(path, lambda p=pair, m=meta: self._apply_mod_pair(p, m))

    def _apply_mod_pair(self, pair, meta):
        title_lbl, desc_lbl = pair
        try:
            title = meta["name"] + ("  " + meta["version"] if meta.get("version") else "")
            title_lbl.configure(text=_shorten(title, 44))
            desc = (meta.get("description") or "").strip()
            if desc:
                desc_lbl.configure(text=_shorten(desc, 70))
        except Exception:
            pass        # the row can be gone by now - the tab was rebuilt

    def _toggle(self, mod, var):
        new_name = mod_manager.set_enabled(self._mods_dir(), mod["filename"], var.get())
        if new_name is None:
            var.set(mod["enabled"])  # revert on failure
            return
        self.mods_note.configure(
            text="Changed \u201c" + mod["name"] + "\u201d. Restart the game for it to take effect.",
            text_color=theme.COL["warn"])
        self._refresh_mods()

    def _delete(self, mod):
        if mod_manager.delete_mod(self._mods_dir(), mod["filename"]):
            self._refresh_mods()

    def _open_browser(self):
        from .mod_browser import ModBrowser
        win = ModBrowser(self.app, self.instance, on_close=self._refresh_mods)
        win.after(120, win.lift)
        win.after(160, win.focus_force)

    def _add_mod(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Choose a mod .jar",
                                          filetypes=[("Mod jar", "*.jar")])
        if path:
            mod_manager.add_mod(self._mods_dir(), path)
            self._refresh_mods()

    def _open_mods_folder(self):
        import subprocess, sys
        d = self._mods_dir()
        os.makedirs(d, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(d)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception:
            pass

    # ---- details tab ---------------------------------------------
    def _build_details_tab(self):
        self.tab_details.grid_columnconfigure(0, weight=1)
        rows = [
            ("Instance", self.instance.name),
            ("Minecraft version", self.instance.mc_version),
            ("Mod loader", "Fabric" if self.instance.loader == "fabric" else "Vanilla"),
            ("Game folder", self.instance.game_dir),
        ]
        for i, (label, value) in enumerate(rows):
            ctk.CTkLabel(self.tab_details, text=label.upper(), font=theme.font(11, "bold"),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=i * 2, column=0, sticky="w", padx=10, pady=(14 if i else 16, 0))
            ctk.CTkLabel(self.tab_details, text=value, font=theme.font(13),
                         text_color=theme.COL["text"], anchor="w", wraplength=560, justify="left"
                         ).grid(row=i * 2 + 1, column=0, sticky="w", padx=10, pady=(0, 2))
        self.pid_label = ctk.CTkLabel(self.tab_details, text="", font=theme.font(11),
                                      text_color=theme.COL["text_faint"], anchor="w")
        self.pid_label.grid(row=99, column=0, sticky="w", padx=10, pady=(18, 4))

    # ---- log tab -------------------------------------------------
    def _build_log_tab(self):
        self.tab_log.grid_columnconfigure(0, weight=1)
        self.tab_log.grid_rowconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(self.tab_log, fg_color=theme.COL["bg"],
                                      text_color=theme.COL["text_dim"],
                                      font=(theme.MONO_FAMILY, 11), wrap="none")
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=2, pady=6)
        self.log_box.insert("end", "Waiting for game output...\n")
        self.log_box.configure(state="disabled")

    def _read_new_log(self):
        try:
            if not os.path.exists(self.log_path):
                return ""
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._log_pos)
                chunk = f.read()
                self._log_pos = f.tell()
            return chunk
        except OSError:
            return ""

    # ---- lifecycle -----------------------------------------------
    def _poll(self):
        chunk = self._read_new_log()
        if chunk:
            self.log_box.configure(state="normal")
            if self._log_pos and self.log_box.get("1.0", "1.5") == "Waiti":
                self.log_box.delete("1.0", "end")
            self.log_box.insert("end", chunk)
            # keep the last ~1500 lines to stay light
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        alive = self.proc.poll() is None
        try:
            self.pid_label.configure(text="Process id: " + str(self.proc.pid)
                                     + ("  (running)" if alive else "  (exited)"))
        except Exception:
            pass

        if not alive:
            code = self.proc.poll()
            self.status_dot.configure(
                text="\u25CF Stopped   \u2022   exit code " + str(code),
                text_color=theme.COL["text_faint"])
            self.stop_btn.configure(text="Close", command=self.destroy,
                                    fg_color=theme.COL["bg3"], text_color=theme.COL["text"],
                                    border_width=0, hover_color=theme.COL["bg_hover"])
            return  # stop polling once it's dead
        self.after(1000, self._poll)

    def _stop(self):
        self.stop_btn.configure(state="disabled", text="Stopping...")
        self.app.stop_instance(self.instance.id)
        self.after(400, self._poll)
