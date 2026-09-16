"""The server window: one per hosted server, and closing it changes nothing.

This is a view, not an owner. The session lives on ``app.servers``
(``core.server_sessions``), so closing this window - or even the whole launcher -
leaves the server running for your friends. Stop, Restart and Kill are explicit
buttons, and the Servers panel always lists what is up.

The header shows live resource usage: the memory you allocated versus what the
Java process actually holds, CPU, players online and the tunnel state.
"""
import os
import threading
import time

import customtkinter as ctk

from .. import paths
from ..core import resources
from . import theme
from .widgets import Card, accent_button, ghost_button, danger_button, pill


_STATUS_COLORS = {
    "starting": ("warn", "#04121a"),
    "running": ("good", "#04140b"),
    "stopping": ("warn", "#04121a"),
    "stopped": ("bg3", "text_dim"),
    "crashed": ("danger", "#ffffff"),
}


class ServerWindow(ctk.CTkToplevel):
    def __init__(self, session, master=None):
        super().__init__(master)
        self.session = session
        self._closed = False
        self._rows_shown = 0

        self.title("Divine server - " + session.name)
        self.geometry("1040x680")
        self.minsize(760, 480)
        self.configure(fg_color=theme.COL["bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        self._build_header()
        self._build_meters()
        self._build_console()
        self._build_actions()

        # the session pushes events; we redraw on a slow tick for the numbers
        session.add_listener(self._on_event)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        try:
            self.after(150, self._apply_icon)
        except Exception:
            pass
        # Seed from the SAME list _redraw() walks. Reading the log file here
        # instead put the history on screen twice: once from the file and once
        # from log_lines on the first redraw (the tailer holds the same lines).
        live = list(session.proc.log_lines) if session.proc else []
        seed = (live or session.history())[-400:]
        for line in seed:
            self._append(line)
        # _redraw() paints log_lines[self._rows_shown:], so everything we just put
        # on screen counts as seen. Lines older than the 400-line window are
        # skipped rather than shown twice.
        self._rows_shown = len(live)
        self._redraw()
        self._tick()

    def _apply_icon(self):
        try:
            import tkinter as tk
            png = paths.resource_path(os.path.join("assets", "emblem.png"))
            if os.path.exists(png):
                self.iconphoto(False, tk.PhotoImage(file=png))
        except Exception:
            pass

    # ------------------------------------------------------------------ build
    def _build_header(self):
        head = Card(self)
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        head.grid_columnconfigure(1, weight=1)
        self.head_badge = ctk.CTkLabel(head, text="S", width=48, height=48, corner_radius=12,
                                       font=theme.font(20, "bold"), text_color="#04140b",
                                       fg_color=theme.COL["accent"])
        self.head_badge.grid(row=0, column=0, rowspan=2, padx=(16, 14), pady=14)

        row0 = ctk.CTkFrame(head, fg_color="transparent")
        row0.grid(row=0, column=1, sticky="w", pady=(14, 0))
        self.title_lbl = ctk.CTkLabel(row0, text=self.session.name,
                                      font=theme.title_font(20),
                                      text_color=theme.COL["text"], anchor="w")
        self.title_lbl.pack(side="left")
        self.status_pill = pill(row0, "starting", theme.COL["warn"])
        self.status_pill.pack(side="left", padx=(10, 0))

        meta = "Minecraft %s  \u2022  %s  \u2022  port %s" % (
            self.session.mc_version,
            "Fabric" if self.session.loader == "fabric" else "Vanilla",
            self.session.port)
        self.meta_lbl = ctk.CTkLabel(head, text=meta, font=theme.font(12),
                                     text_color=theme.COL["text_dim"], anchor="w")
        self.meta_lbl.grid(row=1, column=1, sticky="w", padx=0, pady=(2, 14))

        self.close_note = ctk.CTkLabel(head, text="Closing this window keeps the "
                                     "server running", font=theme.font(11),
                                     text_color=theme.COL["text_faint"])
        self.close_note.grid(row=0, column=2, rowspan=2, sticky="e", padx=(6, 16))

    def _build_meters(self):
        strip = ctk.CTkFrame(self, fg_color="transparent")
        strip.grid(row=1, column=0, sticky="ew", padx=16)
        self.grid_rowconfigure(1, weight=0)
        for c in range(4):
            strip.grid_columnconfigure(c, weight=1, uniform="meters")

        self.meters = {}
        specs = [("mem", "MEMORY"), ("cpu", "CPU"), ("players", "PLAYERS"),
                 ("uptime", "UPTIME")]
        for c, (key, label) in enumerate(specs):
            card = Card(strip, fg_color=theme.COL["bg3"], corner_radius=14)
            card.grid(row=0, column=c, sticky="nsew", padx=(0 if c == 0 else 8), pady=(0, 8))
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=label, font=theme.font(10, "bold"),
                         text_color=theme.COL["text_faint"]
                         ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))
            val = ctk.CTkLabel(card, text="\u2014", font=theme.font(21, "bold"),
                               text_color=theme.COL["text"], anchor="w")
            val.grid(row=1, column=0, sticky="w", padx=14)
            sub = ctk.CTkLabel(card, text="", font=theme.font(11),
                               text_color=theme.COL["text_dim"], anchor="w")
            sub.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 2))
            bar = None
            if key == "mem":
                bar = ctk.CTkProgressBar(card, height=8, corner_radius=4,
                                         progress_color=theme.COL["accent"],
                                         fg_color=theme.COL["bg"])
                bar.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 6))
                bar.set(0)
                sub.configure(text="of %d MB allocated" % self.session.ram_mb)
            self.meters[key] = {"value": val, "sub": sub, "bar": bar}

        # tunnel / address line
        net = Card(self, fg_color=theme.COL["bg2"], corner_radius=14)
        net.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        net.grid_columnconfigure(1, weight=1)
        self.net_lbl = ctk.CTkLabel(net, text="Opening the tunnel...", font=theme.font(12),
                                    text_color=theme.COL["text_dim"], anchor="w",
                                    justify="left", wraplength=680)
        self.net_lbl.grid(row=0, column=0, columnspan=2, sticky="ew",
                          padx=16, pady=(12, 2))
        self.copy_btn = ghost_button(net, "Copy join address", self._copy_address,
                                     width=150, height=30)
        self.copy_btn.grid(row=1, column=1, sticky="e", padx=(6, 14), pady=(0, 12))
        self.open_log_btn = ghost_button(net, "Open log file", self._open_log,
                                         width=120, height=30)
        self.open_log_btn.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        self.grid_rowconfigure(2, weight=0)

    def _build_console(self):
        card = Card(self)
        card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.grid_rowconfigure(3, weight=1)
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 2))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="CONSOLE", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w")
        self.warn_lbl = ctk.CTkLabel(head, text="", font=theme.font(11),
                                     text_color=theme.COL["warn"])
        self.warn_lbl.grid(row=0, column=1, sticky="e")

        self.console = ctk.CTkTextbox(card, font=(theme.MONO_FAMILY, 11),
                                       fg_color="#05070c", text_color="#c8d2e0",
                                       wrap="none")
        self.console.grid(row=1, column=0, sticky="nsew", padx=12, pady=(2, 6))
        self.console.configure(state="disabled")

        self.error_banner = ctk.CTkLabel(card, text="", font=theme.font(12),
                                         text_color=theme.COL["danger"], anchor="w",
                                         justify="left", wraplength=900)
        self.error_banner.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))

        cmd = ctk.CTkFrame(card, fg_color="transparent")
        cmd.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        cmd.grid_columnconfigure(0, weight=1)
        self.cmd_entry = ctk.CTkEntry(cmd, height=38,
                                      placeholder_text="Type a console command, e.g.  say hello   /   op <name>")
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self._send())
        ghost_button(cmd, "Send", self._send, width=84, height=38).grid(row=0, column=1)

    def _build_actions(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        bar.grid_columnconfigure(0, weight=1)
        self.stop_btn = ghost_button(bar, "Stop (saves world)", self._stop, width=170, height=42)
        self.stop_btn.grid(row=0, column=1, padx=(0, 8))
        self.restart_btn = ghost_button(bar, "Restart", self._restart, width=110, height=42)
        self.restart_btn.grid(row=0, column=2, padx=(0, 8))
        self.kill_btn = danger_button(bar, "Kill", self._kill, width=90, height=42)
        self.kill_btn.grid(row=0, column=3, padx=(0, 8))
        self.retry_btn = ghost_button(bar, "Open again", self._reopen, width=120, height=42)
        self.retry_btn.grid(row=0, column=4)
        self.retry_btn.grid_remove()

    # ------------------------------------------------------------------ events
    def _on_event(self, event, session=None):
        if self._closed:
            return
        try:
            self.after(0, self._redraw)
        except Exception:
            pass

    def _tick(self):
        if self._closed:
            return
        try:
            self._redraw()
        except Exception:
            return
        self.after(1000, self._tick)

    def _redraw(self):
        s = self.session
        if self._closed or not self.winfo_exists():
            return
        color_key, text_color = _STATUS_COLORS.get(s.status, ("bg3", "text"))
        self.status_pill.configure(text=s.status,
                                   fg_color=theme.COL.get(color_key, theme.COL["bg3"]),
                                   text_color=("#04140b" if color_key in ("good", "warn", "accent")
                                               else theme.COL.get(text_color, theme.COL["text"])))
        snap = s.resource_snapshot()
        used = snap.get("rss_bytes")
        alloc_bytes = max(1, s.ram_mb) * 1024 * 1024
        m = self.meters["mem"]
        m["value"].configure(text=resources.human_bytes(used) if used else "\u2014")
        if m["bar"] is not None:
            frac = min(1.0, (used or 0) / float(alloc_bytes))
            try:
                m["bar"].set(frac)
            except Exception:
                pass
            over = frac > 1.0 or (used and used > alloc_bytes * 0.92)
            # keep it to one line: the card is ~200px wide and the old
            # "...  •  JVM process memory" tail was being clipped mid-word
            m["sub"].configure(text="%d%% of %d MB allocated"
                               % (int(round(100.0 * (used or 0) / alloc_bytes)), s.ram_mb),
                               text_color=(theme.COL["warn"] if over else theme.COL["text_dim"]))
        cpu = snap.get("cpu_percent")
        self.meters["cpu"]["value"].configure(text=("--" if cpu is None else "%.0f%%" % cpu))
        cores = 1
        try:
            cores = max(1, os.cpu_count() or 1)
        except Exception:
            pass
        # CPU is a share of ONE core (100% = one core busy), so say that instead
        # of the meaningless "of ~200 cores" the old text produced on a 2-core box.
        self.meters["cpu"]["sub"].configure(
            text=("of %d core" % cores) + ("" if cores == 1 else "s") + "  \u00b7  100% = 1 core"
            if cores > 1 else "of 1 core")
        self.meters["players"]["value"].configure(text=str(snap.get("players") or 0))
        self.meters["players"]["sub"].configure(text="online now")
        self.meters["uptime"]["value"].configure(
            text=resources.format_duration(snap.get("uptime")))
        self.meters["uptime"]["sub"].configure(
            text=("restarted %d\u00d7" % s.restarts) if s.restarts else "since start")

        warn = snap.get("lag_warnings") or 0
        self.warn_lbl.configure(text=("%d 'can't keep up' warnings" % warn) if warn else "")

        if s.public_address:
            self.net_lbl.configure(
                text="Friends join at  %s   \u2022   via %s" % (
                    s.public_address, getattr(s.tunnel, "active_provider", "") or "tunnel"),
                text_color=theme.COL["good"])
        elif s.claim_url:
            self.net_lbl.configure(text="Tunnel needs a one-time claim - open the "
                                        "link on the Servers page.",
                                   text_color=theme.COL["warn"])
        elif s.status in ("starting", "running") and s.tunnel_message:
            self.net_lbl.configure(text=s.tunnel_message, text_color=theme.COL["text_dim"])
        elif s.status in ("stopped", "crashed"):
            self.net_lbl.configure(text="Tunnel closed with the server.",
                                   text_color=theme.COL["text_faint"])

        # console: append whatever is new (the tailer keeps session log_lines)
        if s.proc is not None:
            lines = list(s.proc.log_lines)
            if len(lines) < self._rows_shown:
                self._rows_shown = 0
                self.console.configure(state="normal")
                self.console.delete("1.0", "end")
            for line in lines[self._rows_shown:]:
                self._append(line)
            self._rows_shown = len(lines)

        if s.error:
            self.error_banner.configure(text=s.error)
        elif s.status == "running":
            self.error_banner.configure(text="")

        running = s.is_running() or s.status in ("starting", "stopping")
        for btn, key in ((self.stop_btn, "Stop (saves world)"), (self.restart_btn, "Restart")):
            try:
                btn.configure(state=("normal" if running else "disabled"))
            except Exception:
                pass
        try:
            self.cmd_entry.configure(
                state=("normal" if running else "disabled"),
                placeholder_text=("Type a console command, e.g.  say hello   /   op <name>"
                                  if running else "The server is not running"))
        except Exception:
            pass
        if s.status in ("stopped", "crashed"):
            self.kill_btn.grid_remove()
            self.stop_btn.grid_remove()
            self.restart_btn.grid_configure()
            self.retry_btn.grid_configure()
        else:
            self.kill_btn.grid()
            self.stop_btn.grid()
            self.retry_btn.grid_remove()

    def _append(self, line):
        try:
            self.console.configure(state="normal")
            self.console.insert("end", line + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        except Exception:
            pass

    # ---------------------------------------------------------------- actions
    def _send(self):
        text = self.cmd_entry.get()
        if not text.strip():
            return
        self.cmd_entry.delete(0, "end")
        if not self.session.send(text):
            self._append("[not sent - the server is not running]")

    def _stop(self):
        self.session.stop()

    def _restart(self):
        self.session.restart()

    def _kill(self):
        self.session.kill()

    def _reopen(self):
        # finished session: start it again from here
        self.session.restart()

    def _copy_address(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.session.join_address())
            self.copy_btn.configure(text="Copied!")
            self.after(1600, lambda: self.copy_btn.configure(text="Copy join address"))
        except Exception:
            pass

    def _open_log(self):
        path = self.session.log_path
        if not path or not os.path.exists(path):
            return
        try:
            import subprocess
            import sys
            if sys.platform == "win32":
                os.startfile(os.path.dirname(path))            # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", os.path.dirname(path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    def _on_close_request(self):
        # Detach only: the session keeps running and stays in the Servers panel.
        self._closed = True
        try:
            self.session.remove_listener(self._on_event)
        except Exception:
            pass
        self.session._window = None
        self.destroy()
