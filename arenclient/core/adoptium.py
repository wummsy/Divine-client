# Downloads a complete Java runtime from Adoptium (Eclipse Temurin).
#
# Why this exists: Mojang hands its runtime to you as hundreds of separate files,
# and on Windows it's common for one of them (jli.dll being the usual victim) to
# get skipped or quarantined by antivirus. When that happens you get
# "the code execution cannot proceed because jli.dll was not found", and
# re-pulling from Mojang just gives you the same broken set again.
#
# Adoptium ships each Java as one signed .zip with a published checksum. We grab
# that, verify it, and unzip it whole - so either we get a runtime that has every
# file, or the download fails loudly. No more half-installed Java.
import hashlib
import os
import shutil
import tarfile
import zipfile

import requests

from .. import paths

API = "https://api.adoptium.net/v3"
UA = {"User-Agent": "DivineClient/1.0"}

# Where our Adoptium runtimes live, kept separate from Mojang's runtime folder.
# Resolved on demand so it follows the user's chosen game-files location.
def adoptium_dir():
    return os.path.join(paths.MINECRAFT_DIR, "adoptium")

# Adoptium only ships LTS releases. Map whatever Java a version wants onto the
# closest LTS that can actually run it.
def _lts_for(major):
    if major <= 8:
        return 8
    if major <= 11:
        return 11
    if major <= 17:
        return 17
    return 21


def runtime_dir(major):
    return os.path.join(adoptium_dir(), "jre-" + str(_lts_for(major)))


def find_java_exe(major):
    """Return the javaw.exe / java path for an already-installed Adoptium runtime."""
    base = runtime_dir(major)
    if not os.path.isdir(base):
        return None
    names = ("javaw.exe", "java.exe", "java")
    for root, _dirs, files in os.walk(base):
        if os.path.basename(root).lower() == "bin":
            for n in names:
                cand = os.path.join(root, n)
                if os.path.isfile(cand):
                    return cand
    return None


def _asset_info(lts, os_name, arch):
    url = (API + "/assets/latest/" + str(lts) + "/hotspot"
           "?architecture=" + arch + "&image_type=jre&os=" + os_name + "&vendor=eclipse")
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise RuntimeError("Adoptium has no JRE build for Java " + str(lts)
                           + " on " + os_name + "/" + arch)
    pkg = data[0]["binary"]["package"]
    return pkg["link"], pkg.get("checksum", ""), pkg.get("name", "jre.zip")


def install(major, os_name, arch, progress=None):
    """Download + verify + extract a Temurin JRE. Returns the java executable path."""
    lts = _lts_for(major)
    base = runtime_dir(major)
    os.makedirs(adoptium_dir(), exist_ok=True)

    if progress:
        progress.set_status("Getting a clean Java " + str(lts) + " from Adoptium...")
    link, checksum, name = _asset_info(lts, os_name, arch)

    tmp_arc = os.path.join(adoptium_dir(), name + ".part")
    if progress:
        progress.set_status("Downloading Java " + str(lts) + " (about 45 MB)...")

    sha = hashlib.sha256()
    with requests.get(link, headers=UA, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        if progress:
            progress.set_max(total or 1)
        with open(tmp_arc, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress.set_progress(done)

    if checksum and sha.hexdigest().lower() != checksum.lower():
        os.remove(tmp_arc)
        raise RuntimeError("Java download was corrupted (checksum mismatch). "
                           "Please try again.")

    # Clean any previous copy, then extract the whole archive. Windows builds are
    # .zip, everything else is .tar.gz - handle both.
    if os.path.isdir(base):
        shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    if progress:
        progress.set_status("Unpacking Java " + str(lts) + "...")
    if name.endswith(".zip"):
        with zipfile.ZipFile(tmp_arc) as zf:
            zf.extractall(base)
    else:
        with tarfile.open(tmp_arc, "r:*") as tf:
            tf.extractall(base)
    try:
        os.remove(tmp_arc)
    except OSError:
        pass

    exe = find_java_exe(major)
    if not exe:
        raise RuntimeError("Java unpacked but no java executable was found.")
    # Make sure it's runnable on non-Windows.
    try:
        os.chmod(exe, 0o755)
    except OSError:
        pass
    return exe
