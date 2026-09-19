"""Host a Minecraft server from an instance - the player's own mods and world.

This turns an Divine instance into a runnable dedicated server:

  * downloads the matching server jar (vanilla from Mojang, or the Fabric server
    launcher from fabricmc.net so the instance's Fabric mods load);
  * copies the instance's server-compatible mods into the server folder;
  * writes / reads server.properties so the UI can expose the common settings;
  * runs the server java process and exposes its console (stdout + stdin) so the
    launcher can show live output and let the host type commands.

Networking to friends is handled separately by ``tunnel.py`` (playit.gg), which
turns the local port into a public address other people can join.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import zlib

from .. import paths
from . import java_runtime


FABRIC_META = "https://meta.fabricmc.net/v2"
# The file Fabric's own download *installs into*: it is what Java is pointed at once
# the install has run, and it is written by the bootstrap jar, never by us.
FABRIC_LAUNCH_NAME = "fabric-server-launch.jar"
# ...and the file we download. The two are deliberately different names: the bootstrap
# ends by writing FABRIC_LAUNCH_NAME, and on Windows a JVM cannot replace the jar it
# is running from - sharing violation, server dies, "fabric doesn't work".
FABRIC_BOOT_NAME = "fabric-installer.jar"
FABRIC_INSTALLER_MAIN = "net.fabricmc.installer.ServerLauncher"
VERSION_MANIFEST = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
BASE_PORT = 25565


def _is_windows():
    return os.name == "nt"


def servers_root():
    d = os.path.join(paths.get_game_dir(), "servers")
    os.makedirs(d, exist_ok=True)
    return d


def server_dir(instance):
    """Where an instance's server files live (separate from the client game dir)."""
    if hasattr(instance, "server_dir") and isinstance(getattr(instance, "server_dir"), str):
        d = instance.server_dir
    else:
        d = os.path.join(servers_root(), instance.id)
    os.makedirs(d, exist_ok=True)
    return d


# --- downloading the server jar ---------------------------------------------
def _download(url, dest, status=None):
    if status:
        status("Downloading " + os.path.basename(dest))
    tmp = dest + ".part"
    last = None
    # A truncated download is what turns into Java's "Unable to access jarfile"
    # or a "Invalid or corrupt jarfile" exit, so give it a few clean attempts
    # before we bother the user with an error.
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DivineClient"})
            with urllib.request.urlopen(req, timeout=60) as r:
                expected = r.headers.get("Content-Length")
                with open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            if expected and os.path.getsize(tmp) != int(expected):
                raise OSError("incomplete download (%d of %s bytes)"
                              % (os.path.getsize(tmp), expected))
            last = None
            break
        except Exception as e:
            last = e
            try:
                os.remove(tmp)
            except Exception:
                pass
            if attempt < 2:
                if status:
                    status("Download hiccup, retrying (%d of 3)..." % (attempt + 2))
                time.sleep(1.2 * (attempt + 1))
    if last is not None:
        raise RuntimeError(
            "Couldn't download the server file. Check your internet connection "
            "and try again.\n\n" + str(last))
    # a valid jar is a zip; if the download was truncated or replaced by an
    # antivirus stub this will catch it before we hand a broken file to Java
    if dest.lower().endswith(".jar") and not _is_valid_jar(tmp):
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise RuntimeError(
            "The downloaded server file was corrupt or blocked. This is almost "
            "always antivirus deleting it. Add an exclusion for the Divine Client "
            "folder and try again.")
    # os.replace can fail on Windows if AV is still scanning the file; retry
    last = None
    for _ in range(6):
        try:
            os.replace(tmp, dest)
            last = None
            break
        except OSError as e:
            last = e
            time.sleep(0.4)
    if last is not None:
        raise RuntimeError(
            "Divine downloaded the server file but Windows wouldn't let us put it "
            "in place - something else is holding the folder open (usually "
            "antivirus, or the server still running). Close it and try again.\n\n"
            + str(last))
    return dest


def _can_read(path):
    """True only if *another* process could open this file right now.

    os.path.isfile() is not enough on Windows: right after a download, antivirus
    often still holds the freshly-written file open for scanning. The file is
    "there", so our checks pass, and then Java itself fails to open it and shows
    its opaque "Unable to access jarfile" dialog. Opening it for real (and
    reading the header) is the closest thing we have to Java's point of view.
    """
    try:
        with open(path, "rb") as f:
            f.read(64)
        return True
    except Exception:
        return False


def _jar_main_class(path):
    """The Main-Class from a jar's manifest, or None when there isn't a usable one.

    Java refuses to run a jar without it, and it is the only reliable way to tell the
    two Fabric files apart - the bootstrap we download and the tiny launch jar it
    generates look identical from a distance.
    """
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return None
            raw = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except Exception:
        return None
    # manifests wrap at 72 bytes: a continuation line is a space, so unfold first
    for line in raw.replace("\r\n", "\n").replace("\n ", "").split("\n"):
        if line.lower().startswith("main-class:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _is_valid_jar(path):
    """True when Java could be pointed at this file: a readable jar with a manifest.

    This used to be "a zip bigger than a kilobyte", and that size test is what broke
    every Fabric server after its first run: the launch jar Fabric's installer
    generates for itself is 616 bytes of manifest and library paths, so a perfectly
    good install was declared damaged and re-downloaded (and then rewritten under a
    running JVM - see FABRIC_BOOT_NAME). A zip with no manifest, a truncated download
    and an antivirus stub are all rejected by the real check instead.
    """
    try:
        import zipfile
        if not os.path.isfile(path):
            return False
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return False
            return b":" in z.read("META-INF/MANIFEST.MF")
    except Exception:
        return False


def _manifest_attr(path, attr):
    """One attribute from a jar's manifest, with the 72-byte line wrapping undone."""
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            raw = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except Exception:
        return ""
    want = attr.lower() + ":"
    for line in raw.replace("\r\n", "\n").replace("\n ", "").split("\n"):
        if line.lower().startswith(want):
            return line.split(":", 1)[1].strip()
    return ""


def _fabric_installed(sdir):
    """True when this folder holds a *finished* Fabric server install.

    The generated launch jar is a manifest and nothing else: a Main-Class naming
    FabricServerLauncher and a Class-Path of files relative to itself. Both halves of
    that promise have to be true before Java is pointed at it. A first start that was
    interrupted leaves exactly that - the jar written, the files it names still missing -
    and then Java exits 1 without printing anything, which looks like a broken Java
    install and is really a half-installed server. So every file the manifest asks for
    is checked, plus the Minecraft server jar the loader unpacks into versions/.
    """
    path = os.path.join(sdir, FABRIC_LAUNCH_NAME)
    main = _jar_main_class(path)
    if main is None or main == FABRIC_INSTALLER_MAIN:
        return False
    classpath = _manifest_attr(path, "Class-Path")
    if not classpath:
        return False
    for rel in classpath.split():
        if not os.path.isfile(os.path.join(sdir, *rel.replace("\\", "/").split("/"))):
            return False
    vdir = os.path.join(sdir, "versions")
    if not os.path.isdir(vdir):
        return False
    for root, _dirs, files in os.walk(vdir):
        for name in files:
            # the game jar is tens of megabytes; anything smaller is not it
            if name.endswith(".jar"):
                try:
                    if os.path.getsize(os.path.join(root, name)) > 1 << 20:
                        return True
                except OSError:
                    pass
    return False


def wait_jar_readable(jar_path, status=None, attempts=12):
    """Make sure the jar is readable before handing it to Java.

    Retries while antivirus finishes with the file, then raises a message that
    says what to do instead of letting Java pop up its own dialog.
    """
    for i in range(attempts):
        if _can_read(jar_path) and _is_valid_jar(jar_path):
            return jar_path
        if i == 0 and status:
            status("Waiting for antivirus to release the server file...")
        time.sleep(0.5)
    if os.path.isfile(jar_path) and not _can_read(jar_path):
        raise RuntimeError(
            "The server file exists but is locked by another program, so Java "
            "cannot open it:\n" + jar_path + "\n\n"
            "Close any running copy of the server, and add the Divine Client folder "
            "to your antivirus exclusions. Then start it again.")
    raise RuntimeError(
        "The server file is missing or damaged:\n" + jar_path + "\n\n"
        "Divine will re-download it next time you press Start. If this keeps "
        "happening, add the Divine Client folder to your antivirus exclusions.")


# --- "is somebody else in this folder?" ------------------------------------
# A dedicated server locks <level-name>/level.dat and session.lock for as long as
# it runs, and it dies at once with
#   IOException: The process cannot access the file because another process has
#   locked a portion of the file
# if something else still holds them. Two everyday causes: the previous copy of the
# server is still saving (Stop -> Start quickly, or a JVM killed a second ago), and
# antivirus holding a freshly written file open for scanning. Both are transient, so
# the right move is to wait briefly and say what we are waiting for; the third cause
# - a server still running that this launcher lost track of - is not transient, and
# deserves the PID instead of a stack trace.

def _level_lock_files(sdir):
    """The files a running server holds open, in the order worth checking."""
    out = [os.path.join(sdir, "session.lock")]
    name = "world"
    props = os.path.join(sdir, "server.properties")
    try:                                    # the world may not be called "world"
        with open(props, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("level-name="):
                    name = (line.split("=", 1)[1].strip() or "world")
                    break
    except OSError:
        pass
    for leaf in ("level.dat", "level.dat_old"):
        path = os.path.join(sdir, name, leaf)
        if path not in out:
            out.append(path)
    return out


def _lock_is_free(path):
    """Can we take an exclusive lock on this file right now?

    Same mechanism Minecraft uses (an OS byte-range lock), so a file another JVM has
    locked reads as busy here even though plain os.path.isfile() says it is fine.
    """
    if not os.path.isfile(path):
        return True                          # nothing there yet -> nothing holding it
    try:
        with open(path, "r+b") as f:
            if _is_windows():
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.lockf(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1)
                fcntl.lockf(f.fileno(), fcntl.LOCK_UN, 1)
        return True
    except Exception:
        return False


def _java_holders(sdir):
    """PIDs of java/javaw processes whose command line mentions this folder.

    Best effort and quiet: PowerShell's CIM store on Windows (wmic is gone from
    recent builds), /proc on Linux/macOS. An empty list means "could not tell",
    never "nothing is holding it" - so it only ever adds detail to a message that
    is raised anyway.
    """
    mine = os.getpid()
    want = os.path.normcase(os.path.abspath(sdir))
    found = []
    try:
        if _is_windows():
            script = ("Get-CimInstance Win32_Process | "
                      "Select-Object Name,ProcessId,CommandLine | "
                      "ConvertTo-Json -Compress")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=10,
                                 **java_runtime._no_window_kwargs()).stdout
            try:
                data = json.loads(out or "[]")
            except ValueError:
                data = []
            for row in data if isinstance(data, list) else [data]:
                if not isinstance(row, dict):
                    continue
                if (row.get("Name") or "").lower() not in ("java.exe", "javaw.exe"):
                    continue
                cmd = (row.get("CommandLine") or "").replace('"', "")
                if want.lower() in cmd.lower() and row.get("ProcessId"):
                    found.append(int(row["ProcessId"]))
        else:
            for entry in os.listdir("/proc"):
                if not entry.isdigit() or int(entry) == mine:
                    continue
                try:
                    with open("/proc/%s/cmdline" % entry, "rb") as f:
                        cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
                except OSError:
                    continue
                if want.lower() in os.path.normcase(cmd):
                    found.append(int(entry))
    except Exception:
        return []
    return sorted(set(found))


def wait_folder_free(sdir, status=None, attempts=24, hold_pause=0.5):
    """Block until no other process holds the server's world/session locks.

    Returns the file that was busy (or None) so callers can name it in the
    message; raises RuntimeError when the wait does not help.
    """
    busy = None
    for i in range(attempts):
        files = _level_lock_files(sdir)
        busy = next((p for p in files if not _lock_is_free(p)), None)
        if busy is None:
            if i and status:
                status("The folder is free again - starting.")
            return None
        if i == 0 and status:
            status("Waiting for the previous server to let go of its world...")
        time.sleep(hold_pause)
    extra = ""
    pids = _java_holders(sdir)
    if pids:
        extra = ("\n\nStill holding it: Java process %s (another server running from "
                 "this folder). Reopen it from Servers -> Running, or press Stop "
                 "there, before starting a new one."
                 % ", ".join(str(p) for p in pids[:4]))
    raise RuntimeError(
        "Something else has this server's world locked, so a second copy cannot "
        "start:\n" + (busy or sdir) + extra +
        "\n\nIf no server is listed as running, antivirus is probably scanning the "
        "file: add the Divine Client folder to its exclusions, wait ~10 seconds and "
        "press Start again.")


def _vanilla_server_url(mc_version):
    man = json.load(urllib.request.urlopen(VERSION_MANIFEST, timeout=30))
    req_ver = str(mc_version).strip()
    if req_ver in ("latest", "latest_release", "26.2", "1.21.11"):
        direct = next((v for v in man["versions"] if v["id"] == req_ver), None)
        entry = direct or next((v for v in man["versions"] if v["id"] == man["latest"]["release"]), None)
    elif req_ver in ("snapshot", "latest_snapshot"):
        entry = next((v for v in man["versions"] if v["id"] == man["latest"]["snapshot"]), None)
    else:
        entry = next((v for v in man["versions"] if v["id"] == req_ver), None)

    if not entry:
        entry = next((v for v in man["versions"] if v["id"] == man["latest"]["release"]), man["versions"][0])

    meta = json.load(urllib.request.urlopen(entry["url"], timeout=30))
    server = meta.get("downloads", {}).get("server")
    if not server:
        raise RuntimeError("No dedicated server is available for " + mc_version)
    return server["url"], meta.get("javaVersion", {}).get("majorVersion", 21)


def _paper_server_url(mc_version):
    """Fetch latest stable build download URL for PaperMC from Paper Fill API v3."""
    ver_clean = str(mc_version).strip()
    versions_to_try = [ver_clean]
    if ver_clean == "latest":
        versions_to_try = ["1.21.4", "1.21.1", "1.20.4"]

    for ver in versions_to_try:
        # Try fill.papermc.io v3 API first (canonical & fast)
        try:
            req = urllib.request.Request(
                f"https://fill.papermc.io/v3/projects/paper/versions/{ver}/builds",
                headers={"User-Agent": "DivineClient/4.0 (support@divineclient.net)"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.load(resp)
                if isinstance(data, list) and data:
                    # Prefer latest stable or newest build in the list
                    build = data[-1]
                    dl_url = build.get("downloads", {}).get("server:default", {}).get("url")
                    if not dl_url:
                        # Fallback search any download key
                        for k, v in build.get("downloads", {}).items():
                            if isinstance(v, dict) and v.get("url"):
                                dl_url = v.get("url")
                                break
                    if dl_url:
                        return dl_url, str(build.get("id", ""))
        except Exception:
            pass

        # Fallback to api.papermc.io v2 format if available
        try:
            url_v2 = f"https://api.papermc.io/v2/projects/paper/versions/{ver}/builds"
            req = urllib.request.Request(url_v2, headers={"User-Agent": "DivineClient/4.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.load(resp)
                builds = data.get("builds", [])
                if builds:
                    latest = builds[-1]
                    build_num = latest.get("build")
                    downloads = latest.get("downloads", {})
                    app_name = downloads.get("application", {}).get("name")
                    if app_name and build_num:
                        return f"https://api.papermc.io/v2/projects/paper/versions/{ver}/builds/{build_num}/downloads/{app_name}", str(build_num)
        except Exception:
            pass

    raise RuntimeError(f"Could not retrieve Paper server download for Minecraft {mc_version}.")


def _purpur_server_url(mc_version):
    """Fetch Purpur server jar download URL."""
    ver = "1.21.4" if str(mc_version).strip() in ("1.21.11", "26.2", "latest") else str(mc_version).strip()
    return f"https://api.purpurmc.org/v2/purpur/{ver}/latest/download", "latest"


# ---- Paper Plugins Management -----------------------------------------------
def _resolve_plugins_dir(instance):
    sdir = server_dir(instance)
    pdir = os.path.join(sdir, "plugins")
    os.makedirs(pdir, exist_ok=True)
    return pdir


def read_plugin_meta(jar_path):
    """Read plugin.yml from Bukkit/Paper/Spigot plugin jar."""
    try:
        import zipfile
        import yaml
    except ImportError:
        yaml = None

    try:
        import zipfile
        with zipfile.ZipFile(jar_path) as zf:
            if "plugin.yml" in zf.namelist():
                raw = zf.read("plugin.yml").decode("utf-8", "replace")
                data = {}
                for line in raw.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k, v = line.split(":", 1)
                        data[k.strip().lower()] = v.strip().strip("'").strip('"')
                return {
                    "name": data.get("name") or os.path.basename(jar_path),
                    "version": data.get("version", ""),
                    "author": data.get("author") or data.get("authors", ""),
                    "description": data.get("description", ""),
                    "main": data.get("main", "")
                }
            elif "paper-plugin.yml" in zf.namelist():
                raw = zf.read("paper-plugin.yml").decode("utf-8", "replace")
                data = {}
                for line in raw.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k, v = line.split(":", 1)
                        data[k.strip().lower()] = v.strip().strip("'").strip('"')
                return {
                    "name": data.get("name") or os.path.basename(jar_path),
                    "version": data.get("version", ""),
                    "author": data.get("author") or data.get("authors", ""),
                    "description": data.get("description", ""),
                    "main": data.get("main", "")
                }
    except Exception:
        pass
    return None


def list_plugins(instance):
    """List all installed plugins for this server."""
    pdir = _resolve_plugins_dir(instance)
    out = []
    if not os.path.isdir(pdir):
        return out
    for fn in sorted(os.listdir(pdir)):
        low = fn.lower()
        if low.endswith(".jar"):
            enabled = True
        elif low.endswith(".jar.disabled"):
            enabled = False
        else:
            continue
        full = os.path.join(pdir, fn)
        meta = read_plugin_meta(full) or {}
        name = meta.get("name") or fn.replace(".jar.disabled", "").replace(".jar", "")
        version = meta.get("version", "")
        desc = meta.get("description", "")
        try:
            size_mb = round(os.path.getsize(full) / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0
        out.append({
            "filename": fn,
            "path": full,
            "enabled": enabled,
            "name": name,
            "version": version,
            "description": desc,
            "size_mb": size_mb,
        })
    out.sort(key=lambda p: (not p["enabled"], p["name"].lower()))
    return out


def set_plugin_enabled(instance, filename, enabled):
    pdir = _resolve_plugins_dir(instance)
    src = os.path.join(pdir, filename)
    if not os.path.isfile(src):
        return None
    if enabled:
        if filename.endswith(".jar.disabled"):
            new_fn = filename[:-len(".disabled")]
        else:
            return filename
    else:
        if filename.endswith(".jar"):
            new_fn = filename + ".disabled"
        else:
            return filename
    dst = os.path.join(pdir, new_fn)
    try:
        os.replace(src, dst)
        return new_fn
    except OSError:
        return None


def delete_plugin(instance, filename):
    pdir = _resolve_plugins_dir(instance)
    p = os.path.join(pdir, filename)
    try:
        if os.path.isfile(p):
            os.remove(p)
            return True
        return False
    except OSError:
        return False

def _fabric_server_url(mc_version):
    ver = str(mc_version).strip()
    loaders = None
    for try_v in (ver, "1.21.4", "1.21.1", "1.20.4"):
        try:
            loaders = json.load(urllib.request.urlopen(
                FABRIC_META + "/versions/loader/" + try_v, timeout=30))
            if loaders:
                ver = try_v
                break
        except Exception:
            pass

    if not loaders:
        raise RuntimeError("Fabric doesn't support " + mc_version)

    loader = next((l for l in loaders if l.get("loader", {}).get("stable")),
                  loaders[0])
    loader_v = loader["loader"]["version"]
    installer = json.load(urllib.request.urlopen(
        FABRIC_META + "/versions/installer", timeout=30))[0]["version"]
    url = (FABRIC_META + "/versions/loader/" + ver + "/" + loader_v +
           "/" + installer + "/server/jar")
    return url, loader_v


def _state_file(sdir):
    return os.path.join(sdir, ".divine-server.json")


def _read_state(sdir):
    try:
        with open(_state_file(sdir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(sdir, state):
    try:
        with open(_state_file(sdir), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _mod_environment(jar_path):
    """What side a Fabric/Quilt mod jar declares it belongs to.

    "client", "server" or "*" (both). A client-only mod copied onto a dedicated
    server is one of the most common reasons a hosted server prints one error and
    quits a second after you start it, so we need to know before we copy it.
    """
    try:
        import zipfile
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            for meta in ("fabric.mod.json", "quilt.mod.json"):
                if meta not in names:
                    continue
                raw = zf.read(meta).decode("utf-8", "replace")
                data = json.loads(raw)
                if meta == "quilt.mod.json":
                    data = data.get("quilt_mod", data)
                env = str(data.get("environment", "*")).strip().lower()
                return env or "*"
    except Exception:
        pass
    return "*"


def sync_mods(instance, sdir, status=None):
    """Copy this instance's server-compatible mods into the server folder.

    Client-only mods (sodium, iris, minimaps, HUDs...) are skipped on purpose: the
    Fabric loader refuses to start with them, which is exactly the "server closes
    straight away" case. Returns the names it skipped.
    """
    skipped = []
    src_game_dir = getattr(instance, "game_dir", None)
    if not src_game_dir:
        return skipped
    src_mods = os.path.join(src_game_dir, "mods")
    dst_mods = os.path.join(sdir, "mods")
    if os.path.abspath(src_mods) == os.path.abspath(dst_mods):
        return skipped
    os.makedirs(dst_mods, exist_ok=True)
    if not os.path.isdir(src_mods):
        return skipped
    for name in os.listdir(src_mods):
        if not name.lower().endswith(".jar"):
            continue
        src = os.path.join(src_mods, name)
        if _mod_environment(src) == "client":
            skipped.append(name)
            # and if an earlier version of Divine copied it across, drop it again
            try:
                os.remove(os.path.join(dst_mods, name))
            except Exception:
                pass
            continue
        dst = os.path.join(dst_mods, name)
        try:
            if (not os.path.exists(dst) or
                    os.path.getmtime(src) > os.path.getmtime(dst)):
                shutil.copy2(src, dst)
        except Exception:
            pass
    if skipped and status:
        status("Skipped " + str(len(skipped)) + " client-only mod" +
               ("s" if len(skipped) > 1 else "") + " so the server can start: " +
               ", ".join(skipped[:4]) + ("..." if len(skipped) > 4 else ""))
    return skipped


def install_server_perf_mods(instance, sdir, config, status=None):
    """Put the server half of the Divine pack into this server's mods folder.

    Separate from the client pack because these mods declare ``environment: server``:
    on a client the loader has no use for them, and on a server the client ones would
    stop it booting. It runs before the jar is launched and after the sync, so the
    server starts with instance mods plus these; the jars stay in the server folder and
    the next start finds them there.

    No config object means nobody asked for this (tooling, tests) - and a mod fetch is
    not something to do on their behalf. Any failure here leaves the server starting
    with what the instance had, which is the whole point of a *performance* pack.
    """
    try:
        if config is None or not bool(config.get("auto_performance_mods", True)):
            return [], []
    except Exception:
        return [], []
    try:
        from . import mods as _mods
        mods_dir = os.path.join(sdir, "mods")
        installed, skipped = _mods.install_server_pack(
            instance.mc_version, mods_dir,
            progress=(lambda text, frac=0.0: status(text)) if status else None)
        if status and installed:
            status("Server performance mods: " +
                   ", ".join(sorted({i.split("@")[0] for i in installed})))
        return installed, skipped
    except Exception as e:
        if status:
            status("Left the server without the performance pack: " + str(e)[:120])
        return [], []


def prepare(instance, config, status=None):
    """Make sure the server jar, mods, EULA and properties exist. Returns jar path."""
    sdir = server_dir(instance)
    is_fabric = instance.loader == "fabric"
    is_paper = instance.loader == "paper"
    if is_fabric:
        jar_name = FABRIC_LAUNCH_NAME
    elif is_paper:
        jar_name = "paper-server.jar"
    else:
        jar_name = "server.jar"
    jar_path = os.path.join(sdir, jar_name)
    boot_path = os.path.join(sdir, FABRIC_BOOT_NAME)

    # required java major (server side); vanilla meta tells us, default 17/21
    java_major = 17
    # (re)download if the jar is missing OR present-but-corrupt. A jar that
    # exists but is truncated/quarantined is exactly what produces Java's
    # "Unable to access jarfile" dialog, so treat it as missing.
    #
    # Also re-download when the instance was moved to a different Minecraft
    # version: a perfectly valid jar for the old version is otherwise reused and
    # the server then dies a second after starting (world/format/loader mismatch).
    # Divine used to download the bootstrap *as* fabric-server-launch.jar. Move one of
    # those out of the way rather than re-fetching it: the bootstrap is the file that
    # installs everything else, so as long as it is here under its own name the install
    # step never has to overwrite a jar a JVM is reading.
    if is_fabric and _jar_main_class(jar_path) == FABRIC_INSTALLER_MAIN:
        try:
            os.replace(jar_path, boot_path)
        except OSError:
            pass

    state = _read_state(sdir)
    stale = bool(state) and (state.get("mc_version") != instance.mc_version or
                              state.get("loader") != instance.loader)
    if stale:
        if status:
            status("Instance moved to " + instance.mc_version + " - refreshing the "
                   "server files...")
        # both Fabric files are for one specific Minecraft version and loader build
        # (it is baked into the URL), so on a move neither may be kept
        for doomed in (jar_path, boot_path):
            try:
                os.remove(doomed)
            except Exception:
                pass
    # Fabric is "downloaded" in the sense that matters once the install is complete;
    # the bootstrap then only has to be there to finish a half-done one.
    need_download = stale or (not (_fabric_installed(sdir) if is_fabric
                                   else _is_valid_jar(jar_path)))
    loader_v = None
    run_path = jar_path
    if need_download:
        if is_fabric:
            url, loader_v = _fabric_server_url(instance.mc_version)
            # java for fabric server: same rule as the game (newer MC -> 17/21)
            try:
                _vanilla_url, java_major = _vanilla_server_url(instance.mc_version)
            except Exception:
                java_major = 17
            if not _is_valid_jar(boot_path):
                _download(url, boot_path, status)
            if _fabric_installed(sdir):
                run_path = jar_path
            else:
                # Fabric's own bootstrap: it fetches the vanilla server and its
                # libraries, writes fabric-server-launch.jar beside itself, and then
                # starts the server - all in this one run, so the first start is slow
                # and every later one is not.
                run_path = boot_path
                if status:
                    status("Installing the Fabric server files as it starts - the "
                           "first run downloads about 60 MB and takes a minute")
        elif is_paper:
            url, loader_v = _paper_server_url(instance.mc_version)
            try:
                _vanilla_url, java_major = _vanilla_server_url(instance.mc_version)
            except Exception:
                java_major = 17
            _download(url, jar_path, status)
        elif instance.loader == "purpur":
            url, loader_v = _purpur_server_url(instance.mc_version)
            try:
                _vanilla_url, java_major = _vanilla_server_url(instance.mc_version)
            except Exception:
                java_major = 17
            _download(url, jar_path, status)
        else:
            url, java_major = _vanilla_server_url(instance.mc_version)
            _download(url, jar_path, status)
    else:
        try:
            _vanilla_url, java_major = _vanilla_server_url(instance.mc_version)
        except Exception:
            java_major = 17

    # copy the instance's mods so the server runs with the same content. Only
    # matters for Fabric; a vanilla server ignores loose jars.
    if is_fabric:
        sync_mods(instance, sdir, status=status)
        install_server_perf_mods(instance, sdir, config, status=status)

    # accept the EULA (the host is the machine owner and is starting it on purpose)
    with open(os.path.join(sdir, "eula.txt"), "w", encoding="utf-8") as f:
        f.write("# Accepted via Divine Client\neula=true\n")

    # make sure a properties file exists with sane defaults
    props_path = os.path.join(sdir, "server.properties")
    if not os.path.exists(props_path):
        write_properties(instance, default_properties(instance))

    # a port that's already taken is the other "window closed instantly, no
    # message" case: two instances both defaulting to 25565, or a server we lost
    # track of still holding it. Move to a free port instead of letting it die.
    try:
        ensure_free_port(instance, status=status)
    except Exception:
        pass

    # final guard: the jar must actually be readable at this exact path right
    # now, or Java will throw its own opaque "Unable to access jarfile" dialog.
    wait_jar_readable(run_path, status=status)

    # ...and nothing else may be inside the world: a second JVM on the same folder
    # dies a moment later with an IOException about a locked file, which looks
    # nothing like "you started it twice" in the console.
    wait_folder_free(sdir, status=status)

    _write_state(sdir, {"mc_version": instance.mc_version, "loader": instance.loader,
                        "jar": os.path.basename(run_path),
                        "fabric_loader": loader_v or state.get("fabric_loader")})

    instance.data["_server_java_major"] = java_major
    instance.data["_server_is_fresh"] = need_download
    return run_path


# --- server.properties ------------------------------------------------------
def pick_default_port(instance):
    """A stable per-instance port, so two instances never both grab 25565.

    Two hosted servers on the same port is a guaranteed instant exit ("Failed to
    bind"), which looks exactly like "the server closes when I start it". Each
    instance therefore keeps its own port forever (derived from its id, not its
    index, so it survives renames and reordering).
    """
    return BASE_PORT + (zlib.crc32(instance.id.encode("utf-8")) % 40)


def lan_ip():
    """The address other machines on your network see for this PC, or None.

    Nothing is sent: connecting a UDP socket to an unroutable address only makes the
    kernel choose the route, and the source address of that route is the LAN IP. A
    friend on the same network can join with ``<this>:<port>`` without any tunnel;
    nobody outside it can, which is the whole reason bore/playit exist.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.25)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return ip or None
    except OSError:
        return None
    finally:
        try:
            s.close()
        except OSError:
            pass


def port_in_use(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        return s.connect_ex((host, int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def ensure_free_port(instance, status=None):
    """If this instance's configured port is taken, move it to a free one."""
    props = read_properties(instance)
    try:
        port = int(props.get("server-port", BASE_PORT))
    except Exception:
        port = BASE_PORT
    if not port_in_use(port):
        return port
    for cand in range(BASE_PORT, BASE_PORT + 300):
        if cand == port:
            continue
        if not port_in_use(cand):
            props["server-port"] = str(cand)
            write_properties(instance, props)
            if status:
                status("Port " + str(port) + " is already in use by another "
                       "program - moved this server to " + str(cand) + ".")
            return cand
    return port


# --- Dedicated Server Templates System --------------------------------------
SERVER_TEMPLATES = {
    "survival": {
        "id": "survival",
        "name": "Survival SMP",
        "category": "Survival",
        "loader": "paper",
        "mc_version": "1.21.4",
        "ram_mb": 4096,
        "icon": "loader_paper",
        "description": "Optimized Paper survival server with high tick-rate performance, anti-xray, and anti-lag configurations.",
        "properties": {
            "gamemode": "survival",
            "difficulty": "normal",
            "hardcore": "false",
            "pvp": "true",
            "spawn-protection": "0",
            "view-distance": "10",
            "simulation-distance": "8",
            "motd": "created by Divine client servers"
        }
    },
    "creative": {
        "id": "creative",
        "name": "Creative World & Plots",
        "category": "Creative",
        "loader": "paper",
        "mc_version": "1.21.4",
        "ram_mb": 4096,
        "icon": "loader_paper",
        "description": "Creative building sandbox with flat generation, builder permissions, no mob spawning, and full flight.",
        "properties": {
            "gamemode": "creative",
            "difficulty": "peaceful",
            "hardcore": "false",
            "pvp": "false",
            "spawn-monsters": "false",
            "spawn-animals": "false",
            "spawn-protection": "0",
            "allow-flight": "true",
            "view-distance": "16",
            "motd": "created by Divine client servers"
        }
    },
    "lobby": {
        "id": "lobby",
        "name": "Lobby & Minigames Hub",
        "category": "Minigames",
        "loader": "paper",
        "mc_version": "1.21.4",
        "ram_mb": 3072,
        "icon": "loader_paper",
        "description": "High-responsiveness lobby spawn with invulnerable players, instant join, and hub optimizations.",
        "properties": {
            "gamemode": "adventure",
            "difficulty": "peaceful",
            "hardcore": "false",
            "pvp": "false",
            "spawn-monsters": "false",
            "spawn-protection": "16",
            "view-distance": "8",
            "motd": "created by Divine client servers"
        }
    },
    "hardcore": {
        "id": "hardcore",
        "name": "Hardcore Survival Realm",
        "category": "Hardcore",
        "loader": "paper",
        "mc_version": "1.21.4",
        "ram_mb": 4096,
        "icon": "loader_paper",
        "description": "Intense single-life survival realm with hardcore difficulty, player spectate upon death, and natural mob scaling.",
        "properties": {
            "gamemode": "survival",
            "difficulty": "hard",
            "hardcore": "true",
            "pvp": "true",
            "spawn-protection": "0",
            "view-distance": "12",
            "motd": "created by Divine client servers"
        }
    },
    "fabric": {
        "id": "fabric",
        "name": "Fabric Modded Server",
        "category": "Modded",
        "loader": "fabric",
        "mc_version": "1.21.4",
        "ram_mb": 6144,
        "icon": "loader_fabric",
        "description": "Dedicated Fabric server with support for server-side mods, datapacks, and custom dimensions.",
        "properties": {
            "gamemode": "survival",
            "difficulty": "normal",
            "hardcore": "false",
            "pvp": "true",
            "motd": "created by Divine client servers"
        }
    },
    "custom": {
        "id": "custom",
        "name": "Custom Blank Server",
        "category": "Custom",
        "loader": "paper",
        "mc_version": "1.21.4",
        "ram_mb": 2048,
        "icon": "loader_paper",
        "description": "Blank slate dedicated server ready for custom plugin installations, worlds, and configs.",
        "properties": {
            "gamemode": "survival",
            "difficulty": "normal",
            "hardcore": "false",
            "pvp": "true",
            "motd": "created by Divine client servers"
        }
    }
}


def get_server_templates():
    """Return all available server templates."""
    return list(SERVER_TEMPLATES.values())


def get_server_template(template_id):
    """Retrieve a specific template by ID or fallback to custom."""
    return SERVER_TEMPLATES.get(str(template_id).lower(), SERVER_TEMPLATES["custom"])


def register_server_template(template_dict):
    """Register or update a server template dynamically."""
    if not isinstance(template_dict, dict) or not template_dict.get("id"):
        return False
    tid = str(template_dict["id"]).lower()
    SERVER_TEMPLATES[tid] = template_dict
    return True


def apply_server_template(instance, template_id="custom", custom_props=None):
    """Apply a server template configuration to an instance."""
    tmpl = get_server_template(template_id)
    props = default_properties(instance)
    tmpl_props = tmpl.get("properties", {})
    props.update(tmpl_props)
    if custom_props and isinstance(custom_props, dict):
        props.update(custom_props)
    props["motd"] = "created by Divine client servers"
    write_properties(instance, props)
    return props


def default_properties(instance):
    return {
        "motd": "created by Divine client servers",
        "server-port": str(pick_default_port(instance)),
        "max-players": "10",
        "gamemode": "survival",
        "difficulty": "normal",
        "pvp": "true",
        "online-mode": "true",
        "white-list": "false",
        "spawn-protection": "0",
        "view-distance": "10",
        "allow-flight": "false",
        "enable-command-block": "false",
        "level-name": "world",
        "level-seed": "",
    }


def read_properties(instance):
    path = os.path.join(server_dir(instance), "server.properties")
    props = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    merged = default_properties(instance)
    merged.update(props)
    return merged


def write_properties(instance, props):
    path = os.path.join(server_dir(instance), "server.properties")
    existing = {}
    # preserve keys we don't expose in the UI
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    existing[k.strip()] = v.strip()
    existing.update({k: str(v) for k, v in props.items()})
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Minecraft server properties - managed by Divine Client\n")
        for k in sorted(existing):
            f.write(k + "=" + existing[k] + "\n")


def server_port(instance):
    try:
        return int(read_properties(instance).get("server-port",
                                                 pick_default_port(instance)))
    except Exception:
        return pick_default_port(instance)


# --- why did it close? ------------------------------------------------------
def instance_java_major(instance):
    return instance.data.get("_server_java_major") or 17


# (needle in the log, what to tell the user). Ordered: first match wins.
_CRASH_SIGNS = [
    (("another process has locked", "overlappingfilelock", "lockviolation",
      "failed to start the minecraft server"),
     "Another program still has this server's world locked (session.lock or "
     "level.dat), so the new copy was refused. That is normally the previous server finishing its save "
     "- wait a few seconds and press Start again (Divine already waits for up to "
     "12 seconds before launching). If a server for this instance is listed under "
     "Servers -> Running, stop that one first; two servers on one folder will "
     "always end like this."),
    (("Unable to access jarfile", "Invalid or corrupt jarfile", "no main manifest"),
     "Java couldn't open the server file. Antivirus usually locked or deleted it - "
     "add the Divine Client folder to your antivirus exclusions, then press Start "
     "again to re-download it."),
    (("FileSystemException", "sharing violation", "being used by another process",
      "couldn't create filesystem"),
     "Something else had the server's own files open while they were being written - "
     "usually antivirus scanning the folder, or a previous copy of the server that "
     "hasn't finished closing. Wait ~10 seconds and press Start again; the files "
     "Divine already installed are kept, so nothing is downloaded twice."),
    (("Failed to bind", "Address already in use", "bind exception"),
     "Another program already uses this port. Divine normally moves you to a free "
     "port automatically - change \"server-port\" in the properties panel if this "
     "keeps happening."),
    (("agree to the eula", "You need to agree"),
     "The server needs the EULA accepted. Divine writes eula=true for you, so this "
     "means the server folder couldn't be written to - check folder permissions."),
    (("Unsupported class file major version", "compiled by a more recent version of the Java Runtime"),
     "This Minecraft version needs a newer Java than the server got. Divine picks it "
     "automatically - use Repair Java in Settings, then start again."),
    (("OutOfMemoryError", "Could not reserve enough space", "insufficient memory", "There is insufficient memory"),
     "Not enough memory for the size you asked for. Lower \"Server memory\" (for "
     "example 2048 or 3072) and close other programs."),
    (("IncompatibleModsException", "Missing required mods", "mod_resolution",
      "requires any client environment", "incompatible environment",
      "Mod '"),
     "A mod in this instance can't run on a server, or two mods disagree. Remove "
     "client-only mods (client rendering, sodium-ish performance mods that are client "
     "side) from the instance's mods folder and try again."),
    (("UnknownHostException", "Connection refused", "Connection timed out", "SSLHandshakeException", "Network is unreachable"),
     "The first start of a Fabric server downloads Minecraft's server files, and "
     "that download failed. Check your internet connection (and VPN/firewall), "
     "then press Start again."),
    (("Failed to load level", "Corrupted region file", "Error loading world"),
     "The world in that server folder is damaged. Start with a new \"level-name\" "
     "in the properties panel, or delete the server's world folder to regenerate."),
    (("Unsupported settings version", "Failed to load datafixerupper",
      "Unknown data version", "is missing"),
     "This server folder was made for a different Minecraft version. Divine refreshes "
     "it automatically - press Start once more."),
]


_INSTALL_CHATTER = ("unpacking ", "downloading library ", "installing fabric loader ",
                    "generating server launch jar", "downloading minecraft server")


def _symptom_lines(lines):
    """The log, minus the lines a *successful* Fabric install always prints.

    The first start of a Fabric server unpacks ~50 library jars into its own folder and
    prints one line per file, full of names like org.ow2.asm or datafixerupper. Those
    names are also words that appear in real error messages, so scanning them turns a
    healthy first start into "this folder was made for another Minecraft version".
    """
    out = []
    for line in lines or []:
        low = line.lower().lstrip()
        if any(low.startswith(need) or need in low for need in _INSTALL_CHATTER):
            continue
        out.append(line)
    return out


def diagnose(log_lines, exit_code=None, seconds=None):
    """Turn a silent, instant exit into a sentence the user can act on."""
    text = "\n".join(_symptom_lines(log_lines)).lower()
    if not text.strip() and exit_code not in (0, None):
        return ("Java exited with code " + str(exit_code) + " without printing "
                "anything. That usually means the Java runtime itself is broken - "
                "use Repair Java in Settings, then start the server again.")
    for needles, message in _CRASH_SIGNS:
        if any(n.lower() in text for n in needles):
            return message
    if exit_code not in (0, None) and seconds is not None and seconds < 25:
        return ("The server stopped on its own after " + str(int(seconds)) +
                " seconds (exit code " + str(exit_code) + "). The lines above are "
                "the reason - the first error line is usually the one that matters.")
    return None


def _clean_stale_server_logs_and_locks(sdir):
    """Release or remove any stale log locks or session locks before launching."""
    try:
        lock_file = os.path.join(sdir, "world", "session.lock")
        if os.path.isfile(lock_file):
            try:
                os.remove(lock_file)
            except OSError:
                pass
        log_file = os.path.join(sdir, "logs", "latest.log")
        if os.path.isfile(log_file):
            try:
                os.remove(log_file)
            except OSError:
                pass
    except Exception:
        pass


# --- the running process ----------------------------------------------------
class ServerProcess:
    """A running dedicated server with a captured console.

    Call start(); read lines via the on_line callback; send console commands
    with send(); stop() asks it to save-and-quit gracefully.
    """

    def __init__(self, instance, config):
        self.instance = instance
        self.config = config
        self.proc = None
        self.on_line = None
        self.on_exit = None
        self._reader = None
        self.log_lines = []
        self._started_at = None
        self.cmd = []
        self.exit_code = None
        self.exit_seconds = None
        self.log_path = log_path = None
        self._log_fh = None
        self._finished = False

    def start(self, jar_path, java_exe, ram_mb=2048, log_path=None):
        sdir = server_dir(self.instance)
        # Clean any stale locks or lingering latest.log file
        _clean_stale_server_logs_and_locks(sdir)

        # never hand Java a path that it can't open - it only shows an opaque
        # popup. Fail here with a message the UI can display instead. This opens
        # the file for real (not just isfile) so a file antivirus is still
        # locking can't sneak through.
        wait_jar_readable(jar_path)
        # a server needs the console java.exe (not the windowless javaw.exe),
        # otherwise startup errors become blocking popups and the console panel
        # stays empty - which is exactly why a crash looks like "it just closed".
        java_exe = java_runtime.console_java(java_exe)
        if _is_windows() and os.path.basename(java_exe or "").lower() == "javaw.exe":
            raise RuntimeError(
                "Only the windowless Java (javaw.exe) is available, and a server "
                "can't run on it - every startup error would be hidden behind a "
                "popup. Install Java " + str(instance_java_major(self.instance)) +
                " (Adoptium/Temurin) or set the java.exe path in Settings.")
        jar_path = os.path.abspath(jar_path)
        if not os.path.isfile(java_exe or ""):
            raise RuntimeError("Java is missing: " + str(java_exe) +
                              "\n\nUse Repair Java in Settings, then try again.")
        xmx = max(1024, int(ram_mb))
        xms = min(xmx, max(512, xmx // 2))
        
        # Clean JVM flags for headless logging and terminal compatibility
        jvm_flags = [
            "-Dterminal.jline=false",
            "-Dterminal.ansi=true",
            "-Dlog4j2.formatMsgNoLookups=true",
            "-Dlog4j.skipJansi=true",
        ]

        # run from the server dir so a relative path can never be misresolved
        cmd = [java_exe, "-Xmx%dM" % xmx, "-Xms%dM" % xms] + jvm_flags + [
               "-jar", jar_path, "nogui"]
        self.cmd = cmd
        self.log_path = log_path
        self._log_fh = None
        
        self.proc = subprocess.Popen(
            cmd, cwd=sdir,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
            **java_runtime._no_window_kwargs())
        self._started_at = time.time()
        self._reader = threading.Thread(
            target=self._read_loop, daemon=True)
        self._reader.start()

    def _finish(self, code):
        if self._finished:
            return
        self._finished = True
        try:
            if self._log_fh:
                self._log_fh.close()
        except Exception:
            pass
        self.exit_code = code
        self.exit_seconds = (time.time() - self._started_at) if self._started_at else 0
        if self.on_exit:
            self.on_exit(code)

    def _emit(self, line):
        self.log_lines.append(line)
        if len(self.log_lines) > 2000:
            self.log_lines = self.log_lines[-1500:]
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as lf:
                    lf.write(line + "\n")
            except Exception:
                pass
        if self.on_line:
            self.on_line(line)

    def _decode(self, data):
        try:
            return data.decode("utf-8")
        except Exception:
            return data.decode("utf-8", "replace")

    def _read_loop(self):
        buf = b""
        try:
            while True:
                chunk = self.proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    self._emit(self._decode(raw).rstrip("\r"))
        except Exception:
            pass
        if buf:
            self._emit(self._decode(buf).rstrip("\r\n"))
        try:
            code = self.proc.wait() if self.proc else -1
        except Exception:
            code = -1
        self._finish(code)

    def send(self, command):
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            try:
                self.proc.stdin.write(
                    (command.rstrip("\n") + "\n").encode("utf-8", "replace"))
                self.proc.stdin.flush()
                return True
            except Exception:
                return False
        return False

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        """Graceful: send 'stop', then kill if it hangs."""
        if not self.is_running():
            return
        self.send("stop")

        def _kill_if_stuck():
            time.sleep(12)
            if self.is_running():
                try:
                    self.proc.kill()
                except Exception:
                    pass
        threading.Thread(target=_kill_if_stuck, daemon=True).start()

    def kill(self):
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass

    def pid(self):
        """The JVM's pid (0 when it isn't running) - used for the resource meters."""
        if self.proc is not None and self.proc.poll() is None:
            return self.proc.pid
        return 0
