# Reading, listing, and toggling mods inside an instance's mods folder.
import json
import os
import zipfile


def _resolve_mods_dir(path):
    """Normalize directory to ensure we are pointing at the instance's mods folder."""
    if not path:
        return ""
    p = os.path.normpath(path)
    if os.path.basename(p).lower() == "mods":
        return p
    sub = os.path.join(p, "mods")
    if os.path.isdir(sub):
        return sub
    return sub


def read_meta(jar_path):
    """Pull name/version/description out of a Fabric/Quilt/Forge mod jar, best effort."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            if "fabric.mod.json" in names:
                raw = zf.read("fabric.mod.json").decode("utf-8", "replace")
                data = json.loads(raw)
                return {
                    "name": data.get("name") or data.get("id"),
                    "id": data.get("id", ""),
                    "version": data.get("version", ""),
                    "description": (data.get("description", "") or "").strip(),
                }
            if "quilt.mod.json" in names:
                raw = zf.read("quilt.mod.json").decode("utf-8", "replace")
                data = json.loads(raw)
                qmod = data.get("quilt_loader", {}).get("metadata", {})
                return {
                    "name": qmod.get("name") or qmod.get("id"),
                    "id": qmod.get("id", ""),
                    "version": qmod.get("version", ""),
                    "description": (qmod.get("description", "") or "").strip(),
                }
            if "mcmod.info" in names:
                raw = zf.read("mcmod.info").decode("utf-8", "replace")
                data = json.loads(raw)
                entry = data[0] if isinstance(data, list) and data else {}
                return {
                    "name": entry.get("name") or entry.get("modid"),
                    "id": entry.get("modid", ""),
                    "version": entry.get("version", ""),
                    "description": (entry.get("description", "") or "").strip(),
                }
    except Exception:
        pass
    return None


def _pretty_from_filename(filename):
    base = filename
    for ext in (".jar.disabled", ".jar"):
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    # Replace dashes/underscores with clean name formatting
    return base


def count_mods(target_dir):
    """How many mod jars are in the instance."""
    mods_dir = _resolve_mods_dir(target_dir)
    try:
        names = os.listdir(mods_dir)
    except OSError:
        return 0
    return sum(1 for n in names
               if n.lower().endswith(".jar") or n.lower().endswith(".jar.disabled"))


def list_mods(target_dir, with_meta=True):
    """Return a list of dicts describing every mod jar (enabled or disabled)."""
    mods_dir = _resolve_mods_dir(target_dir)
    result = []
    if not os.path.isdir(mods_dir):
        return result
    for filename in sorted(os.listdir(mods_dir)):
        low = filename.lower()
        if low.endswith(".jar"):
            enabled = True
        elif low.endswith(".jar.disabled"):
            enabled = False
        else:
            continue
        path = os.path.join(mods_dir, filename)
        meta = read_meta(path) if with_meta else None
        if meta and meta.get("name"):
            name = meta["name"]
            mod_id = meta.get("id", "")
            version = meta.get("version", "")
            desc = meta.get("description", "")
        else:
            name = _pretty_from_filename(filename)
            mod_id = ""
            version = ""
            desc = ""
        try:
            size_bytes = os.path.getsize(path)
            size_mb = round(size_bytes / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0

        result.append({
            "filename": filename,
            "path": path,
            "enabled": enabled,
            "name": name,
            "id": mod_id,
            "version": version,
            "description": desc,
            "size_mb": size_mb,
        })
    # Enabled first, then alphabetical by display name.
    result.sort(key=lambda m: (not m["enabled"], m["name"].lower()))
    return result


def set_enabled(target_dir, filename, enabled):
    """Flip a mod on or off by renaming between .jar and .jar.disabled."""
    mods_dir = _resolve_mods_dir(target_dir)
    src = os.path.join(mods_dir, filename)
    if not os.path.isfile(src):
        return None
    if enabled:
        if filename.endswith(".jar.disabled"):
            new = filename[:-len(".disabled")]
        else:
            return filename  # already enabled
    else:
        if filename.endswith(".jar"):
            new = filename + ".disabled"
        else:
            return filename  # already disabled
    dst = os.path.join(mods_dir, new)
    try:
        os.replace(src, dst)
        return new
    except OSError:
        return None


def delete_mod(target_dir, filename):
    mods_dir = _resolve_mods_dir(target_dir)
    path = os.path.join(mods_dir, filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False
    except OSError:
        return False


def add_mod(target_dir, source_path):
    """Copy an external .jar into the mods folder."""
    import shutil
    mods_dir = _resolve_mods_dir(target_dir)
    os.makedirs(mods_dir, exist_ok=True)
    name = os.path.basename(source_path)
    if not name.lower().endswith(".jar"):
        return None
    dst = os.path.join(mods_dir, name)
    try:
        shutil.copy2(source_path, dst)
        return name
    except OSError:
        return None
