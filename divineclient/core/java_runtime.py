# Finding, checking and repairing the Java runtime.
#
# The "jli.dll was not found" crash means the Java that got installed is missing
# files - jli.dll lives next to java.exe, so if it's gone Java can't start at all.
# On Windows this usually happens because antivirus grabbed a file during the
# download or the extraction was interrupted.
#
# To avoid it we do two things:
#   1. Prefer Adoptium (Temurin), which ships Java as one checksummed zip that
#      either arrives complete or fails outright - no half-installed runtime.
#   2. Before handing any java path to the game, we actually run "java -version".
#      If it doesn't start, we don't use it - we reinstall, then fall back to a
#      system Java if we have to.
import os
import platform
import shutil
import subprocess
import sys

import minecraft_launcher_lib as mll

from .. import paths
from . import adoptium


def _no_window_kwargs():
    # Keep a console window from flashing up when we probe java on Windows.
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def runtime_files_ok(java_exe):
    """Check the native libraries exist on disk BEFORE we try to run java.

    This is what actually stops the "jli.dll was not found" popup. On Windows,
    launching a java.exe whose jli.dll is missing makes Windows itself throw that
    error dialog - even from our own version probe. So we never execute a runtime
    unless its core DLLs are physically present.
    """
    if not java_exe or not os.path.isfile(java_exe):
        return False
    bin_dir = os.path.dirname(java_exe)
    home = os.path.dirname(bin_dir)
    if sys.platform == "win32":
        required = [
            os.path.join(bin_dir, "jli.dll"),
            os.path.join(bin_dir, "server", "jvm.dll"),
        ]
        for path in required:
            # jvm.dll can sit under bin\server or bin\client depending on build.
            if path.endswith("jvm.dll") and not os.path.exists(path):
                if not os.path.exists(os.path.join(bin_dir, "client", "jvm.dll")):
                    return False
            elif not os.path.exists(path):
                return False
    else:
        # On mac/linux the equivalents are libjli / libjvm.
        found_jli = any(
            os.path.exists(os.path.join(home, sub, name))
            for sub in ("lib", os.path.join("lib", "jli"))
            for name in ("libjli.so", "libjli.dylib")
        )
        if not found_jli and not os.path.exists(os.path.join(bin_dir, "java")):
            return False
    return True


def java_actually_runs(java_exe):
    """Kept for callers that only care that java starts at all."""
    return java_major_version(java_exe) is not None


def java_major_version(java_exe):
    """Run java and return its major version as an int (e.g. 8, 17, 21), or None.

    This is the important check: a Java 8 launches fine but can't run a game that
    was compiled for Java 21 (the "class file version 65.0" crash). So we don't
    just ask "does java start" - we ask "which java is this" and refuse to use
    the wrong one.
    """
    if not java_exe or not os.path.isfile(java_exe):
        return None
    # Never execute a runtime with missing native libs - that is what pops the
    # Windows "jli.dll not found" dialog. Treat it as unusable instead.
    if not runtime_files_ok(java_exe):
        return None
    try:
        result = subprocess.run(
            [java_exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=25,
            **_no_window_kwargs(),
        )
        if result.returncode != 0:
            return None
        text = result.stdout.decode("utf-8", "replace")
    except Exception:
        return None
    return _parse_major(text)


def _parse_major(version_text):
    """Pull the major version number out of `java -version` output."""
    import re
    # Matches: version "1.8.0_502"  ->  8
    #          version "17.0.9"     -> 17
    #          version "21"         -> 21
    m = re.search(r'version "(\d+)(?:\.(\d+))?', version_text)
    if not m:
        return None
    first = int(m.group(1))
    if first == 1 and m.group(2):
        return int(m.group(2))  # old 1.8 style -> 8
    return first


def _acceptable(java_exe, required_major):
    """Is this java new enough (but not the wrong era) to run the game?

    The class-version crash comes from using too-old a Java. But Java 8 era games
    also break on very new Java. So: old games (need <= 8) require exactly Java 8;
    modern games accept their target LTS or anything newer.
    """
    from . import adoptium
    target = adoptium._lts_for(required_major)
    major = java_major_version(java_exe)
    if major is None:
        return False
    if target <= 8:
        return major == 8
    return major >= target


def _runtime_info(mc_version_id):
    """Return (component_name, java_major) for a Minecraft version."""
    try:
        info = mll.runtime.get_version_runtime_information(mc_version_id, paths.MINECRAFT_DIR)
        if info:
            return info.get("name", "jre-legacy"), int(info.get("javaMajorVersion", 8))
    except Exception:
        pass
    return "jre-legacy", 8


def required_component(mc_version_id):
    return _runtime_info(mc_version_id)[0]


def _os_arch():
    """Adoptium's names for this machine's OS and CPU."""
    if sys.platform == "win32":
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "mac"
    else:
        os_name = "linux"
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        arch = "x64"
    elif m in ("arm64", "aarch64"):
        arch = "aarch64"
    elif m in ("x86", "i386", "i686"):
        arch = "x86"
    else:
        arch = "x64"
    return os_name, arch


def console_java(java_exe):
    """Given a java/javaw path, return the console java.exe next to it.

    The game client uses javaw.exe on Windows so no black console window pops
    up. A *server* must use java.exe instead: with javaw.exe, startup errors
    (like a missing jar) become blocking "Java Virtual Machine Launcher" popups
    and no output reaches our captured console. That popup is what makes a
    crashed server look like "it just closed" with nothing to read.

    So: never hand back a javaw. If java.exe isn't sitting next to it, look in
    the rest of that runtime, then JAVA_HOME, then PATH.
    """
    if not java_exe:
        return java_exe
    base = os.path.basename(java_exe)
    stem = os.path.splitext(base)[0].lower()
    if stem != "javaw":
        return java_exe            # already a console launcher (or non-Windows)
    if sys.platform != "win32":
        return java_exe

    d = os.path.dirname(java_exe)
    cand = os.path.join(d, "java.exe")
    if os.path.isfile(cand):
        return cand

    # a JRE zip can be laid out as <root>/bin or <root>/jre/bin
    for probe in (d, os.path.dirname(d), os.path.join(os.path.dirname(d), "jre", "bin")):
        c = os.path.join(probe, "bin", "java.exe")
        if os.path.isfile(c):
            return c
        c = os.path.join(probe, "java.exe")
        if os.path.isfile(c):
            return c

    home = os.environ.get("JAVA_HOME")
    if home:
        c = os.path.join(home, "bin", "java.exe")
        if os.path.isfile(c):
            return c

    found = shutil.which("java")
    if found and os.path.isfile(found):
        return found
    return java_exe                 # caller decides what to do with a javaw-only box



def find_system_java(required_major):
    """Last resort - a Java on the machine that's the right version for this game."""
    candidates = []
    for name in ("javaw", "java"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    home = os.environ.get("JAVA_HOME")
    if home:
        exe = os.path.join(home, "bin", "javaw.exe" if sys.platform == "win32" else "java")
        if os.path.isfile(exe):
            candidates.insert(0, exe)
    for c in candidates:
        if _acceptable(c, required_major):
            return c
    return None


def _try_adoptium(major, progress):
    """Use an existing Adoptium runtime if it's the right version, else download it."""
    exe = adoptium.find_java_exe(major)
    if exe and runtime_files_ok(exe) and _acceptable(exe, major):
        return exe
    os_name, arch = _os_arch()
    # Give the download a couple of tries - a dropped connection or a file the
    # antivirus briefly locked shouldn't send us to the broken Mojang runtime.
    for attempt in range(3):
        try:
            exe = adoptium.install(major, os_name, arch, progress=progress)
        except Exception as e:
            if attempt < 2:
                progress.set_status("Java download failed, retrying... (" + str(e)[:50] + ")")
                continue
            progress.set_status("Adoptium download failed (" + str(e)[:60] + ")")
            return None
        if exe and runtime_files_ok(exe) and _acceptable(exe, major):
            return exe
        if attempt < 2:
            progress.set_status("Java looked incomplete, re-downloading a clean copy...")
    return None


def _try_mojang(mc_version_id, progress, required_major):
    """Fallback to Mojang's runtime, with a verify + one clean-reinstall pass."""
    component = required_component(mc_version_id)
    exe = mll.runtime.get_executable_path(component, paths.MINECRAFT_DIR)
    if exe and _acceptable(exe, required_major):
        return exe
    # wipe and pull a clean copy
    comp_dir = os.path.join(paths.MINECRAFT_DIR, "runtime", component)
    if os.path.isdir(comp_dir):
        shutil.rmtree(comp_dir, ignore_errors=True)
    try:
        progress.set_status("Downloading Java runtime (" + component + ")...")
        mll.runtime.install_jvm_runtime(component, paths.MINECRAFT_DIR,
                                        callback=progress.as_callback())
    except Exception:
        return None
    exe = mll.runtime.get_executable_path(component, paths.MINECRAFT_DIR)
    if exe and _acceptable(exe, required_major):
        return exe
    return None


def ensure_java(mc_version_id, progress, custom_java_path=""):
    """Return a java path that has been verified to actually start.

    Order:
      1. A custom java from Settings (only if it runs).
      2. Adoptium Temurin - a complete, checksummed runtime (the reliable path).
      3. Mojang's runtime, as a fallback.
      4. Any working Java already installed on the system.
    """
    _component, major = _runtime_info(mc_version_id)

    # 1) user supplied - only if it's the right version for this game
    if custom_java_path and os.path.isfile(custom_java_path):
        if _acceptable(custom_java_path, major):
            return custom_java_path
        have = java_major_version(custom_java_path)
        progress.set_status("Your Settings Java is Java " + str(have) + " but this "
                            "version needs Java " + str(major) + " - using managed Java.")

    # 2) Adoptium (preferred)
    exe = _try_adoptium(major, progress)
    if exe:
        return exe

    # 3) Mojang fallback
    progress.set_status("Trying Mojang's Java as a fallback...")
    exe = _try_mojang(mc_version_id, progress, major)
    if exe:
        return exe

    # 4) system java - must be the right version too
    progress.set_status("Looking for a matching Java on your system...")
    exe = find_system_java(major)
    if exe:
        return exe

    raise RuntimeError(
        "Couldn't get Java " + str(major) + ", which this Minecraft version needs. "
        "This is usually antivirus blocking the download or no internet. Add an "
        "antivirus exception for the Divine Client data folder, click Repair Java in "
        "Settings, then try again - or install Java " + str(major) + " yourself and "
        "set its path in Settings."
    )


def get_java_env(java_exe):
    """Return an environment dict with Java bin and server dirs prepended to PATH.
    This guarantees that Windows dynamic linker finds jli.dll, jvm.dll, and other native libs.
    """
    env = os.environ.copy()
    if not java_exe or not os.path.isfile(java_exe):
        return env
    
    bin_dir = os.path.dirname(os.path.abspath(java_exe))
    home_dir = os.path.dirname(bin_dir)
    server_dir = os.path.join(bin_dir, "server")
    client_dir = os.path.join(bin_dir, "client")
    
    extra_paths = [bin_dir, server_dir, client_dir, home_dir]
    existing_path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([p for p in extra_paths if os.path.isdir(p)] + [existing_path])
    env["JAVA_HOME"] = home_dir
    return env
