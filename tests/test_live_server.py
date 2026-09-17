"""End-to-end: a hosted server, its lifecycle, and a real public tunnel.

Run with:  python tests/test_live_server.py

Needs internet. It boots a genuine Fabric server through ServerSessionManager
(the same path the launcher uses), opens a real bore tunnel for it, and then
performs an actual Minecraft "server list ping" *through the public address* -
so the tunnel is proven to carry Minecraft traffic, not just to have started.
It also checks the two behaviours the panel is supposed to have: closing the
window keeps the server up, and only Stop / Restart / Kill end it.
"""
import json
import os
import socket
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp(prefix="divine-live-"))

from divineclient import paths                                   # noqa: E402
from divineclient.core import server_host, server_sessions       # noqa: E402
from divineclient.core.instances import Instance                 # noqa: E402

_PIDS = []
MC = os.environ.get("DIVINE_LIVE_MC", "1.16.5")
BOOT_TIMEOUT = float(os.environ.get("DIVINE_LIVE_TIMEOUT", "420"))


class Config(dict):
    """Stands in for core.config.Config."""

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value

    def save(self):
        pass


# --------------------------------------------------------------- MC protocol
def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(f):
    num = 0
    for i in range(5):
        b = f.read(1)
        if not b:
            raise EOFError("tunnel closed mid-packet")
        byte = b[0]
        num |= (byte & 0x7F) << (7 * i)
        if not (byte & 0x80):
            break
    return num


def server_list_ping(host, port, timeout=25):
    """A real status request, exactly what Minecraft sends when it lists a server."""
    def mcstring(text):
        raw = text.encode("utf-8")
        return _varint(len(raw)) + raw

    handshake = b"\x00" + _varint(754) + mcstring(host) + port.to_bytes(2, "big") + _varint(1)
    packet = _varint(len(handshake)) + handshake
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(packet + b"\x01\x00")
        f = sock.makefile("rb")
        _length = _read_varint(f)
        _packet_id = _read_varint(f)
        str_len = _read_varint(f)
        body = f.read(str_len)
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------- test
def main():
    paths.ensure_dirs()
    inst = Instance({"id": "livetest", "name": "Live Test", "mc_version": MC,
                     "loader": "fabric", "loader_version": None})
    cfg = Config(ram_mb=1024, custom_java_path="", tunnel_provider="bore")
    mgr = server_sessions.ServerSessionManager(cfg, app=None)

    print("== starting a hosted server through the manager", flush=True)
    session = mgr.start(inst, ram_mb=1024, tunnel_provider="bore", open_window=False)
    assert session in mgr.sessions

    # a window would normally be open; simulate closing it. The server must live.
    session._window = "pretend-window"

    deadline = time.time() + BOOT_TIMEOUT
    booted = False
    while time.time() < deadline:
        if session.status == "crashed":
            raise AssertionError("server crashed on start: %s\n%s" % (
                session.error, "\n".join(session.history()[-25:])))
        if any("Done (" in ln for ln in (session.proc.log_lines if session.proc else [])):
            booted = True
            break
        time.sleep(1.5)
    assert booted, "server never finished booting"
    _PIDS.append(session.proc.pid())
    print("   booted, status=%s, pid=%s" % (session.status,
                                            session.proc.pid()))
    assert session.is_running()

    print("== resource meters", flush=True)
    snap = session.resource_snapshot()
    print("   %s" % {k: snap[k] for k in ("allocated_mb", "rss_bytes", "cpu_percent",
                                          "players", "uptime")})
    assert snap["allocated_mb"] == 1024, snap
    assert (snap["rss_bytes"] and snap["rss_bytes"] > 64 * 1024 * 1024), (
        "a running server must be holding real memory: %r" % snap)
    assert snap["uptime"] and snap["uptime"] > 5, snap

    print("== public tunnel (bore, no account)", flush=True)
    end = time.time() + 90
    while time.time() < end and not session.public_address:
        if session.proc is None or not session.proc.is_running():
            raise AssertionError("server died while waiting for the tunnel")
        time.sleep(1.5)
    assert session.public_address, ("no address from the tunnel: %s"
                                   % session.tunnel_message)
    host, _, port = session.public_address.partition(":")
    print("   address: %s" % session.public_address)
    assert host and port.isdigit(), session.public_address

    print("== pinging the server through the public address", flush=True)
    status = server_list_ping(host, int(port))
    desc = status.get("description")
    if isinstance(desc, dict):          # modern servers send a text component
        desc = desc.get("text") or ""
    print("   players: %s  version: %s  motd: %s" % (
        (status.get("players") or {}).get("online"),
        (status.get("version") or {}).get("name"), str(desc)[:60]))
    assert status.get("version"), "a status reply must name the version: %s" % status
    assert MC in (status.get("version") or {}).get("name", ""), status
    assert (status.get("players") or {}).get("online") == 0, status

    print("== closing the window keeps it running", flush=True)
    session._window = None            # what ServerWindow._on_close_request does
    assert session.is_running() and mgr.running_count() == 1
    time.sleep(4)
    assert session.is_running(), "the JVM died when its window went away"
    print("   still up after the window closed")

    print("== Stop from the panel saves and exits cleanly", flush=True)
    assert session.stop()
    end = time.time() + 90
    while session.is_running() and time.time() < end:
        time.sleep(0.5)
    assert not session.is_running(), "server did not stop"
    # the exit callback runs on the log tailer's thread; give it a beat to land
    end = time.time() + 15
    while session.status == "stopping" and time.time() < end:
        time.sleep(0.2)
    assert session.status == "stopped", session.status
    assert session.error is None, "a requested stop must not be reported as a crash"
    assert session.exit_code == 0, "Minecraft should exit 0 after 'stop': %r" % session.exit_code
    assert (session.tunnel is None or not session.tunnel.is_running()), (
        "the tunnel must go down with the server")
    print("   exit code %s, tunnel closed" % session.exit_code)

    print("== panel bookkeeping", flush=True)
    assert mgr.running_count() == 0
    assert session in mgr.finished(), "a finished server stays listed until cleared"
    assert mgr.clear_finished() == 1
    assert mgr.all_sessions() == []
    if _PIDS:
        print("   (started jvm pids: %s)" % ", ".join(str(p) for p in _PIDS))
    print("\nLIVE SERVER + TUNNEL TEST PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # never leave a JVM burning CPU behind if an assert tripped
        try:
            if session.is_running():
                session.kill()
        except Exception:
            pass
