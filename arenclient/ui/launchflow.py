"""Who launches the game, and what every "launch" widget on screen shows about it.

The Launch button lives on the Home page and on every instance card, and they show one
state, not two: the same launch would otherwise answer differently while it is running,
which is exactly when it matters. This object owns the busy flag, the choice and the
worker, so the logic cannot live in either widget - two copies of it would disagree. This is
the one place that knows what is selected, whether it is launching, and how far along it
is; anything that wants to show it registers itself as a *display*.

A display is any object with these methods (all optional):

    set_selected(instance)            the version the button will launch
    set_state(busy, running, text)  what is happening right now
    set_progress(fraction, status)  download/verify progress, or None for indeterminate
    launch_error(message)           a one-line reason the launch failed

They are called on the main thread only; the worker thread posts back through
``app.after``, because Tk is not thread-safe and a launch runs off-thread by design.
"""
import threading

from ..core import launcher
from . import theme


class LaunchFlow:
    def __init__(self, app):
        self.app = app
        self._displays = []
        self._selected_id = None
        self.busy = False
        self._cancel_requested = False
        self._last_running_total = 0
        self._polling = False

    # -------------------------------------------------------------- displays
    def add_display(self, display):
        if display not in self._displays:
            self._displays.append(display)
        self._push(display)

    def _notify(self, method, *args):
        for d in list(self._displays):
            fn = getattr(d, method, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception:
                    pass        # a half-built or destroyed widget must not stop a launch

    def _push(self, display=None):
        targets = [display] if display is not None else list(self._displays)
        inst = self.selected()
        for d in targets:
            fn = getattr(d, "set_selected", None)
            if callable(fn):
                try:
                    fn(inst)
                except Exception:
                    pass
        running = bool(inst) and self.app.running_count(inst.id) > 0
        self._notify("set_state", self.busy, running, "")

    def remove_display(self, d):
        """Forget a display that is being destroyed.

        Tk widgets die in an unpredictable order; a page that is gone must not be
        reached again, or the next notify raises and every display after it is skipped.
        """
        try:
            self._displays.remove(d)
        except (ValueError, AttributeError):
            pass

    def refresh(self):
        """Re-read the instance list and re-push everything (after create/delete)."""
        try:
            self.app.instances.load()
        except Exception:
            pass
        if self.selected() is None:
            insts = self.app.instances.instances
            if insts:
                self.select(insts[0])
                return
        self._push()

    # ------------------------------------------------------------- selection
    def selected(self):
        """The chosen instance, or None.

        The manager is reloaded once when the id is unknown: a version created by the
        editor, the mod browser or a second launcher window is on disk before this
        object knows about it, and a choice that quietly resolves to "nothing" is the
        worst possible failure here - the button would launch a different version than
        the one the page says is chosen.
        """
        if self._selected_id:
            insts = self.app.instances.instances
            for i in insts:
                if i.id == self._selected_id:
                    return i
            if not getattr(self, "_reloaded_once", False):
                self._reloaded_once = True
                try:
                    self.app.instances.load()
                except Exception:
                    pass
                for i in self.app.instances.instances:
                    if i.id == self._selected_id:
                        return i
        return None

    def select(self, inst):
        """Make *inst* the version the Launch button uses. Never launches anything."""
        if inst is None:
            self._selected_id = None
            try:
                self.app.config_store.set("last_instance", "")
                self.app.config_store.save()
            except Exception:
                pass
            self._push()
            return
        self._selected_id = inst.id
        self._reloaded_once = False       # a fresh choice may need a fresh look
        try:
            self.app.config_store.set("last_instance", inst.id)
            self.app.config_store.save()
        except Exception:
            pass
        self._push()

    def restore_selection(self):
        """Pick up the saved choice at startup (last used, else the first version)."""
        try:
            self.app.instances.load()
        except Exception:
            pass
        insts = self.app.instances.instances
        if not insts:
            self._selected_id = None
            self._push()
            return None
        wanted = self.app.config_store.get("last_instance", "")
        for i in insts:
            if i.id == wanted:
                self._selected_id = i.id
                self._push()
                return i
        self._selected_id = insts[0].id
        self._push()
        return insts[0]

    # ------------------------------------------------------------- launching
    def launch(self):
        if self.busy:
            return
        inst = self.selected()
        if inst is None:
            self._notify("launch_error",
                         "No version chosen yet - pick one under Versions.")
            try:
                self.app.show_page("versions")
            except Exception:
                pass
            return
        # One game at a time, and said out loud rather than queued or silently refused: a
        # second JVM is how an afternoon goes, and two windows both claiming to be "the"
        # instance is worse than a button that explains itself. Every way in to a launch comes
        # through here, so this is the whole rule - and it is checked before anything else,
        # because "close the game that is open" is more useful to hear than "sign in first".
        # The pages only draw the greyed button from ``locked_for``; they never decide.
        others = self.others_running(inst)
        if others:
            self._notify("launch_error",
                         "%s is still open. Divine runs one instance at a time: stop it (Stop "
                         "below, or the \u25A0 button in the bar) and this launches."
                         % ", ".join(others[:2]))
            self._push()
            return
        if not self.app.accounts.get_active():
            self._notify("launch_error", "Add an account first (Accounts).")
            try:
                self.app.show_page("accounts")
            except Exception:
                pass
            return
        self._cancel_requested = False
        self._set_busy(True)
        self._notify("set_progress", 0.0, "Preparing " + inst.name)
        threading.Thread(target=self._worker, args=(inst,), daemon=True).start()

    # ------------------------------------------------------------ one at a time
    def others_running(self, inst=None):
        """Names of the *other* instances with a game up right now.

        ``live_games()`` is the only thing that knows, and it is asked here so that Home, the
        Instances grid, the bar and the launch itself cannot disagree about whether a second
        game is allowed.
        """
        try:
            live = self.app.live_games()
        except Exception:
            return []
        keep = getattr(inst, "id", None)
        ids = []
        for iid, _proc in live:
            if iid != keep and iid not in ids:
                ids.append(iid)
        names = []
        for iid in ids:
            name = iid
            try:
                found = self.app.instances.get(iid)
                name = getattr(found, "name", None) or iid
            except Exception:
                pass
            names.append(name)
        return names

    def locked_for(self, inst=None):
        """True when launching ``inst`` would mean a second game."""
        try:
            if self.busy:
                return True
        except Exception:
            pass
        return bool(self.others_running(inst))

    def stop(self):
        inst = self.selected()
        if inst is None:
            return
        if self.busy:
            self._cancel_requested = True
            self._notify("set_state", True, False, "Stopping...")
            threading.Thread(target=self.app.stop_instance, args=(inst.id,),
                             daemon=True).start()
            self.app.after(700, lambda: self._set_busy(False))
            return
        self._notify("set_state", True, True, "Saving the world and stopping...")

        def work():
            killed = self.app.stop_instance(inst.id)
            try:
                self.app.after(0, lambda: self._after_stop(killed))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _after_stop(self, killed):
        self._set_busy(False)
        if killed:
            self._notify("set_state", False, False, "Stopped")
            self.app.after(2200, lambda: self._notify("set_state", False, False, ""))
        self.app.refresh_discord()

    def _set_busy(self, busy):
        self.busy = bool(busy)
        self._push()

    def _worker(self, inst):
        def on_update(status, frac):
            try:
                self.app.after(0, lambda: self._notify("set_progress", frac, status))
            except Exception:
                pass
        prog = launcher.Progress(on_update=on_update)
        try:
            proc, log_path = launcher.launch(inst, self.app.config_store,
                                            self.app.accounts, prog)
            self.app.track_process(inst.id, proc)
            if self._cancel_requested:
                self.app.stop_instance(inst.id)
                self.app.after(0, lambda: self._notify("set_progress", 0.0, "Canceled."))
                self.app.after(400, lambda: self._set_busy(False))
                return
            self.app.after(0, lambda: self._notify("set_progress", 1.0,
                                                   "Minecraft is starting!"))
            self.app.after(1200, lambda: self._after_launch(inst, proc, log_path))
        except Exception as e:
            msg = str(e)
            self.app.after(0, lambda: self._launch_error(msg))

    def _after_launch(self, inst, proc=None, log_path=None):
        self._set_busy(False)
        self.select(inst)
        try:
            self.app.discord.set_playing(inst.name, inst.mc_version, inst.loader)
        except Exception:
            pass
        if proc is not None:
            try:
                from .session_window import SessionWindow
                win = SessionWindow(self.app, inst, proc, log_path)
                win.focus()
            except Exception:
                pass
        if self.app.config_store.get("close_on_launch"):
            self.app._on_close()

    def _refresh_locks(self):
        """Let the pages re-draw their greyed-out Launch buttons.

        They only ever ask, never decide: which buttons are dimmed is a question with one
        answer, and ``launch()`` above is where that answer lives.
        """
        for key in ("instances", "home"):
            page = None
            try:
                page = self.app.pages.get(key)
            except Exception:
                page = None
            fn = getattr(page, "refresh_locks", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def _launch_error(self, msg):
        self._set_busy(False)
        self._notify("launch_error", msg)

    # ------------------------------------------------------------ live state
    def start_polling(self):
        """Keep every display honest about how many games are actually running."""
        if self._polling:
            return
        self._polling = True
        self._poll_once()

    def _poll_once(self):
        try:
            if not self.app.winfo_exists():
                self._polling = False
                return
        except Exception:
            self._polling = False
            return
        total = self.app.total_running()
        if total != self._last_running_total:
            self._last_running_total = total
            self.app.refresh_discord()
            self._push()
            self._refresh_locks()
        try:
            self.app.after(2000, self._poll_once)
        except Exception:
            self._polling = False
