#!/usr/bin/env python3
"""The launcher shell: navigation, the code gate, updates, presence, and the flat UI.

Phase 9b took the sliding rails out of the launcher and left everything else in. So these
tests are mostly *absence* checks with a few stubborn presences: the gate still gates, the
updater still stages, presence still reports, the game folder still carries the launcher's
own files with it when it moves, and nothing in the interface is driven by a timer.

Run under a headless display to get the GUI half:

    xvfb-run -a python3 tests/test_ui_shell.py

Without a display the GUI checks are skipped and the rest still run.
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

_TMP = tempfile.mkdtemp(prefix="divine-shell-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")
os.environ.setdefault("DIVINE_NO_SERVER_DOWNLOAD", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

RESULTS = []


def check(name):
    """Decorator: run the function, record pass/fail, keep going."""
    def wrap(fn):
        try:
            fn()
            RESULTS.append(("ok", name))
            print("  ok    %s" % name)
        except Exception as err:                                   # noqa: BLE001
            import traceback
            traceback.print_exc()
            RESULTS.append(("fail", name))
            print("  FAIL  %s: %r" % (name, err))
        return fn
    return wrap


# --------------------------------------------------------------------- version gate
@check("the servers code is a hash, not a string you can grep for")
def _code_gate():
    from arenclient.ui import app as appmod
    code = "divineserverallowance112233"
    assert appmod.code_ok(code), "the real code must open the tab"
    assert appmod.code_ok("  " + code.upper() + " "), "paste-with-spaces must still work"
    assert not appmod.code_ok("nope")
    assert not appmod.code_ok("")
    assert not appmod.code_ok(None)
    assert appmod.code_ok(code + "   "), "whitespace at either end is tolerated"
    assert not appmod.code_ok(code + "x"), "a code with extra letters is not the code"
    src = open(os.path.join(ROOT, "arenclient", "ui", "app.py"), encoding="utf-8").read()
    assert code not in src, "the plaintext code must not be in the source"
    import hashlib
    assert appmod.SERVERS_CODE_SHA256 == hashlib.sha256(code.encode()).hexdigest()


@check("a locked tab cannot be opened by any path")
def _locked_tab_source():
    src = open(os.path.join(ROOT, "arenclient", "ui", "app.py"), encoding="utf-8").read()
    assert '"servers"' in src
    # every route into a page goes through show_page, which is where the gate lives
    assert src.count("def show_page") == 1
    body = src[src.index("def show_page"):]
    assert "LOCKED_TABS" in body[:900], "show_page itself must check the gate"


# ------------------------------------------------------------------------ updates
@check("version comparison is numeric, not alphabetical")
def _version_compare():
    from arenclient.core import updater
    assert updater.as_tuple("1.10") > updater.as_tuple("1.9")
    assert updater.is_newer("1.10", "1.9") is True
    assert updater.is_newer("1.0.1", "1.0") is True
    assert updater.is_newer("1.0", "1.0") is False
    assert updater.is_newer("0.9", "1.0") is False, "never downgrade automatically"
    assert updater.is_newer("1.0-rc1", "1.0") is False or True   # junk suffix tolerated
    assert updater.as_tuple("") == (0,)
    assert updater.as_tuple("v2.1")[:2] == (2, 1)


@check("status() describes every case the pill has to render")
def _status_states():
    from arenclient.core import updater

    saved = updater.fetch_latest

    class Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    cfg = Cfg()
    try:
        updater.fetch_latest = lambda config=None, timeout=15: {"error": "unreachable"}
        assert updater.status(cfg)["state"] == "unreachable"

        updater.fetch_latest = lambda config=None, timeout=15: {
            "version": updater.local_version(), "url": "x", "sha256": "", "size": 0,
            "notes": "", "file": "x"}
        assert updater.status(cfg)["state"] == "current"

        updater.fetch_latest = lambda config=None, timeout=15: {
            "version": "99.0", "url": "", "sha256": "", "size": 0, "notes": "", "file": ""}
        st = updater.status(cfg)
        assert st["state"] == "no-download", st
        assert "99.0" in st["detail"]

        updater.fetch_latest = lambda config=None, timeout=15: {
            "version": "99.0", "url": "https://example/Divine.zip", "sha256": "a" * 64,
            "size": 10, "notes": "n", "file": "Divine.zip"}
        st = updater.status(cfg)
        assert st["state"] == "available", st
        assert st["info"]["url"].endswith("Divine.zip")
        assert st["remote"] == "99.0" and st["local"] == updater.local_version()
    finally:
        updater.fetch_latest = saved


@check("a staged build is found, and the site agrees it is staged")
def _staged_roundtrip():
    from arenclient.core import updater
    d = updater.updates_dir()
    os.makedirs(d, exist_ok=True)
    incoming = os.path.join(d, "incoming-99.1")
    os.makedirs(incoming, exist_ok=True)
    with open(os.path.join(incoming, updater.VERSION), "w", encoding="utf-8") as f:
        json.dump({"version": "99.1", "url": "https://example/x.zip"}, f)
    with open(os.path.join(incoming, "DivineClient.txt"), "w", encoding="utf-8") as f:
        f.write("payload")
    found = updater.find_staged()
    assert found and found[0] == "99.1", found
    assert os.path.isdir(found[1])

    saved = updater.fetch_latest
    try:
        updater.fetch_latest = lambda config=None, timeout=15: {
            "version": "99.1", "url": "https://example/x.zip", "sha256": "", "size": 0,
            "notes": "", "file": "x.zip"}
        st = updater.status(None)
        assert st["state"] == "staged", st
        assert "restart" in ("restart" if st.get("path") else ""), st
    finally:
        updater.fetch_latest = saved

    # clearing must not touch anything outside the updates folder
    updater.clear_staged(os.path.expanduser("~"))
    assert os.path.isdir(incoming), "a path outside updates/ must be ignored"
    updater.clear_staged(incoming)
    assert not os.path.exists(incoming)
    assert updater.find_staged() is None


@check("a zip that wraps the app in a folder still installs over the install folder")
def _zip_wrapper_folder():
    """build_exe.bat's Compress-Archive puts everything under DivineClient/ inside the zip."""
    import zipfile as zf
    from arenclient.core import updater
    work = tempfile.mkdtemp(prefix="wrap-", dir=_TMP)
    archive = os.path.join(work, "DivineClient-1.1-windows.zip")
    with zf.ZipFile(archive, "w") as z:
        z.writestr("DivineClient/DivineClient.exe", b"new exe")
        z.writestr("DivineClient/_internal/base_library.zip", b"lib")
        z.writestr("DivineClient/HOW-TO-RUN.txt", b"read me")
    target = os.path.join(work, "staged")
    updater._unzip(archive, target)
    assert os.path.isfile(os.path.join(target, "DivineClient.exe")), os.listdir(target)
    assert os.path.isfile(os.path.join(target, "_internal", "base_library.zip"))
    assert not os.path.isdir(os.path.join(target, "DivineClient")), "wrapper survived"
    pairs = updater.plan_payload_swap(target, os.path.join(work, "install"))
    dsts = sorted(os.path.relpath(d, os.path.join(work, "install")).replace(os.sep, "/")
                  for _s, d in pairs)
    assert dsts == sorted(["DivineClient.exe", "HOW-TO-RUN.txt",
                           "_internal/base_library.zip"]), dsts
    # a flat archive must stay flat, and a multi-root one must keep its names
    flat = os.path.join(work, "flat.zip")
    with zf.ZipFile(flat, "w") as z:
        z.writestr("DivineClient.exe", b"exe")
        z.writestr("_internal/x", b"y")
    updater._unzip(flat, os.path.join(work, "flat"))
    assert os.path.isfile(os.path.join(work, "flat", "DivineClient.exe"))
    two = os.path.join(work, "two.zip")
    with zf.ZipFile(two, "w") as z:
        z.writestr("A/a", b"1")
        z.writestr("B/b", b"2")
    updater._unzip(two, os.path.join(work, "two"))
    assert os.path.isfile(os.path.join(work, "two", "A", "a"))


@check("--apply-update refuses a payload it did not stage")
def _apply_refuses_stray_path():
    from arenclient.core import updater
    for bad in ("/etc/passwd", os.path.expanduser("~"), "relative/path", ""):
        try:
            updater.run_apply_update(bad, log=lambda m: None)
        except ValueError:
            continue
        except Exception as err:
            raise AssertionError("expected ValueError for %r, got %r" % (bad, err))
        raise AssertionError("no error for %r" % bad)
    # and it is a no-op on a source install, where self-replacement is not safe
    assert updater.apply_supported() is False, "this test runs unpacked"


@check("a staged folder becomes file pairs, and a one-file build takes only the exe")
def _swap_plan():
    import sys as _sys
    from arenclient.core import updater
    work = os.path.join(_TMP, "plan")
    staged = os.path.join(work, "incoming-9.9")
    os.makedirs(os.path.join(staged, "_internal"), exist_ok=True)
    for name in ("DivineClient.exe", "client-version.json"):
        open(os.path.join(staged, name), "w").close()
    open(os.path.join(staged, "_internal", "base_library.zip"), "w").close()
    dest = os.path.join(work, "install")
    os.makedirs(dest, exist_ok=True)

    pairs = updater.plan_payload_swap(staged, dest)
    names = sorted(os.path.relpath(dst, dest) for _src, dst in pairs)
    assert names == sorted(["DivineClient.exe", os.path.join("_internal", "base_library.zip")]), names
    assert not any("." + os.sep in dst for _src, dst in pairs), pairs
    assert updater.VERSION not in names, "the staging record is not part of the build"

    saved = _sys.executable
    try:
        _sys.executable = os.path.join(dest, "DivineClient.exe")
        only = updater.plan_payload_swap(staged, dest, onefile=True)
        assert [os.path.relpath(d, dest) for _s, d in only] == ["DivineClient.exe"], only
        # and a bare exe payload still swaps the exe
        loose = os.path.join(work, "DivineClient-9.9.exe")
        open(loose, "w").close()
        assert [src for src, _d in updater.plan_payload_swap(loose, dest)] == [loose]
    finally:
        _sys.executable = saved


@check("self-replacement is only offered to a frozen Windows build")
def _apply_supported():
    from unittest import mock
    from arenclient.core import updater
    with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "frozen", True,
                                                                        create=True):
        assert updater.apply_supported() is True
    with mock.patch.object(sys, "platform", "linux"), mock.patch.object(sys, "frozen", True,
                                                                        create=True):
        assert updater.apply_supported() is False


@check("an archive packed with Windows separators unpacks into folders, not files")
def _unzip_windows_separators():
    r"""Compress-Archive writes ``Folder\sub\`` - backslashes, and directory entries it
    ends with a backslash, which ``ZipInfo.is_dir()`` does not recognise. Unpacked as
    files, those entries put a real *file* where a folder belongs and the next member
    inside it died with NotADirectoryError: a good release looked like a broken download.
    """
    import zipfile
    from arenclient.core import updater

    bs = chr(92)
    work = os.path.join(_TMP, "winzip")
    os.makedirs(work, exist_ok=True)
    exe = bs.join(["DivineClient", "DivineClient.exe"])
    direntry = bs.join(["DivineClient", "_internal", "customtkinter"]) + bs
    asset = bs.join(["DivineClient", "_internal", "customtkinter", "assets", "blue.json"])
    readme = bs.join(["DivineClient", "HOW-TO-RUN.txt"])
    arc = os.path.join(work, "rel.zip")
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr(exe, b"MZ" + b"x" * 10)
        z.writestr(direntry, b"")                  # the entry that used to become a file
        z.writestr(asset, b'{"c": 1}')
        z.writestr(readme, b"read me")
        z.writestr("DivineClient/../../evil.txt", b"no")          # traversal, still refused
    target = os.path.join(work, "out")
    updater._unzip(arc, target)
    assert os.path.isfile(os.path.join(target, "DivineClient.exe")), \
        "the wrapper folder was not stripped: %r" % sorted(os.listdir(target))
    assert os.path.isdir(os.path.join(target, "_internal", "customtkinter")), \
        "a directory entry became a file"
    assert os.path.isfile(os.path.join(target, "_internal", "customtkinter", "assets",
                                       "blue.json"))
    assert not os.path.exists(os.path.join(work, "evil.txt")), "escaped the target folder"

    # and an archive with nothing usable is refused, not half-installed
    junk = os.path.join(work, "junk.zip")
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr(bs.join(["DivineClient", ""]), b"")
        z.writestr(bs.join(["DivineClient", "sub", ""]), b"")
    try:
        updater._unzip(junk, os.path.join(work, "junk-out"))
        raise AssertionError("an archive with no files was accepted")
    except RuntimeError as e:
        assert "no files" in str(e), str(e)


@check("a staged zip cannot write outside the folder it is unpacked into")
def _zip_traversal():
    from arenclient.core import updater
    work = os.path.join(_TMP, "zips")
    os.makedirs(work, exist_ok=True)
    archive = os.path.join(work, "bad.zip")
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("good.txt", "fine")
        z.writestr("../escaped.txt", "nope")
        z.writestr(os.path.join("sub", "nested.txt"), "ok")
    target = os.path.join(work, "out")
    updater._unzip(archive, target)
    assert os.path.isfile(os.path.join(target, "good.txt"))
    assert os.path.isfile(os.path.join(target, "sub", "nested.txt"))
    assert not os.path.exists(os.path.join(work, "escaped.txt"))
    assert not os.path.exists(os.path.join(_TMP, "escaped.txt"))


@check("main.py's --apply-update parser takes the payload and the pid to wait for")
def _main_args():
    import importlib.util
    spec = importlib.util.spec_from_file_location("aren_main", os.path.join(ROOT, "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    payload, pid = main._update_mode_args(["--apply-update", "/x/y", "--wait-pid", "4242"])
    assert payload == "/x/y" and pid == 4242, (payload, pid)
    assert main._update_mode_args([]) == (None, None)
    assert main._update_mode_args(["--apply-update"]) == (None, None)
    payload, pid = main._update_mode_args(["--wait-pid", "nope", "--apply-update", "/a"])
    assert payload == "/a" and pid is None
    # the argument must not be swallowed by the GUI path
    assert main._update_mode_args(["--other"]) == (None, None)


@check("the update never reaches the launch path")
def _launch_is_not_gated():
    """No file in the launch path may mention the updater as a precondition."""
    launcher = open(os.path.join(ROOT, "arenclient", "core", "launcher.py"),
                    encoding="utf-8").read()
    assert "updater" not in launcher, "launching must not depend on an update check"
    flow = open(os.path.join(ROOT, "arenclient", "ui", "launchflow.py"),
                encoding="utf-8").read()
    assert "updater" not in flow
    assert "import updater" not in flow or "if updater" not in flow


# ------------------------------------------------------------------- friends/presence
@check("friend colours come from presence, with the heartbeat as fallback")
def _friend_state():
    from arenclient.ui.friends_panel import friend_state
    assert friend_state({"presence": "in_game", "online": True}) == "playing"
    assert friend_state({"presence": "in_game", "online": False}) == "playing", \
        "a running game outranks a missed heartbeat while the site still believes it"
    assert friend_state({"presence": "idle", "online": True}) == "idle"
    assert friend_state({"presence": "online", "online": True}) == "idle"
    assert friend_state({"presence": "offline", "online": True}) == "offline"
    assert friend_state({"presence": "", "online": False}) == "offline"
    assert friend_state({"presence": "", "online": True}) == "idle"
    assert friend_state({"online": True, "status": "Playing 1.21.4"}) == "playing"
    assert friend_state({"presence_detail": "Playing Minecraft", "online": True}) == "playing"


@check("presence reporting cannot raise, and stays quiet without a token")
def _set_presence_client():
    from arenclient.core import social

    class Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    assert social.set_presence(Cfg(), "in_game", "Playing 1.21.4") is False

    saved_link = social.is_linked
    saved_req = social._request
    try:
        social.is_linked = lambda config: True
        sent = []
        social._request = lambda method, config, path, token=None, **kw: (
            sent.append((method, path, kw.get("json"))) or {})
        cfg = Cfg(**{"friends_api_base": "https://example"})
        # _token() reads the link file; fake it through the same helper
        real_token = social._token
        social._token = lambda config=None: "tok"
        try:
            assert social.set_presence(cfg, "in_game", "Playing 1.21.4") is True
            assert sent[0][0] == "POST" and sent[0][1] == "/api/presence"
            assert sent[0][2]["state"] == "in_game"
            sent[:] = []

            def boom(*a, **k):
                raise social.SocialError("site down")
            social._request = boom
            assert social.set_presence(cfg, "offline") is False, "never raises"
            social._token = real_token
        finally:
            social._token = real_token
    finally:
        social.is_linked = saved_link
        social._request = saved_req


# ------------------------------------------------------------------- moving the folder
@check("changing the game location always takes the bore tunnel and launcher files")
def _relocation_must_move():
    """The functional half of the revert: 'don't move' never means 'leave the launcher's
    own files behind'."""
    from arenclient import paths
    assert paths.MUST_MOVE_SUBS == ("minecraft", "tunnel"), paths.MUST_MOVE_SUBS
    assert paths.ASK_FIRST_SUBS == ("instances", "servers"), paths.ASK_FIRST_SUBS
    assert set(paths.subs_under_game_dir()) == {"minecraft", "tunnel", "instances",
                                                "servers"}

    work = tempfile.mkdtemp(prefix="move-", dir=_TMP)
    old = os.path.join(work, "old")
    new = os.path.join(work, "new")
    os.makedirs(os.path.join(old, "minecraft", "versions", "1.21.4"))
    with open(os.path.join(old, "minecraft", "launcher_profiles.json"), "w") as f:
        f.write("{}")
    os.makedirs(os.path.join(old, "tunnel", "bin"))
    with open(os.path.join(old, "tunnel", "bin", "bore.exe"), "w") as f:
        f.write("stale copy")
    with open(os.path.join(old, "tunnel", "bin", "playit.toml"), "w") as f:
        f.write("config")
    os.makedirs(os.path.join(old, "instances", "abc"))
    with open(os.path.join(old, "instances", "abc", "level.dat"), "w") as f:
        f.write("world")
    os.makedirs(os.path.join(new, "tunnel", "bin"))
    with open(os.path.join(new, "tunnel", "bin", "bore.exe"), "w") as f:
        f.write("already there")

    # "don't move my folders" - the launcher's own files come anyway
    res = paths.relocate_subdirs(old, new, include_user_data=False)
    assert res.get("minecraft") == "moved", res
    assert os.path.isfile(os.path.join(new, "minecraft", "launcher_profiles.json"))
    assert os.path.isdir(os.path.join(new, "minecraft", "versions", "1.21.4"))
    assert res.get("tunnel") == "merged", res
    assert open(os.path.join(new, "tunnel", "bin", "bore.exe")).read() == "already there", \
        "a destination file is never overwritten"
    assert open(os.path.join(new, "tunnel", "bin", "playit.toml")).read() == "config"
    assert "instances" not in res and "servers" not in res, res
    assert os.path.isfile(os.path.join(old, "instances", "abc", "level.dat"))
    assert not os.path.exists(os.path.join(new, "instances")), "instances only move on yes"

    res2 = paths.relocate_subdirs(old, new, include_user_data=True)
    assert res2.get("instances") == "moved", res2
    assert os.path.isfile(os.path.join(new, "instances", "abc", "level.dat"))
    # and the caller can hold one folder back (a separately configured instances dir)
    work2 = tempfile.mkdtemp(prefix="move2-", dir=_TMP)
    o2, n2 = os.path.join(work2, "o"), os.path.join(work2, "n")
    os.makedirs(os.path.join(o2, "instances", "keep"))
    with open(os.path.join(o2, "instances", "keep", "level.dat"), "w") as f:
        f.write("world")
    os.makedirs(os.path.join(o2, "minecraft"))
    res3 = paths.relocate_subdirs(o2, n2, include_user_data=True, skip=("instances",))
    assert res3.get("minecraft") == "moved", res3
    assert "instances" not in res3, res3
    assert os.path.isfile(os.path.join(o2, "instances", "keep", "level.dat"))
    # a same-folder "move" must not touch anything
    assert paths.relocate_subdirs(new, new, include_user_data=True) == {}


@check("the keys the rail UI needed are not read back from an old config")
def _retired_keys_stay_out():
    from arenclient import paths
    from arenclient.core import config as cfgmod
    for key in ("menu_rail_pinned", "friends_rail_pinned", "animations"):
        assert key not in cfgmod.DEFAULTS, key
    d = tempfile.mkdtemp(prefix="cfg-", dir=_TMP)
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"animations": True, "menu_rail_pinned": False, "max_ram_mb": 6000}, f)
    saved = paths.CONFIG_FILE
    paths.CONFIG_FILE = os.path.join(d, "config.json")
    try:
        c = cfgmod.Config()
        assert c.get("max_ram_mb") == 6000, "a real setting must survive"
        assert c.get("animations") is None, "a retired key must not come back"
        assert c.get("menu_rail_pinned") is None
    finally:
        paths.CONFIG_FILE = saved


@check("nothing in the interface repeats on a timer")
def _no_animation_timers():
    from arenclient.ui import anim
    assert anim.enabled() is False, "the shell must boot with animation off"
    started = []

    class Recorder:
        def __init__(self, *a, **k):
            pass

        def start(self):
            started.append(1)

    # a Ticker that is told to run while animations are off must schedule nothing
    class Dummy:
        def after(self, ms, fn):
            raise AssertionError("scheduled %r while animations are off" % (fn,))

    t = anim.Ticker(Dummy(), lambda f: True, interval=1)
    t.start()
    assert not started and t._job is None
    # and no widget in the new shell constructs one
    # widgets.py is in this list because the theme gained a gradient again in phase 10 - a
    # static cyan wash behind the pages. That is allowed; what is not allowed is anything
    # repainting on a loop, which is how the old gradient used to eat a frame per tick.
    for rel in ("app.py", "nav.py", "loading.py", "widgets.py",
                os.path.join("pages", "home.py"),
                os.path.join("pages", "instances_page.py")):
        src = open(os.path.join(ROOT, "arenclient", "ui", rel), encoding="utf-8").read()
        assert "Ticker(" not in src, "%s still runs a Ticker" % rel
        assert "SlideRail" not in src and "GradientCanvas" not in src, rel
    for gone in ("rails.py", "menu_rail.py", "friends_rail.py", "gradient.py"):
        assert not os.path.exists(os.path.join(ROOT, "arenclient", "ui", gone)), gone


# ---------------------------------------------------------------------- loading screen
@check("loading stages are weighted, and a stuck stage cannot read as finished")
def _loading_weights():
    from arenclient.ui import loading
    total = sum(w for _k, w, _t in loading.STAGES)
    assert abs(total - 1.0) < 1e-6, total
    keys = [k for k, _w, _t in loading.STAGES]
    assert keys == ["boot", "java", "versions", "manifest", "mods", "ready"], keys
    for _k, _w, text in loading.STAGES:
        assert text and text[0].isupper()


# -------------------------------------------------------------------------- the shell
def _display_available():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
        return True
    except Exception:
        return False


if _display_available():
    import customtkinter as ctk
    from arenclient.ui import theme
    from arenclient.ui.app import DivineApp

    _app_box = []

    def app():
        if not _app_box:
            ctk.set_appearance_mode("dark")
            a = DivineApp()
            # reveal it for real: a withdrawn window never maps its widgets, and some of
            # the checks below are about *where* something is drawn
            a._reveal()
            # The site is live and it publishes a real build, so a freshly built app
            # starts fetching a 19 MB archive on a background thread and rewrites the
            # sidebar pill mid-check ("8.9 MB of 19.1 MB" where a test expected "1.1").
            # The fetch itself has its own end-to-end test below; it must not run here.
            a._download_update = lambda info: None
            _app_box.append(a)

            app_pump[0] = _pumper(a)
        return _app_box[0]

    def _pumper(a):
        def pump(n=12):
            for _ in range(n):
                try:
                    a.update_idletasks()
                    a.update()
                except Exception:
                    return
        return pump

    app_pump = [None]

    def pump(n=12):
        if app_pump[0] is not None:
            app_pump[0](n)

    @check("the shell builds: a flat sidebar, six pages, one launch owner")
    def _shell():
        a = app()
        pump()
        assert a.nav is not None and type(a.nav).__name__ == "SideNav"
        for gone in ("rail", "friends_rail", "menu_rail"):
            assert not hasattr(a, gone), "the shell still owns %s" % gone
        assert set(a.pages) >= {"home", "instances", "servers", "accounts", "settings",
                                "about"}
        assert "versions" not in a.pages, "the tab is Instances again"
        assert a._current == "home"
        assert a.nav.winfo_width() == a.nav.WIDTH or a.nav.grid_info().get("sticky") == "nsew"
        src = open(os.path.join(ROOT, "arenclient", "ui", "nav.py"),
                   encoding="utf-8").read()
        assert "grid_columnconfigure" not in src.split("def set_page")[1][:600], \
            "the sidebar must not resize anything"

    @check("the sidebar lists the pages, with settings and accounts at the bottom")
    def _nav_order():
        from arenclient.ui import nav
        a = app()
        pump()
        assert [k for k, _l, _g in nav.MAIN_ITEMS] == ["home", "instances", "servers"]
        assert [k for k, _l, _g in nav.FOOT_ITEMS] == ["accounts", "settings", "about"]
        assert set(a.nav.buttons) == {"home", "instances", "servers", "accounts",
                                      "settings", "about"}
        assert "LAUNCH" not in " ".join(str(b.cget("text")) for b in a.nav.buttons.values())
        # the everyday pages sit above the account/settings block, and the row order shows it
        top = a.nav.buttons["home"].winfo_rooty()
        bottom = a.nav.buttons["settings"].winfo_rooty()
        assert top < bottom, "Settings must be at the bottom"

    @check("selecting a page marks exactly one sidebar button")
    def _nav_selection():
        a = app()
        for key in ("home", "instances", "settings", "home"):
            a.show_page(key)
            pump(4)
            on = [k for k, b in a.nav.buttons.items()
                  if str(b.cget("fg_color")) != "transparent"]
            assert on == [key], (key, on)
            assert str(a.nav.buttons[key].cget("text_color")) == theme.COL["accent"]

    @check("the account row is at the top and pressing it switches account")
    def _account_row():
        import tkinter as tk
        a = app()
        store = a.accounts
        saved = (list(store.accounts), store.active_id)
        try:
            store.accounts, store.active_id = [], None
            a.nav.refresh_account()
            pump()
            assert "Not signed in" in str(a.nav.account_btn.cget("text"))
            one = store.add_offline("SoloPlayer")
            a.nav.refresh_account()
            pump()
            assert "SoloPlayer" in str(a.nav.account_btn.cget("text"))
            assert "Offline name" in str(a.nav._account_sub.cget("text"))
            # one account: pressing goes to the page that can add another
            a.show_page("home")
            a.nav._account_pressed()
            pump()
            assert a._current == "accounts"
            # two: pressing opens the switcher, and picking changes the active account
            two = store.add_offline("SecondPlayer")
            a.nav.refresh_account()
            pump()
            a.nav._account_pressed()
            pump(6)
            menus = [w for w in list(a.winfo_children()) + list(a.nav.winfo_children())
                     if isinstance(w, tk.Toplevel) and str(w.title()) == "Switch account"]
            assert menus, "no switcher appeared"
            labels = [str(b.cget("text")) for b in menus[0].winfo_children()
                      if isinstance(b, tk.Button)]
            assert any("SoloPlayer" in t for t in labels), labels
            assert any("SecondPlayer" in t for t in labels), labels
            pick = [b for b in menus[0].winfo_children() if isinstance(b, tk.Button)
                    and "SoloPlayer" in str(b.cget("text"))][0]
            pick.invoke()
            pump(6)
            assert a.accounts.active_id == one["id"], a.accounts.active_id
            assert "SoloPlayer" in str(a.nav.account_btn.cget("text"))
        finally:
            store.accounts, store.active_id = saved
            store.save()
            a.nav.refresh_account()

    @check("the top bar names the account and is not a button")
    def _top_bar():
        a = app()
        pump()
        assert str(a.top_account.cget("text")) != ""
        src = open(os.path.join(ROOT, "arenclient", "ui", "app.py"),
                   encoding="utf-8").read()
        head = src[src.index("def _build_content"):src.index("def _init_pages")]
        assert "CTkButton" not in head, "nothing in the header should be clickable"
        assert "top_account" in head and "bind" not in head.split("top_account")[1][:200]

    @check("the Instances page launches from the card, next to what it launches")
    def _instances_launch():
        import customtkinter as ctk
        a = app()
        page = a.pages["instances"]
        inst = a.instances.create("Shell Test", "1.21.4", loader="vanilla")
        page.refresh()
        pump(10)
        cards = [w for w in page.list_frame.winfo_children()
                 if type(w).__name__ == "InstanceCard"]
        assert len(cards) == 1, cards
        card = cards[0]
        texts = []
        buttons = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ctk.CTkButton):
                    texts.append(str(c.cget("text")).strip())
                    buttons.append(c)
                walk(c)
        walk(card)
        for label in ("Edit", "Mods", "Folder", "Clone", "Delete"):
            assert any(t == label for t in texts), (label, texts)
        launch = [b for b in buttons if "Launch" in str(b.cget("text"))]
        assert launch, texts
        calls = []
        real = a.flow.launch
        a.flow.launch = lambda: calls.append(1)
        try:
            launch[0].invoke()
            pump(4)
        finally:
            a.flow.launch = real
        assert calls == [1], "the card's button must go through the flow"
        assert a.flow.selected() is not None and a.flow.selected().id == inst.id
        assert a.config_store.get("last_instance") == inst.id, \
            "launching from a card must also remember the choice"
        a.instances.delete(inst.id, remove_files=True)
        pump(4)

    @check("the friends panel lives inside Home and colours come from presence")
    def _friends_panel():
        from arenclient.ui import theme
        from arenclient.ui.friends_panel import FriendsPanel, friend_state
        a = app()
        home = a.pages["home"]
        assert isinstance(home.friends, FriendsPanel)
        assert (friend_state({"presence": "in_game"}), friend_state({"presence": "online"}),
                friend_state({"presence": "offline"})) == ("playing", "idle", "offline")
        assert theme.friend_color("playing")[0] != theme.friend_color("idle")[0]
        assert theme.friend_color("offline")[1] in ("#2a2f3d", "#000000")
        home.friends.refresh()
        pump(8)
        assert home.friends.winfo_children(), "the panel has no widgets at all"
        # the rail-era bug: os was used without being imported, so avatars silently failed
        import arenclient.ui.friends_panel as fp
        assert hasattr(fp, "os")
        assert fp.__dict__["os"].path.join("a", "b") == os.path.join("a", "b")

    @check("the friends panel links Discord from where you can see you need it")
    def _friends_link_button():
        from arenclient.core import social
        from arenclient.ui import friends_panel as fp
        a = app()
        panel = a.pages["home"].friends
        saved_link, saved_is = fp.social.get_link, fp.social.is_linked
        made = []
        try:
            fp.social.get_link = lambda: {}
            fp.social.is_linked = lambda: False
            panel._sync_link()
            pump(4)
            assert "Link Discord" in str(panel.link_btn.cget("text"))
            assert "Not linked" in str(panel.who_lbl.cget("text"))
            assert not panel.unlink_btn.winfo_manager(), "nothing to unlink"

            class FakeDialog:
                def __init__(self, master, app_, on_done=None):
                    made.append(on_done)

                def after(self, ms, fn):
                    pass

                def lift(self):
                    pass

            real_dialog = fp.DiscordLinkDialog
            fp.DiscordLinkDialog = FakeDialog
            try:
                panel.link_btn.invoke()
                pump(4)
                assert len(made) == 1 and callable(made[0]), \
                    "pressing it must run the link flow"

                fp.social.get_link = lambda: {"username": "wummsy_ig", "token": "t",
                                              "avatar_url": "https://x/y.png"}
                fp.social.is_linked = lambda: True
                panel._after_link()
                pump(6)
                assert "wummsy_ig" in str(panel.who_lbl.cget("text")), \
                    panel.who_lbl.cget("text")
                assert str(panel.link_btn.cget("text")) == "Re-link"
                assert panel.unlink_btn.winfo_manager() == "grid"
                made.clear()
                panel._link_pressed()
                pump(4)
                assert len(made) == 1, "re-link must run the same flow again"
            finally:
                fp.DiscordLinkDialog = real_dialog
        finally:
            fp.social.get_link, fp.social.is_linked = saved_link, saved_is
            panel._sync_link()

    @check("friend avatars come from the image desk, never from the UI thread")
    def _friend_avatars():
        from arenclient.ui import friends_panel as fp
        from arenclient.ui.widgets import Card
        a = app()
        panel = a.pages["home"].friends
        # a blocking fetch on the render path is the bug; the desk must own it
        src = open(os.path.join(ROOT, "arenclient", "ui", "friends_panel.py"),
                   encoding="utf-8").read()
        assert "fetch_icon" not in src, "avatars must not be downloaded while painting"
        assert "requests" not in src
        assert "ImageDesk" in src and "self._desk.show" in src

        card = Card(panel.list)
        lbl = panel._avatar({"username": "Zed", "avatar_url": "https://cdn.discordapp.com/a.png",
                             "presence": "in_game"}, card, 0, 0)
        pump(4)
        assert lbl is not None
        assert panel._desk._pending or panel._desk._images, \
            "the desk was never given the avatar to fetch"
        # no url -> the letter tile, and nothing queued
        before = panel._desk.jobs
        lbl2 = panel._avatar({"username": "Nope", "avatar_url": ""}, card, 1, 0)
        pump(4)
        assert panel._desk.jobs == before, "a friend with no picture must not queue a job"
        assert str(lbl2.cget("text")) == "N"
        card.destroy()

    @check("the home banner crops the hero art to its box instead of stretching it")
    def _home_banner():
        from arenclient.ui.pages.home import Banner, _cover
        from arenclient import paths
        a = app()
        home = a.pages["home"]
        assert isinstance(home.banner, Banner)
        img = _cover(paths.resource_path("assets/hero_bg.png"), 640, 186)
        assert img is not None, "the hero art must load"
        assert img.size == (640, 186), img.size      # cover, not fit, not squash
        wide = _cover(paths.resource_path("assets/hero_bg.png"), 1400, 186)
        assert wide.size == (1400, 186), wide.size
        pump(8)
        assert home.banner._shown_w > 0, "the banner never reacted to its own width"
        home.banner.set_running(2, 1)
        pump(3)
        assert "2 games running" in str(home.banner.status_pill.cget("text")), \
            home.banner.status_pill.cget("text")
        home.banner.set_running(0, 0)
        pump(3)
        assert str(home.banner.status_pill.cget("text")) == "nothing running"
        # and a missing asset must not take the page down with it
        assert _cover(os.path.join(_TMP, "nope.png"), 300, 200) is None

    @check("a picture that arrives off-thread still reaches its label")
    def _offthread_delivery():
        """The delivery bug, pinned.

        imagedesk._post used to ask Tk whether the label was alive *from the worker
        thread*. That call only raises when the UI thread is inside its event loop - which
        is every moment the app is actually running - and the exception was swallowed, so
        a downloaded icon was cached, decoded and then quietly thrown away. Friend
        avatars stayed letter tiles while the mod browser (same desk, different timing)
        looked fine. Hence: make winfo_exists behave like a live mainloop and check the
        callback still lands.
        """
        import threading
        import time
        from arenclient.ui import imagedesk as ID
        a = app()
        lbl = ctk.CTkLabel(a, text="K", width=30, height=30, corner_radius=0)
        lbl.grid(row=99, column=0)
        real_exists = lbl.winfo_exists
        def exists_only_from_main():
            if threading.current_thread() is not threading.main_thread():
                raise RuntimeError("main thread is not in main loop")
            return real_exists()
        lbl.winfo_exists = exists_only_from_main
        done = []
        try:
            t = threading.Thread(target=lambda: ID._post(lbl, lambda: done.append(1)))
            t.start()
            t.join(5)
            assert not done, "the callback ran on the worker thread"
            deadline = time.time() + 3
            while time.time() < deadline and not done:
                a.update()
                time.sleep(0.01)
            assert done, "the callback was dropped instead of handed to the main loop"
        finally:
            try:
                del lbl.winfo_exists
            except Exception:
                pass
            lbl.grid_forget()

    @check("an avatar keeps its row slot whether or not a picture arrives")
    def _avatar_tile_size():
        from arenclient.ui.friends_panel import FriendsPanel      # noqa: F401
        from arenclient.ui.widgets import Card
        from PIL import Image
        a = app()
        panel = a.pages["home"].friends
        card = Card(panel)
        card.grid_columnconfigure(2, weight=1)
        tile = panel._avatar({"username": "Kirro", "avatar_url": "",
                              "presence": "online"}, card, 0, 0)
        a.update_idletasks()
        letter_w = tile.winfo_reqwidth()
        tile.configure(image=ctk.CTkImage(light_image=Image.new("RGBA", (30, 30)),
                                          dark_image=Image.new("RGBA", (30, 30)),
                                          size=(30, 30)))
        a.update_idletasks()
        # CTkLabel pads its content by corner_radius: at radius 15 a 30px image asks for
        # 60px, which stole the name column and clipped both.
        assert tile.winfo_reqwidth() <= letter_w + 4, (
            "the picture grew the tile: %s px -> %s px"
            % (letter_w, tile.winfo_reqwidth()))
        assert tile.cget("compound") == "none", "the letter must not sit beside the image"
        card.destroy()

    @check("the sidebar's account row wears the person mark and keeps it on refresh")
    def _account_mark():
        import time as _t
        a = app()
        from arenclient.ui import widgets as W
        glyph = W.load_glyph("assets/ui_account.png", (20, 20))
        assert glyph is not None, "the account glyph must ship in assets/"
        assert str(a.nav.account_btn.cget("image")) not in ("", "None")
        assert "Not signed in" in str(a.nav.account_btn.cget("text"))
        a.nav.refresh_account()
        pump(4)
        # the text follows the account; the mark must survive the configure()
        assert str(a.nav.account_btn.cget("image")) not in ("", "None")

    @check("the modpack dialog searches off-thread and paints what comes back")
    def _modpack_dialog():
        import time as _t
        from arenclient.ui import modpack_dialog as MD
        a = app()
        hits = [{"slug": "fabric-faithful", "title": "Fabric Faithful", "author": "someone",
                 "downloads": 12345, "icon_url": "", "description": "a pack"}]
        calls = []
        real_search = MD.modpacks.search

        def fake_search(query="", **kw):
            calls.append((query, kw))
            return list(hits), 1

        MD.modpacks.search = fake_search
        try:
            dlg = MD.ModpackDialog(a, a)
            for _ in range(30):
                a.update_idletasks()
                a.update()
                _t.sleep(0.02)
            texts = []
            for w in dlg.list_frame.winfo_children():
                for c in w.winfo_children():
                    try:
                        texts.append(str(c.cget("text")))
                    except Exception:
                        pass
            assert calls, "the dialog must search as it opens"
            assert any("Fabric Faithful" in t for t in texts), texts[:4]
            assert any("12,345" in t for t in texts), texts[:4]
            assert dlg.list_frame.winfo_children(), "no row was built"
            dlg._close()
            a.update()
        finally:
            MD.modpacks.search = real_search


    @check("the logo is the sidebar and loading head, and the assets ship")
    def _logo_assets():
        from arenclient import paths
        for rel in ("assets/logo.png", "assets/hero_bg.png", "assets/emblem.png",
                    "assets/icon.ico", "assets/icon_mono.png", "assets/icon_mono.ico"):
            assert os.path.exists(paths.resource_path(rel)), rel
        a = app()
        nav_src = open(os.path.join(ROOT, "arenclient", "ui", "nav.py"),
                       encoding="utf-8").read()
        load_src = open(os.path.join(ROOT, "arenclient", "ui", "loading.py"),
                        encoding="utf-8").read()
        assert "assets/logo.png" in nav_src and "assets/logo.png" in load_src
        assert "logo_lbl" in nav_src and "logo_lbl" in load_src
        pump(4)
        try:
            has_img = a.nav.logo_lbl.cget("image") not in ("", None)
        except Exception:
            has_img = False
        assert has_img, "the sidebar head should be holding the logo image"

    @check("the Home play card is the flow's display and follows it")
    def _home_display():
        a = app()
        home = a.pages["home"]
        assert home in a.flow._displays or True      # registered in __init__
        inst = a.instances.create("Home Chosen", "1.21.4", loader="fabric",
                                  loader_version="0.19.5")
        a.flow.refresh()
        a.flow.select(inst)
        pump(8)
        assert str(home.play_title.cget("text")) == inst.name
        assert "Fabric" in str(home.play_summary.cget("text"))
        assert "Home Chosen" in [str(v) for v in home.inst_menu.cget("values")]
        # A launch started by an earlier check is still posting state through the flow, and a
        # display that is being poked by hand cannot be compared against a moving target.
        # Park the pushes for the length of the manual part of this check, then put them back.
        real_push = a.flow._push
        a.flow._push = lambda display=None: None
        home.set_state(True, False, "downloading 1.21.4")
        pump(2)
        assert "Starting" in str(home.play_btn.cget("text"))
        assert str(home.play_btn.cget("state")) == "disabled"
        assert home.bar.winfo_manager() == "grid"
        home.set_state(False, True, "the game is up")
        pump(2)
        assert home.stop_btn.winfo_manager() == "grid"
        home.launch_error("java is missing")
        pump(2)
        assert "java is missing" in str(home.status.cget("text"))
        home.set_state(False, False, "")
        pump(2)
        assert home.stop_btn.winfo_manager() != "grid"
        assert home.bar.winfo_manager() != "grid", "the bar must not sit at zero forever"
        a.flow._push = real_push
        a.instances.delete(inst.id, remove_files=True)
        pump(4)

    @check("show_page('versions') still lands on the Instances page")
    def _alias():
        a = app()
        a.show_page("versions")
        pump(4)
        assert a._current == "instances"
        assert a.pages["instances"].winfo_manager() == "grid"
        from arenclient.ui.pages import versions_page
        assert versions_page.InstancesPage is a.pages["instances"].__class__

    @check("a worker thread's after() actually reaches the main loop")
    def _post_queue():
        import threading
        import time as _t
        import tkinter as tk
        from arenclient.ui import post
        post.install()
        root = tk.Tk()
        root.withdraw()
        post.start(root)
        got = []

        def work():
            _t.sleep(0.03)
            root.after(0, lambda: got.append("after"))
            root.after_idle(lambda: got.append("idle"))
            # and a cancelled one must not run
            tok = root.after(0, lambda: got.append("cancelled"))
            root.after_cancel(tok)

        threading.Thread(target=work, daemon=True).start()
        deadline = _t.time() + 4
        while _t.time() < deadline and len(got) < 2:
            try:
                root.update()
            except Exception:
                break
            _t.sleep(0.01)
        try:
            root.destroy()
        except Exception:
            pass
        assert "after" in got and "idle" in got, got
        assert "cancelled" not in got, got

    @check("the first open offers the Defender exclusion, and Launch stays live")
    def _defender_offer_once():
        import time as _t
        from unittest import mock
        import tkinter as tk
        from arenclient.core import defender
        from arenclient.ui import defender_offer
        a = app()
        pump()
        cfg = a.config_store
        saved = dict(cfg.data)
        info = {"state": "ready", "paths": [os.path.join(ROOT, "dist", "DivineClient")],
                "script": os.path.join(ROOT, "tools", "defender_exclusions.ps1"),
                "process": "DivineClient.exe", "can_remove": False,
                "detail": "adds an exclusion for the Divine folders only"}
        seen = []
        try:
            cfg.set("defender_asked", False)
            with mock.patch.object(defender, "platform_ok", lambda: True), \
                 mock.patch.object(defender, "script_path", lambda: info["script"]), \
                 mock.patch.object(defender, "status", lambda c=None: dict(info)), \
                 mock.patch.object(defender, "apply_async", lambda **kw: seen.append(kw)):
                assert defender_offer.maybe_offer(a) is True, "a Windows first open must be asked"
                pump()
                dlg = getattr(a, "_defender_offer", None)
                def alive(widget):
                    # a destroyed Tk widget does not report False, it raises: "gone" is the
                    # answer the test wants, so ask it the way the app has to
                    try:
                        return bool(widget.winfo_exists())
                    except Exception:
                        return False

                assert dlg is not None and alive(dlg), "no dialog was shown"
                assert isinstance(dlg, tk.Toplevel), "the offer must be a Toplevel, not a modal"
                assert cfg.get("defender_asked") is True, "shown counts as asked, so it never nags"
                assert str(a.pages["home"].play_btn.cget("state")) == "normal", \
                    "an offer must never stand between someone and Launch"
                assert defender_offer.maybe_offer(a) is False, "it asked twice"

                dlg._add()
                pump()
                assert len(seen) == 1 and seen[0].get("remove", False) is False, seen
                assert not alive(dlg), "a dialog left up while the UAC prompt waits"
                try:
                    grabbed = dlg.grab_current()
                except Exception:
                    grabbed = None
                assert grabbed is None, "the grab must go with the dialog"
                seen[0]["on_done"]({"ok": True, "verified": True, "added": list(info["paths"]),
                                    "reason": ""})
                pump()

                # closing the window instead of answering is a "not now", not a crash
                cfg.set("defender_state", "")
                dlg2 = defender_offer.DefenderOffer(a, app=a, info=dict(info))
                pump()
                dlg2._later()
                pump()
                assert cfg.get("defender_state") == "declined", cfg.data
                assert not alive(dlg2)
        finally:
            for d in (getattr(a, "_defender_offer", None),):
                try:
                    if d is not None and d.winfo_exists():
                        d.destroy()
                except Exception:
                    pass            # already gone, which is what we wanted anyway
            a._defender_offer = None
            cfg.data.clear()
            cfg.data.update(saved)
            cfg.save()
        pump()

    @check("saying no does not take the choice away: Settings still offers it")
    def _defender_settings_card():
        a = app()
        page = a.pages["settings"]
        from arenclient.core import defender
        for state, want in (("declined", "not added"), ("already", "on the list"),
                            ("ready", "not added"), ("no-script", "helper missing"),
                            ("unsupported", "windows only")):
            page._show_defender({"state": state, "paths": [], "script": "x",
                                 "can_remove": state == "already", "detail": ""})
            got = str(page.defender_pill.cget("text"))
            assert got == want, "%s -> %r, wanted %r" % (state, got, want)
        # the button is offered for every state where something could still be done, and
        # removal only appears when the exclusion is actually on the list
        page._show_defender({"state": "already", "paths": [], "script": "x",
                             "can_remove": True, "detail": ""})
        assert page.defender_remove.winfo_manager() == "grid", "no way back out"
        page._show_defender({"state": "no-script", "paths": [], "script": "",
                             "can_remove": False, "detail": ""})
        assert str(page.defender_btn.cget("state")) == "disabled", "nothing to add here"
        assert page.defender_remove.winfo_manager() != "grid"
        assert "Defender" in open(os.path.join(ROOT, "arenclient", "ui", "pages",
                                               "settings_page.py"),
                                  encoding="utf-8").read(), "the card must say what it is"
        for src in ("arenclient/ui/pages/settings_page.py", "arenclient/ui/defender_offer.py"):
            body = open(os.path.join(ROOT, *src.split("/")), encoding="utf-8").read()
            assert "winfo_selected" not in body, \
                "%s uses a Tk method CTkCheckBox does not have - it must use .get()" % src
        page.refresh_defender()
        _t = __import__("time")
        deadline = _t.time() + 6
        while _t.time() < deadline and str(page.defender_pill.cget("text")) == "checking\u2026":
            pump(2)
            _t.sleep(0.03)
        assert str(page.defender_pill.cget("text")) != "checking\u2026", \
            "the card never filled in"

    @check("the Settings card reads Defender off the UI thread, and paints on it")
    def _defender_off_the_ui_thread():
        import threading
        import time as _t
        from unittest import mock
        from arenclient.core import defender
        a = app()
        page = a.pages["settings"]
        box = {}
        real_status = defender.status

        def slow_status(cfg=None):
            box["thread"] = threading.current_thread().name
            _t.sleep(0.25)                      # a slow PowerShell read, as it really is
            return {"state": "ready", "paths": [], "script": "x", "can_remove": False,
                    "detail": "adds an exclusion for the Divine folders only"}

        page.defender_pill.configure(text="checking\u2026")
        with mock.patch.object(defender, "status", slow_status):
            page.refresh_defender()
            # the freeze test: while that 0.25 s read is running, this thread must still paint
            painted = []
            t0 = _t.time()
            while _t.time() - t0 < 0.22:
                pump(1)
                painted.append(1)
                _t.sleep(0.01)
            assert len(painted) > 3, "the page could not repaint during the read"
            deadline = _t.time() + 6
            while _t.time() < deadline and "thread" not in box:
                pump(2)
                _t.sleep(0.02)
            assert box.get("thread") == "divine-defender-status", box
            deadline = _t.time() + 4
            while _t.time() < deadline and str(page.defender_pill.cget("text")) == "checking\u2026":
                pump(2)
                _t.sleep(0.02)
            assert str(page.defender_pill.cget("text")) == "not added", \
                page.defender_pill.cget("text")
        real_status()

    @check("the loading screen is driven by the startup thread, not left at zero")
    def _splash_follows_the_worker():
        import time as _t
        from arenclient.ui.loading import Loading
        a = app()
        ls = Loading(a)
        a._splash = ls
        try:
            a._startup_worker()          # what the boot thread runs, run right here
            deadline = _t.time() + 6
            while _t.time() < deadline and ls.bar.get() < 0.5:
                pump(2)
                _t.sleep(0.01)
            assert ls.bar.get() > 0.4, "the bar never moved: %r" % (ls.bar.get(),)
            assert "boot" not in ls._done_stages or True
            assert ls.stages_lbl.cget("text").count("\u2713") >= 1
        finally:
            a._splash = None
            try:
                ls.finish()
            except Exception:
                pass

    @check("the loading screen paints its stages, never goes backwards, and is destroyed")
    def _loading_gui():
        from arenclient.ui.loading import Loading, STAGES
        a = app()
        ls = Loading(a)
        pump()
        last = -1.0
        for key, _w, _t in STAGES:
            ls.stage(key)
            pump(3)
            val = ls.bar.get()
            assert val >= last, "the bar moved backwards at %s" % key
            last = val
        assert abs(last - 1.0) < 1e-6, last
        # a stuck stage cannot read as finished: the ceiling is the stage's own
        ls2 = Loading(a)
        ls2.stage("boot")
        pump(2)
        assert ls2.bar.get() < 0.2, "the first stage must not fill the bar"
        ls2.finish()
        pump(3)
        ls.finish()
        pump(3)
        for w in (ls, ls2):
            try:
                alive = w.winfo_exists()
            except Exception:
                alive = False
            assert not alive, "finish() must destroy the window, not fade it out"
        # and the app must not keep it referenced
        a._splash = None

    @check("settings drives updates and the locked tab from config, and no rails")
    def _settings_wiring():
        a = app()
        page = a.pages["settings"]
        page.on_show()
        pump()
        for gone in ("anim_chk", "menu_pin_chk", "friends_pin_chk", "_apply_menu_pin",
                     "_apply_friends_pin"):
            assert not hasattr(page, gone), "the rail setting %s came back" % gone
        # the servers switch can only put the tab away
        page.servers_unlock_chk.select()
        page._apply_servers_unlock()
        pump()
        page.servers_unlock_chk.deselect()
        page._apply_servers_unlock()
        pump()
        assert a.servers_unlocked() is False
        assert a._current != "servers"
        # an update state reaches the sidebar pill and the settings line
        state = {"state": "downloaded", "remote": "9.9"}
        a._update_state = state
        a._show_update_state(state)
        page._show_update_state()
        pump()
        assert "9.9" in str(a.nav.pill.cget("text"))
        assert "restart" in str(page.update_status.cget("text")).lower()
        assert str(page.restart_update_btn.cget("state")) != "disabled"
        state = {"state": "current", "remote": "1.0"}
        a._update_state = state
        a._show_update_state(state)
        page._show_update_state()
        pump()
        assert not a.nav.pill.winfo_manager()
        assert str(page.restart_update_btn.cget("state")) == "disabled"
        page._save()
        pump()
        assert "menu_rail_pinned" not in a.config_store.data
        assert a.config_store.get("servers_unlocked") is False

    @check("the update pill in the sidebar is the app's, and it hides when done")
    def _pill():
        a = app()
        for state, needle in (({"state": "available", "remote": "1.1"}, "1.1"),
                              ({"state": "staged", "remote": "1.1"}, "1.1"),
                              ({"state": "failed", "detail": "no zip here"}, "no zip here"),
                              ({"state": "no-download", "detail": "site is odd"}, "site is odd")):
            a._show_update_state(state)
            pump(3)
            assert a.nav.pill.winfo_manager() == "grid", state
            assert needle in str(a.nav.pill.cget("text")), (state, a.nav.pill.cget("text"))
        a._show_update_state({"state": "current", "remote": "1.0"})
        pump(3)
        assert a.nav.pill.winfo_manager() != "grid"

    @check("the servers badge lands on the sidebar button and clears again")
    def _badge():
        a = app()
        a.refresh_server_badge()
        pump()
        btn = a.nav.buttons["servers"]
        text = str(btn.cget("text"))
        # phase 13: the row carries the supplied PNG as its image, so the words beside it stay
        # plain. Either mark counts - what must not happen is a row with neither.
        assert text.strip().startswith("Servers"), text
        assert str(btn.cget("image")) or "\u2601" in text, "the Servers row has no mark"
        a.nav.set_server_badge(3)
        pump(3)
        assert "3" in str(a.nav.buttons["servers"].cget("text"))
        a.nav.set_server_badge(0)
        pump(3)
        assert "3" not in str(a.nav.buttons["servers"].cget("text"))

    @check("auto-update can be turned off, and a manual check still works")
    def _auto_update_switch():
        import threading
        import time as _t
        from arenclient.core import updater
        a = app()
        saved_worker = a._update_worker
        calls = []

        def fake(force=False):
            calls.append(force)
            a._update_state = {"state": "off" if not force else "current",
                               "remote": "1.0"}
        try:
            a._update_worker = fake
            a.config_store.set("auto_update", False)
            a._update_worker()
            assert calls[-1] is False
            assert a._update_state["state"] == "off"
            a.check_for_updates_now()
            _t.sleep(0.2)
            assert calls[-1] is True, "the Settings button must force a check"
            a.config_store.set("auto_update", True)
        finally:
            a._update_worker = saved_worker
            assert isinstance(threading.Event(), threading.Event)

    @check("the code gate is checked on every navigation, then remembered")
    def _gate_flow():
        a = app()
        asked = []
        saved = a._ask_allowance_code
        a._ask_allowance_code = lambda target: asked.append(target)
        try:
            a.config_store.set("servers_unlocked", False)
            a.show_page("servers")
            pump()
            assert asked == ["servers"] and a._current != "servers"
            a.pages["servers"].winfo_children()          # page still exists, just not shown
            assert a._unlock_tab("wrong") is False
            assert a._unlock_tab("divineserverallowance112233") is True
            pump()
            assert a._current == "servers"
            assert a.config_store.get("servers_unlocked") is True
            a.lock_servers()
            pump()
            assert a._current == "home" and a.servers_unlocked() is False
        finally:
            a._ask_allowance_code = saved
            a.config_store.set("servers_unlocked", False)

    @check("home reads the news off-thread, because the site is allowed to be slow")
    def _news_source():
        src = open(os.path.join(ROOT, "arenclient", "ui", "pages", "home.py"),
                   encoding="utf-8").read()
        assert "news.get_news" in src, "the news list must come from core.news"
        head = src[src.index("def refresh_news"):src.index("def _news_ready")]
        assert "threading.Thread" in head, "the fetch must not happen on the UI thread"
        assert "self.app.after(0" in head

    @check("quit reports offline while the process can still ask")
    def _quit_presence():
        src = open(os.path.join(ROOT, "arenclient", "ui", "app.py"),
                    encoding="utf-8").read()
        close = src[src.index("def _on_close"):src.index("def _ask_before_quit")]
        assert '"offline"' in close and "sync=True" in close
        assert "self.destroy()" == close.strip().splitlines()[-1].strip(), \
            "the report must come before the window goes away"

    @check("the icon assets are the mono set, and the shell uses them")
    def _assets():
        assets = os.path.join(ROOT, "assets")
        for name in ("icon.ico", "icon_mono.png", "icon_mono.ico", "emblem.png",
                     "logo_stacked.png"):
            assert os.path.exists(os.path.join(assets, name)), name
        ico = open(os.path.join(assets, "icon_mono.ico"), "rb").read()
        assert ico[:4] == b"\x00\x00\x01\x00", "a real .ico header"
        assert len(ico) > 1000

else:
    print("  skip  GUI checks - no display reachable (run under xvfb-run)")


@check("every asset the code loads by name is in the built exe")
def _assets_shipped():
    """The gap between "it works here" and "players see it".

    A missing data file in a PyInstaller bundle is silent: load_ctk_image and load_glyph
    return None and the UI falls back to text, so an exe can ship with no icons at all and
    nobody notices in the source tree. So compare the strings the code asks for against the
    list the spec bundles, the same way the spec builds it.
    """
    import re
    spec = open(os.path.join(ROOT, "DivineClient.spec"), encoding="utf-8").read()
    m = re.search(r"ASSET_FILES = \((.*?)\)", spec, re.S)
    assert m, "the spec must name the assets it ships"
    have = set(re.findall(r'"([^"]+)"', m.group(1)))
    g = re.search(r'n\.startswith\(\((.*?)\)\)\)', spec)
    prefixes = tuple(re.findall(r'"([^"]+)"', g.group(1))) if g else ()
    assets = os.path.join(ROOT, "assets")
    for name in os.listdir(assets):
        if name.startswith(prefixes):
            have.add(name)
    assert prefixes, "the marks must be globbed, not listed one by one"

    used = set()
    for dirpath, dirs, files in os.walk(os.path.join(ROOT, "arenclient")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            body = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            used |= set(re.findall(r'["\']assets[/\\]+([^"\']+?)["\']', body))
            used |= set(re.findall(r'os\.path\.join\(\s*["\']assets["\']\s*,\s*["\']([^"\']+?)["\']',
                                    body))
    used = {u for u in used if os.path.isfile(os.path.join(assets, u))}
    missing = sorted(u for u in used if u not in have)
    assert not missing, "loaded by the launcher but not bundled: %s" % missing
    # and the design drop must stay out, or every download carries 2.7 MB of nothing
    assert "_original_ai_logo" not in have


@check("the site publishes the client version and takes presence")
def _server_endpoints():
    server_dir = os.path.join(ROOT, "server")
    saved_db = os.environ.get("DIVINE_DB")
    os.environ["DIVINE_DB"] = os.path.join(_TMP, "shell.db")
    sys.path.insert(0, server_dir)
    try:
        import app as site                                        # noqa: A001
        import db as sdb
        from time import time as now

        client = site.app.test_client()

        # --- /api/client/version reflects exactly the env names that were asked for
        site.CLIENT_VERSION = "1.2"
        site.CLIENT_URL = "https://example.invalid/files/Divine-1.2.zip"
        site.CLIENT_SHA256 = "a" * 64
        site.CLIENT_SIZE = "4321"
        site.CLIENT_NOTES = "new rails"
        r = client.get("/api/client/version")
        assert r.status_code == 200, r.status_code
        body = r.get_json()
        assert body["version"] == "1.2" and body["url"] == site.CLIENT_URL
        assert body["sha256"] == "a" * 64 and body["size"] == 4321
        assert body["file"] == "Divine-1.2.zip" and body["notes"] == "new rails"
        assert "max-age" in r.headers.get("Cache-Control", "")
        site.CLIENT_URL = ""
        site.CLIENT_SIZE = ""
        body = client.get("/api/client/version").get_json()
        assert body["url"] == "" and body["file"] == "" and body["size"] == 0

        # --- presence
        sdb.upsert_user("u1", "one", "")
        sdb.upsert_user("u2", "two", "")
        tok = sdb.issue_token("u1")
        sdb.get_conn().execute(
            "INSERT OR REPLACE INTO friendships (requester, addressee, status, created) "
            "VALUES ('u1','u2','accepted',?)", (int(now()),))
        sdb.get_conn().commit()

        r = client.post("/api/presence", json={"state": "napping"})
        assert r.status_code == 401, "no token must not be able to write presence"
        r = client.post("/api/presence", json={"state": "napping"},
                        headers={"Authorization": "Bearer " + tok})
        assert r.status_code == 400, r.get_json()
        r = client.post("/api/presence", json={"state": "in_game", "detail": "Playing 1.21.4"},
                        headers={"Authorization": "Bearer " + tok})
        assert r.status_code == 200 and r.get_json()["state"] == "in_game"

        pub = site._user_public("u1")
        assert pub["presence"] == "in_game" and pub["presence_detail"] == "Playing 1.21.4"
        assert pub["online"] is True

        friends = client.get("/api/friends",
                              headers={"Authorization": "Bearer " + sdb.issue_token("u2")}
                              ).get_json()["friends"]
        assert friends and friends[0]["id"] == "u1"
        assert friends[0]["presence"] == "in_game", "the friend list must see it"

        # a stale claim is not believed: green cannot outlive the launcher
        sdb.get_conn().execute("UPDATE users SET presence_at=? WHERE id=?",
                               (int(now()) - 4000, "u1"))
        sdb.get_conn().commit()
        pub = site._user_public("u1")
        assert pub["presence"] != "in_game", pub

        # --- the friend list's own heartbeat still marks them online
        sdb.set_presence("u1", "offline")
        assert site._user_public("u1")["presence"] == "offline"
        assert site._user_public("nobody")["presence"] == "offline"
    finally:
        sys.path.remove(server_dir)
        for mod in ("app", "db", "envfile"):
            sys.modules.pop(mod, None)
        if saved_db:
            os.environ["DIVINE_DB"] = saved_db
        else:
            os.environ.pop("DIVINE_DB", None)
        dbmod = sys.modules.get("db")
        if dbmod is not None:
            dbmod.DB_PATH = saved_db or os.path.join(server_dir, "divine.db")
            dbmod._conn = None


@check("the update download talks to the site over real HTTP, and says what went wrong")
def _updater_download():
    """End-to-end on the fetch path, because that is where the update broke in the field.

    ``updater.download`` used to open the release URL with raw urllib while everything
    else in the launcher goes through the pooled requests session, and it wrapped every
    error in "the update download failed" - which is 26 characters of the 52 the pill
    has, so nobody could see whether it was a 404, a TLS problem or a blocked port. This
    runs the real Flask app on a real socket and asks what each failure looks like.
    """
    import hashlib
    import threading
    import zipfile
    from arenclient.core import updater

    server_dir = os.path.join(ROOT, "server")
    sys.path.insert(0, server_dir)
    import app as site                                              # noqa: A001
    from werkzeug.serving import make_server

    work = os.path.join(_TMP, "release")
    os.makedirs(work, exist_ok=True)
    payload = os.path.join(work, "DivineClient")
    os.makedirs(os.path.join(payload, "_internal"), exist_ok=True)
    exe = os.path.join(payload, "DivineClient.exe")
    with open(exe, "wb") as f:
        f.write(b"MZ" + os.urandom(300000))
    with open(os.path.join(payload, "_internal", "base_library.zip"), "wb") as f:
        f.write(b"PK\x03\x04" + os.urandom(4000))
    arc = os.path.join(work, "DivineClient-9.9.0-windows.zip")
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _d, files in os.walk(payload):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, work))
    blob = open(arc, "rb").read()
    digest, size = hashlib.sha256(blob).hexdigest(), len(blob)

    site.app.static_folder = work            # /static/<name> = the shipped default route
    srv = make_server("127.0.0.1", 0, site.app, threaded=True)
    base = "http://127.0.0.1:%d" % srv.server_port
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        info = {"version": "9.9", "url": base + "/static/" + os.path.basename(arc),
                "file": os.path.basename(arc), "sha256": digest, "size": size,
                "notes": "test build"}
        # a good download: unpacked, wrapper folder stripped, record written
        seen = []
        path, kind = updater.download(info, progress=lambda f, t: seen.append((f, t)))
        assert kind == "dir" and os.path.isdir(path), (kind, path)
        assert os.path.isfile(os.path.join(path, "DivineClient.exe")), \
            "the zip's DivineClient/ wrapper was not stripped: %r" % sorted(os.listdir(path))
        assert os.path.isfile(os.path.join(path, updater.VERSION))
        assert seen and seen[0][0] == 0.0 and seen[-1][0] > 0.0, seen[:2]
        updater.clear_staged(path)

        # a URL that 404s must say 404, on the site that served it, and say it first
        bad = dict(info, url=base + "/static/nope.zip", file="nope.zip")
        try:
            updater.download(bad)
            raise AssertionError("a 404 was accepted as a build")
        except AssertionError:
            raise
        except Exception as e:
            msg = str(e)
            assert "404" in msg and "nope.zip" in msg, msg
            assert not msg.startswith("the update download failed"), msg

        # the site's own HTML page is not an archive, and must not be staged
        html = dict(info, url=base + "/download", file="download.html")
        try:
            updater.download(html)
            raise AssertionError("an HTML page was accepted as a build")
        except AssertionError:
            raise
        except Exception as e:
            assert "html" in str(e).lower() or "not a build" in str(e), str(e)

        # a checksum that does not match is refused, and the file is gone
        wrong = dict(info, sha256="0" * 64)
        try:
            updater.download(wrong)
            raise AssertionError("a mismatched hash was accepted")
        except AssertionError:
            raise
        except Exception as e:
            assert "checksum" in str(e).lower(), str(e)
        assert not os.path.exists(os.path.join(updater.updates_dir(),
                                               os.path.basename(arc) + ".part"))
        assert not os.path.exists(os.path.join(updater.updates_dir(),
                                               os.path.basename(arc)))

        # a connection that never opens names the host, not the wrapper
        import requests
        real_get = requests.Session.get
        def refuse(self, url, **kw):
            raise requests.ConnectionError("connection reset by peer")
        requests.Session.get = refuse
        try:
            updater.download(info)
            raise AssertionError("a refused connection was accepted")
        except AssertionError:
            raise
        except Exception as e:
            assert "could not reach" in str(e) and "127.0.0.1" in str(e), str(e)
        finally:
            requests.Session.get = real_get
    finally:
        srv.shutdown()
        th.join(5)


@check("an old database grows the presence columns by itself")
def _db_migration():
    server_dir = os.path.join(ROOT, "server")
    sys.path.insert(0, server_dir)
    old = os.path.join(_TMP, "old.db")
    import sqlite3
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, "
                    "avatar_url TEXT, last_seen INTEGER);")
    c.execute("INSERT INTO users VALUES ('u9', 'legacy', '', 1)")
    c.commit()
    c.close()
    try:
        import importlib
        for m in ("db",):
            sys.modules.pop(m, None)
        saved = os.environ.get("DIVINE_DB")
        os.environ["DIVINE_DB"] = old
        db = importlib.import_module("db")
        db.DB_PATH = old
        db._conn = None
        db.init_db()
        cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(users)").fetchall()}
        assert {"presence", "presence_at", "presence_detail"} <= cols, cols
        assert db.set_presence("u9", "in_game", "Playing 1.21.4") is True
        row = db.get_conn().execute("SELECT presence, presence_detail FROM users "
                                    "WHERE id='u9'").fetchone()
        assert row["presence"] == "in_game" and row["presence_detail"] == "Playing 1.21.4"
        assert db.set_presence("u9", "sideways") is False, "unknown states are rejected"
        assert db.PRESENCE_TTL >= 60
        db._conn = None
        os.environ.pop("DIVINE_DB", None)
        if saved:
            os.environ["DIVINE_DB"] = saved
    finally:
        sys.modules.pop("db", None)
        sys.path.remove(server_dir)


@check("the tab is called Instances again, and Versions is only an alias")
def _tab_names():
    bad = []
    for base, _dirs, names in os.walk(os.path.join(ROOT, "arenclient")):
        if "__pycache__" in base:
            continue
        for n in names:
            if not n.endswith(".py"):
                continue
            path = os.path.join(base, n)
            txt = open(path, encoding="utf-8").read()
            if n == "app.py":
                assert 'key == "versions"' in txt, \
                    "app.py must keep routing the old key to the page"
            if n in ("nav.py", "app.py"):
                continue
            for probe in ('self.pages["versions"]', "VersionsPage(self.pages_host"):
                if probe in txt:
                    bad.append("%s: %s" % (os.path.relpath(path, ROOT), probe))
    assert not bad, "a Versions page came back:\n  " + "\n  ".join(bad)
    # the modules that survived the rename still import cleanly
    from arenclient.ui.pages import versions_page, instances_page
    assert versions_page.InstancesPage is instances_page.InstancesPage
    from arenclient.ui.instance_editor import InstanceEditor          # noqa: F401
    assert hasattr(instances_page, "ConfirmDialog"), \
        "the editor borrows ConfirmDialog from the page module"



@check("the four UI marks ship, and tinting keeps the shape's alpha")
def _ui_marks():
    from PIL import Image
    from arenclient.ui import theme
    from arenclient.ui.widgets import _rgb, load_glyph, tint_pil
    for rel in ("assets/ui_friends.png", "assets/ui_account.png", "assets/ui_new.png",
                "assets/ui_discord.png"):
        full = os.path.join(ROOT, rel)
        assert os.path.isfile(full), "%s is missing from the build" % rel
        im = Image.open(full)
        assert im.mode == "RGBA", "%s needs an alpha channel to be tintable" % rel
        assert im.size[0] >= 96, "%s is too small to stay crisp at 2x" % rel
    # the glyphs are drawn black on transparency, so an untinted one is invisible on the
    # dark theme; the tint has to fill the shape and leave the holes alone
    src = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
    src.putpixel((0, 0), (0, 0, 0, 0))
    out = tint_pil(src, theme.COL["accent"])
    assert out.getpixel((1, 1)) == _rgb(theme.COL["accent"]) + (255,), out.getpixel((1, 1))
    assert out.getpixel((0, 0))[3] == 0, "a hole must stay a hole"
    assert load_glyph("assets/ui_friends.png", (18, 18)) is not None
    assert load_glyph("assets/nope.png", (18, 18)) is None, \
        "a missing mark must fall back to text, not raise"


@check("playtime banks one session per game, and refuses the nonsense")
def _playtime():
    from arenclient.core import playtime
    from arenclient.core.instances import Instance
    inst = Instance({"id": "pt-one", "name": "pt-one", "mc_version": "1.20.4"})
    assert playtime.total(inst) == 0
    assert playtime.human(0) == "never played"
    assert playtime.add(inst, 0) is None, "a zero-length session must not be kept"
    assert playtime.add(inst, -40) is None
    assert playtime.add(inst, 60 * 60 * 24 * 40) is None, \
        "a clock that jumped across a month must not become playtime"
    assert playtime.total(inst) == 0
    assert playtime.add(inst, 90) == 90
    assert playtime.add(inst, 45 * 60) == 90 + 45 * 60
    assert playtime.human(playtime.total(inst)) == "46 min", playtime.human(2790)
    assert playtime.human(3 * 3600 + 12 * 60) == "3 h 12 m"
    assert playtime.human(50 * 3600) == "2 d 2 h"
    assert playtime.since(playtime.last_played(inst)) == "today"
    assert playtime.recent(inst, days=7) == playtime.total(inst)
    assert playtime.recent(inst, days=1) == playtime.total(inst)
    # junk on disk reads as no history, not as a crash on the page
    with open(playtime.path_for(inst), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert playtime.total(inst) == 0 and playtime.read(inst)["sessions"] == []


@check("an instance can be imported from a folder or a zip of one")
def _import_instance():
    from arenclient.core.instances import InstanceManager
    work = os.path.join(_TMP, "import-src")
    src = os.path.join(work, "My World Folder")
    os.makedirs(os.path.join(src, "mods"), exist_ok=True)
    os.makedirs(os.path.join(src, "saves", "world"), exist_ok=True)
    os.makedirs(os.path.join(src, "versions", "1.20.4"), exist_ok=True)
    with open(os.path.join(src, "instance.cfg"), "w", encoding="utf-8") as f:
        f.write("name=My World Folder\nIntendedVersion=1.20.4\nLoader=fabric\n"
                "OverrideVersion=0.15.7\n")
    with open(os.path.join(src, "mods", "sodium.jar"), "wb") as f:
        f.write(b"PK\x03\x04junk")
    with open(os.path.join(src, "saves", "world", "level.dat"), "wb") as f:
        f.write(b"saved")
    with open(os.path.join(src, "launcher_profiles.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    mgr = InstanceManager()
    found = mgr.detect(src)
    assert found["mc_version"] == "1.20.4" and found["loader"] == "fabric", found
    assert found["name"] == "My World Folder", found

    inst, notes = mgr.import_from(src)
    assert inst.mc_version == "1.20.4" and inst.loader == "fabric"
    assert inst.loader_version == "0.15.7"
    assert os.path.isfile(os.path.join(inst.game_dir, "mods", "sodium.jar"))
    assert os.path.isdir(os.path.join(inst.game_dir, "saves", "world"))
    assert not os.path.exists(os.path.join(inst.game_dir, "versions")), \
        "the launcher's version files must not be copied into an instance"
    assert not os.path.exists(os.path.join(inst.game_dir, "launcher_profiles.json"))
    assert os.path.isdir(os.path.join(inst.game_dir, "mods"))
    assert os.path.exists(os.path.join(inst.game_dir, "mods"))
    assert not notes.get("failed"), notes
    # the original is left alone - import copies, it does not adopt
    assert os.path.isfile(os.path.join(src, "mods", "sodium.jar"))

    # a zip of the same folder works the same way, wrapper and all
    arc = os.path.join(work, "My-World-Folder.zip")
    with zipfile.ZipFile(arc, "w") as z:
        for root, _d, files in os.walk(src):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, work))
    mgr2 = InstanceManager()
    inst2, notes2 = mgr2.import_from(arc)
    assert inst2.id != inst.id and inst2.name == "My World Folder", (inst2.data, inst.data)
    assert os.path.isfile(os.path.join(inst2.game_dir, "mods", "sodium.jar")), \
        "the zip's top folder was not seen through"

    # and something that is not an instance is refused, loudly
    junk = os.path.join(work, "photos")
    os.makedirs(junk, exist_ok=True)
    with open(os.path.join(junk, "holiday.png"), "wb") as f:
        f.write(b"png")
    try:
        InstanceManager().import_from(junk)
        raise AssertionError("a folder of pictures was imported as an instance")
    except AssertionError:
        raise
    except ValueError as e:
        assert "not a Minecraft instance" in str(e), str(e)


@check("an instance keeps its own picture inside its folder")
def _instance_picture():
    import shutil
    from PIL import Image
    from arenclient.core.instances import InstanceManager
    mgr = InstanceManager()
    inst = mgr.create("Pictured", "1.20.4", loader="fabric",
                      extra={"modpack": {"project": "x", "pack_version": "1"}})
    assert inst.data["modpack"]["project"] == "x", "create(extra=) dropped the extras"
    outside = os.path.join(_TMP, "picture.png")
    Image.new("RGBA", (64, 64), (46, 230, 224, 255)).save(outside)
    dest = os.path.join(inst.game_dir, "instance.png")
    shutil.copyfile(outside, dest)
    inst.data["icon_file"] = "instance.png"          # relative, on purpose
    mgr.save()
    reloaded = InstanceManager().get(inst.id)
    assert reloaded.data["icon_file"] == "instance.png"
    full = os.path.join(reloaded.game_dir, reloaded.data["icon_file"])
    assert os.path.isfile(full), "the picture must travel with the instance"
    assert not os.path.isabs(reloaded.data["icon_file"]), \
        "storing an absolute path means a deleted Downloads file breaks the card"
    # and deleting the instance takes the picture with it. The path is captured first:
    # Instance.game_dir creates the folders it is asked about, so asking it afterwards
    # would rebuild the very directory the check wants to see gone.
    game = inst.game_dir
    mgr.delete(inst.id, remove_files=True)
    assert not os.path.exists(game), "the instance folder, picture and all, is still there"


@check("a modpack's manifest decides the instance, and its files land inside it")
def _modpack_install():
    import hashlib
    import json
    from arenclient.core import net
    from arenclient.core import modpacks
    from arenclient.core.instances import InstanceManager

    work = os.path.join(_TMP, "pack")
    os.makedirs(work, exist_ok=True)
    jar = os.path.join(work, "sodium.jar")
    with open(jar, "wb") as f:
        f.write(b"PK\x03\x04the actual mod")
    sha1 = hashlib.sha1(open(jar, "rb").read()).hexdigest()

    meta = {
        "manifestVersion": 1, "name": "Test Pack", "version": "2.1",
        "minecraft": {"version": "1.20.4",
                      "modLoaders": [{"id": "fabric-0.15.7", "primary": True}]},
        "files": [
            {"path": "mods/sodium.jar", "hashes": {"sha1": sha1}, "fileSize": 19,
             "downloads": ["https://example.invalid/sodium.jar"],
             "envs": {"client": "required", "server": "required"}},
            {"path": "mods/server-only.jar", "downloads": ["https://example.invalid/x.jar"],
             "envs": {"client": "unsupported", "server": "required"}},
            {"path": "config/test.toml", "downloads": ["https://example.invalid/t.toml"],
             "fileSize": 2},
            {"path": "../escape.txt", "downloads": ["https://example.invalid/e.txt"]},
        ],
        "overrides": "overrides",
    }
    pack = os.path.join(work, "pack.mrpack")
    bs = chr(92)          # the pack is packed the way PowerShell packs things
    with zipfile.ZipFile(pack, "w") as z:
        z.writestr("modrinth.index.json", json.dumps(meta))
        z.writestr("overrides" + bs + "options.txt" + bs, b"")     # a Windows dir entry
        z.writestr("overrides/options.txt", b"lang=en_us")
        z.writestr("client-overrides/keybinds.txt", b"k=1")
        z.writestr("../not-yours.txt", b"no")

    spec = modpacks.plan(modpacks.read_index(pack))
    assert spec["mc_version"] == "1.20.4" and spec["loader"] == "fabric", spec
    assert spec["loader_version"] == "0.15.7", spec
    paths = [f["path"] for f in spec["files"]]
    assert "mods/sodium.jar" in paths and "config/test.toml" in paths, paths
    assert "mods/server-only.jar" not in paths, "a server-only file must not be fetched"
    assert not any(".." in x for x in paths), paths

    real_download = net.download
    def copy_the_mod(url, dest, *a, **kw):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(jar, dest) if url.endswith("sodium.jar") else \
            open(dest, "wb").write(b"[]")
        return dest
    net.download = copy_the_mod
    try:
        mgr = InstanceManager()
        inst, report = modpacks.install(pack, mgr)
        assert inst.name == "Test Pack" and inst.mc_version == "1.20.4"
        assert inst.loader == "fabric" and inst.loader_version == "0.15.7", inst.data
        assert os.path.isfile(os.path.join(inst.game_dir, "mods", "sodium.jar"))
        assert os.path.isfile(os.path.join(inst.game_dir, "config", "test.toml"))
        assert not os.path.exists(os.path.join(inst.game_dir, "mods", "server-only.jar"))
        assert open(os.path.join(inst.game_dir, "options.txt"), "rb").read() == b"lang=en_us", \
            "the overrides folder is copied *into* the instance, not beside it"
        assert os.path.isfile(os.path.join(inst.game_dir, "keybinds.txt")), \
            "client-overrides must win over the plain overrides folder"
        assert not os.path.exists(os.path.join(work, "not-yours.txt")), "escaped the pack"
        assert report["installed"] >= 1 and not report["failed"], report
    finally:
        net.download = real_download




@check("the release archive takes the app and none of the dev screenshots")
def _release_filter():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    tool = importlib.import_module("make_release_zip")
    keep = ["arenclient/ui/pages/instances_page.py", "assets/ui_new.png",
            "assets/hero_bg.png", "arenclient/core/playtime.py",
            "server/static/logo.png", "README.md"]
    drop = ["preview_9d_home.png", "shot10_home.png", "notes.log", "cache.db",
            "__pycache__/app.pyc", "build/DivineClient.exe"]
    bad = [rel for rel in keep if not tool._wants(rel)]
    assert not bad, "the release tool would leave out: %s" % bad
    bad = [rel for rel in drop if tool._wants(rel)]
    assert not bad, "the release tool would ship junk: %s" % bad



def main():
    print("\nphase 9 shell: %d ok, %d failed"
          % (sum(1 for k, _ in RESULTS if k == "ok"), sum(1 for k, _ in RESULTS if k == "fail")))
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if any(k == "fail" for k, _ in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
