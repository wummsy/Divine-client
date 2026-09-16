"""Metadata helpers for the content already installed in an instance.

Two jobs:
  * pull an icon and description straight out of a local .jar / .zip so the
    editor can show them instantly, offline;
  * match a local file back to its Modrinth page by file hash (cached), so we
    can offer a "View on Modrinth" link even for hand-dropped files.
"""
import hashlib
import json
import os
import threading
import zipfile

from .. import paths
from . import modrinth

ICON_CACHE = os.path.join(paths.DATA_DIR, "cache", "content_icons")
_HASH_CACHE_FILE = os.path.join(paths.DATA_DIR, "cache", "modrinth_hashes.json")
_hash_cache = None
_hash_dirty = False
_hash_lock = threading.Lock()


# ---- embedded icons ---------------------------------------------------------
def _cache_icon_bytes(key, ext, data):
    os.makedirs(ICON_CACHE, exist_ok=True)
    safe = hashlib.md5(key.encode("utf-8")).hexdigest()
    dest = os.path.join(ICON_CACHE, safe + ext)
    if os.path.exists(dest) and os.path.getsize(dest) == len(data):
        return dest          # already extracted; don't rewrite it on every refresh
    try:
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return dest
    except OSError:
        return None


def extract_mod_icon(jar_path):
    """Return a local path to a mod jar's embedded icon, or None.

    Reads the ``icon`` field from fabric.mod.json (falling back to common
    names) and copies it into the icon cache.
    """
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = zf.namelist()
            icon_name = None
            if "fabric.mod.json" in names:
                try:
                    meta = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"))
                    ic = meta.get("icon")
                    if isinstance(ic, dict):  # {"128": "path"}
                        ic = ic.get(sorted(ic, key=lambda k: int(k) if k.isdigit() else 0)[-1])
                    if isinstance(ic, str) and ic in names:
                        icon_name = ic
                except Exception:
                    pass
            if icon_name is None:
                for cand in ("assets/icon.png", "icon.png", "logo.png", "pack.png"):
                    if cand in names:
                        icon_name = cand
                        break
            if icon_name is None:
                return None
            data = zf.read(icon_name)
            ext = os.path.splitext(icon_name)[1].lower() or ".png"
            return _cache_icon_bytes(jar_path + "::" + icon_name, ext, data)
    except Exception:
        return None


def extract_pack_meta(pack_path):
    """Return {"icon": path|None, "description": str} for a resource pack.

    Packs are either a .zip or an extracted folder; both hold pack.png and
    pack.mcmeta at the top level.
    """
    icon = None
    desc = ""
    try:
        if os.path.isdir(pack_path):
            png = os.path.join(pack_path, "pack.png")
            if os.path.isfile(png):
                icon = png
            mcmeta = os.path.join(pack_path, "pack.mcmeta")
            if os.path.isfile(mcmeta):
                with open(mcmeta, "r", encoding="utf-8", errors="replace") as f:
                    desc = _pack_desc(f.read())
        elif zipfile.is_zipfile(pack_path):
            with zipfile.ZipFile(pack_path) as zf:
                names = zf.namelist()
                if "pack.png" in names:
                    icon = _cache_icon_bytes(pack_path + "::pack.png", ".png",
                                             zf.read("pack.png"))
                if "pack.mcmeta" in names:
                    desc = _pack_desc(zf.read("pack.mcmeta").decode("utf-8", "replace"))
    except Exception:
        pass
    return {"icon": icon, "description": desc}


def _pack_desc(raw):
    try:
        data = json.loads(raw)
        d = (data.get("pack") or {}).get("description", "")
        if isinstance(d, list):  # can be a list of text components
            parts = []
            for seg in d:
                if isinstance(seg, str):
                    parts.append(seg)
                elif isinstance(seg, dict):
                    parts.append(seg.get("text", ""))
            d = "".join(parts)
        elif isinstance(d, dict):
            d = d.get("text", "")
        return (d or "").strip()
    except Exception:
        return ""


# ---- Modrinth hash lookup (cached) -----------------------------------------
def _load_hash_cache():
    global _hash_cache
    if _hash_cache is None:
        try:
            with open(_HASH_CACHE_FILE, "r", encoding="utf-8") as f:
                _hash_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _hash_cache = {}
    return _hash_cache


def flush_hash_cache():
    """Write the Modrinth hash cache if anything changed.

    Used to be saved inside every lookup, so enriching a list of 30 mods rewrote
    the whole JSON file 30 times over. Call it once when a batch finishes.
    """
    global _hash_dirty
    with _hash_lock:
        if not _hash_dirty:
            return
        _hash_dirty = False
    try:
        os.makedirs(os.path.dirname(_HASH_CACHE_FILE), exist_ok=True)
        tmp = _HASH_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_hash_cache, f)
        os.replace(tmp, _HASH_CACHE_FILE)
    except OSError:
        pass


def sha1_of(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def modrinth_for_file(path):
    """Match a local file to Modrinth by hash. Returns project info dict
    (title, description, icon_url, url, version) or None. Results are cached on
    disk keyed by SHA1 so repeat lookups (and misses) are instant."""
    sha1 = sha1_of(path)
    if not sha1:
        return None
    cache = _load_hash_cache()
    if sha1 in cache:
        return cache[sha1] or None
    info = modrinth.lookup_by_hash(sha1)
    global _hash_dirty
    with _hash_lock:
        cache[sha1] = info  # store misses as None too, so we don't re-hit the API
        _hash_dirty = True
    return info
