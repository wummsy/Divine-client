# Browse and install mods from Modrinth (https://modrinth.com).
#
# This backs the in-app mod installer: search projects, list the versions that
# match an instance's Minecraft version + loader, and download the jar (plus any
# required dependencies) straight into the instance's mods folder.
import hashlib
import json
import os
import re

from . import net

API = "https://api.modrinth.com/v2"
UA = {"User-Agent": net.USER_AGENT}

# Categories worth offering as quick filters in the UI.
CATEGORIES = [
    "optimization", "utility", "adventure", "worldgen", "technology",
    "magic", "storage", "food", "decoration", "library", "management",
]


def _facets(mc_version, loader, category=None, project_type="mod"):
    facets = []
    if project_type == "plugin" or loader in ("paper", "purpur", "spigot", "bukkit"):
        facets.append(["categories:paper", "categories:spigot", "categories:bukkit", "categories:purpur", "project_type:plugin"])
    elif project_type:
        facets.append(["project_type:" + project_type])

    if loader and project_type == "mod" and loader not in ("paper", "purpur", "spigot", "bukkit", "vanilla", "none"):
        facets.append(["categories:" + loader])
    if mc_version:
        facets.append(["versions:" + mc_version])
    if category and category not in ("plugins", "all", ""):
        facets.append(["categories:" + category])
    return json.dumps(facets)


def search(query, mc_version=None, loader="fabric", category=None,
           index="relevance", limit=20, offset=0, project_type="mod"):
    """Search Modrinth. Returns (hits, total). Each hit is a dict for the UI."""
    clean_ver = None
    if mc_version:
        m = re.search(r"\d+\.\d+(\.\d+)?", str(mc_version))
        clean_ver = m.group(0) if m else str(mc_version).strip()

    params = {
        "query": query or "",
        "facets": _facets(clean_ver, loader, category, project_type),
        "index": index or "relevance",  # relevance | downloads | follows | newest | updated
        "limit": limit,
        "offset": offset,
    }
    try:
        data = net.get_json(API + "/search", params=params, ttl=180.0)
    except Exception:
        data = {}

    hits_raw = data.get("hits", [])

    # If user searched a keyword but strict version filter yielded 0 hits, retry without version constraint
    if not hits_raw and query and clean_ver:
        try:
            params["facets"] = _facets(None, loader if project_type == "mod" else None, category, project_type)
            fallback_data = net.get_json(API + "/search", params=params, ttl=180.0)
            hits_raw = fallback_data.get("hits", [])
            data["total_hits"] = fallback_data.get("total_hits", len(hits_raw))
        except Exception:
            pass

    hits = []
    for h in hits_raw:
        hits.append({
            "slug": h.get("slug"),
            "project_id": h.get("project_id"),
            "title": h.get("title"),
            "description": h.get("description", ""),
            "author": h.get("author", ""),
            "downloads": h.get("downloads", 0),
            "follows": h.get("follows", 0),
            "icon_url": h.get("icon_url"),
            "categories": h.get("display_categories") or h.get("categories", []),
        })
    return hits, data.get("total_hits", len(hits))


def get_versions(slug_or_id, mc_version=None, loader="fabric"):
    """List downloadable versions of a project for this MC version + loader.

    Pass loader=None (e.g. for resource packs) to skip the loader filter.
    """
    clean_ver = None
    if mc_version:
        m = re.search(r"\d+\.\d+(\.\d+)?", str(mc_version))
        clean_ver = m.group(0) if m else str(mc_version).strip()

    params = {}
    if loader and loader not in ("vanilla", "none"):
        params["loaders"] = json.dumps([loader])
    if clean_ver:
        params["game_versions"] = json.dumps([clean_ver])

    try:
        data = net.get_json(API + "/project/" + slug_or_id + "/version",
                            params=params, ttl=600.0)
    except Exception:
        data = []

    # If no versions found for exact version, try loader-only
    if not data and clean_ver:
        params.pop("game_versions", None)
        try:
            data = net.get_json(API + "/project/" + slug_or_id + "/version",
                                params=params, ttl=600.0)
        except Exception:
            data = []

    # If still no data and loader was set, try without loader
    if not data and loader:
        try:
            data = net.get_json(API + "/project/" + slug_or_id + "/version", ttl=600.0)
        except Exception:
            data = []

    out = []
    if isinstance(data, list):
        for v in data:
            primary = None
            for f in v.get("files", []):
                if f.get("primary"):
                    primary = f
                    break
            if primary is None and v.get("files"):
                primary = v["files"][0]
            if primary is None:
                continue
            out.append({
                "id": v["id"],
                "project_id": v["project_id"],
                "name": v.get("name", ""),
                "version_number": v.get("version_number", ""),
                "version_type": v.get("version_type", "release"),  # release/beta/alpha
                "game_versions": v.get("game_versions", []),
                "loaders": v.get("loaders", []),
                "downloads": v.get("downloads", 0),
                "date_published": v.get("date_published", ""),
                "filename": primary["filename"],
                "url": primary["url"],
                "size": primary.get("size", 0),
                "sha1": (primary.get("hashes") or {}).get("sha1"),
                "dependencies": v.get("dependencies", []),
            })
    return out


# Alias for compatibility
get_project_versions = get_versions


def get_project(id_or_slug):
    """Fetch a single project's public info (title, description, icon, page url)."""
    p = net.get_json(API + "/project/" + id_or_slug, ttl=net.PROJECT_TTL)
    slug = p.get("slug") or id_or_slug
    ptype = p.get("project_type", "mod")
    return {
        "project_id": p.get("id"),
        "slug": slug,
        "title": p.get("title", ""),
        "description": p.get("description", ""),
        "icon_url": p.get("icon_url"),
        "project_type": ptype,
        "url": "https://modrinth.com/%s/%s" % (ptype, slug),
    }


def lookup_by_hash(sha1):
    """Identify an installed file on Modrinth from its SHA1.

    Returns the project info dict (see get_project) with an added ``version``
    number, or None if the file isn't a known Modrinth release. This is how a
    locally-installed mod/pack gets matched back to its Modrinth page even when
    it was dropped in by hand.
    """
    if not sha1:
        return None
    try:
        ver = net.get_json(API + "/version_file/" + sha1,
                           params={"algorithm": "sha1"})
        pid = ver.get("project_id")
        if not pid:
            return None
        info = get_project(pid)
        info["version"] = ver.get("version_number", "")
        return info
    except Exception:
        return None


def _sha1_of(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _already_have(mods_dir, filename, sha1):
    """True if this exact file (by name, or by hash) is already installed."""
    for cand in (filename, filename + ".disabled"):
        p = os.path.join(mods_dir, cand)
        if os.path.exists(p):
            if not sha1:
                return True
            if _sha1_of(p) == sha1:
                return True
    return False


def _mod_stem(filename):
    """Normalized mod identifier from a jar filename to prevent duplicates."""
    base = os.path.basename(filename or "").lower()
    if base.endswith(".jar"):
        base = base[:-4]
    at = re.search(r"\d", base)
    if at:
        base = base[:at.start()]
    parts = [x for x in re.split(r"[-_ +.]+", base) if x]
    loader_words = ("fabric", "quilt", "neoforge", "forge", "mc", "beta", "alpha", "release", "devbuild", "universal")
    while parts and parts[-1] in loader_words:
        parts.pop()
    return "-".join(parts) if parts else base.strip("-_ ")


def _clean_duplicate_jars(mods_dir, target_stem, exclude_filename=None):
    """Remove older or duplicate jar versions of the same mod to prevent crash on launch."""
    if not os.path.isdir(mods_dir) or not target_stem:
        return []
    removed = []
    try:
        for fname in os.listdir(mods_dir):
            if not fname.lower().endswith((".jar", ".jar.disabled")):
                continue
            if exclude_filename and fname.lower() == exclude_filename.lower():
                continue
            if _mod_stem(fname) == target_stem:
                full_path = os.path.join(mods_dir, fname)
                try:
                    os.remove(full_path)
                    removed.append(fname)
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def download_version(version, mods_dir, progress=None):
    """Download one resolved version dict into mods_dir without duplicate jars.

    Returns the filename or None.
    """
    os.makedirs(mods_dir, exist_ok=True)
    filename = version["filename"]
    dest = os.path.join(mods_dir, filename)
    target_stem = _mod_stem(filename)

    # If the exact same file is already present with matching SHA1, skip re-download
    if _already_have(mods_dir, filename, version.get("sha1")):
        # Still clean any other conflicting versions with different names
        _clean_duplicate_jars(mods_dir, target_stem, exclude_filename=filename)
        return filename

    # Clean out any older versions of the same mod before downloading the new one
    _clean_duplicate_jars(mods_dir, target_stem, exclude_filename=filename)

    tmp = dest + ".part"
    sha = hashlib.sha1()
    try:
        with net.session().get(version["url"], stream=True,
                               timeout=net.FILE_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0)) or version.get("size", 0)
            done = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
        if version.get("sha1") and sha.hexdigest() != version["sha1"]:
            os.remove(tmp)
            raise RuntimeError("Download was corrupted, please try again.")
        os.replace(tmp, dest)
        return filename
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(str(e))


def _best_version_for_project(project_id, mc_version, loader):
    """Pick the single best compatible version for this project, MC version, and loader.

    Prefers official stable releases over betas/alphas and orders by newest release number/date.
    """
    versions = get_versions(project_id, mc_version, loader)
    if not versions and loader:
        # Fall back to version list without loader constraint if loader-agnostic
        versions = get_versions(project_id, mc_version, None)
    if not versions:
        return None

    # Filter to versions that explicitly declare support for the target mc_version
    matched = []
    for v in versions:
        gv = v.get("game_versions") or []
        if not mc_version or mc_version in gv:
            matched.append(v)
    candidates = matched if matched else versions

    # Separate stable releases from pre-releases
    releases = [v for v in candidates if v.get("version_type") == "release"]
    pool = releases if releases else candidates

    # Sort descending by semver numbers and publish date
    pool.sort(key=lambda v: (
        [int(x) for x in re.findall(r"\d+", v.get("version_number") or "")],
        v.get("date_published") or ""
    ), reverse=True)

    return pool[0] if pool else None


def install_with_dependencies(version, mods_dir, mc_version, loader="fabric", progress=None):
    """Install a version plus its required dependencies (including nested). Returns (installed, skipped)."""
    installed = []
    skipped = []
    seen = set()

    def note(text):
        if progress:
            progress(text, None)

    def _process_version(v):
        if not v or not v.get("filename"):
            return
        fname = v["filename"]
        note("Downloading " + fname)
        try:
            name = download_version(v, mods_dir,
                                    progress=lambda f: progress(None, f) if progress else None)
            if name and name not in installed:
                installed.append(name)
        except Exception:
            skipped.append(fname)
            return

        for dep in v.get("dependencies", []):
            if dep.get("dependency_type") != "required":
                continue
            dep_pid = dep.get("project_id")
            if not dep_pid or dep_pid in seen:
                continue
            seen.add(dep_pid)

            note("Resolving dependency...")
            dv = None
            if dep.get("version_id"):
                try:
                    raw = net.get_json(API + "/version/" + dep["version_id"])
                    files = raw.get("files", [])
                    primary = next((f for f in files if f.get("primary")),
                                   files[0] if files else None)
                    if primary:
                        dv = {
                            "filename": primary["filename"],
                            "url": primary["url"],
                            "size": primary.get("size", 0),
                            "sha1": (primary.get("hashes") or {}).get("sha1"),
                            "dependencies": raw.get("dependencies", []),
                        }
                except Exception:
                    dv = None
            if dv is None:
                dv = _best_version_for_project(dep_pid, mc_version, loader)
            if dv:
                _process_version(dv)

    _process_version(version)
    if progress:
        progress("Done", 1.0)
    return installed, skipped


def install_file(version, target_dir, progress=None):
    """Download a resolved version's primary file into target_dir (no deps).

    Used for resource packs, which are simply dropped into resourcepacks/.
    Returns the filename, or None if it was already present.
    """
    os.makedirs(target_dir, exist_ok=True)
    if _already_have(target_dir, version["filename"], version.get("sha1")):
        return None
    return download_version(version, target_dir, progress=progress)


def icon_path(url, cache_dir):
    """Where this icon would live on disk (no download, no network)."""
    return net.cached_path(url, cache_dir)


def fetch_icon(url, cache_dir):
    """Local path for a project icon, downloading it if we do not have it yet.

    This blocks - call it from a worker (ui/imagedesk.py does), never while a Tk
    widget is being built. Two threads asking for the same icon at once share one
    download (net.download coalesces by destination).
    """
    if not url:
        return None
    return net.download(url, icon_path(url, cache_dir), timeout=(6.0, 20.0))


# Repeat searches, sort flips and reopening a version list used to go back to the
# network every time; they are read-only, so remember them for a while. A failed
# request falls back to the stale value, which is far better than "Search failed"
# when Modrinth hiccups.
search = net.cached(search, 180.0)
get_versions = net.cached(get_versions, 600.0)
get_project_versions = get_versions
get_project = net.cached(get_project, net.PROJECT_TTL)
lookup_by_hash = net.cached(lookup_by_hash, 900.0)
