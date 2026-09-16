"""Hosted-server sessions: the part that keeps a server alive.

A session owns the Java process, its log file, its tunnel and its status. It
lives on the app (``app.servers``), NOT in a window, which is what makes the
"close the tab but keep the server up" behaviour work: the window is just a view
that attaches and detaches, and the console history can always be rebuilt from
the log file the JVM is writing to.

Events are pushed to listeners as ``(event, session)`` where event is one of:
"status", "line", "exit", "address", "claim", "tunnel_status". Callbacks may come
from a background thread - UI listeners must schedule onto the main thread.
"""
import itertools
import os
import re
import threading
import time

from .. import paths
from . import launcher
from . import resources
from . import server_host
from . import tunnel as tunnel_mod


_JOIN_RE = re.compile(r"\]:\s+<?([A-Za-z0-9_]{1,16})>?\s+joined the game", re.IGNORECASE)
_LEAVE_RE = re.compile(r"\]:\s+<?([A-Za-z0-9_]{1,16})>?\s+left the game", re.IGNORECASE)
_DONE_RE = re.compile(r"Done \(", re.IGNORECASE)


class ServerSession:
    """One running (or starting, or finished) hosted server."""

    _ids = itertools.count(1)

    def __init__(self, manager, instance, ram_mb=2048, tunnel_provider="auto"):
        self.id = "srv%d" % next(ServerSession._ids)
        self.manager = manager
        self.instance = instance
        self.ram_mb = int(ram_mb)
        self.tunnel_provider = tunnel_provider

        self.proc = None                      # server_host.ServerProcess
        self.tunnel = None
        self.status = "starting"               # starting|running|stopping|stopped|crashed
        self.message = "Preparing server files..."
        self.error = None
        self.exit_code = None
        self.exit_seconds = None
        self.started_at = time.time()
        self.stopped_at = None
        self.jar_path = None
        self.java_major = None
        self.public_address = None
        self.claim_url = None
        self.tunnel_message = ""
        self.players = set()
        self.lag_warnings = 0
        self.restarts = 0
        self.user_stopped = False
        self.log_path = None
        self._window = None
        self._cpu = None
        self._listeners = []
        self._lock = threading.RLock()
        self._worker = None

    # ------------------------------------------------------------- identity
    @property
    def name(self):
        return self.instance.name

    @property
    def port(self):
        try:
            return server_host.server_port(self.instance)
        except Exception:
            return 0

    @property
    def mc_version(self):
        return self.instance.mc_version

    @property
    def loader(self):
        return self.instance.loader

    def is_running(self):
        return bool(self.proc and self.proc.is_running())

    def uptime(self):
        end = self.stopped_at or (time.time() if self.is_running() else None)
        return (end - self.started_at) if end else None

    def join_address(self):
        """What friends type into Minecraft: public tunnel address, or LAN host."""
        if self.public_address:
            return self.public_address
        return "localhost:%d" % self.port

    # ------------------------------------------------------------- listeners
    def add_listener(self, fn):
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn):
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def notify(self, event):
        with self._lock:
            targets = list(self._listeners)
        for fn in targets:
            try:
                fn(event, self)
            except Exception:
                pass

    def set_status(self, text, status=None):
        self.message = text
        if status:
            self.status = status
        self.notify("status")

    # ------------------------------------------------------------- resources
    def resource_snapshot(self):
        """Allocated vs actually-used, for the meters in the server window."""
        pid = self.proc.pid() if self.proc else 0
        if pid and self._cpu is None:
            self._cpu = resources.CpuMeter(pid)
        elif not pid:
            self._cpu = None
        snap = resources.sample(pid, self._cpu)
        rss = snap.get("rss_bytes")
        snap["ram_used_mb"] = round(rss / (1024.0 * 1024.0), 1) if rss else 0.0
        snap["cpu_percent"] = snap.get("cpu_percent") or 0.0
        snap["allocated_mb"] = self.ram_mb
        snap["pid"] = pid or None
        snap["players"] = len(self.players)
        snap["uptime"] = self.uptime()
        snap["lag_warnings"] = self.lag_warnings
        try:
            snap["log_bytes"] = os.path.getsize(self.log_path) if self.log_path else 0
        except Exception:
            snap["log_bytes"] = 0
        return snap

    def history(self, max_bytes=120000):
        """Console lines from the log file, so a reopened window isn't empty."""
        if not self.log_path or not os.path.exists(self.log_path):
            return list(self.proc.log_lines) if self.proc else []
        try:
            size = os.path.getsize(self.log_path)
            with open(self.log_path, "rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                    f.readline()
                data = f.read().decode("utf-8", "replace")
            return data.splitlines()
        except Exception:
            return list(self.proc.log_lines) if self.proc else []

    # ------------------------------------------------------------- commands
    def send(self, command):
        if not (command or "").strip():
            return False
        ok = bool(self.proc and self.proc.send(command))
        if ok:
            self.notify("line")
        return ok

    # ------------------------------------------------------------- shutdown
    def stop(self):
        """Graceful: 'stop' on the console, so the world is saved properly."""
        if not self.is_running():
            return False
        self.user_stopped = True
        self.set_status("Saving and stopping...", "stopping")
        self.proc.stop()
        return True

    def kill(self):
        """Hard: no save, for a wedged server."""
        self.user_stopped = True
        if self.proc:
            self.proc.kill()
        self.set_status("Killed from the panel.", "stopped")
        self._teardown_tunnel()

    def restart(self):
        if self._worker and self._worker.is_alive():
            self.set_status("Still working on it - wait for this one to finish.")
            return
        self.user_stopped = True
        self.restarts += 1
        self.set_status("Restarting...", "stopping")
        self._teardown_tunnel()
        threading.Thread(target=self._restart_worker, daemon=True).start()

    def retry_tunnel(self):
        self._teardown_tunnel()
        self.public_address = None
        self.claim_url = None
        threading.Thread(target=self._start_tunnel, daemon=True).start()

    def _restart_worker(self):
        proc = self.proc
        if proc:
            proc.stop()
            end = time.time() + 40
            while proc.is_running() and time.time() < end:
                time.sleep(0.3)
            if proc.is_running():
                proc.kill()
                time.sleep(1.0)
        self._launch(fresh=False)

    # ------------------------------------------------------------- internals
    def run(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._launch, kwargs={"fresh": True},
                                        daemon=True)
        self._worker.start()

    def _launch(self, fresh=True):
        self._worker = threading.current_thread()
        try:
            # always move back to "starting" first: after a Restart the session was
            # "stopping", and nothing else sets it - the console would then be
            # live while the panel still said stopping (and "running" would never
            # be reached, because that transition only fires from "starting").
            self.set_status("Preparing server files (jar + mods)...", "starting")
            self.user_stopped = False
            self.exit_code = None
            self.exit_seconds = None
            self.stopped_at = None
            self.players = set()
            self.started_at = time.time()

            self.jar_path = server_host.prepare(self.instance, self.manager.config,
                                                 status=self._prep_status)
            self.java_major = self.instance.data.get("_server_java_major")
            if fresh and self.instance.data.get("_server_is_fresh") and \
                    self.loader == "fabric":
                self.set_status("First start: downloading Minecraft's own server "
                                "files. About a minute, then it is cached.")
            self.set_status("Checking Java...")
            java_exe = launcher.ensure_java(self.mc_version, launcher.Progress(),
                                            self.manager.custom_java_path())
            self.set_status("Starting the server...")
            log_dir = os.path.join(paths.LOG_DIR, "servers")
            os.makedirs(log_dir, exist_ok=True)
            self.log_path = os.path.join(
                log_dir, "%s-%s.log" % (self.instance.id, time.strftime("%Y%m%d-%H%M%S")))
            proc = server_host.ServerProcess(self.instance, self.manager.config)
            proc.on_line = self._on_line
            proc.on_exit = self._on_exit
            proc.start(self.jar_path, java_exe, ram_mb=self.ram_mb, log_path=self.log_path)
            self.proc = proc
            # take the first resource sample now: the CPU meter needs two readings
            # before it can show a percentage, and the window opens within a second
            try:
                self.resource_snapshot()
            except Exception:
                pass
            self.set_status("Waiting for the server to finish loading...", "starting")
            self._start_tunnel()
        except Exception as e:
            self.error = str(e)
            self.status = "crashed"
            self.stopped_at = time.time()
            self.message = "Couldn't start: " + (self.error or "unknown error")
            self.notify("exit")
            self.notify("status")

    def _prep_status(self, text):
        # prepare() reports on its own thread; surface it as a status line
        self.set_status(text)

    def _on_line(self, line):
        m = _JOIN_RE.search(line)
        if m:
            self.players.add(m.group(1))
        else:
            m = _leave_or_none(line)
            if m:
                self.players.discard(m)
        if "can't keep up" in line.lower():
            self.lag_warnings += 1
        if self.status == "starting" and _DONE_RE.search(line):
            self.set_status("Running - %s" % self.join_address(), "running")
        self.notify("line")

    def _on_exit(self, code):
        self.exit_code = code
        self.exit_seconds = getattr(self.proc, "exit_seconds", None)
        self.stopped_at = time.time()
        self._teardown_tunnel()
        if self.user_stopped:
            self.status = "stopped"
            self.error = None
            self.message = "Stopped."
        else:
            self.error = server_host.diagnose(self.proc.log_lines if self.proc else [],
                                              code, self.exit_seconds)
            self.status = "crashed"
            self.message = "The server closed on its own."
        self.notify("exit")
        self.notify("status")

    def _start_tunnel(self):
        provider = self.tunnel_provider or self.instance.data.get("tunnel_provider", "bore")
        bore_port = self.instance.data.get("bore_static_port")
        playit_sec = self.instance.data.get("playit_secret")
        t = tunnel_mod.Tunnel(
            local_port=self.port,
            provider=provider,
            bore_static_port=bore_port,
            playit_secret=playit_sec,
        )
        t.on_status = lambda msg: self._tunnel_update(msg)
        t.on_line = lambda msg: self._tunnel_update(msg)
        t.on_address = self._on_address
        t.on_claim = self._on_claim
        self.tunnel = t
        try:
            t.start()
        except Exception as e:
            self.tunnel_message = "Tunnel failed: " + str(e)[:160]
            self.notify("tunnel_status")

    def _tunnel_update(self, msg):
        if msg:
            self.tunnel_message = str(msg)[:200]
            self.notify("tunnel_status")

    def _on_address(self, addr):
        self.public_address = addr
        self.set_status("Running - %s" % addr, "running")
        self.notify("address")

    def _on_claim(self, url):
        self.claim_url = url
        self.notify("claim")

    def _teardown_tunnel(self):
        t = self.tunnel
        self.tunnel = None
        if t:
            try:
                t.stop()
            except Exception:
                pass


def _leave_or_none(line):
    m = _LEAVE_RE.search(line)
    return m.group(1) if m else None


class ServerSessionManager:
    """Holds every hosted server the launcher started, across windows and tabs."""

    def __init__(self, config_store, app=None):
        self.config = config_store
        self.app = app          # main window, used as the parent for server windows
        self.sessions = []
        self._listeners = []
        self._lock = threading.RLock()

    # --------------------------------------------------------------- config
    def custom_java_path(self):
        try:
            return self.config.get("custom_java_path", "") or ""
        except Exception:
            return ""

    def tunnel_provider(self):
        try:
            return self.config.get("tunnel_provider", "auto") or "auto"
        except Exception:
            return "auto"

    # ------------------------------------------------------------- listeners
    def add_listener(self, fn):
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn):
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def notify(self, event):
        with self._lock:
            targets = list(self._listeners)
        for fn in targets:
            try:
                fn(event, self)
            except Exception:
                pass

    # ---------------------------------------------------------------- create
    def start(self, instance, ram_mb=2048, tunnel_provider=None, open_window=True):
        """Create a session and start it in the background. Returns immediately."""
        if tunnel_provider is None:
            tunnel_provider = self.tunnel_provider()
        existing = self.running_for(instance)
        if existing:
            raise RuntimeError("'%s' is already hosting a server. Stop it first, "
                               "or open its window." % instance.name)
        session = ServerSession(self, instance, ram_mb=ram_mb,
                                tunnel_provider=tunnel_provider)
        with self._lock:
            self.sessions.append(session)
        session.add_listener(lambda event, s: self.notify(event))
        session.run()
        self.notify("added")
        if open_window:
            self._open_window_for(session)
        return session

    def _open_window_for(self, session):
        # imported lazily so core never depends on the UI package
        try:
            from ..ui.server_window import ServerWindow
        except Exception:
            return
        master = getattr(self, "app", None)
        try:
            session._window = ServerWindow(session, master)
        except Exception:
            pass

    # ------------------------------------------------------------------- get
    def get(self, session_id):
        with self._lock:
            for s in self.sessions:
                if s.id == session_id:
                    return s
        return None

    def running_for(self, instance):
        with self._lock:
            for s in self.sessions:
                if s.instance.id == instance.id and (s.is_running() or
                                                      s.status in ("starting", "stopping")):
                    return s
        return None

    def all_sessions(self):
        with self._lock:
            return list(self.sessions)

    def running_count(self):
        return sum(1 for s in self.all_sessions() if s.is_running())

    def finished(self):
        return [s for s in self.all_sessions()
                if s.status in ("stopped", "crashed") and not s.is_running()]

    def clear_finished(self):
        with self._lock:
            dead = [s for s in self.sessions
                    if s.status in ("stopped", "crashed") and not s.is_running()]
            for s in dead:
                s._listeners = []
                win = getattr(s, "_window", None)
                if win is not None:
                    try:
                        win.destroy()
                    except Exception:
                        pass
                s._window = None
            self.sessions = [s for s in self.sessions if s not in dead]
        if dead:
            self.notify("removed")
        return len(dead)

    def forget(self, session):
        with self._lock:
            if session in self.sessions:
                self.sessions.remove(session)
        win = getattr(session, "_window", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            session._window = None
        self.notify("removed")

    def reopen_window(self, session):
        self._open_window_for(session)

    # -------------------------------------------------------------- shutdown
    def shutdown(self, keep_running=True):
        """Called when the launcher quits.

        keep_running=True leaves the JVMs alone on purpose: a hosted server is
        meant to survive closing the launcher (its console is a log file, so no
        pipe backs up and freezes it). Their own 'stop'/'kill' buttons, or
        shutdown(False), are how they end.
        """
        if keep_running:
            return False
        for s in self.all_sessions():
            if s.is_running():
                s.stop()
        end = time.time() + 20
        while time.time() < end and self.running_count():
            time.sleep(0.3)
        for s in self.all_sessions():
            if s.is_running():
                s.kill()
        return True
