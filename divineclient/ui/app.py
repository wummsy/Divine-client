"""Main Divine Client application window: a sidebar and one page.

    [ sidebar ]   [ header + page ]

The sidebar (``ui.nav.SideNav``) is fixed width and flat: logo, the account you are using
(press it to switch), the pages, Settings at the bottom, the update pill and the version.
It used to be two rails that slid in and out on hover; that was taken out because a panel
that animates its width while the middle column reflows looks broken on a remote display,
and because a launch button in a rail nobody can see is worse than no launch button.

Everything the pages need is created before the window is shown, and the loading screen
(``ui.loading``) covers it with real stage weights. One deliberate rule in here: nothing
in ``__init__`` waits on the network. The version lists, the update check and the friends
refresh all run in the background, because a launcher that opens after DNS times out feels
broken even when it is only being polite.
"""
import hashlib
import os
import sys
import threading
import time
import tkinter as tk

import customtkinter as ctk

from .. import __version__, paths
from ..core.config import Config
from ..core.accounts import AccountStore
from ..core.instances import InstanceManager
from ..core import launcher, updater
from ..core.server_sessions import ServerSessionManager
from . import anim, theme
from . import post as _post          # thread-safe after(); installed below
from .widgets import Gradient, flow_label, load_ctk_image
from .launchflow import LaunchFlow
from .loading import Loading
from .nav import SideNav
from .pages.home import HomePage
from .pages.instances_page import InstancesPage
from .pages.servers_page import ServersPage
from .pages.accounts_page import AccountsPage
from .pages.settings_page import SettingsPage
from .pages.about_page import AboutPage

ctk.set_appearance_mode("dark")

# Must happen before a single widget exists: it makes widget.after() safe to call from the
# launcher's worker threads, which is how version lists, news, the update download and the
# loading screen's stages reach the UI at all. See ui/post.py.
_post.install()

# The Servers tab is unfinished work that people keep finding and reporting as a bug, so
# it now hides behind a code: anyone who wants it types the allowance code and keeps it for
# good. Only the *hash* of the code is in the binary - a plain string in a packed exe is
# readable with ``strings`` and the gate would be decorative.
SERVERS_CODE_SHA256 = "f20ea98d01226ca251ff1ae1afca8b36bc86e0f34c569b4d2aef2990a087a667"

# Presence is a courtesy: it must never make the launcher wait, so the normal report
# gets a short timeout and a thread that nobody joins.
_PRESENCE_TIMEOUT = 8
LOCKED_TABS = {"servers": "Servers is still work in progress. If you have the allowance "
                          "code, enter it to open the tab."}


def code_ok(text):
    """Does *text* match the Servers allowance code?

    Trimmed and lower-cased first, because the code gets pasted out of a chat message and
    one stray space or capital should not read as "wrong code". The comparison is on a
    SHA-256 so the literal never sits in the binary in plain text.
    """
    got = hashlib.sha256((text or "").strip().lower().encode("utf-8")).hexdigest()
    return got == SERVERS_CODE_SHA256


_code_ok = code_ok      # internal name kept for the dialog's call site


class DivineApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        paths.ensure_dirs()
        _post.start(self)

        # Build the whole UI hidden, behind the loading screen, and reveal it once the
        # slow startup work is done. The window is never shown half-drawn.
        self.withdraw()
        self._splash = None
        self._revealed = False
        self._defender_offer = None
        try:
            self._splash = Loading(self)
        except Exception:
            self._splash = None

        # --- state --------------------------------------------------
        self.config_store = Config()
        # No animation switch: the interface does not animate, and a config key for it
        # would only invite someone to turn back on the thing that broke the panel.
        self.accounts = AccountStore()
        self.instances = InstanceManager()
        self.running_procs = {}     # instance_id -> list[Popen]
        # Hosted servers live here, not in a page: a server keeps running when its
        # window is closed (and when the launcher is closed - see _on_close) until
        # Stop / Restart / Kill is pressed.
        self.servers = ServerSessionManager(self.config_store, app=self)
        self._version_cache = None
        self._fabric_cache = None
        self._update_state = None
        self._update_thread = None

        from ..core.discord_rpc import DiscordPresence
        self.discord = DiscordPresence(
            app_id=self.config_store.get("discord_app_id", ""),
            enabled=bool(self.config_store.get("discord_rpc", True)),
        )
        self.discord.start()
        self.discord.set_idle()

        # --- window -------------------------------------------------
        # The palette is chosen before a single widget is built. Colours are resolved at
        # build time in this UI, so a widget created first would keep the old colours - and
        # Settings > Appearance is the only place that changes it, which rebuilds instead.
        try:
            theme.set_background(self.config_store.get("ui_background",
                                                        theme.DEFAULT_BACKGROUND))
        except Exception:
            pass
        self.title("Divine Client")
        self.geometry("1240x780")
        self.minsize(980, 620)
        self.configure(fg_color=theme.COL["bg"])
        self._set_window_icon()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # the one place launch state lives, so Home, Instances and the sidebar can never
        # show two different answers
        self.flow = LaunchFlow(self)

        self.nav = SideNav(self, self)
        self.nav.grid(row=0, column=0, sticky="nsew")
        self.nav.grid_propagate(False)
        self.nav.configure(width=SideNav.WIDTH)
        self._build_content()
        self.nav.refresh_account()

        self.servers.add_listener(self._on_server_event)

        self.pages = {}
        self._init_pages()
        self.flow.add_display(self)          # so the bar's Play follows the selection
        self._paint_shell()
        theme.auto_pin(self)                 # and keep it pinned across resizes, not just once
        self.flow.restore_selection()
        self.flow.start_polling()
        self.show_page("home")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # the worker owns the stage list from here on; staging anything here would make
        # the bar move backwards on a fast machine
        threading.Thread(target=self._startup_worker, daemon=True).start()
        # Safety net: never leave someone stuck on the loading screen because a network
        # call is slow. It reveals itself, with a line saying what is still pending.
        self.after(7000, self._reveal)

    def _set_window_icon(self):
        """Taskbar/titlebar icon.

        Windows wants the .ico - it is what shows in the taskbar and in Alt-Tab -
        and everything else takes a PhotoImage. Both are optional: a missing asset
        must not stop the window from opening, hence the silence.
        """
        try:
            if sys.platform == "win32":
                ico = paths.resource_path(os.path.join("assets", "icon.ico"))
                if os.path.exists(ico):
                    self.iconbitmap(ico)
                    return
            png = paths.resource_path(os.path.join("assets", "emblem.png"))
            if os.path.exists(png):
                self.iconphoto(False, tk.PhotoImage(file=png))
        except Exception:
            pass

    # --------------------------------------------------------------- startup
    # The loading screen is only honest if each stage is a real piece of work, so the
    # slow part of starting up happens here, in this order, one stage per line. The dwell
    # keeps the bar visible as *progress* instead of a strobe on a fast machine; it is a
    # cap on the animation, never a wait on the network, and the 7 s watchdog in
    # __init__ means a site that does not answer still cannot hold the window shut.
    _STAGE_DWELL = 0.25

    def _startup_worker(self):
        import time
        for key, work in (("java", self._stage_java),
                          ("versions", self._stage_instances),
                          ("manifest", self._stage_manifest),
                          ("mods", self._stage_fabric),
                          ("ready", None)):
            self._splash_stage(key)
            started = time.time()
            if work is not None:
                try:
                    work()
                except Exception:
                    pass          # a missing network is not a reason to not open
            left = self._STAGE_DWELL - (time.time() - started)
            if left > 0:
                time.sleep(left)
        try:
            self.after(0, self._versions_ready)
            self.after(0, self._reveal)
        except Exception:
            pass

    def _stage_java(self):
        """Do we already have a Java to use? Checked, never downloaded, at startup."""
        cfg = self.config_store
        custom = str(cfg.get("custom_java_path", "") or "").strip()
        if custom:
            from ..core import java_runtime
            if not java_runtime.runtime_files_ok(custom):
                cfg.set("custom_java_path", "")      # stale path: fall back to ours
                cfg.save()
            return

    def _stage_instances(self):
        try:
            self.instances.load()
        except Exception:
            pass

    def _stage_manifest(self):
        try:
            self._version_cache = launcher.get_version_list()
        except Exception:
            self._version_cache = []

    def _stage_fabric(self):
        try:
            self._fabric_cache = launcher.get_fabric_supported_versions()
        except Exception:
            self._fabric_cache = set()

    def _splash_stage(self, key, note=""):
        """Say what the launcher is doing, from any thread.

        The queue in ui/post.py is what makes this safe: calling Tk here directly from
        the startup worker is exactly the mistake that used to leave the bar at 0%.
        """
        splash = getattr(self, "_splash", None)
        if splash is None:
            return
        _post.post(lambda: splash.stage(key, note))

    def _reveal(self):
        """Drop the loading screen and show the window. Idempotent."""
        if getattr(self, "_revealed", False):
            return
        self._revealed = True
        splash = getattr(self, "_splash", None)
        self._splash = None
        if splash is not None:
            try:
                splash.finish()
            except Exception:
                pass
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        # only after the window is up: an update check and a friends refresh must not
        # sit between double-clicking the icon and seeing something
        threading.Thread(target=self._update_worker, daemon=True).start()
        self._report_presence("idle")
        self.after(60000, self._presence_beat)
        # and once only, on a real Windows box: the Defender offer. It is a Toplevel, not a
        # modal, and it never touches the Launch path - see defender_offer.maybe_offer.
        self.after(600, self._maybe_defender_offer)

    def _maybe_defender_offer(self):
        """Offer the Windows Defender exclusion the first time the launcher is opened.

        Everything about this is behind a try/except that does nothing: a machine with no
        PowerShell, no Defender, or a half-copied install must still reach the Home page and
        be able to press Launch.
        """
        try:
            from .defender_offer import maybe_offer
            maybe_offer(self)
        except Exception:
            pass

    def _post_status(self, text):
        try:
            self.after(0, lambda: self.set_status(text))
        except Exception:
            pass

    # --------------------------------------------------------------- content
    def _build_content(self):
        """The right-hand side of the window: a title bar, the pages, one status line.

        Every surface here is a solid colour or its own wash, and nothing depends on a
        background showing through it. That is a look decision (Modern-style: flat panels, one
        accent, no wallpaper) and a correctness one at the same time: Tk repaints what it
        knows is dirty, so a transparent container over a painted surface is where stale
        pixels survive - which is exactly what a "glitch on maximize" is.
        """
        # a plain Tk frame, not a CTkFrame, and that is deliberate. CTkFrame paints its fill
        # on a canvas that it `place`s over itself, and a placed window stacks above
        # grid-managed children - which is what left a strip of theme grey across the top of a
        # page after a maximize or a rebuild. A container only has to be a colour, so this is
        # one -colour Tk frame: it cannot cover a child and cannot be sized wrong.
        self.content = tk.Frame(self, bg=theme.COL["bg"])
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        # A header sized by what is in it, never by a number. It used to be `height=60` with
        # `grid_propagate(False)`, which is how the Play button came to hang three pixels past
        # the bottom hairline of the bar on a real window, and how the selected instance's name
        # ended up clipped to one letter by its own button: the bar's height was decided without
        # asking the things inside it, so they simply did not fit. Now the row minimums are the
        # floor and the content decides the rest, and every label in here gets its own cell
        # instead of sharing one with a button.
        bar = tk.Frame(self.content, bg=theme.COL["bg2"],
                       highlightthickness=1, highlightbackground=theme.COL["border_soft"],
                       highlightcolor=theme.COL["border_soft"])
        bar.grid(row=0, column=0, sticky="ew")
        self._bar = bar
        bar.grid_columnconfigure(0, weight=1)
        for _r in range(3):
            bar.grid_rowconfigure(_r, minsize=27)

        titles = ctk.CTkFrame(bar, fg_color="transparent")
        # sticky="ew", not "w": a flow label wrapped to its own allocation only learns the
        # truth if its container is sized by the window rather than hugging it. Hugged, the
        # frame asked for the two-line height the first measurement produced and kept it.
        titles.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(26, 0), pady=(15, 15))
        titles.grid_columnconfigure(0, weight=1, minsize=260)
        # A line above the title that says what the launcher can do right now, so the header is
        # worth the height it takes: "READY" / "LAUNCHING" / "1 GAME RUNNING" is the answer to
        # the only question the top of the window exists to answer.
        self.overline_lbl = ctk.CTkLabel(titles, text="READY", anchor="w", height=16,
                                         font=theme.font(9, "bold"),
                                         text_color=theme.COL["accent"])
        self.overline_lbl.grid(row=0, column=0, sticky="w")
        self.title_lbl = ctk.CTkLabel(titles, text="", anchor="w", height=31,
                                      font=theme.title_font(22),
                                      text_color=theme.COL["text"])
        self.title_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.subtitle_lbl = flow_label(titles, "", height=19, font=theme.font(11),
                                                text_color=theme.COL["text_faint"])
        self.subtitle_lbl.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        # What is selected and whether it can be launched, on the right: the same thing Home
        # shows, because pressing Play from any page should be possible. It is a display of the
        # launch flow like every page is, so it cannot disagree with them. Two boxes, and the
        # instance name sits *above* the button rather than beside it - beside it is what cut it.
        from .widgets import Card, accent_button, ghost_button
        strip = ctk.CTkFrame(bar, fg_color="transparent")
        strip.grid(row=0, column=1, rowspan=3, sticky="e", padx=(16, 24), pady=(11, 11))

        acct_box = Card(strip, fg_color=theme.COL["bg3"], corner_radius=12,
                         border_width=0)
        acct_box.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        acct_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(acct_box, text="SIGNED IN AS", height=14, font=theme.font(8, "bold"),
                     text_color=theme.COL["text_faint"], anchor="e"
                     ).grid(row=0, column=0, sticky="e", padx=(16, 16), pady=(8, 0))
        # whose account this is, read-only. It is a label and not a button on purpose:
        # switching account happens in the sidebar, where pressing something does
        # something; two ways to do one thing is how people end up signed out by accident.
        self.top_account = flow_label(acct_box, text="No account", height=20,
                                      font=theme.font(12, "bold"),
                                      text_color=theme.COL["text_dim"], anchor="e",
                                      justify="right", max_lines=1)
        self.top_account.grid(row=1, column=0, sticky="e", padx=(16, 16), pady=(1, 8))

        play = Card(strip, fg_color=theme.COL["bg3"], corner_radius=12,
                      border_width=0)
        play.grid(row=0, column=1, sticky="nsew")
        # minsize, so the chip is never squeezed to the width of one letter: at the smallest
        # window the header's left column gives ground instead, and its own label wraps.
        play.grid_columnconfigure(0, weight=1, minsize=196)
        # max_lines=1: this is a caption line, not a paragraph. Left free it took three lines
        # for a long instance name and the header strip grew by two rows - and a strip that grows
        # on a rename is a strip that moves the Play button out from under the pointer.
        self.top_inst = flow_label(play, text="no instance", height=17, anchor="e",
                                   justify="right", min_px=132, wrap=250, max_lines=1,
                                   font=theme.font(11), text_color=theme.COL["text_dim"])
        self.top_inst.grid(row=0, column=0, columnspan=2, sticky="e", padx=(16, 16),
                           pady=(8, 4))
        self.top_play = accent_button(play, "Play", self._top_play_pressed,
                                      width=112, height=34, corner_radius=10,
                                      font=theme.font(14, "bold"))
        self.top_play.grid(row=1, column=0, padx=(16, 8), pady=(0, 10))
        self.top_stop = ghost_button(play, "Stop", self._top_stop_pressed,
                                     width=86, height=34)
        self.top_stop.grid(row=1, column=1, padx=(0, 16), pady=(0, 10))
        self.top_stop.grid_remove()

        self.pages_host = tk.Frame(self.content, bg=theme.COL["bg"])
        self.pages_host.grid(row=1, column=0, sticky="nsew")
        self.pages_host.grid_columnconfigure(0, weight=1)
        self.pages_host.grid_rowconfigure(0, weight=1)

        # one status line for the whole window, so a page never has to invent its own
        self.status_lbl = ctk.CTkLabel(self.content, text="", anchor="w",
                                       font=theme.font(11),
                                       text_color=theme.COL["text_faint"])
        self.status_lbl.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 8))

    # ------------------------------------------------------- the bar's Play button
    def _top_play_pressed(self):
        try:
            self.flow.launch()
        except Exception as exc:
            self.set_status("Could not launch: %s" % exc)

    def _top_stop_pressed(self):
        try:
            self.flow.stop()
        except Exception as exc:
            self.set_status("Could not stop: %s" % exc)

    # these two are the LaunchFlow display protocol - the bar is a display like a page is,
    # so one running game greys Play out everywhere at once
    def set_selected(self, inst):
        try:
            self.top_inst.configure(text=(inst.name if inst else "no instance"))
        except Exception:
            pass

    def _set_overline(self, text, color=None):
        try:
            self.overline_lbl.configure(text=text, color=color or theme.COL["accent"])
        except Exception:
            pass

    def set_state(self, busy, running, text=""):
        live = 0
        try:
            live = len(self.live_games())
        except Exception:
            live = 0
        self._set_overline(("LAUNCHING" if busy else
                            ("%d GAME%s RUNNING" % (live, "" if live == 1 else "S")
                             if (running or live) else "READY")),
                           theme.COL["warn"] if busy else
                           (theme.COL["accent"] if not (running or live) else "#5bd6a0"))
        try:
            if running:
                self.top_play.grid_remove()
                self.top_stop.grid()
                self.top_stop.configure(state=("disabled" if busy else "normal"),
                                         text=("Stopping\u2026" if busy else "Stop"))
                return
            self.top_stop.grid_remove()
            self.top_play.grid()
            blocked = busy or bool(self.live_games())
            self.top_play.configure(
                state=("disabled" if blocked else "normal"),
                text=("Launching\u2026" if busy else "Play"))
            if not busy and blocked:
                self.top_inst.configure(text="one instance at a time")
        except Exception:
            pass

    def live_games(self):
        """Every game this launcher started that is still running, across all instances.

        One place asks, because Divine runs one instance at a time on purpose: two JVMs on a
        laptop is how an afternoon goes, and the grey-out rule ("another instance is open")
        has to give the same answer on Home, on the Instances grid and in the bar. The
        per-instance ``running_count()`` stays for the cards, which show *this* one.
        """
        out = []
        for iid, procs in list((self.running_procs or {}).items()):
            for proc in procs or []:
                try:
                    if proc.poll() is None:
                        out.append((iid, proc))
                except Exception:
                    pass
        return out

    def set_status(self, text, color=None):
        """Say something in the window's status line. Pages use this instead of dialogs."""
        try:
            self.status_lbl.configure(text=text or "",
                                      text_color=color or theme.COL["text_faint"])
        except Exception:
            pass

    def _init_pages(self):
        self.pages["home"] = HomePage(self.pages_host, self)
        self.pages["instances"] = InstancesPage(self.pages_host, self)
        self.pages["servers"] = ServersPage(self.pages_host, self)
        self.pages["accounts"] = AccountsPage(self.pages_host, self)
        self.pages["settings"] = SettingsPage(self.pages_host, self)
        self.pages["about"] = AboutPage(self.pages_host, self)
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()

    # ------------------------------------------------------------------ theme
    def _paint_shell(self):
        """Re-stamp the plain Tk frames of the shell with the palette.

        They are Tk frames on purpose (see ``_build_content``), so CustomTkinter's theme never
        touches them and the palette has to be pushed by hand: once after the shell is built,
        again on a background switch and after ``restyle``.
        """
        for widget, color in ((getattr(self, "content", None), theme.COL["bg"]),
                              (getattr(self, "pages_host", None), theme.COL["bg"]),
                              (getattr(self, "_bar", None), theme.COL["bg2"]),
                              (getattr(self, "status_lbl", None), theme.COL["bg"])):
            if widget is None:
                continue
            try:
                widget.configure(bg=color)
            except Exception:
                pass      # torn down mid-restyle, which the next one will paint anyway
        try:
            self.configure(bg=color)
        except Exception:
            pass
        theme.pin_surfaces(self)

    def set_background(self, key):
        """Change the wash + panels, save it, and build the interface again.

        Returns False for an unknown name, leaving the config and the window untouched.
        """
        if not theme.set_background(key):
            return False
        self.config_store.set("ui_background", key)
        try:
            self.config_store.save()
        except Exception:
            pass
        self.restyle()
        return True

    def restyle(self):
        """Rebuild the shell so the palette reaches every widget that already exists.

        Colours in this UI are read when a widget is built - that is what keeps a page cheap
        to paint - so there is no colour to update on a widget that was built under another
        palette. Rebuilding the window is a couple of hundred milliseconds on a change someone
        makes once, and it cannot leave a widget behind with the old hue, which any
        half-measure of "reconfigure the ones I remember" does.
        """
        keep = getattr(self, "_current", "home")
        try:
            self.flow.remove_display(self)
        except Exception:
            pass
        for _name, page in list(self.pages.items()):
            try:
                page.destroy()
            except Exception:
                pass        # a page's own destroy unregisters it; a half-built one is noise
        self.pages = {}
        for attr in ("content", "nav"):
            try:
                getattr(self, attr).destroy()
            except Exception:
                pass
        self.nav = SideNav(self, self)
        self.nav.grid(row=0, column=0, sticky="nsew")
        self.nav.grid_propagate(False)
        self.nav.configure(width=SideNav.WIDTH)
        self._build_content()
        self.nav.refresh_account()
        try:
            self.configure(fg_color=theme.COL["bg"])
        except Exception:
            pass
        self._init_pages()
        self.flow.add_display(self)
        self.flow.refresh()
        self.show_page(keep)
        self._paint_shell()
        self.refresh_top_account()
        self._nav_sync()
        try:                                   # the sidebar pill is a widget we just replaced
            self._show_update_state(self._update_state or {})
        except Exception:
            pass

    # ------------------------------------------------------------- navigation
    def nav_request(self, key):
        """What a tab click does - including the gate on the unfinished ones."""
        if key in LOCKED_TABS and not self.servers_unlocked():
            self._ask_allowance_code(key)
            return
        self.show_page(key)

    def servers_unlocked(self):
        return bool(self.config_store.get("servers_unlocked", False))

    def _ask_allowance_code(self, target):
        box = CodeDialog(self, LOCKED_TABS.get(target, "Enter the allowance code."),
                         on_ok=self._unlock_tab)
        box.after(60, box.focus_entry)

    def _unlock_tab(self, code):
        """Returns True when the code matches; the dialog says so either way."""
        if not _code_ok(code):
            return False
        self.config_store.set("servers_unlocked", True)
        try:
            self.config_store.save()
        except Exception:
            pass
        self._nav_sync()
        self.show_page("servers")
        return True

    def lock_servers(self):
        """Settings can put the tab back behind the code."""
        self.config_store.set("servers_unlocked", False)
        try:
            self.config_store.save()
        except Exception:
            pass
        self._nav_sync()
        if self._current == "servers":
            self.show_page("home")

    def show_page(self, key):
        if key == "versions":        # phase 9 renamed this tab; old callers still work
            key = "instances"
        if key in LOCKED_TABS and not self.servers_unlocked():
            self._ask_allowance_code(key)
            return
        page = self.pages.get(key)
        if page is None:
            return
        self._current = key
        for name, other in self.pages.items():
            if other is page:
                continue
            if other.winfo_manager():
                try:
                    other.on_hide()
                except Exception:
                    pass
                other.grid_remove()
        page.grid()
        try:
            page.tkraise()          # all pages share one cell: say which one is on top
        except Exception:
            pass
        try:
            page.on_show()
        except Exception:
            pass
        theme.pin_surfaces(page)    # after on_show: a page that refreshes on show has just
                                    # built the widgets that need this, not the ones it threw away
        self.nav.set_page(key)
        self._set_title(key)

    TITLES = {
        "home": ("Home", "what is running, and what is new"),
        "instances": ("Instances", "create, edit and launch your versions"),
        "servers": ("Servers", "host a world for friends"),
        "accounts": ("Accounts", "Microsoft sign-in and offline names"),
        "settings": ("Settings", "Java, memory, game files, appearance"),
        "about": ("About", "what this launcher is and does"),
    }

    def _set_title(self, key):
        title, sub = self.TITLES.get(key, (key.title(), ""))
        if key == "servers" and self.servers_unlocked():
            title += "  \u00b7  unlocked"
        try:
            self.title_lbl.configure(text=title)
            self.subtitle_lbl.configure(text=sub)
        except Exception:
            pass

    def refresh_top_account(self):
        acc = None
        try:
            acc = self.accounts.get_active()
        except Exception:
            acc = None
        try:
            if acc:
                kind = "Microsoft" if acc.get("type") == "microsoft" else "Offline"
                self.top_account.configure(text="%s  \u00b7  %s" % (acc.get("name"), kind),
                                          text_color=theme.COL["text"])
            else:
                self.top_account.configure(text="No account",
                                          text_color=theme.COL["warn"])
        except Exception:
            pass
        self._nav_sync()

    def _nav_sync(self):
        """Keep the sidebar's account row and Servers badge in step with reality."""
        try:
            self.nav.refresh_account()
        except Exception:
            pass
        try:
            self.nav.set_page(getattr(self, "_current", "home"))
        except Exception:
            pass

    # --------------------------------------------------------------- versions
    def _prefetch_versions(self):
        """Fetch what is not cached yet, then tell the pages. Used by Versions dialogs
        and by Settings' "check again", where a refresh is the whole point."""
        if self._version_cache and self._fabric_cache:
            try:
                self.after(0, self._versions_ready)
            except Exception:
                pass
            return

        def work():
            # the same two fetches the loading screen runs, without the staging: on a
            # refresh the splash is long gone and there is nothing to animate
            self._stage_manifest()
            self._stage_fabric()
            try:
                self.after(0, self._versions_ready)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _versions_ready(self):
        for hook in ("on_versions_ready", "refresh"):
            for page in self.pages.values():
                fn = getattr(page, hook, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
            if hook == "on_versions_ready":
                break
        self.flow.refresh()

    def get_versions(self):
        if self._version_cache is None:
            try:
                self._version_cache = launcher.get_version_list()
            except Exception:
                self._version_cache = []
        return self._version_cache

    def get_fabric_versions(self):
        if self._fabric_cache is None:
            try:
                self._fabric_cache = launcher.get_fabric_supported_versions()
            except Exception:
                self._fabric_cache = set()
        return self._fabric_cache

    def refresh_all(self):
        for page in self.pages.values():
            for hook in ("refresh", "on_show"):
                fn = getattr(page, hook, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
        self.flow.refresh()
        self.refresh_top_account()

    # ---------------------------------------------------------------- updates
    def _update_worker(self, force=False):
        """Ask the site what is current, and start a download if it is newer.

        Skipped entirely when automatic updates are off - except when the user pressed
        "Check now", which forces exactly once. Either way the answer is only a
        suggestion: nothing here can stop a launch, and a site that does not answer is
        not a launcher that does not open.
        """
        if not force and not self.config_store.get("auto_update", True):
            self._update_state = {"state": "off"}
            try:
                self.after(0, lambda: self._show_update_state(self._update_state))
            except Exception:
                pass
            return
        try:
            state = updater.status(self.config_store, force=bool(force))
        except Exception as e:
            state = {"state": "unreachable", "detail": str(e)[:80]}
        self._update_state = state
        try:
            self.after(0, lambda: self._show_update_state(state))
        except Exception:
            pass
        # "forces download of new version": once we know there is one, fetch it
        if state.get("state") == "available":
            self._download_update(state.get("info") or {})

    def _show_update_state(self, state):
        """The pill in the sidebar's footer. Text and colour, nothing else."""
        kind = state.get("state")
        remote = state.get("remote", "") or ""
        detail = state.get("detail") or ""
        if kind == "staged":
            self.nav.set_update_state("good", "\u21B3  Update %s ready \u2014 restart" % remote)
        elif kind == "available":
            self.nav.set_update_state("info", "\u21B5  Update %s \u2014 downloading" % remote)
        elif kind == "downloading":
            self.nav.set_update_state("info", "\u21B5  %s" % (detail or "downloading\u2026"))
        elif kind == "downloaded":
            self.nav.set_update_state("good", "\u21B3  Restart to update to %s" % remote)
        elif kind == "failed":
            self.nav.set_update_state("danger", "!  %s" % (detail or "update failed")[:52])
            # The pill has room for 52 characters and the reason does not fit in them,
            # which is how "the update download failed" came to be the whole message
            # somebody had to debug from. The status line carries all of it.
            self.set_status("Update failed: %s  \u00b7  press the pill to retry"
                            % (detail or "update failed"), theme.COL["danger"])
        elif kind == "no-download":
            self.nav.set_update_state("warn", "!  %s" % (detail or "")[:52])
        else:
            # "current", "off", "unreachable": nothing to say in either place. Clearing
            # the pill here is what hides it, so the status line is cleared in the same
            # branch - a resolved complaint must not leave its sentence behind.
            self.nav.set_update_state("info", "")
            self.set_status("")

    def _download_update(self, info):
        if self._update_thread and self._update_thread.is_alive():
            return

        def work():
            def progress(frac, text):
                state = {"state": "downloading", "detail": text,
                         "remote": info.get("version", ""), "frac": frac}
                try:
                    self.after(0, lambda: self._show_update_state(state))
                except Exception:
                    pass
            try:
                path, kind = updater.download(info, progress=progress)
                state = {"state": "staged" if kind == "dir" else "downloaded",
                         "remote": info.get("version", ""), "path": path,
                         "detail": "Restart to update to %s" % info.get("version", "")}
                if kind == "exe":
                    state["detail"] = "Downloaded - the updater cannot run from source"
                    state["state"] = "downloaded" if updater.apply_supported() else "staged"
            except Exception as e:
                state = {"state": "failed", "detail": str(e)[:300]}
            self._update_state = state
            try:
                self.after(0, lambda: self._show_update_state(state))
            except Exception:
                pass
        self._update_thread = threading.Thread(target=work, daemon=True)
        self._update_thread.start()

    def update_action(self):
        """Press the pill: apply a staged update, or get out of the way."""
        state = dict(self._update_state or {})
        if state.get("state") in ("staged", "downloaded") and updater.apply_supported():
            try:
                if updater.apply_later():
                    self._force_quit = True
                    self._on_close()
                    return
            except Exception as e:
                state = {"state": "failed", "detail": str(e)[:140]}
                self._show_update_state(state)
                return
        if state.get("state") in ("available", "no-download", "unreachable", "failed"):
            try:
                from ..core import endpoints
                import webbrowser
                webbrowser.open(endpoints.site_url("/download"))
            except Exception:
                pass
            self._update_worker()
            return
        try:
            self.show_page("settings")
        except Exception:
            pass

    def check_for_updates_now(self):
        """Settings' button: the same path, forced past the auto-update switch.

        On a thread, always: this is a network call, and a button that freezes the window
        for fifteen seconds reads as a crash.
        """
        threading.Thread(target=lambda: self._update_worker(force=True),
                         daemon=True).start()

    # -------------------------------------------------------------- presence
    def _report_presence(self, state, detail="", sync=False):
        """Tell the site whether we are in a game, so friends see green or orange.

        Fire-and-forget in a thread normally. ``sync`` is used once, on exit: after that
        there is no process left to finish an async request, so the quit path waits a
        moment for the "offline" line to land and then stops caring.
        """
        def work():
            try:
                from ..core import social
                social.set_presence(self.config_store, state, detail,
                                    timeout=3 if sync else _PRESENCE_TIMEOUT)
            except Exception:
                pass
        if sync:
            work()
            return
        threading.Thread(target=work, daemon=True).start()

    def _presence_state(self):
        """"in_game" plus what is running, or "idle" - the friend list's colour source."""
        try:
            for iid in list(self.running_procs.keys()):
                if self.running_count(iid) > 0:
                    inst = None
                    try:
                        inst = self.instances.get(iid)
                    except Exception:
                        inst = None
                    return "in_game", ("Playing %s" % (getattr(inst, "mc_version", "")
                                                        or "Minecraft"))
        except Exception:
            pass
        return "idle", ""

    def _presence_beat(self):
        """Re-post presence once a minute, and re-check for updates every fifteen.

        The site believes a presence line only while the launcher keeps saying it, which
        is what lets a friend drift from green to black when this process is killed rather
        than quit. The slow update re-check is here too so a launcher left open across a
        release still offers the restart, without a second timer to keep in sync.
        """
        self._beat = int(getattr(self, "_beat", 0)) + 1
        try:
            state, detail = self._presence_state()
            self._report_presence(state, detail)
            if self._beat % 15 == 0:
                live = getattr(self, "_update_thread", None)
                if not (live and live.is_alive()):
                    threading.Thread(target=self._update_worker, daemon=True).start()
        except Exception:
            pass
        try:
            self.after(60000, self._presence_beat)
        except Exception:
            pass

    # ------------------------------------------------------------- processes
    def track_process(self, instance_id, proc):
        self.running_procs.setdefault(instance_id, []).append(proc)
        # when it started, so the session can be banked when it stops
        if not hasattr(self, "_proc_started"):
            self._proc_started = {}
        self._proc_started[id(proc)] = time.time()
        inst = None
        try:
            inst = self.instances.get(instance_id)
        except Exception:
            pass
        self._report_presence("in_game",
                              "Playing %s" % (inst.mc_version if inst else "Minecraft"))
        self.flow._push()

    def running_count(self, instance_id):
        return len(self._reap(instance_id))

    def _reap(self, instance_id):
        """Drop the processes that have gone, banking each one as playtime.

        This is the only place a finished game is noticed, so it is also the only place
        playtime is written - which is what keeps the number honest: one entry per process
        that actually ran, whether the player quit or the window was killed.
        """
        alive = []
        for proc in self.running_procs.get(instance_id, []) or []:
            if proc.poll() is None:
                alive.append(proc)
            else:
                self._bank_playtime(instance_id, proc)
        self.running_procs[instance_id] = alive
        return alive

    def _bank_playtime(self, instance_id, proc):
        started = getattr(self, "_proc_started", {}).pop(id(proc), None)
        if not started:
            return                      # already banked, or tracked before this existed
        try:
            from ..core import playtime
            inst = self.instances.get(instance_id)
            if inst is None:
                return
            total = playtime.add(inst, time.time() - started, at=time.time())
            if total is not None:
                self._push_playtime(instance_id, inst, total, playtime)
        except Exception:
            pass

    def _push_playtime(self, instance_id, inst, total, playtime):
        """Tell that instance's card how long the session was, without rebuilding it.

        The card reads playtime when the page is built anyway; this is only the part that
        makes the number move the moment a game window closes, so it reads as tracked
        rather than guessed.
        """
        try:
            page = self.pages.get("instances")
            card = (getattr(page, "_cards", None) or {}).get(instance_id) if page else None
            if card is not None:
                card.set_playtime(total, playtime.since(playtime.last_played(inst)))
        except Exception:
            pass

    def total_running(self):
        return sum(self.running_count(i) for i in list(self.running_procs.keys()))

    def stop_instance(self, instance_id):
        killed = 0
        for proc in list(self.running_procs.get(instance_id, [])):
            if proc.poll() is None:
                if self._terminate(proc):
                    killed += 1
        self._reap(instance_id)
        if not self.total_running():
            self._report_presence("idle")
        return killed

    def stop_all(self):
        killed = 0
        for iid in list(self.running_procs.keys()):
            killed += self.stop_instance(iid)
        return killed

    def _terminate(self, proc):
        import time
        try:
            proc.terminate()
        except Exception:
            pass
        for _ in range(20):
            if proc.poll() is not None:
                return True
            time.sleep(0.1)
        try:
            proc.kill()
        except Exception:
            pass
        return proc.poll() is not None

    # -------------------------------------------------------- server events
    def _on_server_event(self, event, manager=None):
        try:
            self.after(0, self._server_event_on_main)
        except Exception:
            pass

    def _server_event_on_main(self):
        self.refresh_server_badge()
        page = self.pages.get("servers")
        if page is not None:
            try:
                page.on_server_change()
            except Exception:
                pass

    def refresh_server_badge(self):
        try:
            n = self.servers.running_count()
        except Exception:
            n = 0
        try:
            self.nav.set_server_badge(n)
        except Exception:
            pass

    def refresh_discord(self):
        if not getattr(self, "discord", None):
            return
        for iid in list(self.running_procs.keys()):
            if self.running_count(iid) > 0:
                inst = self.instances.get(iid)
                if inst:
                    self.discord.set_playing(inst.name, inst.mc_version, inst.loader)
                    return
        self.discord.set_idle()

    # ------------------------------------------------------------- window close
    def _on_close(self):
        """Closing the launcher must not silently kill a server someone is playing on."""
        running = 0
        try:
            running = self.servers.running_count()
        except Exception:
            running = 0
        if running and not getattr(self, "_force_quit", False):
            self._ask_before_quit(running)
            return
        try:
            if getattr(self, "discord", None):
                self.discord.close()
        except Exception:
            pass
        # say "offline" while there is still a process to say it with
        try:
            self._report_presence("offline", "", sync=True)
        except Exception:
            pass
        self.destroy()

    def _ask_before_quit(self, running):
        box = ctk.CTkToplevel(self)
        box.title("Servers are still running")
        box.resizable(False, False)
        box.transient(self)
        box.grab_set()
        box.configure(fg_color=theme.COL["bg2"])
        word = "server" if running == 1 else "servers"
        ctk.CTkLabel(box, text="%d %s still hosting" % (running, word),
                     font=theme.title_font(18), text_color=theme.COL["text"]
                     ).pack(padx=22, pady=(18, 4), anchor="w")
        ctk.CTkLabel(
            box, text="Friends connected to them stay online if you close Divine "
                      "Client. You can stop them later from the Servers page, or "
                      "shut them down now.",
            font=theme.font(12), text_color=theme.COL["text_dim"], wraplength=420,
            justify="left").pack(padx=22, pady=(0, 14), anchor="w")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 18))
        row.grid_columnconfigure(0, weight=1)

        def keep():
            box.destroy()
            self._force_quit = True
            self._on_close()

        def stop_and_quit():
            box.destroy()
            threading.Thread(target=self._stop_servers_then_quit, daemon=True).start()

        from .widgets import ghost_button, accent_button
        ghost_button(row, "Stop them and quit", stop_and_quit, width=170, height=40
                     ).grid(row=0, column=1, padx=(10, 0))
        accent_button(row, "Leave them running", keep, width=170, height=40).grid(
            row=0, column=2)

    def _stop_servers_then_quit(self):
        try:
            self.servers.shutdown(keep_running=False)
        except Exception:
            pass
        self._force_quit = True
        self.after(0, self._on_close)


class CodeDialog(ctk.CTkToplevel):
    """The little gate for a work-in-progress tab: type the code, get the tab.

    It stays open on a wrong answer (with the reason shown) rather than closing, because
    the usual cause is a stray space from copying it out of a message.
    """

    def __init__(self, master, message, on_ok=None):
        super().__init__(master)
        self._on_ok = on_ok
        self.title("Work in progress")
        self.resizable(False, False)
        self.transient(master)
        self.configure(fg_color=theme.COL["bg2"])
        try:
            self.configure(bg=theme.COL["bg2"])
        except Exception:
            pass
        self.grab_set()

        card = ctk.CTkFrame(self, corner_radius=16, border_width=1,
                            border_color=theme.COL["border"], fg_color=theme.COL["bg2"])
        card.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkLabel(card, text="\u2609   Servers \u00b7 W.I.P", font=theme.title_font(19),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w",
                                                         padx=22, pady=(20, 4))
        ctk.CTkLabel(card, text=message, font=theme.font(12), wraplength=380,
                     justify="left", anchor="w", text_color=theme.COL["text_dim"]
                     ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 12))
        self.entry = ctk.CTkEntry(card, height=42, corner_radius=12, show="\u2022",
                                  font=theme.font(14), placeholder_text="allowance code",
                                  fg_color=theme.COL["bg3"],
                                  border_color=theme.COL["border"], border_width=1,
                                  text_color=theme.COL["text"])
        self.entry.grid(row=2, column=0, sticky="ew", padx=22)
        self.entry.bind("<Return>", lambda e: self._try())
        self.note = ctk.CTkLabel(card, text="", font=theme.font(11),
                                 text_color=theme.COL["danger"], anchor="w")
        self.note.grid(row=3, column=0, sticky="w", padx=22, pady=(6, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=4, column=0, sticky="ew", padx=22, pady=(8, 20))
        row.grid_columnconfigure(0, weight=1)
        from .widgets import ghost_button, accent_button
        ghost_button(row, "Not now", lambda: self.destroy(), width=120, height=38
                     ).grid(row=0, column=0, sticky="w")
        accent_button(row, "Unlock", self._try, width=130, height=38).grid(row=0, column=1)

        # Centred over the window rather than dumped at a screen corner. It used to open
        # with -alpha set to 0.0 and a ticker fading it in; the ticker is gone, so the
        # dialog would have stayed invisible on Windows - the initial state of an
        # animation is never allowed to be a widget's resting state anymore.
        self._center_over(master)
        self.after(40, self.focus_entry)

    def _center_over(self, master):
        try:
            self.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw, ph = master.winfo_width(), master.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 3)
            self.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    def focus_entry(self):
        try:
            self.entry.focus_force()
        except Exception:
            pass

    def _try(self):
        text = self.entry.get()
        ok = False
        if self._on_ok is not None:
            try:
                ok = bool(self._on_ok(text))
            except Exception:
                ok = False
        if ok:
            self.destroy()
            return
        self.note.configure(text="That is not it. Codes are one long word, no spaces.")


def apply_update_and_exit(payload, wait_pid=None):
    """``DivineClient.exe --apply-update <staged build>``: swap files in, start the new one.

    Run before anything GUI-ish exists, from main.py. It has no access to the launcher's
    state and needs none: it waits for the previous process to go, copies the staged files
    over the install folder, clears the updates folder, and relaunches.
    """
    log_path = os.path.join(paths.LOG_DIR, "update.log")
    os.makedirs(paths.LOG_DIR, exist_ok=True)

    def log(msg):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("%s update: %s\n" % (time_str(), msg))
        except Exception:
            pass

    try:
        moved, failed = updater.run_apply_update(payload, wait_pid=wait_pid, log=log)
        log("done (moved=%d failed=%s)" % (moved, ", ".join(failed[:6]) or "none"))
        return 0
    except Exception as err:                                # noqa: BLE001
        log("failed: %r" % (err,))
        return 1


def time_str():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run():
    app = DivineApp()
    app.mainloop()
