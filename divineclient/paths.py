"""Central location for all filesystem paths used by Divine Client.

The launcher keeps its own settings, accounts and logs in a fixed per-user
directory (DATA_DIR). The heavy game files - Minecraft versions, libraries,
assets, the Java runtimes and the instances - live under GAME_DIR, which the
user can point anywhere (a bigger drive, for example). The chosen location is
remembered in a small file next to the launcher settings so it survives across
runs without any circular dependency on the config module.
"""
import json
import os
import sys


def _base_data_dir() -> str:
    """Return the per-user data directory for Divine Client."""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        p_divine = os.path.join(root, ".divineclient")
        p_fallback = os.path.join(root, ".divineclient")
        if os.path.isdir(p_fallback) and not os.path.isdir(p_divine):
            return p_fallback
        return p_divine
    elif sys.platform == "darwin":
        p_divine = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "divineclient")
        p_fallback = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "divineclient")
        if os.path.isdir(p_fallback) and not os.path.isdir(p_divine):
            return p_fallback
        return p_divine
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        p_divine = os.path.join(root, "divineclient")
        p_fallback = os.path.join(root, "divineclient")
        if os.path.isdir(p_fallback) and not os.path.isdir(p_divine):
            return p_fallback
        return p_divine


DATA_DIR = _base_data_dir()
# Launcher-owned files stay with the launcher regardless of where game files go.
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")
# Where the chosen game-files location is remembered.
LOCATION_FILE = os.path.join(DATA_DIR, "location.json")


def _read_location() -> dict:
    """Read the saved locations file: {game_dir, instances_dir}."""
    try:
        with open(LOCATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_location(game_dir: str, instances_dir: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = LOCATION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"game_dir": game_dir, "instances_dir": instances_dir},
                  f, indent=2)
    os.replace(tmp, LOCATION_FILE)


def _apply_paths(game_dir: str, instances_dir: str = None) -> None:
    """Point the module-level path globals at the chosen locations.

    ``game_dir`` holds the shared Minecraft files (versions, libraries, assets,
    Java runtimes). ``instances_dir`` holds the per-instance game directories
    (saves, mods, options...) and can live somewhere separate; when not given it
    defaults to an ``instances`` folder under ``game_dir``.
    """
    global GAME_DIR, MINECRAFT_DIR, INSTANCES_DIR
    GAME_DIR = game_dir
    MINECRAFT_DIR = os.path.join(GAME_DIR, "minecraft")
    INSTANCES_DIR = instances_dir or os.path.join(GAME_DIR, "instances")


# Initialise from whatever was saved (or the defaults).
GAME_DIR = DATA_DIR
MINECRAFT_DIR = os.path.join(GAME_DIR, "minecraft")
INSTANCES_DIR = os.path.join(GAME_DIR, "instances")

_saved = _read_location()
_g = _saved.get("game_dir", "")
_i = _saved.get("instances_dir", "")
_g = _g if (_g and os.path.isabs(_g)) else DATA_DIR
_i = _i if (_i and os.path.isabs(_i)) else None
_apply_paths(_g, _i)


def get_game_dir() -> str:
    """Return the current game-files root (shared Minecraft files)."""
    return GAME_DIR


def get_instances_dir() -> str:
    """Return the directory where instances (and their saves) are stored."""
    return INSTANCES_DIR


def is_default_game_dir() -> bool:
    return os.path.normpath(GAME_DIR) == os.path.normpath(DATA_DIR)


def is_default_instances_dir() -> bool:
    return os.path.normpath(INSTANCES_DIR) == os.path.normpath(
        os.path.join(GAME_DIR, "instances"))


def set_game_dir(path: str) -> None:
    """Remember ``path`` as the game-files root and switch to it immediately.

    Keeps any custom instances directory as-is; if none is set, instances keep
    following ``game_dir``.
    """
    path = os.path.abspath(os.path.expanduser(path))
    inst = None if is_default_instances_dir() else INSTANCES_DIR
    _apply_paths(path, inst)
    _write_location(GAME_DIR, INSTANCES_DIR)
    ensure_dirs()


def set_instances_dir(path: str) -> None:
    """Remember ``path`` as where instances (and their saves) are stored and
    switch to it immediately."""
    path = os.path.abspath(os.path.expanduser(path))
    _apply_paths(GAME_DIR, path)
    _write_location(GAME_DIR, INSTANCES_DIR)
    ensure_dirs()


# Everything the launcher keeps under the game-files root, and what has to come along
# when that root moves. `minecraft` holds the versions, libraries, assets *and* the Java
# runtime (MINECRAFT_DIR/adoptium, MINECRAFT_DIR/runtime), so without it everything
# re-downloads; `tunnel` holds the bore/playit agents, and without it a hosted server
# loses its public address mid-game. Both are ours, both are moved without asking.
# The two user-data folders are not: they only move when the user said yes.
MUST_MOVE_SUBS = ("minecraft", "tunnel")
ASK_FIRST_SUBS = ("instances", "servers")


def subs_under_game_dir():
    """The folders that live under the current game-files root."""
    root = get_game_dir()
    return {name: os.path.join(root, name) for name in MUST_MOVE_SUBS + ASK_FIRST_SUBS}


def relocate_subdirs(old_root, new_root, include_user_data=True, progress=None,
                     skip=()):
    """Move the launcher's folders from `old_root` to `new_root` after a location change.

    ``skip`` names folders the caller has decided do not belong to this move - the
    instances folder, for example, when it was pointed somewhere else and so is not a
    child of either root.

    Returns ``{name: "moved" | "merged" | "skipped" | "failed"}`` so the caller can say
    what actually happened instead of claiming a clean move. Files that already exist at
    the destination are never overwritten - a half-copied tree is worse than a duplicate -
    and the source is left in place when that happens, so nothing is ever deleted to make
    the move tidy.
    """
    import shutil

    def say(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    results = {}
    old_root = os.path.abspath(old_root or ".")
    new_root = os.path.abspath(new_root or ".")
    if os.path.normpath(old_root) == os.path.normpath(new_root):
        return results
    skip = set(skip or ())
    names = [n for n in list(MUST_MOVE_SUBS)
             + (list(ASK_FIRST_SUBS) if include_user_data else []) if n not in skip]
    os.makedirs(new_root, exist_ok=True)
    for name in names:
        src = os.path.join(old_root, name)
        dst = os.path.join(new_root, name)
        if not os.path.isdir(src):
            results[name] = "skipped"
            continue
        if not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                results[name] = "moved"
                say("moved " + name)
                continue
            except OSError as err:
                say("%s could not be moved (%s), copying what is new" % (name, err))
        # destination already has one: bring over only what is missing
        copied, kept = 0, 0
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            for fn in files:
                to = os.path.join(dst, rel, fn) if rel != "." else os.path.join(dst, fn)
                if os.path.exists(to):
                    kept += 1
                    continue
                os.makedirs(os.path.dirname(to), exist_ok=True)
                try:
                    shutil.copy2(os.path.join(root, fn), to)
                    copied += 1
                except OSError:
                    kept += 1
        results[name] = "merged" if copied else "skipped"
        say("%s: %d new file(s) copied, %d already there" % (name, copied, kept))
    return results


def ensure_dirs() -> None:
    for d in (DATA_DIR, MINECRAFT_DIR, INSTANCES_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def resource_path(relative: str) -> str:
    """Resolve a bundled asset path, working both from source and a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        p1 = os.path.join(exe_dir, "_internal", relative)
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(exe_dir, relative)
        if os.path.exists(p2):
            return p2
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", relative)
