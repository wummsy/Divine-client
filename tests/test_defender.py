"""Tests for the Windows Defender helper the launcher offers on its first open.

Run with:  python tests/test_defender.py

This code decides what gets elevated and what gets excluded, so the tests are mostly about
refusals: a drive root must never reach an exclusion list, the launcher must never invent
PowerShell of its own, and on a machine that is not Windows nothing at all may be run. There
is no PowerShell in this sandbox, so every elevated path here goes through a fake
``subprocess.run`` - which is exactly the point: the real one is only ever
``tools/defender_exclusions.ps1``, a file a person can read before they run it.
"""
import os
import shutil
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="divine-defender-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")
os.environ.setdefault("DIVINE_NO_SERVER_DOWNLOAD", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from divineclient.core import defender                                  # noqa: E402
from divineclient import paths                                          # noqa: E402

paths.ensure_dirs()
B = chr(92)             # one backslash; Windows paths below are built from this, not escaped
RESULTS = []


def check(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append(("ok", name))
            print("  ok    %s" % name)
        except Exception as err:                                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            RESULTS.append(("fail", name))
            print("  FAIL  %s: %r" % (name, err))
        return fn
    return wrap


class FakeConfig:
    """The bits of the real config object the module uses."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saved = True


def W(*pieces):
    """A Windows-shaped path from components: W('C:', 'Games', 'DivineClient')."""
    joiner = B if pieces[0].endswith(":") else B
    out = pieces[0]
    for piece in pieces[1:]:
        out += joiner + piece
    return out


# --------------------------------------------------------------------- platform rules
@check("a non-Windows box gets a refusal, not a subprocess")
def _not_windows_refuses():
    if sys.platform == "win32":
        return                                    # covered by the same code path on CI
    calls = []
    real = subprocess.run
    subprocess.run = lambda *a, **k: calls.append(a) or real(["true"])
    try:
        report = defender.apply()
    finally:
        subprocess.run = real
    assert report["ok"] is False and report["reason"] == "not Windows", report
    assert not calls, "nothing may be run on a machine without Defender"
    info = defender.status()
    assert info["state"] == "unsupported", info
    assert "Windows" in info["detail"], info
    assert defender.first_run_pending(FakeConfig()) is False
    assert defender.auto_pending(FakeConfig({"defender_auto": True})) is False


@check("the offer is pending exactly once, and either answer ends it")
def _once_only():
    cfg = FakeConfig()
    real = (defender.platform_ok, defender.script_path)
    try:
        defender.platform_ok = lambda: True
        defender.script_path = lambda: os.path.join(ROOT, "tools", defender.SCRIPT_NAME)
        assert defender.first_run_pending(cfg) is True, "a fresh Windows box must be asked"
        defender.mark(cfg, "asked")
        assert defender.first_run_pending(cfg) is False, "asking again is nagging"
        assert cfg.data["defender_asked"] is True and cfg.saved is True
        cfg2 = FakeConfig({"defender_asked": True})
        assert defender.first_run_pending(cfg2) is False
    finally:
        defender.platform_ok, defender.script_path = real
    # a Windows box with no helper script next to the exe is not offered anything
    cfg3 = FakeConfig()
    real2 = (defender.platform_ok, defender.script_path)
    try:
        defender.platform_ok = lambda: True
        defender.script_path = lambda: ""
        assert defender.first_run_pending(cfg3) is False, "no script, no dialog"
        info = defender.status(cfg3)
        assert info["state"] == "no-script" and "not next to" in info["detail"], info
    finally:
        defender.platform_ok, defender.script_path = real2


@check("an empty exclusion list is read as empty, not as 'cannot ask'")
def _empty_list_is_known():
    real = (defender.platform_ok, defender.powershell, defender._which)
    ran = []

    class Res:
        returncode = 0
        stdout = "\n##PROC##\n"
        stderr = ""

    def fake_run(cmd, **kw):
        ran.append(cmd)
        return Res()

    try:
        defender.platform_ok = lambda: True
        defender.powershell = lambda: "powershell.exe"
        real_run, subprocess.run = subprocess.run, fake_run
        try:
            assert defender.read_exclusions() == [], "empty must be [], not None"
        finally:
            subprocess.run = real_run
        assert ran and "Get-MpPreference" in ran[0][-1], ran
    finally:
        defender.platform_ok, defender.powershell, defender._which = real


# --------------------------------------------------------------------- path safety
@check("the exclusion refuses a drive, a share, and the profile")
def _too_broad():
    shape = [
        ("C:" + B, True, "drive root"),
        ("C:/", True, "drive root, slash"),
        ("D:", True, "bare drive"),
        (W("C:", "Users"), True, "nothing named below the root"),
        (W("C:", "Games"), True, "a folder of other people's games"),
        (B + B + "box" + B + "share", True, "a whole share"),
        (B + B + "box" + B + "share" + B + "aren", False, "one folder on a share"),
        (W("C:", "Games", "DivineClient"), False, "the app folder"),
        (W("C:", "Program Files", "DivineClient"), False, "the app folder, elsewhere"),
        (W("C:", "Users", "me", "AppData", "Roaming", ".divineclient"), False, "the data folder"),
        (W("C:", "Users", "me", "AppData", "Local", "Temp", "x"), False, "a temp install"),
        ("/", True, "the posix root"),
        ("/home", True, "one level deep on posix"),
        ("/opt/divineclient", False, "a linux install folder"),
    ]
    for path, want, why in shape:
        got = defender.too_broad(path)
        assert got is want, "%s (%s): got %r" % (path, why, got)
    # and the profile rule, with HOME pointed at a Windows-shaped profile
    real = os.path.expanduser
    try:
        os.path.expanduser = lambda p: (W("C:", "Users", "me") if p == "~" else real(p))
        assert defender.too_broad(W("C:", "Users", "me")) is True, "the profile itself"
        assert defender.too_broad(W("C:", "Users")) is True, "above the profile"
        assert defender.too_broad("C:") is True, "the drive, and so everything on it"
        inside = W("C:", "Users", "me", "AppData", "Roaming", ".divineclient")
        assert defender.too_broad(inside) is False, "inside the profile is fine"
    finally:
        os.path.expanduser = real


@check("plan() keeps only our own folders and drops anything too broad")
def _plan_filters():
    app_dir, data_dir = defender.app_dir, defender.data_dir
    home = os.path.expanduser("~")
    try:
        # the ordinary case: the exe folder and the data folder
        defender.app_dir = lambda: os.path.join(ROOT)
        defender.data_dir = lambda: paths.DATA_DIR
        out = defender.plan()
        assert os.path.normpath(ROOT) in out, out
        assert len(out) in (1, 2), out
        # a portable install sitting at D:\ or in the profile is never excluded
        defender.app_dir = lambda: home
        defender.data_dir = lambda: os.path.sep
        assert defender.plan() == [], "the profile or the root must be dropped"
        defender.app_dir = lambda: "/"
        defender.data_dir = lambda: ""
        assert defender.plan() == [], "a bare root must be dropped"
        # a folder that does not exist is not offered either
        defender.app_dir = lambda: os.path.join(_TMP, "not-here")
        defender.data_dir = lambda: paths.DATA_DIR
        assert defender.plan() == [os.path.normpath(paths.DATA_DIR)], defender.plan()
    finally:
        defender.app_dir, defender.data_dir = app_dir, data_dir


# --------------------------------------------------------------------- the command
@check("what gets elevated is the shipped file, not PowerShell built from strings")
def _command_shape():
    real = defender.powershell
    defender.powershell = lambda: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    try:
        script = os.path.join(ROOT, "tools", defender.SCRIPT_NAME)
        folder = W("C:", "Games", "DivineClient")
        cmd = defender.build_command(script, folder)
        text = " ".join(cmd)
        assert cmd[0].endswith("powershell.exe"), cmd[0]
        assert "-NoProfile" in cmd and "-ExecutionPolicy" in cmd and "Bypass" in cmd
        assert "Start-Process" in text and "-Verb RunAs" in text, text
        assert script.replace(B, "/") in text.replace(B, "/"), "the script's own path must be there"
        assert "-AppPath" in text and folder in text, text
        assert "-Remove" not in text, text
        # nothing about Defender's settings is spelled out here: no policy logic in Python
        for forbidden in ("Add-MpPreference", "Set-MpPreference", "Remove-MpPreference",
                          "DisableRealtimeMonitoring", "ExclusionPath"):
            assert forbidden not in text, "%s must live only in the .ps1" % forbidden
        gone = " ".join(defender.build_command(script, folder, extra=("-Remove",)))
        assert "'-Remove'" in gone and "-ExclusionPath" not in gone, gone
    finally:
        defender.powershell = real


@check("the elevated helper only ever excludes, and says so")
def _script_is_honest():
    ps1 = os.path.join(ROOT, "tools", defender.SCRIPT_NAME)
    bat = os.path.join(ROOT, "tools", "add_defender_exclusions.bat")
    assert os.path.isfile(ps1) and os.path.isfile(bat)
    text = open(ps1, encoding="utf-8").read()
    assert "Add-MpPreference -ExclusionPath" in text and "-ExclusionProcess" in text, text[:400]
    assert "$Remove" in text and "Remove-MpPreference" in text, "an undo must exist"
    for forbidden in ("DisableRealtimeMonitoring", "Set-MpPreference -Allow",
                      "New-ItemProperty", "HKLM", "Set-MpPreference -Signature",
                      "New-NetFirewallRule", "CurrentVersion\\Run"):
        assert forbidden not in text, "the helper touched %s" % forbidden
    assert "exit 2" in text and "Test-IsAdmin" in text, "must refuse to do anything unelevated"
    assert "Get-RegisteredAv" in text, "must say who is really providing protection"
    # the .bat hands off to the .ps1 next to it, so the launcher and the double-click agree
    body = open(bat, encoding="utf-8").read()
    assert "defender_exclusions.ps1" in body and "-Verb RunAs" in body, body[:300]
    # and the build copies both next to the exe, which is where script_path() looks
    build = open(os.path.join(ROOT, "build_exe.bat"), encoding="utf-8").read()
    for name in (defender.SCRIPT_NAME, "add_defender_exclusions.bat"):
        assert name in build, "%s is not shipped into dist" % name


@check("a status() answer is a shape the UI can print without thinking")
def _status_shape():
    real = (defender.powershell, defender.platform_ok, defender.read_exclusions,
            defender.script_path)
    folder = os.path.join(ROOT)
    try:
        defender.platform_ok = lambda: True
        defender.powershell = lambda: "powershell.exe"
        defender.script_path = lambda: os.path.join(ROOT, "tools", defender.SCRIPT_NAME)
        defender.read_exclusions = lambda: None
        info = defender.status(FakeConfig())
        assert set(info) >= {"state", "paths", "script", "process", "can_remove", "detail"}
        assert info["state"] == "ready" and info["can_remove"] is False, info
        assert "administrator" in info["detail"].lower(), info
        assert folder in info["paths"], info
        assert "not added" in defender.describe({"state": "ready"}).lower()
        # everything we would add is already there -> "already", and removal becomes possible
        defender.read_exclusions = lambda: list(info["paths"])
        again = defender.status(FakeConfig())
        assert again["state"] == "already", again
        assert again["can_remove"] is True, again
        assert "already" in defender.describe(again).lower()
        # only one of two folders excluded is not "already"
        if len(info["paths"]) > 1:
            defender.read_exclusions = lambda: info["paths"][:1]
            assert defender.status(FakeConfig())["state"] == "ready", "half is not whole"
        # and a remembered "done" survives a restart, while the state stays honest
        defender.read_exclusions = lambda: []
        done = defender.status(FakeConfig({"defender_state": "done"}))
        assert done["state"] == "done", done
    finally:
        (defender.powershell, defender.platform_ok, defender.read_exclusions,
         defender.script_path) = real


# --------------------------------------------------------------------- running it
@check("apply() reports the truth about the elevation prompt")
def _apply_reports():
    real = (defender.platform_ok, defender.powershell, defender.read_exclusions,
            subprocess.run)
    seen = {}

    class Res:
        def __init__(self, code=0):
            self.returncode = code
            self.stdout = ""
            self.stderr = ""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return Res(seen.get("code", 0))

    try:
        defender.platform_ok = lambda: True
        defender.powershell = lambda: "powershell.exe"
        paths_ = [os.path.normpath(ROOT)]
        real_plan = defender.plan
        defender.plan = lambda: list(paths_)
        subprocess.run = fake_run
        cfg = FakeConfig()

        seen["code"] = 0
        defender.read_exclusions = lambda: paths_
        report = defender.apply(config=cfg)
        assert report["ok"] is True, report
        assert report["verified"] is True, report
        assert report["added"] == paths_, report
        assert cfg.data["defender_state"] == "done", cfg.data

        seen["code"] = 1          # UAC declined, or the script refused
        report = defender.apply(config=cfg)
        assert report["ok"] is False and "exit 1" in report["reason"], report

        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 240)

        real_run, subprocess.run = subprocess.run, boom
        try:
            report = defender.apply(config=cfg)
        finally:
            subprocess.run = real_run
        assert report["ok"] is False and "elevation prompt" in report["reason"], report

        # removing: same wrapper, -Remove on the end, and "verified" means the paths are gone
        seen["code"] = 0
        defender.read_exclusions = lambda: []
        report = defender.apply(config=cfg, remove=True)
        assert report["ok"] is True and report["verified"] is True, report
        assert "'-Remove'" in " ".join(seen["cmd"]), seen["cmd"]
        assert cfg.data["defender_state"] == "declined", cfg.data

        # nothing to do at all: a machine where plan() was filtered down to nothing
        defender.plan = lambda: []
        report = defender.apply(config=cfg)
        assert report["ok"] is False and report["reason"] == "nothing to do", report
        # no shell at all -> a reason, never an exception
        defender.plan = lambda: list(paths_)
        defender.powershell = lambda: ""
        report = defender.apply(config=cfg)
        assert report["ok"] is False and "PowerShell" in report["reason"], report
        defender.plan = real_plan
    finally:
        (defender.platform_ok, defender.powershell, defender.read_exclusions,
         subprocess.run) = real


@check("the worker thread hands the answer to the main loop instead of calling back itself")
def _apply_async_threads():
    """The elevated call can wait a minute on UAC; its result must land on the UI thread.

    ``ui.post`` keeps a queue that the running app drains. There is no app here, so the test
    drains it by hand - which is also the assertion: the callback had to *wait* in that queue,
    and calling it straight from the worker thread would have left the queue empty.
    """
    import queue
    import threading
    import time as _t
    from divineclient.ui import post as postmod
    real = (defender.platform_ok, defender.apply)
    box = {}

    def fake_apply(config=None, remove=False):
        box["thread"] = threading.current_thread().name
        box["remove"] = remove
        return {"ok": True, "verified": True, "reason": "", "added": []}

    got = []
    try:
        defender.platform_ok = lambda: True
        defender.apply = fake_apply
        while True:                                   # start from an empty queue
            try:
                postmod._Q.get_nowait()
            except queue.Empty:
                break
        t = defender.apply_async(config=None, on_done=lambda rep: got.append(("cb", rep)),
                                 remove=True)
        deadline = _t.time() + 5
        while _t.time() < deadline and "thread" not in box:
            _t.sleep(0.02)
        assert box.get("thread") == "divine-defender", box
        assert box.get("remove") is True, box
        assert got == [], "the callback must not run on the worker thread"
        item = postmod._Q.get(timeout=5)              # queued for the main loop
        item()
        assert got and got[0][0] == "cb" and got[0][1]["ok"] is True, got
        assert not got or True
        t.join(2)
    finally:
        defender.platform_ok, defender.apply = real


@check("the config keys the flow needs are in DEFAULTS")
def _defaults():
    from divineclient.core import config as configmod
    for key in ("defender_asked", "defender_state", "defender_auto"):
        assert key in configmod.DEFAULTS, "%s is not a declared default" % key
    cfg = configmod.Config()
    assert cfg.get("defender_asked") is False and cfg.get("defender_auto") is False


def main():
    ok = sum(1 for k, _ in RESULTS if k == "ok")
    bad = sum(1 for k, _ in RESULTS if k == "fail")
    print("\ndefender: %d ok, %d failed" % (ok, bad))
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
