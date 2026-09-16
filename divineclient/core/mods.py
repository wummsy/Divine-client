"""Built-in performance mod pack & Divine Client Mod manager."""
import hashlib
import json
import os
import re
import shutil
import zipfile

import requests

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "DivineClient/1.0 (Divine dev team launcher) / performance pack"

PERFORMANCE_PACK = [
    ("fabric-api", "The core library most Fabric mods need, these ones included."),
    ("sodium", "Rewrites the renderer - the single biggest frame-rate jump."),
    ("immediatelyfast", "Batches the model, GUI and font drawing vanilla does one by one."),
    ("entityculling", "Stops rendering entities, armor stands and item frames you cannot see."),
    ("cull-less-leaves", "Leaves and vines stop hiding what is behind them, so there is less to draw."),
    ("ebe", "Draws chests, signs, skulls and banners as ordinary blocks."),
    ("dynamic-fps", "Drops the frame rate to what you set while the window is not focused."),
    ("ferrite-core", "Cuts the memory spent on models, palettes and biome data."),
    ("modernfix", "Faster launch, less memory, and a pile of vanilla inefficiencies fixed."),
    ("memoryleakfix", "Closes the known leaks: recipes, scoreboards, chunk maps, entities."),
    ("lithium", "Optimises game logic - mob ticking, colliders, lighting, chunk saving."),
    ("modmenu", "The in-game list of installed mods and their config screens."),
]

ULTIMATE_OPTIMIZATION_PACK = [
    ("fabric-api", "Essential Fabric modding runtime API and lifecycle hooks."),
    ("sodium", "Next-generation rendering engine rewrite providing 3x-10x FPS gains."),
    ("iris", "Modern, ultra-fast shader pack loader integrated with Sodium."),
    ("lithium", "Massive physics, mob AI, lighting, and world ticking optimization."),
    ("ferrite-core", "Memory allocation and RAM footprint reduction by up to 50%."),
    ("entityculling", "Asynchronous frustum entity culling for occluded mobs and tile entities."),
    ("immediatelyfast", "Optimizes immediate-mode drawing: HUD, fonts, map rendering, and particles."),
    ("modernfix", "Eliminates game launch stalls, startup lag, and vanilla memory leaks."),
    ("memoryleakfix", "Patches engine memory leaks in chunk tracking, recipes, and scoreboards."),
    ("cull-less-leaves", "Optimizes tree leaf geometry and transparent foliage rendering."),
    ("ebe", "Enhanced Block Entities: converts chests, signs, and banners to high-speed static block models."),
    ("dynamic-fps", "Reduces GPU/CPU power consumption when the game window is out of focus."),
    ("krypton", "Optimized network stack and packet serialization for smooth multiplayer and chunk loading."),
    ("cloth-config", "Standard in-game configuration screen framework."),
    ("modmenu", "Comprehensive in-game mod management and settings browser."),
]

SERVER_PACK = [
    ("lithium", "Optimised game logic, so the world stops eating the tick budget."),
    ("krypton", "Rewrites the network stack so a full server stops drowning in packets."),
    ("noisium", "Faster world generation and lighting, for the versions that still need it."),
    ("alternate-current", "Rewrites redstone scheduling: same behaviour, far fewer block ticks."),
    ("ferrite-core", "The same memory savings as the client, applied to the server."),
]

PACK_STATE = ".divine-pack.json"
_LOADER_WORDS = ("fabric", "quilt", "neoforge", "forge", "mc", "beta", "alpha",
                 "release", "devbuild", "universal")


def _headers():
    return {"User-Agent": USER_AGENT}


def _stem(filename):
    base = os.path.basename(filename or "").lower()
    if base.endswith(".jar"):
        base = base[:-4]
    at = re.search(r"\d", base)
    if at:
        base = base[:at.start()]
    parts = [x for x in re.split(r"[-_ +.]+", base) if x]
    while parts and parts[-1] in _LOADER_WORDS:
        parts.pop()
    return "-".join(parts) if parts else base.strip("-_ ")


def _existing_jars(mods_dir):
    out = {}
    try:
        for name in os.listdir(mods_dir):
            if name.lower().endswith(".jar"):
                out.setdefault(_stem(name), name)
    except OSError:
        pass
    return out


_RANK = {"release": 0, "beta": 1, "alpha": 2}


def _version_key(v):
    nums = [int(x) for x in re.findall(r"\d+", v.get("version_number") or "")]
    return (nums, v.get("date_published") or "")


def _best_file(versions):
    usable = []
    for v in versions or []:
        files = [f for f in (v.get("files") or [])
                 if (f.get("filename") or "").lower().endswith(".jar") and
                 not re.search(r"sources|javadoc|sourcesjar", f.get("filename") or "", re.I)]
        if files:
            usable.append((v, files))
    if not usable:
        return None
    rank = min(_RANK.get(v.get("version_type"), 3) for v, _ in usable)
    pool = [(v, f) for v, f in usable if _RANK.get(v.get("version_type"), 3) == rank]
    v, files = max(pool, key=lambda pair: _version_key(pair[0]))
    f = next((x for x in files if x.get("primary")), files[0])
    return {"url": f.get("url"), "filename": f.get("filename"),
            "sha512": (f.get("hashes") or {}).get("sha512"),
            "size": f.get("size"), "name": v.get("name") or "",
            "version": v.get("version_number") or "",
            "type": v.get("version_type") or ""}


def _resolve(slug, mc_version, loader="fabric"):
    url = "%s/project/%s/version" % (MODRINTH_API, slug)
    params = {"loaders": json.dumps([loader]),
              "game_versions": json.dumps([mc_version])}
    r = requests.get(url, params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    return _best_file(data if isinstance(data, list) else [])


def _state_path(mods_dir):
    return os.path.join(mods_dir, PACK_STATE)


def _read_state(mods_dir):
    try:
        with open(_state_path(mods_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(mods_dir, state):
    try:
        with open(_state_path(mods_dir), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except OSError:
        pass


def install_pack(entries, mc_version, mods_dir, loader="fabric", progress=None,
                 what="performance pack"):
    os.makedirs(mods_dir, exist_ok=True)
    state = _read_state(mods_dir)
    have = _existing_jars(mods_dir)
    installed, skipped = [], []
    total = max(1, len(entries))

    for idx, (slug, desc) in enumerate(entries):
        if progress:
            progress("Resolving %s..." % slug, idx / float(total))
        try:
            info = _resolve(slug, mc_version, loader)
        except (requests.exceptions.RequestException, ValueError, TypeError):
            skipped.append(slug)
            continue
        if not info or not info.get("url"):
            skipped.append(slug)
            continue
        filename = os.path.basename(info["filename"])
        stem = _stem(filename)
        dest = os.path.join(mods_dir, filename)
        if os.path.exists(dest):
            installed.append("%s@%s" % (slug, filename))
            have.setdefault(stem, filename)
            state[slug] = {"filename": filename, "note": desc}
            continue
        if stem in have:
            skipped.append("%s(already installed)" % slug)
            continue
        try:
            if progress:
                progress("Downloading %s..." % filename, (idx + 0.5) / float(total))
            _download(info, dest, progress)
        except (requests.exceptions.RequestException, OSError, ValueError) as e:
            _discard(dest)
            skipped.append("%s(%s)" % (slug, str(e)[:40]))
            continue
        installed.append("%s@%s" % (slug, filename))
        have.setdefault(stem, filename)
        state[slug] = {"filename": filename, "note": desc,
                       "mc_version": mc_version}

    _write_state(mods_dir, {"mc_version": mc_version, "loader": loader,
                            "entries": state, "skipped": skipped})
    if progress:
        progress("%s ready" % (what or "pack").capitalize(), 1.0)
    return installed, skipped


def _download(info, dest, progress=None):
    tmp = dest + ".part"
    h = hashlib.sha512()
    got = 0
    try:
        with requests.get(info["url"], headers=_headers(), stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
        if info.get("size") and got != info["size"]:
            raise ValueError("got %d of %d bytes" % (got, info["size"]))
        want = (info.get("sha512") or "").lower()
        if want and h.hexdigest() != want:
            raise ValueError("checksum did not match Modrinth's")
        if not _looks_like_a_mod(tmp):
            raise ValueError("that is not a mod jar")
        os.replace(tmp, dest)
    finally:
        _discard(tmp)


def _looks_like_a_mod(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        return bool({"fabric.mod.json", "quilt.mod.json"} & names)
    except Exception:
        return False


def _discard(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def install_performance_pack(mc_version, mods_dir, loader="fabric", progress=None):
    return install_pack(PERFORMANCE_PACK, mc_version, mods_dir, loader=loader,
                        progress=progress, what="performance pack")


def install_ultimate_optimization_pack(mc_version, mods_dir, loader="fabric", progress=None):
    return install_pack(ULTIMATE_OPTIMIZATION_PACK, mc_version, mods_dir, loader=loader,
                        progress=progress, what="ultimate optimization pack")


def install_server_pack(mc_version, mods_dir, progress=None, loader="fabric"):
    return install_pack(SERVER_PACK, mc_version, mods_dir, loader=loader,
                        progress=progress, what="server performance pack")


def ensure_divine_client_mod(mods_dir):
    """Automatically installs DivineClientMod-1.0.0.jar into the instance mods folder."""
    os.makedirs(mods_dir, exist_ok=True)
    dest = os.path.join(mods_dir, "DivineClientMod-1.0.0.jar")

    possible_sources = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "mods", "DivineClientMod-1.0.0.jar")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "assets", "mods", "DivineClientMod-1.0.0.jar")),
        "/home/user/DivineClientMod-1.0.0.jar",
        "/home/user/divineclient-1.0.0.jar"
    ]
    for src in possible_sources:
        if os.path.isfile(src):
            try:
                shutil.copy2(src, dest)
                for old_name in ("DivineClient-Full-1.0.0.jar", "DivineClient-Standalone-1.0.0.jar"):
                    old_path = os.path.join(mods_dir, old_name)
                    if os.path.isfile(old_path):
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass
                return True
            except Exception:
                pass
    return False


def ensure_builder_suite(mods_dir, mc_version="1.21.11"):
    """Ensures Axiom, WorldEdit, Flashback, Fabric API, and DivineClientMod are installed in Builder instance."""
    os.makedirs(mods_dir, exist_ok=True)
    ensure_divine_client_mod(mods_dir)

    assets_mods_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "mods"))
    if os.path.isdir(assets_mods_dir):
        for fname in os.listdir(assets_mods_dir):
            if fname.lower().endswith(".jar"):
                src = os.path.join(assets_mods_dir, fname)
                dst = os.path.join(mods_dir, fname)
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                except Exception:
                    pass
    return True
