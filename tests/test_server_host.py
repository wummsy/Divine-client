"""Tests for the server-hosting fixes.

Run with:  python tests/test_server_host.py          (no dependencies)
      or:  pytest tests/test_server_host.py

The last test boots a real Fabric Minecraft server through the same code the
Servers page uses, and types a command into its console, so the console pipe,
the stdin pipe and the jar checks are all exercised for real. Set
DIVINE_TEST_FAST=1 to skip that slow one.
"""
import io
import json
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# keep every test inside its own data dir
_TMP = tempfile.mkdtemp(prefix="divine-test-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")

from divineclient import paths                      # noqa: E402
from divineclient.core import server_host            # noqa: E402
from divineclient.core import java_runtime           # noqa: E402
from divineclient.core.instances import Instance     # noqa: E402

paths.ensure_dirs()


def inst(iid="ayyy", mc="1.16.5", loader="fabric"):
    return Instance({"id": iid, "name": iid, "mc_version": mc, "loader": loader,
                     "loader_version": None})


FABRIC_LAUNCH_MAIN = "net.fabricmc.loader.impl.launch.server.FabricServerLauncher"
FABRIC_BOOT_MAIN = "net.fabricmc.installer.ServerLauncher"


def fake_jar(path, valid=True, main_class=FABRIC_LAUNCH_MAIN, extra_pad=4096):
    """Write a jar-shaped file (a real zip with a runnable manifest, or garbage).

    ``main_class`` is the manifest's Main-Class, which is the one thing that decides
    whether Divine treats the file as an installed server or as Fabric's bootstrap. The
    padding exists only to make a *broken* jar bigger than a valid one - the size test
    this replaced used to be the only thing telling them apart.
    """
    if valid:
        manifest = "Manifest-Version: 1.0\r\nMain-Class: %s\r\n\r\n" % main_class
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", manifest)
            if extra_pad:
                z.writestr("padding.txt", "x" * extra_pad)
    else:
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04truncated")
    return path


FABRIC_TEST_CLASSPATH = ("libraries/test/lib.jar versions/1.21.4/server-1.21.4.jar")


def fake_fabric_install(sdir, main_class=FABRIC_LAUNCH_MAIN, complete=True):
    """Pretend Fabric's own bootstrap has finished in this folder.

    The generated launch jar is a manifest and nothing else: its Class-Path names the
    library jars and the Minecraft server jar it needs next to itself, so a fixture that
    claims a finished install has to provide those too. ``complete=False`` writes the
    jar and the folders but not the files - the shape a first start interrupted by a
    power cut or a Stop press leaves behind.
    """
    launch = os.path.join(sdir, server_host.FABRIC_LAUNCH_NAME)
    with zipfile.ZipFile(launch, "w") as z:
        z.writestr("META-INF/MANIFEST.MF",
                   "Manifest-Version: 1.0\r\nMain-Class: %s\r\nClass-Path: %s\r\n\r\n"
                   % (main_class, FABRIC_TEST_CLASSPATH))
    lib = os.path.join(sdir, "libraries", "test", "lib.jar")
    game = os.path.join(sdir, "versions", "1.21.4", "server-1.21.4.jar")
    os.makedirs(os.path.dirname(lib), exist_ok=True)
    os.makedirs(os.path.dirname(game), exist_ok=True)
    if complete:
        fake_jar(lib)
    if complete:
        with open(game, "wb") as f:            # the game jar is judged by its size
            f.write(b"\0" * (2 << 20))
    return launch


def stub_fabric_downloads(box):
    """Keep prepare() off the network: record downloads, write a jar-shaped file.

    Returns (calls, patch, unpatch); ``calls`` collects the destination paths.
    """
    calls = []
    real = (server_host._download, server_host._fabric_server_url,
            server_host._vanilla_server_url)

    def fake_download(url, dest, status=None):
        calls.append(dest)
        fake_jar(dest, main_class=box.get("main_class", FABRIC_BOOT_MAIN))
        return dest

    server_host._download = fake_download
    server_host._fabric_server_url = lambda mc: ("http://x/fabric-server.jar", "0.16.9")
    server_host._vanilla_server_url = lambda mc: ("http://x/server.jar", 17)
    return calls, real


def case(name):
    print("  " + name, flush=True)
    return name


def test_can_read_detects_a_locked_file():
    """os.path.isfile() says yes while Java would still fail - the actual bug."""
    d = tempfile.mkdtemp(prefix="divine-sdir-", dir=_TMP)
    jar = fake_jar(os.path.join(d, "fabric-server-launch.jar"))
    assert server_host._can_read(jar)
    assert server_host.wait_jar_readable(jar, attempts=1) == jar

    os.chmod(jar, 0)          # exists, but nobody can open it
    assert os.path.isfile(jar), "isfile must still be True for this case to mean anything"
    assert not server_host._can_read(jar), "a file we cannot open must not pass"
    try:
        server_host.wait_jar_readable(jar, attempts=1)
        raise AssertionError("expected RuntimeError for an unreadable jar")
    except RuntimeError as e:
        assert "locked" in str(e).lower(), str(e)
    finally:
        os.chmod(jar, 0o644)


def test_corrupt_jar_rejected():
    d = tempfile.mkdtemp(prefix="divine-sdir-", dir=_TMP)
    assert not server_host._is_valid_jar(fake_jar(os.path.join(d, "a.jar"), valid=False))
    assert server_host._is_valid_jar(fake_jar(os.path.join(d, "b.jar"), valid=True))
    assert not server_host._is_valid_jar(os.path.join(d, "missing.jar"))
    open(os.path.join(d, "empty.jar"), "wb").close()
    assert not server_host._is_valid_jar(os.path.join(d, "empty.jar"))


def test_download_rejects_a_truncated_body():
    """A short body must not become a half-written jar Java can't open."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    payload = b"not-a-jar-at-all" * 10

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload) * 3))  # lie
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp(prefix="divine-sdir-", dir=_TMP)
    dest = os.path.join(d, "server.jar")
    try:
        server_host._download("http://127.0.0.1:%d/x.jar" % port, dest)
        raise AssertionError("expected RuntimeError on a truncated download")
    except RuntimeError as e:
        assert "download" in str(e).lower(), str(e)
    finally:
        srv.shutdown()
    assert not os.path.exists(dest + ".part"), "no .part file should be left behind"


def test_ports_are_unique_per_instance():
    a, b = inst("ayyy"), inst("other")
    assert server_host.pick_default_port(a) == server_host.pick_default_port(inst("ayyy"))
    assert server_host.pick_default_port(a) != server_host.pick_default_port(b)
    assert a.mc_version and 1024 <= server_host.pick_default_port(a) <= 65535


def test_busy_port_moves_to_a_free_one():
    i = inst("portuser")
    sdir = server_host.server_dir(i)
    props = os.path.join(sdir, "server.properties")
    if not os.path.exists(props):
        server_host.write_properties(i, server_host.default_properties(i))
    before = server_host.server_port(i)

    srv = socket.socket()
    srv.bind(("127.0.0.1", before))
    srv.listen(1)
    try:
        assert server_host.port_in_use(before)
        after = server_host.ensure_free_port(i)
    finally:
        srv.close()
    assert after != before, "an occupied port must be moved off"
    assert server_host.server_port(i) == after, "the move must be persisted"
    assert not server_host.port_in_use(after)


def test_console_java_never_returns_javaw():
    real_platform = java_runtime.sys.platform
    try:
        java_runtime.sys.platform = "win32"
        d = tempfile.mkdtemp(prefix="divine-java-", dir=_TMP)
        bindir = os.path.join(d, "bin")
        os.makedirs(bindir)
        open(os.path.join(bindir, "javaw.exe"), "wb").close()
        # (a) sibling java.exe wins
        open(os.path.join(bindir, "java.exe"), "wb").close()
        assert java_runtime.console_java(os.path.join(bindir, "javaw.exe")) == \
            os.path.join(bindir, "java.exe")
        # (b) no sibling -> keep looking in the runtime, then JAVA_HOME
        os.remove(os.path.join(bindir, "java.exe"))
        home = os.path.join(d, "java-home")
        os.makedirs(os.path.join(home, "bin"))
        open(os.path.join(home, "bin", "java.exe"), "wb").close()
        os.environ["JAVA_HOME"] = home
        assert java_runtime.console_java(os.path.join(bindir, "javaw.exe")) == \
            os.path.join(home, "bin", "java.exe"), "JAVA_HOME fallback"
        os.environ.pop("JAVA_HOME")
        # (c) a console launcher is left alone
        assert java_runtime.console_java(os.path.join(bindir, "java.exe")) == \
            os.path.join(bindir, "java.exe")
    finally:
        java_runtime.sys.platform = real_platform
    # (d) on mac/linux there is no javaw at all, so nothing is rewritten
    assert java_runtime.console_java("/usr/bin/java") == "/usr/bin/java"


def test_diagnose_turns_silent_exits_into_messages():
    cases = [
        (["Error: Unable to access jarfile C:\\x\\fabric-server-launch.jar"], 1, "antivirus"),
        (["[Server thread/ERROR]: Failed to bind to the server"], 1, "port"),
        (["Failed to start minecraft server", "You need to agree to the EULA"], 1, "eula"),
        (["java.lang.UnsupportedClassVersionError: Unsupported class file major version 65"], 1, "Java"),
        (["java.lang.OutOfMemoryError: Java heap space"], 1, "memory"),
        (["net.fabricmc.loader.impl.FormattedException: IncompatibleModsException"], 1, "mod"),
        (["java.net.UnknownHostException: meta.fabricmc.net"], 1, "internet"),
        (["org.apache.logging.log4j.core.LoggerContext@1: ok"], 1, "seconds"),
    ]
    for lines, code, want in cases:
        msg = server_host.diagnose(lines, code, 4)
        assert msg and want.lower() in msg.lower(), (lines[0][:40], want, msg)
    assert server_host.diagnose([], 1, 3) and "without printing" in server_host.diagnose([], 1, 3)
    assert server_host.diagnose(["[Server] Done (31.6s)!"], 0, 600) is None


def test_start_refuses_to_launch_without_a_readable_jar():
    i = inst("nofound")
    server_host.server_dir(i)
    p = server_host.ServerProcess(i, None)
    try:
        p.start(os.path.join(server_host.server_dir(i), "fabric-server-launch.jar"),
                "/usr/bin/java")
        raise AssertionError("expected RuntimeError for a missing jar")
    except RuntimeError as e:
        assert "missing or damaged" in str(e).lower(), str(e)


def test_start_refuses_windowless_java():
    """javaw.exe is what turns a crash into an unreadable popup - must be refused."""
    i = inst("javawcase")
    sdir = server_host.server_dir(i)
    jar = fake_jar(os.path.join(sdir, "fabric-server-launch.jar"))
    real_win = server_host._is_windows
    real_plat = java_runtime.sys.platform
    real_which = java_runtime.shutil.which
    real_home = java_runtime.os.environ.get("JAVA_HOME")
    try:
        server_host._is_windows = lambda: True
        java_runtime.sys.platform = "win32"
        # a machine that only has the windowless JRE: nothing to fall back on
        java_runtime.shutil.which = lambda name: None
        java_runtime.os.environ.pop("JAVA_HOME", None)
        p = server_host.ServerProcess(i, None)
        try:
            p.start(jar, os.path.join(sdir, "javaw.exe"))
            raise AssertionError("expected RuntimeError for javaw-only")
        except RuntimeError as e:
            assert "javaw" in str(e).lower(), str(e)
    finally:
        server_host._is_windows = real_win
        java_runtime.sys.platform = real_plat
        java_runtime.shutil.which = real_which
        if real_home:
            java_runtime.os.environ["JAVA_HOME"] = real_home


def test_stale_jar_for_a_changed_mc_version():
    """Instance moved to another Minecraft version: the old install must be dropped."""
    i = inst("stalecheck", mc="1.16.5")
    sdir = server_host.server_dir(i)
    os.makedirs(sdir, exist_ok=True)
    jar = fake_fabric_install(sdir)
    first = os.path.getmtime(jar)
    server_host._write_state(sdir, {"mc_version": "1.16.5", "loader": "fabric",
                                     "jar": server_host.FABRIC_LAUNCH_NAME,
                                     "fabric_loader": "0.15.0"})
    calls, real = stub_fabric_downloads({})
    try:
        i.data["mc_version"] = "1.21.4"
        run = server_host.prepare(i, None)
        assert os.path.exists(jar) is False, "the old version's launch jar survived"
        assert calls, "moving versions must fetch the bootstrap for the new one"
        assert os.path.basename(run) == server_host.FABRIC_BOOT_NAME, run
        st = server_host._read_state(sdir)
        assert st.get("mc_version") == "1.21.4", st
        assert st.get("fabric_loader") == "0.16.9", "the loader installed must be remembered"
        assert i.data.get("_server_is_fresh") is True, "first prepare must report fresh"
        # the bootstrap has now done its job: a second prepare has nothing to do
        fake_fabric_install(sdir)
        os.utime(run, (first, first))
        before = len(calls)
        assert server_host.prepare(i, None) == jar
        assert len(calls) == before, "a finished install must not download again"
        assert i.data.get("_server_is_fresh") is False
    finally:
        server_host._download, server_host._fabric_server_url, \
            server_host._vanilla_server_url = real


def test_real_server_boots_and_takes_console_commands():
    """End to end through ServerProcess: jar check, mod filter, stdout, stdin.

    1.21.4 because that is what the JDK here can run, and because a modern version is
    where Fabric's bootstrap install (libraries/, versions/, the generated launch jar)
    actually gets exercised.
    """
    if os.environ.get("DIVINE_TEST_FAST") == "1":
        try:
            import pytest
            pytest.skip("DIVINE_TEST_FAST=1")
        except Exception:
            return

    try:
        import urllib.request
        urllib.request.urlopen("https://meta.fabricmc.net", timeout=3)
    except Exception:
        try:
            import pytest
            pytest.skip("Fabric meta is unreachable (offline/sandboxed environment)")
        except Exception:
            return

    i = inst("e2e", mc="1.21.4")
    # a client-only mod in the instance must not be carried onto the server - if
    # it is, the Fabric loader refuses to boot and the window closes at once
    src = os.path.join(i.game_dir, "mods")
    os.makedirs(src, exist_ok=True)
    fake_mod(os.path.join(src, "purely-client.jar"), env="client")
    sdir = server_host.server_dir(i)
    os.makedirs(os.path.join(sdir, "mods"), exist_ok=True)
    fake_mod(os.path.join(sdir, "mods", "purely-client.jar"), env="client")
    jar = server_host.prepare(i, None)
    assert server_host._is_valid_jar(jar)
    assert "purely-client.jar" not in os.listdir(os.path.join(sdir, "mods")), \
        "a client-only mod was copied onto the server"
    assert not os.path.exists(os.path.join(sdir, "mods", "purely-client.jar")), \
        "a stale client-only mod survived in the server folder"

    lines, state = [], {}
    p = server_host.ServerProcess(i, None)
    p.on_line = lambda ln: lines.append(ln)
    p.on_exit = lambda code: state.__setitem__("code", code)
    from divineclient.core import adoptium, java_runtime
    java_exe = adoptium.find_java_exe(21)
    if not java_exe:
        class _P:
            def set_status(self, *a): pass
            def set_progress(self, *a): pass
            def set_fraction(self, *a): pass
            def set_max(self, *a): pass
        os_name, arch = java_runtime._os_arch()
        java_exe = adoptium.install(21, os_name, arch, progress=_P())
    p.start(jar, java_exe, ram_mb=1024)

    deadline = time.time() + 240
    while time.time() < deadline:
        if any("Done (" in ln for ln in lines):
            break
        if state.get("code") is not None:
            break
        time.sleep(1)
    assert any("Done (" in ln for ln in lines), \
        "server never started: %s" % "\n".join(lines[-25:])
    assert p.is_running()

    # the server must answer on the console AND on the configured port
    assert p.send("list"), "typing a command into stdin failed"
    t = time.time()
    while time.time() - t < 25 and not any('There are' in ln for ln in lines):
        time.sleep(0.5)
    assert any('There are' in ln for ln in lines), \
        "no console reply to a command: %s" % "\n".join(lines[-10:])

    port = server_host.server_port(i)
    s = socket.socket()
    s.settimeout(3)
    s.connect(("127.0.0.1", port))
    s.close()

    # and it must shut down cleanly, without being flagged as a crash
    p.stop()
    t = time.time()
    while p.is_running() and time.time() - t < 60:
        time.sleep(0.5)
    assert not p.is_running(), "server did not stop"
    assert p.exit_seconds and p.exit_seconds > 10
    assert server_host.diagnose(p.log_lines, p.exit_code, p.exit_seconds) is None or \
        p.exit_code not in (0, None)


def fake_mod(path, meta="fabric.mod.json", env="*", nested=False):
    """A jar that looks like a mod to the loader (so we can read its side)."""
    import json as _json
    body = {"id": os.path.splitext(os.path.basename(path))[0], "name": "test mod",
            "version": "1.0"}
    if env is not None:
        body["environment"] = env
    if nested:
        body = {"quilt_mod": dict(body, id="quilted")}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(meta, _json.dumps(body))
        z.writestr("padding.txt", "x" * 2048)
    return path


def test_client_only_mods_are_not_copied_to_the_server():
    """A client-only mod is the classic 'server prints one line and quits'."""
    i = inst("mods-case")
    assert server_host._mod_environment(fake_mod(os.path.join(_TMP, "m1.jar"), env="client")) == "client"
    assert server_host._mod_environment(fake_mod(os.path.join(_TMP, "m2.jar"), env="*")) == "*"
    assert server_host._mod_environment(fake_mod(os.path.join(_TMP, "m3.jar"), env="server")) == "server"
    # no metadata at all -> assume it belongs on both sides, never hide a mod
    assert server_host._mod_environment(fake_mod(os.path.join(_TMP, "m4.jar"), env=None)) == "*"
    assert server_host._mod_environment(
        fake_mod(os.path.join(_TMP, "m5.jar"), meta="quilt.mod.json", env="client",
                 nested=True)) == "client"

    sdir = server_host.server_dir(i)
    src = os.path.join(i.game_dir, "mods")
    dst = os.path.join(sdir, "mods")
    os.makedirs(dst, exist_ok=True)
    for n in ("client-only.jar", "works-both.jar", "dedicated.jar"):
        fake_mod(os.path.join(src, n), env={"client-only.jar": "client",
                                            "works-both.jar": "*",
                                            "dedicated.jar": "server"}[n])
    # something an older Divine already copied across must get cleaned out
    fake_mod(os.path.join(dst, "client-only.jar"), env="client")

    skipped = server_host.sync_mods(i, sdir)
    assert skipped == ["client-only.jar"], skipped
    names = sorted(os.listdir(dst))
    assert names == ["dedicated.jar", "works-both.jar"], names



# ---------------------------------------------------------------- tunnel units
def test_tunnel_strips_ansi_and_reads_the_address():
    from divineclient.core import tunnel as tmod
    raw = "\x1b[2m2026-09-02T09:04:22Z\x1b[0m \x1b[32m INFO\x1b[0m listening at bore.pub:60234"
    assert "\x1b" not in tmod.strip_ansi(raw)
    t = tmod.Tunnel(local_port=25565, provider="bore")
    seen = []
    t.on_address = seen.append
    t._handle(tmod.strip_ansi(raw))
    assert seen == ["bore.pub:60234"], seen
    # a second address line must not overwrite the first
    t._handle("listening at bore.pub:99999")
    assert t.public_address == "bore.pub:60234"
    # local listener lines are never a public address
    t2 = tmod.Tunnel(local_port=25565, provider="bore")
    t2._handle("tunnel to 127.0.0.1:25565 established")
    assert t2.public_address is None, t2.public_address
    # playit claim links are picked up
    t3 = tmod.Tunnel(local_port=1, provider="playit")
    claims = []
    t3.on_claim = claims.append
    t3._handle("Please claim this instance: https://playit.gg/claim/abc123")
    assert claims and claims[0].startswith("https://playit.gg/claim/")


def test_the_pack_picks_the_newest_release_not_just_the_last_row():
    """Modrinth returns a project's builds in an arbitrary order and mix of channels."""
    from divineclient.core import mods

    def v(num, kind, date, fname=None):
        return {"version_number": num, "version_type": kind, "date_published": date,
                "name": num, "files": [{"filename": fname or ("m-%s.jar" % num),
                                        "url": "https://example/%s.jar" % num,
                                        "primary": True, "size": 10,
                                        "hashes": {"sha512": "ab" * 64}}]}

    builds = [v("0.6.2", "beta", "2025-12-01"),        # newest by date, wrong channel
              v("0.6.13", "release", "2025-04-04"),    # what we want
              v("0.6.9", "release", "2025-02-19"),
              v("0.6.10", "release", "2024-11-01")]    # older date, higher number? no
    got = mods._best_file(builds)
    assert got["filename"] == "m-0.6.13.jar", got
    # a higher number with an older date still wins over 0.6.2 as *text*: check that
    assert mods._best_file([v("0.6.2", "release", "2026-01-01"),
                            v("0.6.13", "release", "2020-01-01")])["filename"] == "m-0.6.13.jar"
    # nothing but pre-releases -> take the newest of those rather than no mod at all
    assert mods._best_file([v("0.3.1", "alpha", "2024-01-01"),
                            v("0.3.2", "beta", "2024-02-01")])["filename"] == "m-0.3.2.jar"
    assert mods._best_file([]) is None
    assert mods._best_file([{"version_type": "release", "files": []}]) is None
    assert mods._best_file([{"version_type": "release",
                             "files": [{"filename": "sources.jar"}]}]) is None
    case("the pack takes the newest release, not the newest row")


def test_the_pack_notices_a_mod_the_user_already_has():
    """Duplicate mod ids stop Fabric from starting at all, so the pack must defer."""
    from divineclient.core import mods
    for a, b in (("sodium-fabric-0.6.13+mc1.21.4.jar", "sodium-mc1.20.1-0.4.10.jar"),
                 ("lithium-fabric-mc1.21.4-0.15.3.jar", "lithium-fabric-0.15.3+mc1.21.4.jar"),
                 ("ImmediatelyFast-Fabric-1.8.7+1.21.4.jar", "immediatelyfast-1.5.0.jar")):
        assert mods._stem(a) == mods._stem(b), (mods._stem(a), mods._stem(b))
    assert mods._stem("cull-less-leaves-1.20.1-2.2.2.jar") == "cull-less-leaves"
    assert mods._stem("fabric-api-0.119.4+1.21.4.jar") == "fabric-api"
    assert mods._stem("modmenu-13.0.4.jar") == "modmenu"
    case("a mod's name is found the same way whatever the file is called")


def test_a_bad_download_is_rejected_and_leaves_nothing_behind(tmp=None):
    """Offline, yanked, HTML-instead-of-a-jar, wrong hash: all must be silent skips."""
    import http.server
    import socketserver
    import threading
    import zipfile as _z
    from divineclient.core import mods

    good = io.BytesIO()
    with _z.ZipFile(good, "w") as zf:
        zf.writestr("fabric.mod.json", '{"id":"tester","version":"1"}')
        zf.writestr("data.bin", "y" * 500)
    GOOD = good.getvalue()
    payloads = {"ok.jar": GOOD, "hash.jar": GOOD, "junk.jar": b"<html>502 bad gateway</html>"}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = payloads[self.path.strip("/")]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp(prefix="divine-pack-", dir=_TMP)
    real_resolve, real_req = mods._resolve, mods.requests.get
    try:
        def fake(slug, mc, loader="fabric"):
            if slug == "gone":
                raise mods.requests.exceptions.ConnectionError("no network")
            if slug == "no-build":
                return None
            name = {"ok": "ok.jar", "junk": "junk.jar", "hash": "hash.jar"}[slug]
            body = payloads[name]
            # "hash" gets a digest of the *right* file it does not have, "junk" gets
            # the correct digest of an HTML body: each must fail for its own reason.
            want = {"ok": hashlib.sha512(GOOD).hexdigest(),
                    "hash": hashlib.sha512(b"something else entirely").hexdigest(),
                    "junk": hashlib.sha512(body).hexdigest()}[slug]
            return {"url": "http://127.0.0.1:%d/%s" % (port, name),
                    "filename": {"ok": "packok", "junk": "packjunk",
                                 "hash": "packhash"}[slug] + "-1.0.jar",
                    "sha512": want, "size": len(body),
                    "name": "t", "version": "1", "type": "release"}

        mods._resolve = fake
        installed, skipped = mods.install_pack([("ok", "fine"), ("junk", "not a jar"),
                                                ("hash", "wrong bytes"), ("gone", "offline"),
                                                ("no-build", "nothing for this version")],
                                               "1.21.4", d)
        assert [i.split("@")[0] for i in installed] == ["ok"], (installed, skipped)
        assert len(skipped) == 4, skipped
        assert any("checksum" in x for x in skipped), skipped      # sha512 mismatch caught
        assert any("not a mod jar" in x for x in skipped), skipped  # HTML body refused
        assert not [f for f in os.listdir(d) if f.endswith(".part")], "a .part was left behind"
        jars = [f for f in os.listdir(d) if f.endswith(".jar")]
        assert jars == ["packok-1.0.jar"], jars
        # and the same slug again is a no-op, not a second copy
        inst2, skip2 = mods.install_pack([("ok", "fine")], "1.21.4", d)
        assert inst2 == ["ok@packok-1.0.jar"] and not skip2, (inst2, skip2)
        # a jar the user put there themselves wins over ours
        d2 = tempfile.mkdtemp(prefix="divine-pack-user-", dir=_TMP)
        open(os.path.join(d2, "packok-0.9.jar"), "wb").write(b"theirs")
        mods._resolve = lambda slug, mc, loader="fabric": fake("ok", mc, loader)
        inst3, skip3 = mods.install_pack([("ok", "fine")], "1.21.4", d2)
        assert not inst3 and "ok(already installed)" in skip3, (inst3, skip3)
        assert open(os.path.join(d2, "packok-0.9.jar"), "rb").read() == b"theirs"
        # what the pack wrote down is readable by the UI later
        state = json.load(open(os.path.join(d, mods.PACK_STATE)))
        assert state["entries"]["ok"]["filename"] == "packok-1.0.jar", state
        assert state["mc_version"] == "1.21.4"
    finally:
        mods._resolve, mods.requests.get = real_resolve, real_req
        srv.shutdown()
    case("a pack download is verified, and any failure is a silent skip")


def test_the_pack_lists_are_safe_for_their_side():
    """Nothing client-only may be installed on a server, or vice versa by accident."""
    from divineclient.core import mods
    for name, entries in (("client", mods.PERFORMANCE_PACK), ("server", mods.SERVER_PACK)):
        slugs = [s for s, _ in entries]
        assert len(slugs) == len(set(slugs)), (name, slugs)
        for slug, desc in entries:
            assert re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug), (name, slug)
            assert len(desc) > 20 and desc[0].isupper() and desc.endswith("."), (slug, desc)
    client_only = {"sodium", "modmenu", "iris", "dynamic-fps", "entityculling",
                   "immediatelyfast", "ebe", "cull-less-leaves"}
    assert not (client_only & {s for s, _ in mods.SERVER_PACK}), \
        "a client-only mod would stop a hosted server booting"
    assert mods.PERFORMANCE_PACK[0][0] == "fabric-api", "dependencies come first"
    assert "fabric-api" not in [s for s, _ in mods.SERVER_PACK], "the server gets it via sync"
    assert len(mods.PERFORMANCE_PACK) >= 10, "the point of this was more mods"
    case("both pack lists are shaped for the side they install on")


def test_prepare_adds_server_mods_only_when_asked():
    """The server pack hangs off the same switch as the client one, and only there."""
    from divineclient.core import mods, server_host as SH
    calls = []
    real = mods.install_server_pack
    try:
        mods.install_server_pack = lambda mc, d, **kw: (calls.append(mc), ([], []))[1]
        i = inst("packgate")
        sdir = tempfile.mkdtemp(prefix="divine-sdir-", dir=_TMP)
        assert SH.install_server_perf_mods(i, sdir, None) == ([], []), "no config must not fetch"
        assert not calls, calls
        SH.install_server_perf_mods(i, sdir, {"auto_performance_mods": False})
        assert not calls, "the setting is off, but it fetched anyway"
        SH.install_server_perf_mods(i, sdir, {})
        assert calls == ["1.16.5"], calls
        calls.clear()
        boom = Exception("modrinth is down")
        mods.install_server_pack = lambda *a, **k: (_ for _ in ()).throw(boom)
        got = SH.install_server_perf_mods(i, sdir, {})      # must not raise at the caller
        assert got == ([], []), got
    finally:
        mods.install_server_pack = real
    case("prepare()'s server pack respects the switch and survives a dead API")


def test_the_lan_address_helper_never_lies():
    """`lan_ip()` is printed as joinable, so a wrong value is worse than None."""
    import socket as _s
    from divineclient.core import server_host as SH
    ip = SH.lan_ip()
    assert ip is None or (_s.inet_aton(ip) and not ip.startswith("127.")), ip
    # an isolated box with no route still gets an answer, not a crash or "0.0.0.0"
    assert not (ip or "").endswith(".0"), ip


def test_a_socket_path_is_never_the_public_address():
    """Regression: the agent's own control socket used to be published as the address.

    playit is told to put its socket in ``<game dir>/tunnel/playit.sock``, and that one
    log line contains both "tunnel" - so it reads like an announcement - and
    "playit.sock" - so the host pattern matches it. The launcher then put a file name
    where a join address belongs, which is worse than showing nothing: a friend types
    it, Minecraft says the address could not be resolved, and nobody can tell that was
    our bug and not their network.
    """
    from divineclient.core import tunnel as tmod
    sock = "/home/me/.divineclient/game/tunnel/playit.sock"
    for line in ("[INFO] agent: socket=" + sock,
                 "tunnel: C:\\Users\\me\\tunnel\\playit.sock",
                 "address file: playit.sock",
                 "using socket playit.sock for the tunnel api"):
        assert tmod.parse_address(line) is None, line
        t = tmod.Tunnel(local_port=25565, provider="playit")
        t._handle(line)
        assert t.public_address is None, (line, t.public_address)
    # a real address on the same line still wins - the guard must not blind the parser
    assert tmod.parse_address("socket path: %s (tunnel ready at 7c9f.craft.playit.gg)"
                             % sock) == "7c9f.craft.playit.gg"
    assert tmod.parse_address("forwarding 127.0.0.1:25565 to %s -> bore.pub:51234"
                              % sock) == "bore.pub:51234"
    # the playit claim link is a URL, with slashes, and is still found (it is matched
    # on the raw line, not the path-stripped one)
    t = tmod.Tunnel(local_port=1, provider="playit")
    got = []
    t.on_claim = got.append
    t._handle("claim this tunnel at https://playit.gg/connect/ab12 to finish setup")
    assert got == ["https://playit.gg/connect/ab12"], got
    assert t.public_address is None


def test_tunnel_provider_order_and_none():
    from divineclient.core import tunnel as tmod
    assert tmod.Tunnel(provider="auto")._provider_order() == ["bore", "playit"]
    assert tmod.Tunnel(provider="bore")._provider_order() == ["bore"]
    assert tmod.Tunnel(provider="none")._provider_order() == []
    t = tmod.Tunnel(local_port=25565, provider="none")
    t.start()                       # must not raise, not download, not spawn
    assert t.proc is None and t.public_address is None


def test_bore_asset_url_resolves_or_falls_back():
    from divineclient.core import tunnel as tmod
    url = tmod._latest_bore_url("win32")
    assert url.startswith("https://github.com/ekzhang/bore/releases/download/")
    assert "windows" in url
    # a broken API must not break the download: pinned URL is the safety net
    import urllib.request
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    try:
        assert tmod._latest_bore_url("linux") == tmod.BORE_PINNED["linux"]
    finally:
        urllib.request.urlopen = real


# ------------------------------------------------------------- session manager
def test_manager_refuses_a_second_server_on_one_instance():
    from divineclient.core import server_sessions as ssm
    cfg = {"tunnel_provider": "none", "custom_java_path": ""}
    mgr = ssm.ServerSessionManager(cfg)
    i = inst("dupcase")
    # build the running session directly instead of going through start(), so no
    # real download/JVM is involved in a test about the refusal itself
    busy = ssm.ServerSession(mgr, i, ram_mb=1024, tunnel_provider="none")
    busy.status = "running"
    busy.proc = type("P", (), {"is_running": lambda self: True})()
    mgr.sessions.append(busy)
    assert mgr.running_count() == 1
    assert mgr.running_for(i) is busy
    try:
        mgr.start(i, ram_mb=1024, tunnel_provider="none", open_window=False)
        raise AssertionError("expected a refusal for a second server on the same instance")
    except RuntimeError as e:
        assert "already hosting" in str(e), str(e)
    # a *different* instance must still be welcome - but this is a unit test, so
    # stub the worker out: an unstubbed start() really downloads Java and boots a
    # JVM that nothing here ever stops (that orphan held ~700MB on this box).
    # The live path is covered by tests/test_live_server.py.
    launched = []
    real_launch = ssm.ServerSession._launch
    ssm.ServerSession._launch = lambda self, fresh=True: launched.append(self.id)
    try:
        other = mgr.start(inst("othercase"), ram_mb=1024, tunnel_provider="none",
                          open_window=False)
    finally:
        ssm.ServerSession._launch = real_launch
    assert other in mgr.sessions
    deadline = time.time() + 3
    while not launched and time.time() < deadline:
        time.sleep(0.05)
    assert launched == [other.id], "start() must hand the launch to the session worker"
    for _s in list(mgr.sessions):     # leave no sessions behind for the next test
        mgr.forget(_s)


def test_manager_lifecycle_without_a_window():
    """The session must outlive its window, and be stoppable from the panel."""
    from divineclient.core import server_sessions as ssm
    i = inst("lifecycle")
    fake = ssm.ServerSession(None, i, ram_mb=1024, tunnel_provider="none")
    fake.status = "running"

    class DeadProc:
        def __init__(self):
            self.alive = True
        def is_running(self):
            return self.alive
        def pid(self):
            return 0
        def kill(self):
            self.alive = False
        def stop(self):
            self.alive = False
        log_lines = []
        exit_seconds = 3

    fake.proc = DeadProc()
    assert fake.is_running()
    fake.kill()
    assert not fake.is_running()
    assert fake.user_stopped is True
    assert fake.status == "stopped"
    assert fake.error is None, "a kill we asked for must not look like a crash"


def test_resource_formats_and_snapshot_shape():
    from divineclient.core import resources
    assert resources.human_bytes(None) == "\u2014"
    assert resources.human_bytes(1024) == "1.0 KB"
    assert "MB" in resources.human_bytes(50 * 1024 * 1024)
    assert resources.format_duration(3725) == "1h 02m"   # 3725s = 1h02m05s
    assert resources.format_duration(65) == "1m 05s"
    snap = resources.sample(os.getpid(), resources.CpuMeter(os.getpid()))
    assert set(snap) == {"rss_bytes", "cpu_percent"}
    assert snap["rss_bytes"] and snap["rss_bytes"] > 0, "we must read our own RSS"
    assert resources.sample(0)["rss_bytes"] is None
    # a second sample produces a cpu percentage
    time.sleep(0.2)
    m = resources.CpuMeter(os.getpid())
    pid = os.getpid()
    rss, secs = resources._rss_posix(pid)
    m.update(secs)
    time.sleep(0.25)
    _, secs2 = resources._rss_posix(pid)
    pct = m.update(secs2)
    assert pct is None or pct >= 0.0


def test_player_tracking_and_lag_counting():
    from divineclient.core import server_sessions as ssm
    i = inst("players")
    s = ssm.ServerSession(None, i, ram_mb=1024, tunnel_provider="none")
    s._on_line("[Server thread/INFO]: Alice joined the game")
    s._on_line("[Server thread/INFO]: Bob joined the game")
    assert s.players == {"Alice", "Bob"}
    s._on_line("[Server thread/INFO]: Bob left the game")
    assert s.players == {"Alice"}
    s._on_line("[Server thread/WARN]: Can't keep up! Is the server overloaded?")
    assert s.lag_warnings == 1
    assert s.resource_snapshot()["players"] == 1


def test_ui_modules_have_no_dangling_self_method_calls():
    """Every self._thing() the UI calls must exist.

    Rewriting big Tkinter classes is exactly where a helper gets dropped and the
    page only breaks when a user clicks it, so check it statically instead.

    Members are collected per class *and inherited from base classes defined in this
    repo*: the rails share a SlideRail that owns _open/_width/_job, and calling that a
    dangling reference would be a false alarm on the one pattern the UI uses most.
    """
    import ast
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = []
    top = os.path.join(root, "divineclient")
    for dirpath, _dirs, names in os.walk(top):
        if "__pycache__" in dirpath:
            continue
        files += [os.path.join(dirpath, n) for n in names if n.endswith(".py")]

    own = {}       # (file, class) -> members defined or assigned in that class
    bases = {}     # (file, class) -> base class names
    by_name = {}   # class name -> [(file, class)]
    for path in files:
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        key0 = os.path.basename(path)
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            key = (key0, cls.name)
            members = {f.name for f in cls.body if isinstance(f, ast.FunctionDef)}
            # class-level assignments are attributes too (weights, hashes, title maps)
            for stmt in cls.body:
                if isinstance(stmt, ast.Assign):
                    members |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    members.add(stmt.target.id)
            for node in ast.walk(cls):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == "self" and isinstance(node.ctx, ast.Store)):
                    members.add(node.attr)
            own[key] = members
            bases[key] = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                          for b in cls.bases]
            by_name.setdefault(cls.name, []).append(key)

    cache = {}

    def members_of(key, seen=()):
        """Own members plus those of any base class we can see in this repo."""
        if key in cache:
            return cache[key]
        if key in seen:
            return set()
        out = set(own.get(key, set()))
        for name in bases.get(key, ()):
            for parent in by_name.get(name, ()):
                out |= members_of(parent, seen + (key,))
        cache[key] = out
        return out

    problems = []
    for path in files:
        key0 = os.path.basename(path)
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            have = members_of((key0, cls.name))
            for node in ast.walk(cls):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == "self" and isinstance(node.ctx, ast.Load)):
                    name = node.attr
                    if name.startswith("_") and name not in have:
                        problems.append("%s: %s.%s" % (key0, cls.name, name))
    assert not problems, "undefined members referenced:\n  " + "\n  ".join(sorted(set(problems)))


def test_agent_checksums_are_pinned_and_enforced():
    """The launcher downloads a program and runs it, so it must verify the bytes.

    This is the antivirus-relevant one: a downloaded agent that is not the published
    binary gets deleted instead of launched, and a cached one is re-checked before it
    is started. Uses a fake digest so the test does not depend on GitHub.
    """
    import hashlib
    from divineclient.core import tunnel

    for (kind, plat), digest in tunnel.AGENT_SHA256.items():
        assert len(digest) == 64, "%s/%s digest is not a sha256" % (kind, plat)
        assert all(c in "0123456789abcdef" for c in digest), (kind, plat)
    assert "v0.6.0" in tunnel.BORE_PINNED["win32"], "pin the digest with the release"

    tmp = tempfile.mkdtemp(prefix="divine-agent-")
    path = os.path.join(tmp, "bore")
    with open(path, "wb") as f:
        f.write(b"the genuine bore binary, as far as this test is concerned" * 64)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    saved = dict(tunnel.AGENT_SHA256)
    try:
        tunnel.AGENT_SHA256[("bore", "linux")] = digest
        assert tunnel.verify_agent("bore", path, "linux") == digest, "good file rejected"

        # a truncated or edited download is refused and removed
        with open(path, "ab") as f:
            f.write(b"<injected>")
        try:
            tunnel.verify_agent("bore", path, "linux")
            raise AssertionError("tampered agent was accepted")
        except tunnel.AgentChecksumError as e:
            assert "deleted" in str(e), e
        assert not os.path.exists(path), "the bad file must not stay for next time"

        # nothing pinned for that platform: skip, do not break the optional provider
        assert tunnel.verify_agent("bore", __file__, "darwin") is None
        # a missing file is not a checksum failure (it gets downloaded next)
        assert tunnel.verify_agent("bore", os.path.join(tmp, "nope"), "linux") is None

        # and the documented escape hatch for people who build their own agent
        tunnel.VERIFY_OFF = True
        try:
            assert tunnel.verify_agent("bore", __file__, "linux") is None
        finally:
            tunnel.VERIFY_OFF = tunnel.os.environ.get("DIVINE_SKIP_AGENT_VERIFY") == "1"
    finally:
        tunnel.AGENT_SHA256.clear()
        tunnel.AGENT_SHA256.update(saved)
        shutil.rmtree(tmp, ignore_errors=True)
    case("downloaded agents are checksum-verified, refused on mismatch")


def test_client_endpoint_lookup_prefers_the_domain():
    """The site moved to a domain; old installs and broken DNS must still work."""
    from divineclient.core import endpoints, social
    import requests

    assert endpoints.SITE == "https://divineclient.wispbyte.org"
    assert endpoints.current_base(None) == endpoints.SITE

    chain = endpoints.candidates(None)
    assert chain[0] == endpoints.SITE, chain
    assert endpoints.LEGACY[0] in chain, "the old ip:port has to stay a fallback"

    class Cfg(dict):
        def get(self, key, default=""):
            return dict.get(self, key, default)

    mine = Cfg({"friends_api_base": "http://mybox.lan:8787"})
    assert endpoints.candidates(mine)[0] == "http://mybox.lan:8787", "an override must win"
    inherited = Cfg({"friends_api_base": "http://78.154.103.46:10230"})
    assert endpoints.candidates(inherited)[0] == endpoints.SITE, \
        "an address inherited from an old default must not lock out the domain"
    assert endpoints.site_url("download") == endpoints.SITE + "/download"
    assert endpoints.site_url("") == endpoints.SITE, "the landing page too"

    class Resp:
        """Enough of a requests.Response for the 500 case: non-JSON body included."""
        status_code, ok, text, content = 500, False, "boom", b""

        def json(self):
            raise ValueError("no json here")

    calls = []
    real = requests.request
    try:
        def fake(method, url, **kw):
            calls.append(url)
            return Resp()

        requests.request = fake
        # A real HTTP error must surface to the user (with the server's own words
        # when it sends any) and must NOT be retried against the legacy address -
        # a 500 means we reached the right server.
        for text, want in (("boom", "boom"), ("", "HTTP 500")):
            Resp.text = text
            calls.clear()
            try:
                social._request("GET", None, "/api/friends")
                raise AssertionError("an HTTP error should surface, not fall through")
            except social.SocialError as e:
                assert want in str(e), (text, str(e))
            assert len(calls) == 1, "a 500 from the domain must not be retried elsewhere"

        calls.clear()

        def dead(method, url, **kw):
            calls.append(url)
            raise requests.ConnectionError("nope")

        requests.request = dead
        try:
            social._request("GET", None, "/api/friends")
            raise AssertionError("unreachable server should raise")
        except social.SocialError as e:
            assert f"tried {len(chain)} addresses" in str(e), e
        assert calls == [base + "/api/friends" for base in chain], calls
    finally:
        requests.request = real
        endpoints._last_good = None
    case("launcher tries the domain first, falls back only on a connection error")


def test_site_pages_render_and_old_hosts_redirect():
    """The public site: real pages, the new domain, and no dead legacy links.

    Renders the shipped Flask app through its test client, so a template that throws
    or a page still advertising the old address fails here rather than in production.
    """
    import importlib

    root = os.path.dirname(HERE)
    server_dir = os.path.join(root, "server")
    tmp = tempfile.mkdtemp(prefix="divine-site-")
    saved_db = os.environ.get("DIVINE_DB")
    os.environ["DIVINE_DB"] = os.path.join(tmp, "divine.db")     # never touch the dev db
    sys.path.insert(0, server_dir)
    sys.modules.pop("app", None)
    try:
        site = importlib.import_module("app")
        importlib.reload(site)
    finally:
        sys.path.remove(server_dir)

    client = site.app.test_client()

    # what a visitor can reach: three pages, their assets, the news feed
    for path in ("/", "/download", "/link", "/api/news", "/robots.txt", "/sitemap.xml",
                 "/static/emblem.png", "/static/logo.png", "/static/og.png"):
        r = client.get(path)
        assert r.status_code == 200, "%s -> %s" % (path, r.status_code)
        if path.endswith((".png", ".ico")):
            assert len(r.get_data()) > 400, "%s served an empty %s" % (path, r.mimetype)
    assert client.get("/assets/config.json").status_code == 404, "must not serve source"
    assert client.get("/discord").status_code in (301, 302), "invite redirect"
    assert "discord" in client.get("/discord").headers["Location"]
    # the invite must be a joinable one, never the placeholder this used to default to
    assert site.DISCORD_INVITE_URL == "https://discord.gg/ER2haQtach", site.DISCORD_INVITE_URL
    for path in ("/", "/download", "/link"):
        body = client.get(path).get_data(as_text=True)
        assert "discord.gg/divineclient" not in body, path + " still links the fake invite"
        assert "discord.gg/ER2haQtach" in body, path + " lost the real invite"
        # The app mark is built in Python and handed to Jinja, which autoescapes.
        # That used to print the markup as words - every page opened with a big line
        # reading "<svg class=&quot;cube&quot; ... <polygon points=..." - so it has to
        # come out as a real element, and nothing of it may survive in the *text*.
        assert '<svg class="cube"' in body, path + " shows the mark as text"
        assert "&lt;svg" not in body and "&lt;polygon" not in body, path
        said = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body))
        assert "polygon" not in said.lower(), path + " leaks markup into the visible text"
    assert client.get("/api/news").get_json().get("news"), "news feed is empty"

    # the partners shelf is gone from the site: page, API, and promo folder. The art
    # moved to tools/, where the generator that owns it lives.
    for gone in ("/partners", "/api/partners", "/static/promo/wide.png",
                 "/static/promo/og.png"):
        assert client.get(gone).status_code == 404, gone + " is still served"
    assert not os.path.isdir(os.path.join(server_dir, "static", "promo"))
    assert os.path.isfile(os.path.join(root, "tools", "promo", "wide.png")), \
        "the ad moved out of the web root but no longer exists"

    # a visitor gets the app, what it needs and where to ask. Nothing else.
    for word in ("antivirus", "smartscreen", "get-filehash", "defender", "git clone",
                 "code sign", "partner", "run it from source", "powershell",
                 "bore.pub", "playit", "port forward", "port-forward", "tunnel",
                 "server hosting", "host a server", "25565", "#hosting"):
        for path in ("/", "/download", "/link", "/robots.txt"):
            body = client.get(path).get_data(as_text=True).lower()
            assert word not in body, "%s on %s still talks about %s" % (word, path, word)

    for path in ("/", "/download", "/link"):
        body = client.get(path).get_data(as_text=True)
        assert '<a href="' + site.PUBLIC_BASE_URL not in body, \
            path + " sends its own navigation off-origin (links must be relative)"
        assert 'rel="canonical"' in body and "/static/og.png" in body, \
            path + " lost its meta or its social card"
        assert "devwummsy" not in body, path + " advertises the dead hostname"
        assert "78.154" not in body, path + " advertises the bare IP"
        assert "divineclient.wispbyte.org" in body, path + " has no canonical link"

    # the advice itself stays in the repo, where an admin can still find it
    for f in ("defender_exclusions.ps1", "add_defender_exclusions.bat"):
        assert os.path.isfile(os.path.join(root, "tools", f)), f + " left the repo"
    assert os.path.isfile(os.path.join(root, "docs", "ANTIVIRUS.md")), "docs/ANTIVIRUS.md left"

    # address handling: old hosts bounce to the domain, the API and dev hosts never do
    r = client.get("/", headers={"Host": "devwummsy.site.je"})
    assert r.status_code == 301, r.status_code
    assert r.headers["Location"].startswith(site.SITE_DEFAULT), r.headers["Location"]
    assert client.get("/download", headers={"Host": "78.154.103.46"}).status_code == 301
    assert client.get("/api/news", headers={"Host": "78.154.103.46"}).status_code == 200
    assert client.get("/static/emblem.png",
                      headers={"Host": "78.154.103.46"}).status_code == 200
    for host in ("127.0.0.1:8787", "localhost", "10.0.0.5:8787"):
        assert client.get("/", headers={"Host": host}).status_code == 200, host
    assert client.get("/", headers={"Host": "some-other-domain.com"}).status_code == 200
    # an old bookmark to a page that no longer exists moves to the new domain first
    # (and 404s there) rather than dying on the deprecated host
    r = client.get("/nope", headers={"Host": "78.154.103.46"})
    assert r.status_code == 301 and r.headers["Location"].endswith("/nope"), r.status_code


HOLDER_SRC = """
import os, sys, time
sys.path.insert(0, %r)
from divineclient.core import server_host as SH
sdir, hold = sys.argv[1], float(sys.argv[2])
handles = []
for p in SH._level_lock_files(sdir):
    if not os.path.isfile(p):
        continue
    f = open(p, "r+b")
    if sys.platform == "win32":
        import msvcrt; msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl; fcntl.lockf(f.fileno(), fcntl.LOCK_EX)
    handles.append(f)
print("HELD", flush=True)
time.sleep(hold)
for f in handles:
    try:
        if sys.platform == "win32":
            import msvcrt; msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl; fcntl.lockf(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    f.close()
""" % os.path.dirname(HERE)


def _write_world(sdir, level_name="world"):
    """A server folder that has been started once, so the world files exist."""
    os.makedirs(os.path.join(sdir, level_name), exist_ok=True)
    with open(os.path.join(sdir, "session.lock"), "wb") as f:
        f.write(b"# Session created by server with id 1234\n")
    with open(os.path.join(sdir, level_name, "level.dat"), "wb") as f:
        f.write(b"\x0a" * 64)
    with open(os.path.join(sdir, "server.properties"), "w", encoding="utf-8") as f:
        f.write("level-name=%s\nserver-port=25565\n" % level_name)


def _hold_locks(holder_path, sdir, seconds):
    """Start a process that locks the world the way a running server does."""
    return subprocess.Popen([sys.executable, holder_path, sdir, str(seconds)],
                            stdout=subprocess.PIPE, text=True)


def test_world_lock_is_detected_and_waited_out():
    """Stop-then-Start (or an orphaned JVM) used to hand Java a locked level.dat.

    The real failure this guards is the one from the report: the server dies with
    "The process cannot access the file because another process has locked a portion
    of the file". A genuine second process holds the lock here, so the probe, the
    wait and the message are all exercised for real.
    """
    holder_path = os.path.join(_TMP, "lock_holder.py")
    with open(holder_path, "w", encoding="utf-8") as f:
        f.write(HOLDER_SRC)
    sdir = os.path.join(_TMP, "server-lock")
    os.makedirs(sdir, exist_ok=True)
    _write_world(sdir)

    files = [os.path.basename(p) for p in server_host._level_lock_files(sdir)]
    assert files[:2] == ["session.lock", "level.dat"], files
    assert server_host._lock_is_free(os.path.join(sdir, "session.lock"))
    assert server_host.wait_folder_free(sdir, attempts=2) is None

    # the level-name in server.properties decides which world is checked
    _write_world(sdir, "plot_smp")
    names = [os.path.relpath(p, sdir).replace(os.sep, "/")
             for p in server_host._level_lock_files(sdir)]
    assert names[1].startswith("plot_smp/level.dat"), names
    _write_world(sdir)

    holder = _hold_locks(holder_path, sdir, 25)
    try:
        assert holder.stdout.readline().strip() == "HELD", "holder failed to lock"
        assert not server_host._lock_is_free(os.path.join(sdir, "session.lock")), \
            "a locked file read as free"
        seen = []
        t0 = time.time()
        try:
            server_host.wait_folder_free(sdir, status=seen.append, attempts=4,
                                         hold_pause=0.3)
            raise AssertionError("wait_folder_free accepted a locked folder")
        except RuntimeError as e:
            waited = time.time() - t0
            assert 0.8 < waited < 4.0, "did not actually wait (%.1fs)" % waited
            assert "session.lock" in str(e) or "level.dat" in str(e), e
            assert "antivirus" in str(e), e
            assert seen and "world" in seen[0], seen
        if sys.platform != "win32":
            assert holder.pid in server_host._java_holders(sdir), \
                "the holder's pid should be named in the message"
        holder.kill()
    finally:
        try:
            holder.wait(timeout=5)
        except Exception:
            pass
    case("a locked world is spotted, waited for, and explained with the PID")


def test_prepare_waits_before_launching_the_server():
    """The pre-flight check is wired into prepare(), where it can still help."""
    holder_path = os.path.join(_TMP, "lock_holder.py")
    if not os.path.isfile(holder_path):
        with open(holder_path, "w", encoding="utf-8") as f:
            f.write(HOLDER_SRC)
    inst_ = inst("lockprep", loader="vanilla")   # vanilla: server.jar, no mod sync
    sdir = server_host.server_dir(inst_)
    os.makedirs(sdir, exist_ok=True)
    jar = os.path.join(sdir, "server.jar")
    fake_jar(jar)                                   # a real zip, so it looks valid
    _write_world(sdir)

    saved = (server_host._is_valid_jar, server_host._vanilla_server_url,
             server_host.sync_mods, server_host.wait_jar_readable,
             server_host.ensure_free_port)
    try:
        server_host._is_valid_jar = lambda path: os.path.isfile(path)
        server_host._vanilla_server_url = lambda v: ("http://x/server.jar", 17)
        server_host.sync_mods = lambda *a, **k: []
        server_host.wait_jar_readable = lambda path, status=None, attempts=12: path
        server_host.ensure_free_port = lambda instance, status=None: 25565

        holder = _hold_locks(holder_path, sdir, 2.0)
        assert holder.stdout.readline().strip() == "HELD"
        t0 = time.time()
        try:
            # the lock lets go after ~2s, so this must come through, not raise
            got = server_host.prepare(inst_, {}, status=lambda m: None)
            waited = time.time() - t0
            assert got == jar, got
            assert waited > 1.5, "prepare() did not wait for the world: %.1fs" % waited
            ok_msg = True
        except RuntimeError as e:
            raise AssertionError("prepare() gave up instead of waiting: %s" % e)
        finally:
            holder.wait(timeout=15)
        assert ok_msg
    finally:
        (server_host._is_valid_jar, server_host._vanilla_server_url,
         server_host.sync_mods, server_host.wait_jar_readable,
         server_host.ensure_free_port) = saved
    case("prepare() holds the launch until the world is free, then starts")


def test_diagnose_names_a_locked_world_not_the_jar():
    """The reported stack trace has to come out as a sentence, not Java's noise."""
    log = ["[14:13:05] [main/ERROR]: Failed to start the minecraft server",
           "java.io.IOException: The process cannot access the file because "
           "another process has locked a portion of the file",
           "\tat java.base/sun.nio.ch.FileDispatcherImpl.write0(Native Method)",
           "\tat knot//net.minecraft.class_5125.method_26803(class_5125.java:35)",
           "\tat knot//net.minecraft.class_32$class_5143.<init>(class_32.java:369)",
           "\tat net.fabricmc.loader.impl.launch.server.FabricServerLauncher.main"]
    msg = server_host.diagnose(log, exit_code=1, seconds=3)
    assert msg and "locked" in msg.lower(), msg
    assert "level.dat" in msg and "world" in msg, msg
    assert "Servers -> Running" in msg, msg
    assert "exclusions" not in msg, "a world lock must not be blamed on the jar bug"
    # and the jar version of the same class of problem keeps its own advice
    jar = server_host.diagnose(["Error: Unable to access jarfile x.jar"], 1, 2)
    assert "server file" in jar, jar
    case("a locked-world exit is diagnosed as a locked world")


def test_the_bore_program_is_picked_by_name_not_by_prefix():
    """A release's own folder must never be taken for the program inside it."""
    from divineclient.core import tunnel as tmod
    d = tempfile.mkdtemp(prefix="divine-bore-", dir=_TMP)

    zp = os.path.join(d, "bore-win.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("bore-v0.6.0-x86_64-pc-windows-msvc/", b"")        # the directory
        z.writestr("bore-v0.6.0-x86_64-pc-windows-msvc/README.md", b"docs" * 900)
        z.writestr("bore-v0.6.0-x86_64-pc-windows-msvc/bore.exe", b"M" * 40000)
    got = os.path.join(d, "bore.exe")
    tmod.unpack_bore(zp, got, "win32")
    assert open(got, "rb").read() == b"M" * 40000, "the .exe is the program, not the README"

    # on the other platforms nothing has a .exe, and a stray one must be ignored
    linux = os.path.join(d, "bore-linux.zip")
    with zipfile.ZipFile(linux, "w") as z:
        z.writestr("bore-v0.6.0-x86_64-unknown-linux-musl/bore", b"L" * 31000)
        z.writestr("bore-v0.6.0-x86_64-unknown-linux-musl/bore.exe", b"W" * 99000)
    out2 = os.path.join(d, "bore")
    tmod.unpack_bore(linux, out2, "linux")
    assert open(out2, "rb").read() == b"L" * 31000, "a Windows binary is not a Linux one"

    # a tar.gz is a tar.gz: the same rules, the same biggest-file-wins tie break
    import tarfile as _tf
    tg = os.path.join(d, "bore.tgz")
    with _tf.open(tg, "w:gz") as t:
        di = _tf.TarInfo("bore"); di.type = _tf.DIRTYPE; t.addfile(di)
        for name, body in (("bore/README.md", b"notes" * 500), ("bore/bore", b"B" * 30000)):
            mi = _tf.TarInfo(name); mi.size = len(body); t.addfile(mi, io.BytesIO(body))
    out3 = os.path.join(d, "bore-from-tar")
    tmod.unpack_bore(tg, out3, "linux")
    assert open(out3, "rb").read() == b"B" * 30000

    # nothing usable at all: the message names what it looked for and what it found
    junk = os.path.join(d, "junk.zip")
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr("LICENSE", b"mit")
    try:
        tmod.unpack_bore(junk, os.path.join(d, "nope.exe"), "win32")
        raise AssertionError("expected RuntimeError for an archive with no bore program")
    except RuntimeError as e:
        assert "didn't contain a bore program" in str(e), str(e)
        assert "LICENSE" in str(e), "the message should say what was in there"


def test_ensure_bore_leaves_exactly_the_program_behind():
    """Where the program ends up is our decision, and a failure leaves nothing.

    The reported crash was "[Errno 22] Invalid argument:
    'D:\\..\\tunnel\\/tmpXXXX\\/bore.exe'" - a path zipfile.extract() had built for
    itself, with separators Windows refuses. ensure_bore must never hand a path it did
    not assemble to the file API, and must not leave a half-written bore behind.
    """
    import tarfile as _tf
    from divineclient.core import tunnel as tmod
    d = tempfile.mkdtemp(prefix="divine-bore-e2e-", dir=_TMP)
    os.makedirs(d, exist_ok=True)
    real = (tmod.tunnel_dir, tmod.bore_path, tmod._latest_bore_url, tmod._fetch,
            tmod.VERIFY_OFF)
    try:
        tmod.tunnel_dir = lambda: d
        tmod.bore_path = lambda: os.path.join(d, "bore")
        tmod.VERIFY_OFF = True
        tmod._latest_bore_url = lambda key: "http://x/bore-v0.6.0-x86_64.tar.gz"

        def fake_fetch(url, dest, status=None, **kw):
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with _tf.open(dest, "w:gz") as t:      # a tar.gz, as the name says
                di = _tf.TarInfo("bore-v0.6.0-x86_64-unknown-linux-musl")
                di.type = _tf.DIRTYPE
                t.addfile(di)
                body = b"Z" * 30000
                mi = _tf.TarInfo("bore-v0.6.0-x86_64-unknown-linux-musl/bore")
                mi.size = len(body)
                mi.mode = 0o644                     # not executable in the archive
                t.addfile(mi, io.BytesIO(body))
            return dest

        tmod._fetch = fake_fetch
        path = tmod.ensure_bore()
        assert path == tmod.bore_path()
        assert open(path, "rb").read() == b"Z" * 30000
        assert os.access(path, os.X_OK), "a program we are about to exec must be runnable"
        assert sorted(os.listdir(d)) == ["bore"], os.listdir(d)

        # second call: nothing to do, nothing asked
        asked = []
        tmod._fetch = lambda *a, **k: asked.append(a)
        assert tmod.ensure_bore() == path
        assert not asked, "an unpacked bore must be reused, not re-downloaded"

        # a stub in place of the binary is refused, and does not stay behind
        os.remove(path)

        def tiny(url, dest, status=None, **kw):
            body = b"<html>blocked by your proxy</html>"
            with _tf.open(dest, "w:gz") as t:
                mi = _tf.TarInfo("bore")
                mi.size = len(body)
                t.addfile(mi, io.BytesIO(body))
            return dest
        tmod._fetch = tiny
        try:
            tmod.ensure_bore()
            raise AssertionError("expected RuntimeError for a stubbed download")
        except RuntimeError as e:
            assert "not an executable" in str(e).lower(), str(e)
        assert os.listdir(d) == [], "the failed attempt left %s behind" % os.listdir(d)
    finally:
        (tmod.tunnel_dir, tmod.bore_path, tmod._latest_bore_url, tmod._fetch,
         tmod.VERIFY_OFF) = real


def test_a_jar_is_judged_by_its_manifest_not_its_size():
    """The 616-byte jar Fabric generates is a real server jar; size said otherwise."""
    d = tempfile.mkdtemp(prefix="divine-jar-", dir=_TMP)
    thin = os.path.join(d, "fabric-server-launch.jar")
    with zipfile.ZipFile(thin, "w") as z:
        z.writestr("META-INF/MANIFEST.MF",
                   "Manifest-Version: 1.0\r\nMain-Class: %s\r\n\r\n"
                   % FABRIC_LAUNCH_MAIN)
    assert os.path.getsize(thin) < 1024, "this fixture is the small case on purpose"
    assert server_host._is_valid_jar(thin), "a runnable jar of any size is valid"
    assert server_host._jar_main_class(thin) == FABRIC_LAUNCH_MAIN

    # manifests wrap at 72 bytes, and the wrap is a space on the next line
    wrapped = os.path.join(d, "wrapped.jar")
    long_main = "net.fabricmc.loader.impl.launch.server.VeryLongFabricServerLauncherName"
    with zipfile.ZipFile(wrapped, "w") as z:
        z.writestr("META-INF/MANIFEST.MF",
                   "Manifest-Version: 1.0\r\nMain-Class: net.fabricmc.loader.impl."
                   "launch.server.VeryLongFabric\r\n ServerLauncherName\r\n\r\n")
    assert server_host._jar_main_class(wrapped) == long_main, "unfolded wrong"

    no_manifest = os.path.join(d, "zip.jar")
    with zipfile.ZipFile(no_manifest, "w") as z:
        z.writestr("readme.txt", "x" * 5000)
    assert not server_host._is_valid_jar(no_manifest), "a zip is not a jar"
    with open(os.path.join(d, "page.jar"), "wb") as f:
        f.write(b"<html>302 found</html>" * 400)
    assert not server_host._is_valid_jar(os.path.join(d, "page.jar")), "an html page is not a jar"


def test_a_finished_fabric_install_starts_the_generated_jar_with_no_network():
    """The restart case: every Fabric start after the first used to re-download."""
    i = inst("secondstart", mc="1.21.4")
    sdir = server_host.server_dir(i)
    os.makedirs(sdir, exist_ok=True)
    launch = fake_fabric_install(sdir)
    real = (server_host._download, server_host._fabric_server_url,
            server_host._vanilla_server_url)

    def no_network(*a, **k):
        raise AssertionError("a finished install must not go online")
    try:
        server_host._download = no_network
        server_host._fabric_server_url = no_network
        server_host._vanilla_server_url = no_network
        assert server_host.prepare(i, None) == launch
    finally:
        (server_host._download, server_host._fabric_server_url,
         server_host._vanilla_server_url) = real
    st = server_host._read_state(sdir)
    assert st.get("jar") == server_host.FABRIC_LAUNCH_NAME, st
    # nothing on this path needs to know which loader build it is, and asking meta for
    # it is exactly the network call that used to happen on every single start
    assert not st.get("fabric_loader"), st


def test_a_half_installed_fabric_server_is_finished_not_reused():
    """The launch jar present but not what it points at: that is not a server yet."""
    i = inst("halfinstall", mc="1.21.4")
    sdir = server_host.server_dir(i)
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir, exist_ok=True)
    fake_jar(os.path.join(sdir, server_host.FABRIC_LAUNCH_NAME), extra_pad=0)
    assert not server_host._fabric_installed(sdir), "a manifest with no Class-Path names nothing to load"
    fake_fabric_install(sdir, complete=False)      # the folders, none of the files
    assert not server_host._fabric_installed(sdir), "the jars it promises are missing"
    fake_fabric_install(sdir)
    assert server_host._fabric_installed(sdir), "a complete install must be believed"
    # and the bootstrap is never taken for an installed server, at any size
    fake_jar(os.path.join(sdir, server_host.FABRIC_LAUNCH_NAME), extra_pad=0,
             main_class=server_host.FABRIC_INSTALLER_MAIN)
    assert not server_host._fabric_installed(sdir), "that is the installer, not the server"


def test_an_interrupted_fabric_install_is_redone_not_launched():
    """The jar written but its libraries not: Java would exit 1 with no message."""
    i = inst("partialinstall", mc="1.21.4")
    sdir = server_host.server_dir(i)
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir, exist_ok=True)
    fake_fabric_install(sdir, complete=False)
    assert not server_host._fabric_installed(sdir), \
        "a launch jar whose Class-Path is missing is not a server"
    fake_jar(os.path.join(sdir, "libraries", "test", "lib.jar"))
    assert not server_host._fabric_installed(sdir), \
        "the Minecraft jar in versions/ is still missing"
    with open(os.path.join(sdir, "versions", "1.21.4", "server-1.21.4.jar"), "wb") as f:
        f.write(b"\0" * (2 << 20))
    assert server_host._fabric_installed(sdir), "now it is complete"
    os.remove(os.path.join(sdir, "libraries", "test", "lib.jar"))
    assert not server_host._fabric_installed(sdir), "a lost library must be noticed"


def test_an_old_bootstrap_in_the_launch_jar_slot_is_moved_not_refetched():
    """Divine used to download the bootstrap *as* fabric-server-launch.jar.

    Renaming it is what makes the fix safe to install over: the file is the same bytes,
    and from now on the bootstrap never writes over a jar a JVM is reading from.
    """
    i = inst("moveboot", mc="1.20.1")
    sdir = server_host.server_dir(i)
    os.makedirs(sdir, exist_ok=True)
    jar = fake_jar(os.path.join(sdir, server_host.FABRIC_LAUNCH_NAME),
                   main_class=server_host.FABRIC_INSTALLER_MAIN)
    calls, real = stub_fabric_downloads({})
    try:
        run = server_host.prepare(i, None)
        assert not calls, "the bootstrap already here must be reused, not re-downloaded"
        assert os.path.basename(run) == server_host.FABRIC_BOOT_NAME, run
        assert os.path.isfile(os.path.join(sdir, server_host.FABRIC_BOOT_NAME))
        assert not os.path.exists(jar), "the launch jar slot must be left free for Fabric"
    finally:
        (server_host._download, server_host._fabric_server_url,
         server_host._vanilla_server_url) = real


def test_diagnose_ignores_the_first_start_install_chatter():
    """A healthy first Fabric start used to be diagnosed as a version mismatch."""
    healthy = ["Downloading Minecraft server",
               "Installing Fabric Loader 0.19.5(1.21.4) on the server",
               "Downloading library net.fabricmc:intermediary:1.21.4",
               "Unpacking com/mojang/datafixerupper/8.0.16/datafixerupper-8.0.16.jar "
               "(libraries:com.mojang:datafixerupper:8.0.16) to libraries/com/mojang/"
               "datafixerupper/8.0.16/datafixerupper-8.0.16.jar",
               "Generating server launch JAR",
               "[14:03:09] [Server thread/INFO]: Done (15.155s)! For help, type \"help\""]
    assert server_host.diagnose(healthy, 0, 33.7) is None, server_host.diagnose(healthy, 0, 33.7)
    # the same words in a real error are still called out
    assert server_host.diagnose(["[main/ERROR]: Unsupported settings version"], 1, 4)
    assert server_host.diagnose(["Exception in thread \"main\" java.nio.file."
                                 "FileSystemException: C:\\server\\fabric-server-launch.jar:"
                                 " The process cannot access the file because it is being "
                                 "used by another process"], 1, 3)



def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    if os.environ.get("DIVINE_TEST_FAST") == "1":
        tests = [t for t in tests if "real_server" not in t[0]]
        print("(DIVINE_TEST_FAST=1 - skipping the live server boot)")
    failed = 0
    for name, fn in tests:
        print("== " + name.replace("test_", ""))
        try:
            fn()
            print("   PASS")
        except Exception as e:
            failed += 1
            import traceback
            print("   FAIL: " + type(e).__name__ + ": " + str(e)[:400])
            traceback.print_exc()
    shutil.rmtree(_TMP, ignore_errors=True)
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
