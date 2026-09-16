"""Unpacking an archive we did not write, without trusting it.

Two separate things go wrong with zips, and both have bitten this launcher:

* **Separators.** PowerShell's ``Compress-Archive`` - what ``build_exe.bat`` packs with -
  writes Windows names inside the archive, ``Folder\\sub\\`` for a *directory*. Python's
  ``ZipInfo.is_dir()`` only knows about a trailing ``/``, so those entries look like
  zero-length files; unpacked as files they sit where a folder belongs and the next real
  member inside it dies with ``NotADirectoryError``. A release that was perfectly good
  looked like a broken download.
* **Paths that escape.** An archive whose member is ``../../things`` must not be able to
  write outside the folder it was unpacked into - for the updater that is the difference
  between "replaces its own files" and "a program that overwrites arbitrary files", which
  is exactly the behaviour antivirus looks for.

Everything here is pure: it returns what it wrote and raises on a useless archive, so both
the updater and the modpack installer get the same guarantees.
"""
import os
import shutil
import zipfile


def member_path(info):
    r"""``(forward_slash_path, is_directory_entry)`` for one archive member."""
    raw = str(info.filename)
    is_dir = raw.endswith("/") or raw.endswith("\\") or bool(info.is_dir())
    return raw.replace("\\", "/"), is_dir


def wrapper_folder(names):
    r"""The single top-level folder an archive wraps everything in, or ``""``.

    ``Compress-Archive -Path dist\DivineClient`` puts every file under ``DivineClient/``. The
    payload is copied relative to the archive root, so a wrapper that is not removed
    installs the program *next to* itself - a silent no-op update. Only strip it when every
    entry sits inside the same one folder and nothing lives at the root.
    """
    files = [str(n).replace("\\", "/").rstrip("/") for n in names]
    if not files or any("/" not in n for n in files):
        return ""
    tops = {n.split("/", 1)[0] for n in files}
    if len(tops) != 1:
        return ""
    top = tops.pop()
    return (top + "/") if top and top not in (".", "..") else ""


def usable_members(archive):
    """``[(name, ZipInfo)]`` - the files worth writing, directories and junk left out."""
    out = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name, is_dir = member_path(info)
            if is_dir:
                continue
            name = name.rstrip("/")
            if not name or name.endswith(("/.", "/..")) or "/../" in ("/" + name):
                continue
            out.append((name, info))
    return out


def names(archive):
    """Every member path, normalised. Handy for peeking without extracting."""
    return [member_path(i)[0] for i in zipfile.ZipFile(archive).infolist()]


def safe_extract(archive, target, strip_wrapper=True, only=None, progress=None):
    """Extract ``archive`` into ``target``. Returns the relative paths written.

    ``only`` restricts the extraction to members under a given prefix (modpacks use that
    for ``overrides/``) and the prefix is removed from the written name. A member that
    cannot be written is skipped rather than fatal: one odd file inside an archive is not a
    reason to have no update, or half a modpack.
    """
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    entries = usable_members(archive)
    if strip_wrapper:
        prefix = wrapper_folder([n for n, _ in entries])
    else:
        prefix = ""
    if only:
        only = only.rstrip("/") + "/"
        entries = [(n[len(prefix + only):] if (prefix + only) and n.startswith(prefix + only)
                    else (n[len(only):] if n.startswith(only) else None), info)
                   for n, info in entries]
        entries = [(n, info) for n, info in entries if n]
    root = os.path.normpath(target)
    written = []
    with zipfile.ZipFile(archive) as z:
        for i, (name, info) in enumerate(entries):
            rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
            out = os.path.normpath(os.path.join(root, rel))
            if not out.startswith(root + os.sep) or out == root:
                continue                     # tries to write outside: not ours
            parent = os.path.dirname(out)
            if os.path.isfile(parent):
                continue                     # a file where a folder should be
            try:
                os.makedirs(parent, exist_ok=True)
                with z.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except (OSError, zipfile.BadZipFile):
                try:
                    if os.path.isfile(out):
                        os.remove(out)
                except OSError:
                    pass
                continue
            written.append(os.path.relpath(out, root).replace(os.sep, "/"))
            if progress:
                try:
                    progress(i + 1, len(entries), rel)
                except Exception:
                    pass
    if not written:
        raise RuntimeError("the archive held no files that could be unpacked - it is "
                           "not a build")
    return written
