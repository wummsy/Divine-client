"""Auto-update: ask the site which client version is current, and get it if we are not.

How it is wired
---------------
The site keeps the number in ``server/.env`` as ``clientversion=1.0`` and publishes it at
``GET /api/client/version`` together with the download URL and a SHA-256. The client
compares that with its own bundled ``divineclient.CLIENT_VERSION``; **any mismatch on a
higher patch forces the download** - no "later" button, because a launcher running an old
build against a changed site is how people end up with half the features missing.

What it deliberately is not
---------------------------
*A dropper.* An unsigned exe that downloads another exe, writes it next to itself and
runs it is the exact behaviour list antivirus heuristics punish, and this build has no
code-signing certificate to fall back on. So:

  * the file lands in ``<data>/updates/`` - never ``%TEMP%``, never beside a running
    process' exe, and nothing is executed from there;
  * the bytes are checked against the published SHA-256 before they are trusted at all;
  * swapping files happens in a second copy of *this same program* (``DivineClient.exe
    --apply-update``) after the launcher has exited, so no process ever replaces a file it
    is running from, and no batch file or helper binary is created anywhere;
  * every failure is a one-line message in the UI. A failed update must never stop the
    game from starting - that would make the updater the thing that breaks the launcher.

Where the download comes from
-----------------------------
The URL in the site's response is used as-is, so the exe can live behind a CDN, in
``server/static/releases/`` on the same box, or on GitHub Releases. If the site is
unreachable, ``check`` returns ``unreachable`` and the launcher stays quiet about it.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

VERSION = "client-version.json"


def local_version():
    try:
        from .. import CLIENT_VERSION
        return str(CLIENT_VERSION)
    except Exception:
        return "0"


def data_dir():
    from .. import paths
    return paths.DATA_DIR


def updates_dir():
    d = os.path.join(data_dir(), "updates")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------- version maths
def as_tuple(text):
    """'1.2.3' -> (1, 2, 3); junk sorts lowest instead of raising.

    A leading "v" is dropped: a version read back from a release tag or a file
    name arrives as ``v1.1`` often enough to be worth tolerating, and treating it
    as junk would hide an update from everyone running that build.
    """
    text = str(text or "").strip()
    if text[:1].lower() == "v":
        text = text[1:]
    out = []
    for part in text.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out or [0])


def _pad(a, b):
    n = max(len(a), len(b))
    return tuple(list(a) + [0] * (n - len(a))), tuple(list(b) + [0] * (n - len(b)))


def is_newer(remote, local=None):
    """True when ``remote`` is ahead of the client's own version.

    A *lower* number means somebody is running a dev build against an older site, and
    silently downgrading them would be worse than saying nothing.
    """
    r, l = _pad(as_tuple(remote), as_tuple(local if local is not None else local_version()))
    return r > l


# ------------------------------------------------------------------------- the check
def fetch_latest(config=None, timeout=15):
    """Ask the site what the current client version is.

    Returns a dict (possibly ``{"error": ...}``) with at least ``version``. Never raises:
    an update check that can throw is an update check that closes the launcher.
    """
    try:
        from . import endpoints
        data = endpoints.get_json(config, "/api/client/version", timeout=timeout)
        if data is None:
            return {"error": "unreachable"}
        if not isinstance(data, dict):
            return {"error": "bad answer from the site"}
        info = {
            "version": str(data.get("version") or ""),
            "url": (data.get("url") or "").strip(),
            "sha256": (data.get("sha256") or "").strip().lower(),
            "size": int(data.get("size") or 0),
            "notes": data.get("notes") or "",
            "file": data.get("file") or "",
        }
        if not info["version"]:
            return {"error": "the site did not say which version is current"}
        return info
    except Exception as e:
        return {"error": str(e)[:120]}


def status(config=None, force=False):
    """One-shot description of what an update would do right now.

    ``{"state": "current"|"available"|"staged"|"unreachable"|"no-download", ...}`` - the
    UI turns these into a pill, and the tests assert on them directly.
    """
    info = fetch_latest(config)
    local = local_version()
    if info.get("error"):
        return {"state": "unreachable", "local": local, "detail": info["error"]}
    remote = info["version"]
    staged = find_staged()
    if staged and staged[0] == remote:
        return {"state": "staged", "local": local, "remote": remote,
                "path": staged[1], "notes": info.get("notes", "")}
    if not is_newer(remote, local):
        return {"state": "current", "local": local, "remote": remote}
    if not info.get("url"):
        return {"state": "no-download", "local": local, "remote": remote,
                "detail": "the site published version %s without a download URL" % remote}
    return {"state": "available", "local": local, "remote": remote, "info": info,
            "notes": info.get("notes", "")}


# ------------------------------------------------------------------------ downloading
class _ReleaseError(RuntimeError):
    """A failure whose message is already the whole story, for the pill to show."""


def _open_release(url, info):
    """Open the release URL for streaming: ``(chunks, total_bytes, close)``.

    Goes through ``core.net``'s pooled requests session, like every other download in
    the launcher. This used to be raw ``urllib``, and that difference is what made
    "the update download failed" so useless: a frozen build could fetch a 20 MB jar from
    Modrinth all day and still fail on its own update, because requests brings certifi's
    CA bundle, retries, proxy support from the environment and - mostly - an exception
    that names the HTTP status instead of a bare URLError.

    urllib is kept as a fallback so a source checkout without requests installed can
    still run the updater. Errors are converted into ``_ReleaseError`` with the reason up
    front: the sidebar pill has room for about 50 characters, so a sentence that starts
    "the update download failed: " hides which one of four problems it is.
    """
    from urllib.parse import urlparse
    parts = urlparse(url)
    where = (parts.netloc or "?") + (parts.path or "/")
    headers = {"User-Agent": "DivineClient/%s" % local_version()}
    try:
        from . import net as _net
    except Exception:
        _net = None

    if _net is not None:
        try:
            import requests
            resp = _net.session().get(url, stream=True, headers=headers, allow_redirects=True,
                                      timeout=getattr(_net, "FILE_TIMEOUT", (10.0, 180.0)))
        except ImportError:
            return _open_release_urllib(url, info, headers, where)
        except Exception as e:
            raise _ReleaseError("could not reach %s (%s)" % (where, _why(e)))
        if resp.status_code != 200:
            resp.close()
            raise _ReleaseError("%s answered %s for %s" % (
                where, resp.status_code, _meaning(resp.status_code)))
        total = int(resp.headers.get("Content-Length") or 0) or int(info.get("size") or 0)
        served = resp.headers.get("Content-Type") or ""
        if served and served.split(";")[0].strip().lower() in ("text/html", "text/plain"):
            resp.close()
            raise _ReleaseError("%s sent %s, not an archive - is the file really at that "
                                "path?" % (where, served.split(";")[0].strip()))
        return resp.iter_content(chunk_size=1 << 16), total, resp.close

    return _open_release_urllib(url, info, headers, where)


def _open_release_urllib(url, info, headers, where):
    import urllib.request
    from urllib.error import HTTPError, URLError
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                     timeout=60)
    except HTTPError as e:
        raise _ReleaseError("%s answered %s for %s" % (where, e.code, _meaning(e.code)))
    except URLError as e:
        raise _ReleaseError("could not reach %s (%s)" % (where, _why(e.reason)))
    except Exception as e:
        raise _ReleaseError("%s while opening %s (%s)" % (type(e).__name__, where, _why(e)))
    total = int(raw.headers.get("Content-Length") or 0) or int(info.get("size") or 0)
    return iter(lambda: raw.read(1 << 16) or None, None), total, raw.close


def _why(e):
    """The innermost useful words of an exception, without its traceback padding."""
    text = str(e or "").strip()
    reason = getattr(e, "reason", None)
    if reason and str(reason).strip():
        text = str(reason).strip()
    inner = getattr(e, "args", ())
    if isinstance(inner, tuple) and len(inner) == 2 and isinstance(inner[1], str):
        text = text or inner[1]
    return (text or e.__class__.__name__)[:90]


def _meaning(code):
    return {401: "401 (the URL needs a login - a release archive must be public)",
            403: "403 (blocked or directory listing denied)",
            404: "404 (no such file - check the name in clienturl)",
            500: "500", 502: "502", 503: "503", 504: "504"}.get(code, code)


def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def download(info, progress=None, timeout=1800):
    """Fetch the published build into the updates folder and verify it.

    Returns ``(path, kind)`` where kind is "zip" or "exe". Progress is
    ``progress(fraction, text)`` with fraction in 0..1 (or None when the size is unknown,
    which the UI draws as a moving bar).
    """
    url = info["url"]
    name = info.get("file") or os.path.basename(url.split("?")[0]) or "DivineClient-update"
    dest = os.path.join(updates_dir(), name)
    part = dest + ".part"
    if os.path.isfile(dest):
        try:
            os.remove(dest)
        except OSError:
            dest = os.path.join(updates_dir(), "new-" + name)
            part = dest + ".part"

    def say(frac, text):
        if progress:
            try:
                progress(frac, text)
            except Exception:
                pass

    say(0.0, "Downloading " + name)
    done = 0

    def drop():
        try:
            if os.path.isfile(part):
                os.remove(part)
        except OSError:
            pass

    try:
        chunks, total, close = _open_release(url, info)
    except _ReleaseError as e:
        drop()
        raise RuntimeError(str(e))
    except Exception as e:
        drop()
        raise RuntimeError("%s fetching %s (%s)" % (type(e).__name__, name, _why(e)))

    try:
        with open(part, "wb") as out:
            for buf in chunks:
                if not buf:
                    continue
                out.write(buf)
                done += len(buf)
                if total:
                    say(min(1.0, done / float(total)),
                        "%s of %s" % (_human(done), _human(total)))
                else:
                    say(None, "%s downloaded" % _human(done))
            out.flush()
            os.fsync(out.fileno())
    except Exception as e:
        drop()
        raise RuntimeError("the download stopped at %s of %s (%s)"
                           % (_human(done), _human(total) if total else "an unknown size",
                              _why(e)))
    finally:
        try:
            close()
        except Exception:
            pass

    size = os.path.getsize(part)
    if size < 200000:
        head = b""
        try:
            with open(part, "rb") as f:
                head = f.read(64)
        except OSError:
            pass
        drop()
        raise RuntimeError("that download was only %d bytes, so it is not a build%s"
                           % (size, " (it starts %r - a page, not the archive)" % head[:16]
                              if head[:2] not in (b"PK", b"MZ") else ""))
    if name.lower().endswith(".zip"):
        with open(part, "rb") as f:
            if f.read(2) != b"PK":
                drop()
                raise RuntimeError("that file is not a zip archive, so it is not the build "
                                   "the site pointed at")
    expect = (info.get("sha256") or "").lower()
    got = _sha256(part)
    if expect and got != expect:
        os.remove(part)
        raise RuntimeError(
            "the download did not match the checksum the site published (got %s..., "
            "expected %s...), so it was deleted. Check your connection and try again."
            % (got[:12], expect[:12]))
    if not expect:
        say(0.99, "no checksum published for %s - trusting the size only" % name)
    os.replace(part, dest)
    kind = "zip" if dest.lower().endswith(".zip") else "exe"
    if kind == "zip":
        unpacked = os.path.join(updates_dir(), "incoming-" + info["version"])
        _unzip(dest, unpacked)
        record = os.path.join(unpacked, VERSION)
        with open(record, "w", encoding="utf-8") as f:
            json.dump({"version": info["version"], "sha256": got, "at": int(time.time()),
                       "notes": info.get("notes", "")}, f, indent=2)
        say(1.0, "Update %s is ready" % info["version"])
        return unpacked, "dir"
    say(1.0, "Update %s is ready" % info["version"])
    return dest, kind


def _wrapper_folder(names):
    """The shared "this zip wraps everything in one folder" rule, kept in ``core.zipio``.

    Re-exported by name because ``plan_payload_swap`` and the unpack step have to agree on
    what the archive's root is, and the updater's tests reach for this one directly.
    """
    from .zipio import wrapper_folder
    return wrapper_folder(names)


def _unzip(archive, target):
    """Unpack a release into the staging folder. See ``core.zipio`` for the rules.

    Kept as a named function because this is the one place where "the archive the site
    served" becomes "a folder of files to copy over the install", and the modpack
    installer now needs exactly the same care with Windows separators and escaping paths.
    """
    from .zipio import safe_extract
    safe_extract(archive, target)
    return target


def _human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024


def find_staged():
    """``(version, path)`` for an update that is downloaded and waiting, else None."""
    d = updates_dir()
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return None
    for name in names:
        full = os.path.join(d, name)
        if os.path.isdir(full):
            record = os.path.join(full, VERSION)
            if os.path.isfile(record):
                try:
                    with open(record, encoding="utf-8") as f:
                        meta = json.load(f)
                    return str(meta.get("version") or name.split("-", 1)[-1]), full
                except Exception:
                    return name.split("-", 1)[-1], full
        elif name.startswith("DivineClient") and name.endswith((".exe", ".zip")):
            return "", full
    return None


def clear_staged(path=None):
    d = updates_dir()
    targets = [path] if path else [os.path.join(d, n) for n in os.listdir(d)]
    for t in targets:
        if not t or not str(t).startswith(d):
            continue                 # never delete anything outside our own folder
        try:
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
            elif os.path.isfile(t):
                os.remove(t)
        except OSError:
            pass


def apply_update_from_zip(zip_path, target_dir=None):
    """Unpack an update zip archive and overwrite client files in target_dir."""
    if target_dir is None:
        target_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import tempfile
    scratch = tempfile.mkdtemp(prefix="divine-apply-")
    try:
        from .zipio import safe_extract
        safe_extract(zip_path, scratch, strip_wrapper=True)

        # If the extracted folder has an inner 'divine-client' folder
        src_root = scratch
        if os.path.isdir(os.path.join(scratch, "divine-client")):
            src_root = os.path.join(scratch, "divine-client")

        moved = 0
        failed = []
        for root, dirs, files in os.walk(src_root):
            rel_root = os.path.relpath(root, src_root)
            # Never overwrite databases, data directory, or log files
            parts = rel_root.split(os.sep)
            if "data" in parts or "logs" in parts or ".divineclient" in parts:
                continue
            for f in files:
                if f.endswith((".db", ".sqlite", ".db-wal", ".db-shm", ".log", ".tmp")):
                    continue
                src_file = os.path.join(root, f)
                rel_path = os.path.relpath(src_file, src_root)
                dst_file = os.path.join(target_dir, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                if _replace(src_file, dst_file):
                    moved += 1
                else:
                    try:
                        shutil.copy2(src_file, dst_file)
                        moved += 1
                    except Exception as ex:
                        failed.append(f"{rel_path}: {ex}")
        return moved, failed
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ----------------------------------------------------------------------------- apply
def apply_supported():
    """Can this install replace itself? Only a frozen Windows build can, safely."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def install_dir():
    """The folder the app lives in (onedir) or the exe itself (onefile)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def relaunch_args():
    return [os.path.abspath(sys.executable)]


def apply_later(progress=None):
    """Hand the swap to a detached copy of this program, then let the launcher quit.

    ``--apply-update`` is a mode of the same exe: it waits for this process to disappear,
    moves the staged files in, and starts the new build. That is why there is no .bat, no
    PowerShell and no second binary - every one of those is a heuristic hit, and this one
    is invisible to them because nothing new is ever created or run.
    """
    staged = find_staged()
    if not staged or not apply_supported():
        return False
    payload = staged[1]
    # the pid matters: the child must not start copying over an exe this process
    # is still holding, and on Windows a locked file is an error, not a queue
    cmd = relaunch_args() + ["--apply-update", payload,
                             "--wait-pid", str(os.getpid())]
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, cwd=os.path.dirname(payload) or None, close_fds=True,
                     creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return True


def run_apply_update(payload, wait_pid=None, log=None):
    """The ``--apply-update`` mode: swap the staged build in and start it.

    Called before any GUI code, from main.py. It may only ever copy files from the updates
    folder into the install folder, and every file it overwrites is first moved aside as
    ``<name>.previous``, so a bad update is recoverable by hand and the swap is one
    rename per file rather than a delete-and-copy that can leave half an install.
    """
    def say(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    target = install_dir()
    # 0. only ever take files from our own updates folder. The argument comes from the
    #    command line, so without this a stray invocation could name any directory and
    #    have its contents copied into the install - and a program that overwrites
    #    arbitrary files is precisely the behaviour antivirus looks for.
    payload = os.path.abspath(str(payload or ""))
    allowed = os.path.normpath(updates_dir()) + os.sep
    if not payload.startswith(allowed) or not os.path.exists(payload):
        say("refused: %s is not a staged update" % payload)
        raise ValueError("an update must be staged inside %s" % updates_dir())
    # 1. wait for the launcher to let go of its own files
    deadline = time.time() + 25
    while time.time() < deadline:
        if wait_pid and _pid_alive(int(wait_pid)):
            time.sleep(0.4)
            continue
        break
    # 2. copy everything the staged build has, file by file, tolerating locks
    moved, failed = 0, []
    onefile = bool(getattr(sys, "_MEIPASS", ""))
    items = plan_payload_swap(payload, target, onefile=onefile)
    if onefile and items:
        say("one-file build: only the program itself is replaced")
    for src, dst in items:
        if _replace(src, dst):
            moved += 1
        else:
            failed.append(os.path.basename(dst))
    say("moved %d files, %d failed" % (moved, len(failed)))
    clear_staged(payload if os.path.isdir(payload) else None)
    # 3. start the new one
    try:
        exe = os.path.join(target, os.path.basename(sys.executable))
        subprocess.Popen([exe if os.path.isfile(exe) else sys.executable], close_fds=True)
    except Exception as e:
        say("relaunch failed: %s" % e)
    return moved, failed


def plan_payload_swap(payload, target, onefile=False):
    """The ``(src, dst)`` pairs an update consists of.

    A one-dir install is a folder, so the staged folder is copied over it file by file. A
    *one-file* build keeps its support files in a temp folder that is rebuilt on every
    start, so dropping ``_internal``-style files next to the exe would leave junk that
    nothing reads - there, only the program itself is replaced.
    """
    items = []
    exe_name = os.path.basename(sys.executable)
    if os.path.isdir(payload):
        for root, _dirs, files in os.walk(payload):
            for name in sorted(files):
                if name == VERSION:
                    continue
                if onefile and name.lower() != exe_name.lower():
                    continue
                where = os.path.relpath(root, payload)
                where = "" if where == "." else where
                items.append((os.path.join(root, name),
                              os.path.normpath(os.path.join(target, where, name))))
    else:
        items.append((payload, os.path.join(target, exe_name)))
    return items


def _pid_alive(pid):
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32          # type: ignore[attr-defined]
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    except Exception:
        return False


def _replace(src, dst, tries=8):
    """Copy src over dst, renaming the old one aside rather than deleting it.

    Windows will not let a file be replaced while something still has it open - so we move
    the *old* file first (which succeeds once the launcher is gone) and copy the new one
    in. If the move is refused, retry: at update time the previous process is exiting.
    """
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    for i in range(tries):
        try:
            if os.path.isfile(dst):
                backup = dst + ".previous"
                if os.path.isfile(backup):
                    os.remove(backup)
                os.replace(dst, backup)
            shutil.copy2(src, dst)
            try:
                os.chmod(dst, 0o755)
            except OSError:
                pass
            return True
        except OSError:
            time.sleep(0.5 + 0.25 * i)
    return False
