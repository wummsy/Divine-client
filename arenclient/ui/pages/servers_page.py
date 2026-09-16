"""Servers page: host a server from an instance, or join a friend's by code.

Host flow:
  1. pick one of your instances (its mods + world become the server)
  2. Divine downloads the matching server jar, copies the mods, starts it
  3. the playit.gg tunnel gives a public address; we register it and show a
     short JOIN CODE the host can share
  4. a live console (output + command input), a properties editor, and an
     "invite friends" panel are all right there

Join flow:
  enter a friend's code (or accept an invite); Divine looks it up and points the
  matching instance at that address so the next launch connects straight in.
"""
import threading
import webbrowser

import customtkinter as ctk

from ...core import resources
from ...core import social
from ...core import server_host
from ...core import tunnel as tunnel_mod
from ...core import launcher
from .. import theme
from ..widgets import flow_label
from ..widgets import Card, PageFrame, accent_button, danger_button, ghost_button, scroll_frame


class ServersPage(PageFrame):
    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(22, 6))
        header.grid_columnconfigure(2, weight=1)
# the page name lives in the bar above; repeating it here reads as a mistake
        self.tab_host = ghost_button(header, "Host a server", self._show_host,
                                     width=140, height=36)
        self.tab_host.grid(row=0, column=3, padx=(0, 8))
        self.tab_join = ghost_button(header, "Join a server", self._show_join,
                                     width=140, height=36)
        self.tab_join.grid(row=0, column=4)

        self.body = ctk.CTkFrame(self)
        self.body.grid(row=1, column=0, sticky="nsew", padx=26, pady=(6, 20))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self._mode = "host"
        self._session = None

    # ------------------------------------------------------------------ tabs
    def on_show(self):
        # the session list is owned by app.servers, so anything that is still
        # running (even from before this window opened) shows up here
        self._show_host() if self._mode == "host" else self._show_join()

    def on_server_change(self):
        """Called by the app when a session is added, changes status or ends."""
        if self._mode != "host":
            return
        try:
            if self._running_holder is not None and self._running_holder.winfo_exists():
                self._render_running()
        except Exception:
            pass

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _tab_style(self, active):
        self.tab_host.configure(
            fg_color=theme.COL["accent"] if active == "host" else theme.COL["bg3"],
            text_color="#04121a" if active == "host" else theme.COL["text"])
        self.tab_join.configure(
            fg_color=theme.COL["accent"] if active == "join" else theme.COL["bg3"],
            text_color="#04121a" if active == "join" else theme.COL["text"])

    def _show_host(self):
        self._mode = "host"
        self._tab_style("host")
        self._clear_body()
        self._build_host_setup()
        self._build_running_list()

    def _show_join(self):
        self._mode = "join"
        self._tab_style("join")
        self._clear_body()
        self._build_join()

    # -------------------------------------------------------------- host setup
    def _host_card_title(self, card, title, sub):
        ctk.CTkLabel(card, text=title, font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 2))
        flow_label(card, text=sub, font=theme.font(12),
                     text_color=theme.COL["text_dim"], anchor="w", justify="left").grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))

    def _build_host_setup(self):
        card = Card(self.body)
        card.grid(row=0, column=0, sticky="new", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        self._host_card = card
        self._host_row = 2

        self.app.instances.load()
        insts = self.app.instances.instances
        if not insts:
            self._host_card_title(card, "HOST A SERVER",
                                  "You have no instances yet. Create one on the "
                                  "Instances page first.")
            return
        if not social.is_linked():
            self._host_card_title(
                card, "HOST A SERVER",
                "You can host right away - friends just need the address. Connect "
                "Discord on the Play screen to also send invites and share a short code.")

        grid = ctk.CTkFrame(card)
        grid.grid(row=self._host_row, column=0, sticky="ew", padx=20, pady=(0, 6))
        self._host_row += 1
        for c in range(3):
            grid.grid_columnconfigure(c, weight=(3 if c == 0 else 1))

        def field(col, label, widget):
            ctk.CTkLabel(grid, text=label, font=theme.font(11, "bold"),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 12, 0))
            widget.grid(row=1, column=col, sticky="ew", padx=(0 if col == 0 else 12), pady=(4, 0))

        self._inst_names = ["%s  (%s)" % (i.name, i.mc_version) for i in insts]
        self._host_menu = ctk.CTkOptionMenu(
            grid, values=self._inst_names, height=40, font=theme.font(13, "bold"),
            corner_radius=10, fg_color=theme.COL["bg3"],
            button_color=theme.COL["bg_hover"], button_hover_color=theme.COL["accent"],
            dropdown_fg_color=theme.COL["bg3"], dropdown_hover_color=theme.COL["bg_hover"])
        field(0, "INSTANCE (its version, mods and world become the server)", self._host_menu)

        self._ram_entry = ctk.CTkEntry(grid, height=40, font=theme.font(13, "bold"))
        self._ram_entry.insert(0, str(self.app.config_store.get("ram_mb", 2048)))
        field(1, "MEMORY (MB)", self._ram_entry)

        self._tunnel_menu = ctk.CTkOptionMenu(
            grid, values=["auto", "bore (no setup)", "playit.gg", "none (LAN only)"],
            height=40, font=theme.font(13, "bold"), corner_radius=10,
            fg_color=theme.COL["bg3"], button_color=theme.COL["bg_hover"],
            button_hover_color=theme.COL["accent"], dropdown_fg_color=theme.COL["bg3"],
            dropdown_hover_color=theme.COL["bg_hover"])
        self._tunnel_menu.set(self._provider_from_config())
        field(2, "PUBLIC ADDRESS", self._tunnel_menu)

        actions = ctk.CTkFrame(card)
        actions.grid(row=self._host_row, column=0, sticky="ew", padx=20, pady=(14, 18))
        actions.grid_columnconfigure(0, weight=1)
        self._host_status = flow_label(actions, text="", font=theme.font(12),
                                         text_color=theme.COL["accent"], anchor="w", justify="left")
        self._host_status.grid(row=0, column=0, sticky="w")
        self._start_btn = accent_button(actions, "\u25B6   Start server", self._start_host,
                                        width=190, height=44)
        self._start_btn.configure(fg_color=theme.COL["good"], hover_color="#63eda0",
                                  text_color="#04140b")
        self._start_btn.grid(row=0, column=1, sticky="e")

    def _provider_from_config(self):
        try:
            p = self.app.config_store.get("tunnel_provider", "auto")
        except Exception:
            p = "auto"
        return {"bore": "bore (no setup)", "playit": "playit.gg",
                "none": "none (LAN only)"}.get(p, "auto")

    def _provider_choice(self):
        text = (self._tunnel_menu.get() or "auto").lower()
        if text.startswith("bore"):
            return "bore"
        if text.startswith("playit"):
            return "playit"
        if text.startswith("none"):
            return "none"
        return "auto"

    def _start_host(self):
        try:
            idx = self._inst_names.index(self._host_menu.get())
        except Exception:
            idx = 0
        inst = self.app.instances.instances[idx]
        try:
            ram = max(1024, int(str(self._ram_entry.get()).strip()))
        except Exception:
            ram = 2048
        provider = self._provider_choice()
        try:
            self.app.config_store.set("tunnel_provider", provider)
            self.app.config_store.save()
        except Exception:
            pass
        try:
            self.app.servers.start(inst, ram_mb=ram, tunnel_provider=provider)
        except Exception as e:
            self._safe_status("Couldn't start: " + str(e))
            return
        self._safe_status("Starting in its own window - closing that window keeps "
                          "the server up.")
        self._show_host()

    # ------------------------------------------------------------ running list
    def _build_running_list(self):
        wrap = Card(self.body)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(wrap)
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="YOUR SERVERS", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w")
        self._running_note = ctk.CTkLabel(head, text="", font=theme.font(11),
                                          text_color=theme.COL["text_dim"])
        self._running_note.grid(row=0, column=1, sticky="e")
        ghost_button(head, "Clear finished", self._clear_finished, width=130, height=30
                     ).grid(row=0, column=2, padx=(10, 0))

        self._running_holder = scroll_frame(wrap)
        self._running_holder.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 14))
        self._running_holder.grid_columnconfigure(0, weight=1)
        self._row_widgets = {}
        self._render_running()
        self._tick_running()

    def _clear_finished(self):
        try:
            self.app.servers.clear_finished()
        except Exception:
            pass
        self._render_running()

    def _render_running(self):
        holder = getattr(self, "_running_holder", None)
        if holder is None or not holder.winfo_exists():
            return
        for w in holder.winfo_children():
            w.destroy()
        self._row_widgets = {}
        sessions = self.app.servers.all_sessions()
        if not sessions:
            ctk.CTkLabel(holder, text="Nothing hosted right now. Pick an instance "
                         "above and press Start server.", font=theme.font(12),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=0, column=0, sticky="w", padx=8, pady=14)
            return
        for i, s in enumerate(sessions):
            self._session_row(holder, s, i)

    def _session_row(self, holder, s, i):
        row = Card(holder, fg_color=theme.COL["bg3"], corner_radius=14)
        row.grid(row=i, column=0, sticky="ew", padx=4, pady=5)
        row.grid_columnconfigure(1, weight=1)

        status_col = {"running": theme.COL["good"], "starting": theme.COL["warn"],
                      "stopping": theme.COL["warn"], "crashed": theme.COL["danger"]
                      }.get(s.status, theme.COL["bg_hover"])
        badge = ctk.CTkLabel(row, text="\u25CF", font=theme.font(16),
                             text_color=status_col)
        badge.grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=12)

        left = ctk.CTkFrame(row)
        left.grid(row=0, column=1, rowspan=2, sticky="w")
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text=s.name + "   \u00b7   MC " + s.mc_version,
                     font=theme.font(14, "bold"), text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", pady=(10, 0))
        vals = ctk.CTkLabel(left, text="", font=theme.font(11),
                            text_color=theme.COL["text_dim"], anchor="w", justify="left")
        vals.grid(row=1, column=0, sticky="w", pady=(0, 10))

        btns = ctk.CTkFrame(row)
        btns.grid(row=0, column=2, rowspan=2, padx=(8, 12))
        accent_button(btns, "Open", lambda sid=s.id: self._open_window(sid),
                      width=76, height=32).grid(row=0, column=0, padx=(0, 6))
        ghost_button(btns, "Stop", lambda sid=s.id: self._act(sid, "stop"),
                     width=64, height=32).grid(row=0, column=1, padx=(0, 6))
        ghost_button(btns, "Restart", lambda sid=s.id: self._act(sid, "restart"),
                     width=76, height=32).grid(row=0, column=2, padx=(0, 6))
        danger_button(btns, "Kill", lambda sid=s.id: self._act(sid, "kill"),
                      width=60, height=32).grid(row=0, column=3)
        ghost_button(btns, "Settings", lambda sid=s.id: self._open_settings(sid),
                     width=84, height=32).grid(row=1, column=0, columnspan=2,
                                               pady=(6, 8), sticky="ew")
        ghost_button(btns, "Invite", lambda sid=s.id: self._open_invite(sid),
                     width=84, height=32).grid(row=1, column=2, columnspan=2,
                                               pady=(6, 8), sticky="ew")
        if s.status in ("running", "starting") and not s.public_address:
            # a tunnel that never came up is otherwise only fixable by restarting the
            # whole server, which is a lot of asking when the world is loaded
            ghost_button(btns, "Retry tunnel", lambda sid=s.id: self._act(sid, "retry_tunnel"),
                         width=84, height=32).grid(row=1, column=4, padx=(6, 0),
                                                   pady=(6, 8), sticky="ew")
        self._row_widgets[s.id] = {"badge": badge, "vals": vals, "session": s}

    def _tick_running(self):
        """Refresh the live numbers in each row without rebuilding the widgets."""
        if self._mode != "host" or not hasattr(self, "_running_holder"):
            return
        try:
            if not self._running_holder.winfo_exists():
                return
        except Exception:
            return
        alive = 0
        for sid, widgets in list(self._row_widgets.items()):
            s = widgets.get("session")
            if s is None:
                continue
            if s.is_running():
                alive += 1
            snap = s.resource_snapshot()
            used = snap.get("rss_bytes")
            mem = ("%s / %d MB" % (resources.human_bytes(used), s.ram_mb)) if used else "\u2014"
            cpu = snap.get("cpu_percent")
            parts = [mem,
                     ("cpu %d%%" % round(cpu)) if cpu is not None else "cpu \u2014",
                     "%d player%s" % (snap.get("players") or 0,
                                      "" if (snap.get("players") or 0) == 1 else "s"),
                     resources.format_duration(snap.get("uptime"))]
            if s.public_address:
                parts.append(s.public_address)
            elif s.status in ("running", "starting"):
                parts.append((s.tunnel_message or "opening tunnel\u2026")[:48])
            try:
                widgets["vals"].configure(text="   \u00b7   ".join(parts))
                col = {"running": theme.COL["good"], "starting": theme.COL["warn"],
                       "stopping": theme.COL["warn"],
                       "crashed": theme.COL["danger"]}.get(s.status, theme.COL["bg_hover"])
                widgets["badge"].configure(text_color=col)
            except Exception:
                pass
        try:
            self._running_note.configure(
                text=("%d running" % alive) if alive else "nothing running")
        except Exception:
            pass
        self.after(1000, self._tick_running)

    # -------------------------------------------------------------- operations
    def _get(self, session_id):
        return self.app.servers.get(session_id)

    def _open_window(self, session_id):
        s = self._get(session_id)
        if not s:
            return
        win = getattr(s, "_window", None)
        if win is not None:
            try:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            except Exception:
                pass
        self.app.servers.reopen_window(s)

    def _act(self, session_id, what):
        s = self._get(session_id)
        if not s:
            return
        try:
            getattr(s, what)()
        except Exception as e:
            self._safe_status("That didn't work: " + str(e)[:120])
        if what == "kill":
            self._render_running()

    # ------------------------------------------------------- settings / invite
    def _open_settings(self, session_id):
        s = self._get(session_id)
        if not s:
            return
        win = ctk.CTkToplevel(self)
        win.title("Server settings - " + s.name)
        win.geometry("520x620")
        win.configure(fg_color=theme.COL["bg"])
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)
        body = scroll_frame(win)
        body.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 0))
        body.grid_columnconfigure(1, weight=1)
        props = server_host.read_properties(s.instance)
        widgets = {}
        fields = [("motd", "MOTD", "entry"),
                  ("max-players", "Max players", "entry"),
                  ("gamemode", "Game mode", ["survival", "creative", "adventure", "spectator"]),
                  ("difficulty", "Difficulty", ["peaceful", "easy", "normal", "hard"]),
                  ("pvp", "PvP", ["true", "false"]),
                  ("online-mode", "Online mode", ["true", "false"]),
                  ("white-list", "Whitelist", ["true", "false"]),
                  ("view-distance", "View distance", "entry"),
                  ("server-port", "Port", "entry"),
                  ("level-name", "World name", "entry"),
                  ("level-seed", "Seed", "entry")]
        for r, (key, label, kind) in enumerate(fields):
            ctk.CTkLabel(body, text=label, font=theme.font(12),
                         text_color=theme.COL["text_dim"], anchor="w"
                         ).grid(row=r, column=0, sticky="w", padx=(6, 12), pady=4)
            val = str(props.get(key, ""))
            if kind == "entry":
                w = ctk.CTkEntry(body, height=32, fg_color=theme.COL["bg3"],
                                 border_color=theme.COL["border"])
                w.insert(0, val)
            else:
                w = ctk.CTkOptionMenu(body, values=kind, height=32,
                                      fg_color=theme.COL["bg3"],
                                      button_color=theme.COL["bg_hover"])
                w.set(val if val in kind else kind[0])
            w.grid(row=r, column=1, sticky="ew", pady=4)
            widgets[key] = w
        note = ctk.CTkLabel(win, text="Changes apply on the next restart of the server.",
                            font=theme.font(11), text_color=theme.COL["text_faint"])
        note.grid(row=1, column=0, sticky="w", padx=20, pady=(2, 0))
        bar = ctk.CTkFrame(win)
        bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 16))
        bar.grid_columnconfigure(0, weight=1)
        ghost_button(bar, "Close", win.destroy, width=100, height=38).grid(row=0, column=1, padx=(8, 0))

        def save():
            vals = {k: w.get() for k, w in widgets.items()}
            port = str(vals.get("server-port", "")).strip()
            if port:
                try:
                    if not 1024 <= int(port) <= 65535:
                        raise ValueError
                except ValueError:
                    note.configure(text="Port must be a number between 1024 and 65535.",
                                   text_color=theme.COL["danger"])
                    return
            server_host.write_properties(s.instance, vals)
            note.configure(text="Saved. Restart the server to apply.",
                           text_color=theme.COL["good"])
        accent_button(bar, "Save", save, width=110, height=38).grid(row=0, column=2)

    def _open_invite(self, session_id):
        """The window that hands an address to a friend.

        It used to print ``join_address()`` unconditionally, which is how a broken
        tunnel became a broken invite: with no public address it said
        ``localhost:25567`` (useful to nobody across the internet), and when the agent
        only managed to say something about its own socket the launcher happily showed
        that instead. So the card now states which of the three cases it is in - an
        address, a playit link waiting to be approved, or nothing yet - and gives the
        LAN address separately, because that one is real but only on this network.
        """
        s = self._get(session_id)
        if not s:
            return
        win = ctk.CTkToplevel(self)
        win.title("Invite friends - " + s.name)
        win.geometry("460x520")
        win.configure(fg_color=theme.COL["bg"])
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)
        self._invite_win = win

        top = Card(win)
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="SHARE THIS ADDRESS", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"]).grid(row=0, column=0,
                                                              pady=(12, 2), sticky="w")
        addr_lbl = flow_label(top, text="\u2026", font=theme.title_font(20),
                                text_color=theme.COL["accent"], anchor="w", justify="left")
        addr_lbl.grid(row=1, column=0, sticky="w")
        note = flow_label(top, text="", font=theme.font(11),
                            text_color=theme.COL["text_dim"], anchor="w", justify="left")
        note.grid(row=2, column=0, sticky="w", pady=(3, 4))
        share = {"text": ""}          # what the Copy button puts on the clipboard
        btns = ctk.CTkFrame(top)
        btns.grid(row=3, column=0, sticky="ew", padx=14, pady=(2, 12))
        copy_btn = ghost_button(btns, "Copy", lambda: self._copy_text(share["text"]),
                                width=90, height=30)
        copy_btn.grid(row=0, column=0, padx=(0, 8))
        retry_btn = ghost_button(btns, "Retry tunnel",
                                 lambda: self._act(s.id, "retry_tunnel"),
                                 width=120, height=30)
        retry_btn.grid(row=0, column=1)

        def paint():
            if not win.winfo_exists():
                return
            public = (s.public_address or "").strip()
            lan = server_host.lan_ip()
            lan_line = ("%s:%d" % (lan, s.port)) if lan else ("port %d on this PC" % s.port)
            if public:
                addr_lbl.configure(text=public, text_color=theme.COL["accent"])
                note.configure(text="Java Edition \u2192 Multiplayer \u2192 Add server, and it "
                                    "must be on MC " + s.mc_version + ". Your network only: "
                                    + lan_line + ".", text_color=theme.COL["text_dim"])
                share["text"] = public
                copy_btn.configure(state="normal")
                # same label either way: a bore address is random, so "retry" is also
                # how you get a fresh one after the relay drops - the card repaints
            elif getattr(s, "claim_url", None):
                addr_lbl.configure(text="Waiting on playit", text_color=theme.COL["warn"])
                note.configure(text="Open this link once and approve the tunnel, then press "
                                    "Retry tunnel:\n" + s.claim_url,
                               text_color=theme.COL["text_dim"])
                share["text"] = s.claim_url
                copy_btn.configure(state="normal")
            elif s.status in ("running", "starting"):
                addr_lbl.configure(text="No public address yet", text_color=theme.COL["warn"])
                note.configure(text=(s.tunnel_message or "opening the tunnel\u2026")
                               + "  \u00b7  LAN only for now: " + lan_line,
                               text_color=theme.COL["text_dim"])
                share["text"] = ""
                copy_btn.configure(state="disabled")
            else:
                addr_lbl.configure(text="Server is not running", text_color=theme.COL["text_faint"])
                note.configure(text="Start it from the Servers list; the address appears here "
                                    "once the tunnel is up.", text_color=theme.COL["text_dim"])
                share["text"] = ""
                copy_btn.configure(state="disabled")
            win.after(1000, paint)

        win.after(80, paint)
        holder = scroll_frame(win)
        holder.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))
        holder.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(holder, text="Loading friends\u2026", font=theme.font(12),
                     text_color=theme.COL["text_faint"]).grid(row=0, column=0, sticky="w", padx=6)

        def load():
            try:
                data = social.list_friends(self.app.config_store)
                friends = data.get("friends", [])
            except Exception:
                friends = []
            self.after(0, lambda: render(friends))

        def render(friends):
            for w in holder.winfo_children():
                w.destroy()
            if not friends:
                ctk.CTkLabel(holder, text="No friends yet - add them on the Play screen.",
                             font=theme.font(12), text_color=theme.COL["text_faint"]
                             ).grid(row=0, column=0, sticky="w", padx=6, pady=10)
                return
            for i, f in enumerate(friends):
                r = ctk.CTkFrame(holder)
                r.grid(row=i, column=0, sticky="ew", pady=3)
                r.grid_columnconfigure(0, weight=1)
                dot = "\u25CF " if f.get("online") else "\u25CB "
                ctk.CTkLabel(r, text=dot + f.get("username", "?"), font=theme.font(12, "bold"),
                             text_color=theme.COL["text"], anchor="w"
                             ).grid(row=0, column=0, sticky="w", padx=6)
                ghost_button(r, "Invite", lambda fid=f.get("id"): invite(fid),
                             width=76, height=30).grid(row=0, column=1, padx=(0, 4))

        def invite(fid):
            def work():
                try:
                    code = self._ensure_code(s)
                    social.invite_to_server(self.app.config_store, code, [fid])
                    self.after(0, lambda: self._copy_text("Invite sent."))
                except Exception as e:
                    self.after(0, lambda: self._copy_text("Invite failed: " + str(e)[:80]))
            threading.Thread(target=work, daemon=True).start()

        threading.Thread(target=load, daemon=True).start()

    def _ensure_code(self, session):
        """Register the running server with the social service, once."""
        code = getattr(session, "code", None)
        if code:
            return code
        try:
            r = social.host_server(self.app.config_store, session.name,
                                    session.public_address or "",
                                    session.mc_version, session.loader)
            code = r.get("code")
        except Exception:
            code = None
        session.code = code
        return code

    def _copy_text(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._toast("Copied to clipboard")
        except Exception:
            pass

    def _safe_status(self, msg):
        try:
            self._host_status.configure(text=msg, text_color=theme.COL["accent"])
        except Exception:
            pass

    # ------------------------------------------------------------------- join
    def _build_join(self):
        wrap = ctk.CTkFrame(self.body)
        wrap.grid(row=0, column=0, sticky="new")
        wrap.grid_columnconfigure(0, weight=1)

        card = Card(wrap)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="JOIN BY CODE", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 2))
        flow_label(card, text="Enter a friend's server code. Divine points a "
                     "matching instance at it, then launch to connect.",
                     font=theme.font(12), text_color=theme.COL["text_dim"],
                     anchor="w", justify="left").grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        row = ctk.CTkFrame(card)
        row.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 6))
        row.grid_columnconfigure(0, weight=1)
        self._join_entry = ctk.CTkEntry(row, placeholder_text="e.g. 5H2QE6",
                                        height=44, font=theme.font(16, "bold"))
        self._join_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        accent_button(row, "Find server", self._do_join, height=44, width=140
                      ).grid(row=0, column=1)
        self._join_status = flow_label(card, text="", font=theme.font(12),
                                         text_color=theme.COL["accent"], anchor="w",
                                         justify="left")
        self._join_status.grid(row=3, column=0, sticky="w", padx=20, pady=(6, 18))

        inv = Card(wrap)
        inv.grid(row=1, column=0, sticky="ew")
        inv.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(inv, text="INVITES", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        self._invites_holder = ctk.CTkFrame(inv)
        self._invites_holder.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 14))
        self._invites_holder.grid_columnconfigure(0, weight=1)
        if social.is_linked():
            ctk.CTkLabel(self._invites_holder, text="Loading\u2026", font=theme.font(12),
                         text_color=theme.COL["text_faint"]).grid(row=0, column=0, sticky="w", padx=8)
            threading.Thread(target=self._load_invites, daemon=True).start()
        else:
            ctk.CTkLabel(self._invites_holder, text="Connect Discord to receive invites.",
                         font=theme.font(12), text_color=theme.COL["text_faint"]
                         ).grid(row=0, column=0, sticky="w", padx=8)

    def _load_invites(self):
        try:
            invites = social.list_server_invites(self.app.config_store)
        except Exception:
            invites = []
        self.after(0, lambda: self._render_invites(invites))

    def _render_invites(self, invites):
        holder = self._invites_holder
        for w in holder.winfo_children():
            w.destroy()
        if not invites:
            ctk.CTkLabel(holder, text="No invites right now.", font=theme.font(12),
                         text_color=theme.COL["text_faint"]).grid(row=0, column=0,
                                                                  sticky="w", padx=8)
            return
        for i, inv in enumerate(invites):
            c = Card(holder, fg_color=theme.COL["bg3"])
            c.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
            c.grid_columnconfigure(0, weight=1)
            title = f"{inv['name']}   ({inv['mc_version']} \u00b7 " \
                    f"{'Fabric' if inv['loader'] == 'fabric' else 'Vanilla'})"
            ctk.CTkLabel(c, text=title, font=theme.font(13, "bold"),
                         text_color=theme.COL["text"], anchor="w"
                         ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
            state = "online" if inv["status"] == "online" else "offline"
            ctk.CTkLabel(c, text=f"from {inv['from']}  \u00b7  {state}  \u00b7  code {inv['code']}",
                         font=theme.font(11), text_color=theme.COL["text_dim"], anchor="w"
                         ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
            btns = ctk.CTkFrame(c)
            btns.grid(row=0, column=1, rowspan=2, padx=12)
            accent_button(btns, "Join", lambda code=inv["code"]: self._join_code(code),
                          width=80, height=34).grid(row=0, column=0, padx=(0, 6))
            ghost_button(btns, "Dismiss",
                         lambda code=inv["code"]: self._dismiss_invite(code),
                         width=80, height=34).grid(row=0, column=1)

    def _dismiss_invite(self, code):
        def work():
            try:
                social.dismiss_server_invite(self.app.config_store, code)
            except Exception:
                pass
            self.after(0, self._load_invites)
        threading.Thread(target=work, daemon=True).start()

    def _do_join(self):
        code = self._join_entry.get().strip().upper()
        self._join_code(code)

    def _join_code(self, code):
        if not code:
            return
        self._set_join_status("Looking up " + code + "\u2026", theme.COL["accent"])
        def work():
            try:
                info = social.join_server(self.app.config_store, code)
            except Exception as e:
                self.after(0, lambda: self._set_join_status(str(e), theme.COL["danger"]))
                return
            self.after(0, lambda: self._apply_join(info))
        threading.Thread(target=work, daemon=True).start()

    def _apply_join(self, info):
        addr = info.get("address") or ""
        name = info.get("name", "Server")
        if not addr:
            self._set_join_status(
                "Found '" + name + "', but the host's public address isn't ready "
                "yet. Try again in a moment.", theme.COL["warn"])
            return
        # save the target so a matching instance can connect; also add to the
        # multiplayer server list of the best-matching instance
        host, _, port = addr.partition(":")
        self._save_join_target(info, host, port or "25565")
        self._set_join_status(
            "Ready! '" + name + "' added to your Minecraft server list. Launch a "
            + info.get("mc_version", "") + " instance and it'll be in Multiplayer.",
            theme.COL["good"])

    def _save_join_target(self, info, host, port):
        """Write the address into a matching instance's servers.dat-style list.

        Minecraft reads servers from servers.dat (NBT). Rather than depend on an
        NBT library, we drop a small marker file the instance launch can turn
        into a direct-connect, and also remember the last joined address.
        """
        self.app.config_store.set("last_join_address", (host + ":" + port))
        self.app.config_store.set("last_join_name", info.get("name", "Server"))
        self.app.config_store.save()
        try:
            self._write_servers_dat(info, host, int(port))
        except Exception:
            pass

    def _write_servers_dat(self, info, host, port):
        import os
        # pick the instance whose version matches; else the first
        self.app.instances.load()
        insts = self.app.instances.instances
        target = None
        for i in insts:
            if i.mc_version == info.get("mc_version"):
                target = i
                break
        if target is None and insts:
            target = insts[0]
        if target is None:
            return
        try:
            from nbtlib import File, Compound, List, String
            path = os.path.join(target.game_dir, "servers.dat")
            entry = Compound({"name": String("Divine: " + info.get("name", "Server")),
                              "ip": String(host + ":" + str(port))})
            if os.path.exists(path):
                f = File.load(path, gzipped=False)
                servers = f["servers"]
            else:
                f = File(Compound({"servers": List[Compound]([])}))
                f.gzipped = False
                servers = f["servers"]
            servers.insert(0, entry)
            f.save(path, gzipped=False)
        except Exception:
            pass

    def _set_join_status(self, msg, color):
        try:
            self._join_status.configure(text=msg, text_color=color)
        except Exception:
            pass

    # ------------------------------------------------------------------ util
    def _notice(self, text):
        card = Card(self.body)
        card.grid(row=0, column=0, sticky="new")
        flow_label(card, text=text, font=theme.font(13),
                     text_color=theme.COL["text_dim"], justify="left"
                     ).grid(row=0, column=0, sticky="ew", padx=20, pady=20)

    def _toast(self, text):
        # lightweight status echo into whichever status label exists
        if hasattr(self, "_host_status") and self._host_status.winfo_exists():
            self._host_status.configure(text=text, text_color=theme.COL["good"])
