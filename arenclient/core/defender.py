"""Windows Defender: offer the one exclusion that actually stops a "virus" report.

Why this asks instead of just doing it
-------------------------------------
A program that quietly elevates itself to change antivirus settings is doing the exact thing
malware does, and Defender's behaviour heuristics know it - a silent attempt would make the
verdict on an unsigned ``DivineClient.exe`` worse, not better. A UAC prompt is unavoidable here
anyway, so the only real choice is whether the user sees *why* first. Hence: one dialog on the
first open, "no" is remembered, and the same action is a button in Settings forever after.

What it can and cannot do
-------------------------
* The only settings it ever touches are ``ExclusionPath`` and ``ExclusionProcess``, for the
  folder the exe lives in and ``%APPDATA%\\.divineclient`` - never a drive root, never the profile,
  never a wildcard. It never disables real-time protection and never writes a Run key.
* The elevated work is a **file**: ``defender_exclusions.ps1``, shipped next to the exe, which
  a person can open and read before running it. This module builds no PowerShell out of
  strings except the fixed ``Start-Process -Verb RunAs`` wrapper around that file.
* It cannot bring back a file Defender already quarantined (that is "Allow on device" in
  Protection history), and it does nothing where Defender is not the registered antivirus.
"""
import os
import subprocess
import sys

SCRIPT_NAME = "defender_exclusions.ps1"
EXE_NAME = "DivineClient.exe"

#: what the state label means, so the UI never invents its own wording
STATES = ("unsupported", "no-script", "ready", "already", "done", "asked", "declined")

#: one short line per state, shared by the first-open dialog and the Settings card
LABELS = {
    "unsupported": "Windows Defender does not run here",
    "no-script": "The exclusion helper is missing from the install",
    "ready": "Not added yet",
    "already": "Already added",
    "done": "Added - Defender will leave these folders alone",
    "asked": "You chose not to add it",
    "declined": "You chose not to add it",
}


def describe(info: dict) -> str:
    """The sentence a screen shows for a ``status()`` result."""
    return LABELS.get(str((info or {}).get("state") or ""), LABELS["ready"])


def app_dir() -> str:
    """The folder that holds DivineClient.exe - the one an exclusion has to cover.

    In a PyInstaller onedir build the program runs from ``DivineClient\\`` with ``_internal``
    inside it, so the *parent* of the exe directory is what matters when the exe itself is the
    entry point. In a source checkout it is the repo, which is right for testing the flow.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return here


def data_dir() -> str:
    try:
        from .. import paths
        return paths.DATA_DIR
    except Exception:
        return ""


def script_path() -> str:
    """Where the helper script is: next to the exe (it ships there), else in tools/."""
    here = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(here, SCRIPT_NAME),
                 os.path.join(here, "tools", SCRIPT_NAME),
                 os.path.join(os.path.dirname(here), "tools", SCRIPT_NAME),
                 os.path.join(app_dir(), SCRIPT_NAME)):
        try:
            if cand and os.path.isfile(cand):
                return cand
        except OSError:
            continue
    return ""


def powershell() -> str:
    """The shell to run. Windows PowerShell ships with every Windows 10/11 box."""
    for name in ("powershell.exe", "powershell", "pwsh"):
        found = _which(name)
        if found:
            return found
    return ""


def _which(name):
    import shutil
    try:
        return shutil.which(name)
    except Exception:
        return ""


def platform_ok() -> bool:
    return sys.platform == "win32"


# ---- what would be excluded --------------------------------------------------
def _parts(path: str) -> list:
    """Path pieces with either separator, no empties: ``C:\\Games\\Divine`` -> ['C:', 'Games', 'Divine']"""
    return [piece for piece in path.replace("\\", "/").split("/") if piece]


def too_broad(path: str) -> bool:
    """Refuse the folders that would un-scan half the machine.

    An exclusion is a permanent hole, so the *shape* of the path is what matters, not who asked:
    a drive or share root, anything with no name of its own below the root (``C:\\Games``), the
    user profile or any folder above it, all get refused. What is left is a real folder like
    ``C:\\Games\\DivineClient`` or the Divine data folder, which is what we want excluded anyway.
    """
    text = (path or "").replace("\\", "/").rstrip("/")
    parts = _parts(text)
    if not parts:
        return True                                   # "/" or "\"
    if text.startswith("//") and len(parts) < 3:
        return True                                   # "\\box\\share" is a whole share
    drive = len(parts[0]) == 2 and parts[0][1] == ":"
    if len(parts) - (1 if drive else 0) < 2:
        return True                                   # C:\, C:\Games, /home
    profile = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    if profile and (text.lower() == profile.lower() or profile.lower().startswith(text.lower() + "/")):
        return True                                   # the profile itself, or above it
    return False


def plan() -> list:
    """The folders to exclude, filtered to the ones that are ours and real.

    Anything that fails the check is dropped rather than passed along: this list is handed to
    an elevated command, so "weird path" has to mean "not excluded", never "the whole drive is
    now unscanned and nobody noticed".
    """
    out = []
    for path in (app_dir(), data_dir()):
        if not path:
            continue
        try:
            if not os.path.isdir(path):
                continue
            norm = os.path.normpath(os.path.abspath(path))
            if too_broad(norm):
                continue
        except (OSError, ValueError):
            continue
        if norm not in out:
            out.append(norm)
    return out


# ---- state ------------------------------------------------------------------
def _cfg(config):
    class _Empty(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

        def set(self, key, value):
            self[key] = value

        def save(self):
            pass
    return config if config is not None else _Empty()


def set_auto(config, on: bool) -> None:
    """Whether later launches may re-add it without a dialog (only if it is actually missing)."""
    cfg = _cfg(config)
    cfg.set("defender_auto", bool(on))
    try:
        cfg.save()
    except Exception:
        pass


def asked(config) -> bool:
    return bool(_cfg(config).get("defender_asked"))


def auto_run(config) -> bool:
    """The user may say "just do it" once; then re-adding after a Defender update is silent."""
    return bool(_cfg(config).get("defender_auto"))


def mark(config, state) -> None:
    cfg = _cfg(config)
    cfg.set("defender_asked", True)
    cfg.set("defender_state", state)
    try:
        cfg.save()
    except Exception:
        pass


def first_run_pending(config) -> bool:
    """True exactly once: a Windows box that has the script and has never been asked."""
    return bool(platform_ok() and script_path() and not asked(config))


def auto_pending(config) -> bool:
    """True when the person said "just do it" and the exclusion is genuinely missing.

    Checked without elevation on purpose: reading the list is free, so on an ordinary launch
    this costs one PowerShell call and no UAC prompt. The prompt only returns after a Defender
    reset or a reinstall, which is exactly when re-adding it is wanted.
    """
    if not (platform_ok() and script_path() and auto_run(config)):
        return False
    current = read_exclusions()
    if current is None:
        return False            # cannot tell, so do not surprise anyone with a prompt
    want = plan()
    return bool(want) and not all(p.lower() in [c.lower() for c in current] for p in want)


def status(config=None) -> dict:
    """Everything a screen needs, with no elevated process and no exception, ever."""
    out = {"state": "unsupported", "paths": [], "script": "", "process": EXE_NAME,
           "can_remove": False, "detail": ""}
    try:
        out["paths"] = plan()
        out["script"] = script_path()
        if not platform_ok():
            out["detail"] = "Defender is a Windows thing"
            return out
        if not out["script"]:
            out["state"] = "no-script"
            out["detail"] = "%s is not next to DivineClient.exe" % SCRIPT_NAME
            return out
        if not powershell():
            out["state"] = "no-script"
            out["detail"] = "PowerShell was not found"
            return out
        current = read_exclusions()
        if current is None:
            out["state"] = "ready"
            out["detail"] = "Windows will ask for administrator rights"
        elif out["paths"] and all(p.lower() in [c.lower() for c in current]
                                  for p in out["paths"]):
            out["state"] = "already"
            out["detail"] = "both folders are already on the list"
            out["can_remove"] = True
        else:
            out["state"] = "ready"
            out["detail"] = "adds an exclusion for the Divine folders only"
        if str(_cfg(config).get("defender_state") or "") == "done":
            out["state"] = "done" if out["state"] != "already" else "already"
        return out
    except Exception as exc:
        out["detail"] = "%s: %s" % (type(exc).__name__, exc)
        return out


def read_exclusions():
    """The paths Defender currently excludes, or None if we cannot ask it.

    Reading usually works without elevation; on a machine where it does not, callers treat
    None as "unknown" and say so instead of guessing.
    """
    ps = powershell()
    if not ps or not platform_ok():
        return None
    cmd = ("$p = Get-MpPreference; "
           "@($p.ExclusionPath) -join '|'; '##PROC##'; "
           "@($p.ExclusionProcess) -join '|'")
    try:
        res = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", cmd], capture_output=True, timeout=20,
                             text=True, creationflags=_no_window())
        if res.returncode != 0 or "##PROC##" not in (res.stdout or ""):
            return None
        head = (res.stdout or "").split("##PROC##")[0].strip()
        return [p.strip() for p in head.split("|") if p.strip()]
    except Exception:
        return None


def _no_window():
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


# ---- do it ------------------------------------------------------------------
def build_command(script: str, appfolder: str, extra=()) -> list:
    """The wrapper that asks for elevation and hands off to the script.

    Kept in one function so a test can read exactly what would run: a fixed verb, the
    script's own path, and no PowerShell logic written here at all - the elevated work is a
    file the user can open and read before they run it.
    """
    ps = powershell() or "powershell.exe"
    args = ["'-NoProfile'", "'-ExecutionPolicy'", "'Bypass'", "'-File'", "'%s'" % script,
            "'-AppPath'", "'%s'" % appfolder]
    for flag in extra:
        args.append("'%s'" % flag)
    return [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "Start-Process -FilePath '%s' -Verb RunAs -Wait -ArgumentList %s"
            % (ps, ",".join(args))]


def apply(config=None, remove=False) -> dict:
    """Run the helper elevated. Returns a report; never raises, never runs on other OSes."""
    report = {"ok": False, "reason": "", "added": [], "script": "", "verified": None}
    try:
        if not platform_ok():
            report["reason"] = "not Windows"
            return report
        paths = plan()
        script = script_path()
        report["script"] = script
        if not paths or not script:
            report["reason"] = "nothing to do" if not paths else "helper script not found"
            return report
        if not powershell():
            report["reason"] = "PowerShell was not found"
            return report
        report["added"] = list(paths)
        cmd = build_command(script, paths[0], extra=("-Remove",) if remove else ())
        res = subprocess.run(cmd, capture_output=True, timeout=240, text=True,
                             creationflags=_no_window())
        if res.returncode != 0:
            report["reason"] = ("the elevation prompt was declined or the helper failed "
                                "(exit %s)" % res.returncode)
            return report
        report["ok"] = True
        after = read_exclusions()
        if after is None:
            report["verified"] = None          # could not ask Defender either way
        elif remove:
            report["verified"] = not any(p.lower() in [a.lower() for a in after] for p in paths)
        else:
            report["verified"] = all(p.lower() in [a.lower() for a in after] for p in paths)
        if config is not None:
            mark(config, "declined" if remove else "done")
        return report
    except subprocess.TimeoutExpired:
        report["reason"] = "timed out waiting for the elevation prompt"
        return report
    except FileNotFoundError:
        report["reason"] = "PowerShell was not found"
        return report
    except Exception as exc:
        report["reason"] = "%s: %s" % (type(exc).__name__, exc)
        return report


def apply_async(config=None, on_done=None, remove=False):
    """``apply`` on a worker thread, with the answer posted back to the UI thread.

    The elevated helper can sit on a UAC prompt for a minute while the person reads it, so it
    cannot run on the thread that paints - and the dialog that starts it must already be gone.
    """
    import threading

    def work():
        result = apply(config=config, remove=remove)
        if on_done:
            try:
                from ..ui.post import post
                post(on_done, result)
            except Exception:
                try:
                    on_done(result)
                except Exception:
                    pass

    t = threading.Thread(target=work, name="divine-defender", daemon=True)
    t.start()
    return t
