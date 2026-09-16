"""Modpacks: find one on Modrinth and install it as an instance.

A modpack is a ``.mrpack`` - a zip whose root holds ``modrinth.index.json``:

    { "name": "...", "version": "1.2",
      "minecraft": {"version": "1.20.4",
                    "modLoaders": [{"id": "fabric-0.15.7", "primary": true}]},
      "files": [{"path": "mods/x.jar", "downloads": ["https://..."],
                 "hashes": {"sha1": "..."}, "fileSize": 123,
                 "envs": {"client": "required", "server": "unsupported"}}],
      "overrides": "overrides" }

So installing one is three steps, and none of them are special: make an instance with the
version and loader the manifest asks for, fetch each client file into the paths it names,
and copy the overrides folder over the top. That is why this module is allowed to write an
instance directly: after it, the instance is an ordinary one - mods, worlds, settings and
the mod browser all work on it exactly as on a hand-made instance.

Two rules kept on purpose:

* a file whose ``envs.client`` is ``unsupported`` is skipped, and one whose sha1 does not
  match is re-downloaded once and then reported, not silently kept;
* anything that failed is *listed*, not thrown. A pack with three dead mirrors is still a
  playable pack, and "installed 148 of 151 files (3 failed)" is something a person can act
  on. Launch is never blocked by this.
"""
import hashlib
import json
import os
import shutil
import tempfile

from . import modrinth, net
from .zipio import safe_extract

INDEX = "modrinth.index.json"
CLIENT_ONLY = ("client-only", "clientonly")
SKIP = ("unsupported",)


def search(query="", mc_version=None, limit=20, offset=0, index="relevance"):
    """Modrinth modpack search. Returns ``(hits, total)`` like ``modrinth.search``."""
    return modrinth.search(query, mc_version=mc_version, loader=None, index=index,
                           limit=limit, offset=offset, project_type="modpack")


def mrpack_versions(slug, mc_version=None):
    """The downloadable ``.mrpack`` files for a project, newest listed first."""
    out = []
    for v in modrinth.get_versions(slug, mc_version=mc_version, loader=None):
        name = str(v.get("filename") or "")
        if name.lower().endswith(".mrpack") or name.lower().endswith(".zip"):
            out.append(v)
    return out or modrinth.get_versions(slug, mc_version=mc_version, loader=None)


def download_mrpack(version, dest_dir=None, progress=None):
    """Fetch the pack archive itself. Returns the path, or None if it could not be had."""
    base = dest_dir or os.path.join(_scratch(), "downloads")
    os.makedirs(base, exist_ok=True)
    name = str(version.get("filename") or "pack.mrpack").replace("/", "_")
    dest = os.path.join(base, name)
    if progress:
        try:
            progress(0, 1, "Downloading %s" % name)
        except Exception:
            pass
    return net.download(str(version.get("url") or ""), dest,
                        expected_sha256=None)


def _scratch():
    from .. import paths
    d = os.path.join(paths.DATA_DIR, "modpacks")
    os.makedirs(d, exist_ok=True)
    return d


def _sha1_of(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_index(mrpack):
    """The manifest of a ``.mrpack``, as a dict. Raises ``ValueError`` if it has none."""
    import zipfile
    try:
        with zipfile.ZipFile(mrpack) as z:
            raw = None
            for info in z.infolist():
                name = str(info.filename).replace("\\", "/").lstrip("/")
                if name == INDEX or name.endswith("/" + INDEX):
                    raw = z.read(info)
                    break
            if raw is None:
                raise ValueError("that archive has no %s, so it is not a modpack" % INDEX)
            return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        if str(e).startswith("that archive"):
            raise
        raise ValueError("the modpack manifest is not readable JSON")


def plan(meta):
    """``(mc_version, loader, loader_version, files, overrides_dir)`` from a manifest."""
    mc = ""
    loader, loader_version = "vanilla", None
    mine = meta.get("minecraft") or {}
    mc = str(mine.get("version") or (meta.get("dependencies") or {}).get("minecraft") or "")
    for entry in (mine.get("modLoaders") or []):
        ident = str((entry or {}).get("id") or "")
        if not ident:
            continue
        name, _, ver = ident.rpartition("-")
        if name in ("fabric", "quilt", "forge", "neoForge", "neoforge"):
            loader = "neoforge" if name.lower().startswith("neo") else name
            loader_version = ver or None
        break
    files = []
    for f in (meta.get("files") or []):
        path = str(f.get("path") or "").replace("\\", "/").lstrip("/")
        envs = f.get("envs") or {}
        client = str(envs.get("client") or "required").lower()
        url = (f.get("downloads") or [""])[0]
        if not path or not url or "/.." in ("/" + path):
            continue
        if client in SKIP:
            continue
        files.append({"path": path, "url": url, "sha1": (f.get("hashes") or {}).get("sha1"),
                      "size": int(f.get("fileSize") or 0), "client": client in CLIENT_ONLY})
    return {
        "name": str(meta.get("name") or "Modpack"),
        "pack_version": str(meta.get("version") or ""),
        "mc_version": mc,
        "loader": loader,
        "loader_version": loader_version,
        "files": files,
        "overrides": str(meta.get("overrides") or "overrides"),
    }


def install(mrpack, manager, name=None, progress=None, keep=False):
    """Turn a ``.mrpack`` into a real instance. Returns ``(instance, report)``.

    ``progress(done, total, text, extra_info)`` is called for the archive and for each file, so the UI
    can show a progress bar with downloaded files count, speed, and real-time ETA.
    """
    import time
    start_time = time.time()
    done_bytes = 0

    def note(done, total, text, extra_info=None):
        if progress:
            try:
                import inspect
                sig = inspect.signature(progress)
                params_len = len(sig.parameters)
                if params_len >= 4 or "extra_info" in sig.parameters or "info" in sig.parameters:
                    progress(done, total, text, extra_info or {})
                elif params_len == 1:
                    info = {
                        "done_files": done,
                        "total_files": total,
                        "text": text,
                        **(extra_info or {})
                    }
                    progress(info)
                else:
                    progress(done, total, text)
            except Exception:
                try:
                    progress(done, total, text)
                except Exception:
                    pass

    work = tempfile.mkdtemp(prefix="mrpack-", dir=_scratch())
    try:
        note(0, 1, "Reading the pack manifest", {"status": "reading_manifest", "percentage": 0})
        target = os.path.join(work, "tree")
        safe_extract(mrpack, target, strip_wrapper=False)
        meta_path = None
        for root, _dirs, files in os.walk(target):
            if INDEX in files:
                meta_path = os.path.join(root, INDEX)
                break
        if not meta_path:
            raise ValueError("that archive has no %s, so it is not a modpack" % INDEX)
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        spec = plan(meta)
        if not spec["mc_version"]:
            raise ValueError("the pack does not say which Minecraft version it is for")

        note(1, 1, "Creating %s" % spec["name"], {"status": "creating_instance", "percentage": 2})
        inst = manager.create(name or spec["name"], spec["mc_version"],
                              loader=spec["loader"], loader_version=spec["loader_version"],
                              extra={"modpack": {"project": spec["name"],
                                                 "pack_version": spec["pack_version"]}})
        game = inst.game_dir
        report = {"installed": 0, "skipped": 0, "failed": [], "total_files": len(spec["files"])}

        total_files = max(1, len(spec["files"]))
        total_bytes = sum(int(entry.get("size") or 0) for entry in spec["files"])
        done_bytes = 0
        start_time = time.time()

        for i, entry in enumerate(spec["files"], start=1):
            dest = os.path.join(game, *entry["path"].split("/"))
            file_name = os.path.basename(entry["path"])
            file_size = int(entry.get("size") or 0)

            elapsed = max(0.05, time.time() - start_time)
            speed_bps = done_bytes / elapsed
            rem_bytes = max(0, total_bytes - done_bytes)
            eta_seconds = int(rem_bytes / max(1024.0, speed_bps)) if total_bytes > 0 and speed_bps > 0 else 0
            pct = round((done_bytes / max(1, total_bytes)) * 100, 1) if total_bytes > 0 else round(((i - 1) / total_files) * 100, 1)

            extra_info = {
                "current_file": file_name,
                "done_files": i - 1,
                "total_files": total_files,
                "done_bytes": done_bytes,
                "total_bytes": total_bytes,
                "speed_bps": speed_bps,
                "eta_seconds": eta_seconds,
                "percentage": pct,
                "status": "downloading_files"
            }

            note(i - 1, total_files, "%s of %s files (%s%%)  \u00b7  %s"
                 % (i - 1, total_files, pct, file_name), extra_info=extra_info)

            got = _fetch(entry["url"], dest, entry.get("sha1"))
            done_bytes += file_size

            if got:
                report["installed"] += 1
            elif os.path.isfile(dest):
                report["skipped"] += 1
            else:
                report["failed"].append(entry["path"])

        note(total_files, total_files, "Copying the pack's settings and files", extra_info={
            "current_file": "overrides",
            "done_files": total_files,
            "total_files": total_files,
            "done_bytes": total_bytes,
            "total_bytes": total_bytes,
            "speed_bps": 0,
            "eta_seconds": 0,
            "percentage": 100,
            "status": "extracting_overrides"
        })
        report["overrides"] = _copy_overrides(target, meta_path, spec["overrides"], game)

        if report["failed"]:
            note(total_files, total_files, "Installed %d of %d files (%d failed)"
                 % (report["installed"], total_files, len(report["failed"])), extra_info={
                "done_files": total_files, "total_files": total_files, "percentage": 100, "status": "completed"
            })
        else:
            note(total_files, total_files, "Installed %d files" % report["installed"], extra_info={
                "done_files": total_files, "total_files": total_files, "percentage": 100, "status": "completed"
            })
        return inst, report
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _fetch(url, dest, sha1=None):
    """One file from the manifest: download it, verify it once, and never keep a bad copy."""
    for attempt in (0, 1):
        got = net.download(url, dest)
        if not got or not os.path.isfile(dest):
            continue
        if not sha1:
            return True
        try:
            if _sha1_of(dest).lower() == str(sha1).lower():
                return True
        except OSError:
            return False
        try:
            os.remove(dest)          # the mirror served something else; try once more
        except OSError:
            return False
    return False


def _copy_overrides(tree, meta_path, folder, game_dir):
    """Copy ``overrides/`` (and ``client-overrides/``, which wins) over the instance.

    Only files whose names stay inside the instance folder are written, and nothing that is
    already there is deleted: the pack ships a ``pack.mcmeta`` and an options file, not a
    license to wipe a person's saves.
    """
    written = 0
    root = os.path.normpath(game_dir)
    base = os.path.dirname(meta_path)          # where the manifest sat, not the zip root
    for name in (folder, "client-overrides"):
        src = os.path.join(base, str(name or ""))
        if not name or not os.path.isdir(src):
            continue
        for sub, _dirs, files in os.walk(src):
            for f in files:
                rel = os.path.relpath(os.path.join(sub, f), src).replace(os.sep, "/")
                if "/.." in ("/" + rel) or rel.startswith("../"):
                    continue
                out = os.path.normpath(os.path.join(root, rel))
                if not out.startswith(root + os.sep):
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                try:
                    shutil.copy2(os.path.join(sub, f), out)
                    written += 1
                except OSError:
                    continue
    return written
