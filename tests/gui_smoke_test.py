"""Headless UI test for the server window and the Servers panel.

Run with:
    xvfb-run -a python tests/gui_smoke_test.py

Covers the behaviour the panel is built around:
  * starting a server opens its own window, with live resource meters
  * closing that window does NOT stop the server, and the console can be
    reopened later with its history intact
  * Stop / Restart / Kill are driven from the panel row
Uses a real Fabric server (set DIVINE_GUI_DATA to a data dir that already has one
installed, otherwise it downloads). The tunnel is disabled here and covered by
tests/test_live_server.py instead.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("DIVINE_GUI_DATA")
if DATA:
    os.environ["XDG_DATA_HOME"] = DATA

import customtkinter as ctk                                     # noqa: E402

from divineclient import paths                                    # noqa: E402
from divineclient.core import server_host                          # noqa: E402
from divineclient.core.instances import Instance, InstanceManager  # noqa: E402
from divineclient.core.server_sessions import ServerSessionManager  # noqa: E402
from divineclient.ui.pages import servers_page                    # noqa: E402
from divineclient.ui.pages.servers_page import ServersPage        # noqa: E402

BOOT_TIMEOUT = float(os.environ.get("AREN_GUI_TIMEOUT", "420"))


class StubTunnel:
    """playit/bore are exercised by test_live_server.py; here they'd just be noise."""

    def __init__(self, local_port=0, provider="auto"):
        self.local_port = local_port
        self.provider = provider
        self.public_address = None
        self.claim_url = None
        self.active_provider = "stub"
        self.on_status = None
        self.on_line = None
        self.on_address = None
        self.on_claim = None

    def start(self, status=None):
        self.public_address = "tunnel.test:25565"
        if self.on_address:
            self.on_address(self.public_address)

    def is_running(self):
        return True

    def stop(self):
        pass


class StubSocial:
    def __getattr__(self, name):
        def _call(*a, **k):
            if name == "is_linked":
                return True
            if name == "host_server":
                return {"code": "GUI-TEST"}
            if name in ("list_friends", "list_server_invites"):
                return []
            return None
        return _call


class FakeApp(ctk.CTk):
    """The page reads app.instances / app.config_store / app.servers, so give it
    exactly those on a real Tk root (a window needs one as its master)."""

    def __init__(self):
        super().__init__()
        self.config_store = {"ram_mb": 1024, "custom_java_path": "",
                             "tunnel_provider": "none"}
        self.instances = InstanceManager().load()
        self.servers = ServerSessionManager(self.config_store, app=self)

    def get(self, key, default=None):
        return self.config_store.get(key, default)

    def set(self, key, value):
        self.config_store[key] = value

    def save(self):
        pass


FAILURES = []
STEPS = []


def console_of(win):
    try:
        return win.console.get("1.0", "end")
    except Exception:
        return ""


def main():
    servers_page_social = servers_page
    servers_page_social.tunnel_mod.Tunnel = StubTunnel
    # the page itself imports social for invites/registration
    import divineclient.ui.pages.servers_page as sp
    sp.social = StubSocial()

    paths.ensure_dirs()
    app = FakeApp()
    iid = os.environ.get("AREN_GUI_INSTANCE", "ayyy")
    mc = os.environ.get("AREN_GUI_MC", "1.16.5")
    inst = Instance({"id": iid, "name": iid, "mc_version": mc, "loader": "fabric",
                     "loader_version": None})
    app.instances.instances = [inst]
    app.withdraw()

    page = ServersPage(app, app)
    page.pack(fill="both", expand=True)
    app.servers.add_listener(lambda event, m=None: None)

    def finish():
        if FAILURES:
            print("\n".join("FAIL: " + f for f in FAILURES))
        else:
            print("\nGUI SMOKE TEST PASSED")
        root_quit()

    def root_quit():
        try:
            app.quit()
        except Exception:
            pass

    def start_and_wait():
        session = app.servers.start(inst, ram_mb=1024, tunnel_provider="bore")
        STEPS.append("start() opened a window: %s" % type(session._window).__name__)

        def wait_boot(t0):
            win = session._window
            text = console_of(win) if win else ""
            if "Done (" in text:
                STEPS.append("window console streamed the running server")
                check_meters(session, wait_command)
            elif session.status == "crashed":
                FAILURES.append("server crashed: %s\n%s" % (
                    session.error, "\n".join((session.history()[-15:]))))
                finish()
            elif time.time() - t0 > BOOT_TIMEOUT:
                FAILURES.append("boot timed out; console tail:\n" + text[-1200:])
                finish()
            else:
                app.after(400, wait_boot, t0)

        app.after(300, wait_boot, time.time())

    def check_meters(session, then):
        win = session._window
        mem = win.meters["mem"]["value"].cget("text")
        sub = win.meters["mem"]["sub"].cget("text")
        alloc = win.meters["mem"]["sub"].cget("text")
        up = win.meters["uptime"]["value"].cget("text")
        assert "allocated" in alloc and "1024 MB" in alloc, alloc
        assert mem not in ("", "\u2014"), "memory meter empty: %r" % mem
        STEPS.append("meters: mem=%s | %s | uptime=%s | players=%s" % (
            mem, sub, up, win.meters["players"]["value"].cget("text")))
        then(session, win)

    def wait_command(session, win):
        win.cmd_entry.delete(0, "end")
        win.cmd_entry.insert(0, "list")
        win._send()

        def check(t0):
            if "There are" in console_of(win):
                STEPS.append("console command round-trip works")
                close_window_and_check(session)
            elif session.proc.proc.poll() is not None:
                FAILURES.append("server died during the command test")
                finish()
            elif time.time() - t0 > 45:
                FAILURES.append("no reply to the typed command")
                finish()
            else:
                app.after(400, check, t0)

        app.after(300, check, time.time())

    def close_window_and_check(session):
        pid_before = session.proc.pid()
        session._window._on_close_request()          # the user presses the X
        STEPS.append("window closed")

        def check(t0):
            if time.time() - t0 > 10:
                FAILURES.append("server went away after its window closed")
                finish()
                return
            if not session.is_running() or session.proc.pid() != pid_before:
                FAILURES.append("the JVM died (or restarted) when the window closed")
                finish()
                return
            STEPS.append("server still running after the window was closed "
                         "(pid %s)" % pid_before)
            reopen(session, pid_before)
            return

        app.after(6000, check, time.time())

    def reopen(session, pid_before):
        row_session_id = session.id
        page._open_window(row_session_id)
        win = session._window
        if win is None:
            FAILURES.append("Open from the panel did not bring the window back")
            finish()
            return
        text = console_of(win)
        if "Done (" not in text:
            FAILURES.append("reopened window lost the console history")
        elif session.proc.pid() != pid_before:
            FAILURES.append("reopen changed the process")
        else:
            STEPS.append("reopened from the panel with history intact (%d chars)"
                         % len(text))
        invite_card(session)

    def invite_card(session):
        """The Invite window has to be the thing that tells a friend where to connect.

        It used to print join_address() whatever happened, so a session with no tunnel
        advertised localhost:25567 - an address that cannot work - and after the
        playit.sock bug it could print a file path. Check all three states the card can
        be in, and that its Retry tunnel button calls through to the session.
        """
        page._open_invite(session.id)
        win = getattr(page, "_invite_win", None)
        if win is None:
            FAILURES.append("the invite window did not open")
            return restart_from_panel(session)

        def texts(w, out=None):
            out = [] if out is None else out
            for c in w.winfo_children():
                try:
                    t = c.cget("text")
                    if isinstance(t, str) and t.strip():
                        out.append(t)
                except Exception:
                    pass
                texts(c, out)
            return out

        def check_public():
            got = " | ".join(texts(win))
            if session.public_address and session.public_address in got:
                STEPS.append("invite shows the public address (%s)" % session.public_address)
            else:
                FAILURES.append("invite did not show the address: " + got[:160])
            if "localhost:" in got:
                FAILURES.append("invite offered localhost to a friend: " + got[:120])
            if ".sock" in got:
                FAILURES.append("invite offered the agent socket: " + got[:120])
            if "Retry tunnel" not in got:
                FAILURES.append("invite has no Retry tunnel button: " + got[:120])
            # the LAN line must be there too - it is real, but only on this network
            if "MC " not in got:
                FAILURES.append("invite forgot which version friends need: " + got[:120])
            win.destroy()
            restart_from_panel(session)

        win.after(400, check_public)



    def restart_from_panel(session):
        old_pid = session.proc.pid()
        page._act(session.id, "restart")

        def wait_new(t0):
            alive = session.is_running() and session.proc.pid() not in (0, old_pid)
            text = console_of(session._window) if session._window else ""
            if alive and "Done (" in text:
                STEPS.append("Restart from the panel brought it back on a new pid "
                             "(%s -> %s), status=%s"
                             % (old_pid, session.proc.pid(), session.status))
                assert session.status == "running", session.status
                assert session.restarts == 1, session.restarts
                kill_from_panel(session)
            elif session.status == "crashed":
                FAILURES.append("restart crashed it: %s" % session.error)
                finish()
            elif time.time() - t0 > BOOT_TIMEOUT:
                FAILURES.append("restart timed out (status=%s, pid=%s)" % (
                    session.status, session.proc.pid() if session.proc else None))
                finish()
            else:
                app.after(1000, wait_new, t0)

        app.after(1500, wait_new, time.time())

    def kill_from_panel(session):
        page._act(session.id, "kill")

        def check(t0):
            if session.is_running():
                if time.time() - t0 > 25:
                    FAILURES.append("Kill from the panel did not end the server")
                    finish()
                else:
                    app.after(500, check, t0)
                return
            assert session.status == "stopped", session.status
            assert session.error is None, "a kill must not read as a crash: %s" % session.error
            assert app.servers.running_count() == 0
            STEPS.append("Kill from the panel stopped it, listed as finished")
            app.servers.clear_finished()
            assert app.servers.all_sessions() == []
            STEPS.append("Clear finished removed it from the panel")
            finish()

        app.after(300, check, time.time())

    app.after(400, start_and_wait)
    app.mainloop()
    for s in STEPS:
        print("  ok -", s)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
