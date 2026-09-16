"""Instance management.

An *instance* is a named, isolated Minecraft configuration: its own game
directory (saves, resource packs, mods, options.txt), tied to a specific
Minecraft version and loader (vanilla or Fabric). Multiple instances can run
at the same time.
"""
import json
import os
import re
import shutil

from .. import paths


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "instance"


class Instance:
    def __init__(self, data):
        self.data = data

    @property
    def id(self):
        return self.data["id"]

    @property
    def name(self):
        return self.data["name"]

    @property
    def mc_version(self):
        return self.data["mc_version"]

    @property
    def loader(self):
        return self.data.get("loader", "vanilla")

    @property
    def loader_version(self):
        # The actual launchable version id (e.g. "fabric-loader-0.15.7-1.20.4")
        return self.data.get("loader_version") or self.data["mc_version"]

    @property
    def icon(self):
        return self.data.get("icon") or self.data.get("custom_icon") or "grass"

    @property
    def custom_icon(self):
        return self.data.get("custom_icon") or self.data.get("icon") or ""

    @property
    def game_dir(self):
        custom = self.data.get("custom_game_dir")
        if custom and os.path.isabs(custom):
            d = custom
        else:
            d = os.path.join(paths.INSTANCES_DIR, self.id)
        os.makedirs(d, exist_ok=True)
        os.makedirs(os.path.join(d, "mods"), exist_ok=True)
        return d

    def to_dict(self):
        return self.data


class InstanceManager:
    def __init__(self):
        paths.ensure_dirs()
        self.instances = []
        self.load()

    @property
    def index_file(self):
        # Resolved on demand so it follows the chosen game-files location.
        return os.path.join(paths.INSTANCES_DIR, "instances.json")

    def load(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.instances = [Instance(d) for d in raw.get("instances", [])]
            except (json.JSONDecodeError, OSError):
                self.instances = []
        if not self.instances:
            self._ensure_defaults()
        return self

    def _ensure_defaults(self):
        paths.ensure_dirs()
        default_defs = [
            {
                "id": "divine-fabric-ultra-1-21-11",
                "name": "Divine Client 1.21.11 (Ultra Performance)",
                "mc_version": "1.21.11",
                "loader": "fabric",
                "loader_version": "0.16.10",
                "ram_mb": 4096,
                "icon": "lightning",
                "mods_count": 48,
                "is_divine_exclusive": True
            },
            {
                "id": "divine-builder-cinematic-studio",
                "name": "Builder Studio 1.21.11 (Axiom + WorldEdit + Flashback)",
                "mc_version": "1.21.11",
                "loader": "fabric",
                "loader_version": "0.16.10",
                "ram_mb": 6144,
                "icon": "cube",
                "mods_count": 5
            },
            {
                "id": "divine-bedwars-pvp-1-8-9",
                "name": "Divine Bedwars PvP 1.8.9",
                "mc_version": "1.8.9",
                "loader": "forge",
                "loader_version": "11.15.1.2318",
                "ram_mb": 2048,
                "icon": "sword",
                "mods_count": 16
            },
            {
                "id": "divine-vanilla-survival",
                "name": "Divine Vanilla Survival 1.21.4",
                "mc_version": "1.21.4",
                "loader": "vanilla",
                "loader_version": None,
                "ram_mb": 3072,
                "icon": "grass",
                "mods_count": 0
            },
            {
                "id": "divine-multiplayer-smp",
                "name": "Divine Multiplayer SMP 1.21.4",
                "mc_version": "1.21.4",
                "loader": "fabric",
                "loader_version": "0.16.9",
                "ram_mb": 4096,
                "icon": "server",
                "mods_count": 8
            }
        ]
        self.instances = [Instance(d) for d in default_defs]
        try:
            self.save()
        except Exception:
            pass

    def save(self):
        paths.ensure_dirs()
        tmp = self.index_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"instances": [i.to_dict() for i in self.instances]}, f, indent=2)
        shutil.move(tmp, self.index_file)

    def get(self, instance_id):
        for i in self.instances:
            if i.id == instance_id:
                return i
        return None

    def create(self, name, mc_version, loader="vanilla", loader_version=None, icon="grass",
               extra=None):
        base = _slugify(name)
        iid = base
        n = 1
        existing = {i.id for i in self.instances}
        while iid in existing:
            n += 1
            iid = f"{base}-{n}"
        data = {
            "id": iid,
            "name": name,
            "mc_version": mc_version,
            "loader": loader,
            "loader_version": loader_version,
            "icon": icon,
        }
        # Anything else a caller knows - where a modpack came from, what the pack's own
        # version was - rides along in instances.json. The launcher ignores what it does not
        # understand, so an import never has to throw information away.
        if extra:
            data.update(extra)
        inst = Instance(data)
        self.instances.append(inst)
        self.save()

        # If creating a Fabric instance, auto-install DivineClientMod-1.0.0.jar
        if loader == "fabric":
            try:
                from . import mods as mods_mod
                mods_mod.ensure_divine_client_mod(os.path.join(inst.game_dir, "mods"))
            except Exception:
                pass

        return inst

    # ------------------------------------------------------------------ import
    #: what makes a folder "a Minecraft instance" enough to be worth offering
    MARKERS = ("mods", "saves", "resourcepacks", "options.txt", "version.json",
               "instance.json", "instance.cfg", "pack.toml")
    #: things that live in the launcher, not in the instance - copying them wastes minutes
    SKIP_TOP = ("versions", "runtime", "logs", "launcher_profiles.json", ".cache")

    def looks_like_instance(self, folder):
        """True when ``folder`` has anything a Minecraft instance keeps."""
        if not folder or not os.path.isdir(folder):
            return False
        try:
            names = set(os.listdir(folder))
        except OSError:
            return False
        return bool(names & set(self.MARKERS))

    def detect(self, folder):
        """``{"name", "mc_version", "loader", "loader_version"}`` read from the folder.

        MultiMC/Prism writes ``instance.cfg``, AtLauncher writes ``instance.json``; a bare
        ``.minecraft``-style folder has neither, so the name falls back to the folder and the
        version is whatever ``versions/`` holds. Anything undetected comes back empty and the
        UI asks for it rather than guessing a version that will not launch.
        """
        out = {"name": os.path.basename(os.path.normpath(folder)) or "Imported",
               "mc_version": "", "loader": "", "loader_version": ""}
        cfg = os.path.join(folder, "instance.cfg")
        if os.path.isfile(cfg):
            try:
                with open(cfg, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        key, sep, val = line.partition("=")
                        if not sep:
                            continue
                        key, val = key.strip().lower(), val.strip()
                        if key in ("name", "instancename") and val:
                            out["name"] = val
                        elif key in ("intendedversion", "minecraftversion") and val:
                            out["mc_version"] = val
                        elif key == "loader" and val and val.lower() != "none":
                            out["loader"] = val.lower()
                        elif key in ("overrideversion", "loaderversion") and val:
                            out["loader_version"] = val
            except OSError:
                pass
        js = os.path.join(folder, "instance.json")
        if os.path.isfile(js):
            try:
                with open(js, encoding="utf-8", errors="replace") as f:
                    raw = json.load(f)
                out["name"] = str(raw.get("name") or out["name"])
                prof = raw.get("javaSettings") or {}
                out["mc_version"] = str(raw.get("runtimeVersion") or prof.get("version")
                                        or out["mc_version"])
                for comp in (raw.get("components") or []):
                    ident = str((comp or {}).get("id") or "")
                    if ident.startswith("net.fabricmc.loader") or "fabric" in ident:
                        out["loader"], _, out["loader_version"] = ("fabric", "",
                                                                   ident.rpartition("-")[2])
                    elif "quilt" in ident:
                        out["loader"], _, out["loader_version"] = ("quilt", "",
                                                                    ident.rpartition("-")[2])
            except (OSError, ValueError):
                pass
        if not out["mc_version"]:
            vdir = os.path.join(folder, "versions")
            if os.path.isdir(vdir):
                try:
                    ids = sorted(os.listdir(vdir), reverse=True)
                    out["mc_version"] = ids[0] if ids else ""
                except OSError:
                    pass
        if os.path.isdir(os.path.join(folder, "mods")):
            try:
                jars = [n for n in os.listdir(os.path.join(folder, "mods"))
                        if n.lower().endswith(".jar")]
            except OSError:
                jars = []
            if jars and not out["loader"]:
                out["loader"] = "fabric"
        return out

    def import_from(self, source, name=None, mc_version=None, loader=None,
                    loader_version=None, move=False, progress=None):
        """Register an existing folder (or a zip of one) as an instance.

        Returns ``(instance, notes)``. A zip is unpacked into a scratch folder first, so a
        pack of the ``DivineClient/``-wrapped shape people zip by hand works the same as a
        folder. Nothing is deleted from ``source`` unless ``move`` is asked for explicitly.
        """
        from .. import paths
        source = os.path.abspath(str(source or ""))
        if not os.path.exists(source):
            raise ValueError("there is nothing at %s" % source)
        scratch = None
        folder = source
        if os.path.isfile(source):
            if not source.lower().endswith((".zip", ".mrpack")):
                raise ValueError("import takes a folder or a zip archive")
            import tempfile
            from .zipio import safe_extract
            scratch = tempfile.mkdtemp(prefix="import-", dir=paths.DATA_DIR)
            tree = os.path.join(scratch, "tree")
            safe_extract(source, tree, progress=progress and
                         (lambda i, n, rel: progress(i, n, rel)))
            # a zip of a folder keeps one level: "MyInstance/" wrapping everything
            folder = tree
            try:
                kids = [k for k in os.listdir(tree) if not k.startswith(".")]
                if len(kids) == 1 and os.path.isdir(os.path.join(tree, kids[0])):
                    folder = os.path.join(tree, kids[0])
            except OSError:
                pass
        if not self.looks_like_instance(folder) and not os.path.isdir(
                os.path.join(folder, "mods")):
            # one level down: people zip the parent of the instance more often than not
            try:
                kids = [os.path.join(folder, k) for k in sorted(os.listdir(folder))]
            except OSError:
                kids = []
            pick = next((k for k in kids if os.path.isdir(k)
                         and self.looks_like_instance(k)), None)
            if not pick:
                raise ValueError("that folder has no mods, saves or options.txt, so it is "
                                 "not a Minecraft instance")
            folder = pick

        found = self.detect(folder)
        mc_version = mc_version or found.get("mc_version") or ""
        name = name or found.get("name") or "Imported"
        loader = (loader or found.get("loader") or "").strip().lower() or "vanilla"
        if loader not in ("vanilla", "fabric", "quilt", "forge", "neoforge"):
            loader = "vanilla"
        loader_version = loader_version or found.get("loader_version") or None
        if loader == "vanilla":
            loader_version = None
        if not mc_version:
            raise ValueError("that folder does not say which Minecraft version it is - "
                             "pick one and import again")

        inst = self.create(name, mc_version, loader=loader, loader_version=loader_version,
                           extra={"imported_from": os.path.basename(folder) or "import"})
        dest = inst.game_dir
        notes = {"copied": 0, "skipped": 0, "failed": []}
        src_mods = os.path.join(folder, "mods")
        if os.path.isdir(src_mods) and os.path.isdir(dest):
            pass   # copied below with everything else
        for entry in sorted(_top_level(folder)):
            if entry in self.SKIP_TOP or entry.startswith("."):
                notes["skipped"] += 1
                continue
            a = os.path.join(folder, entry)
            b = os.path.join(dest, entry)
            try:
                if os.path.isdir(a):
                    shutil.copytree(a, b, dirs_exist_ok=True)
                else:
                    shutil.copy2(a, b)
                notes["copied"] += 1
            except (OSError, shutil.Error):
                notes["failed"].append(entry)
        os.makedirs(os.path.join(dest, "mods"), exist_ok=True)
        if move and not scratch:
            try:
                shutil.rmtree(source, ignore_errors=True)
                notes["moved"] = True
            except OSError:
                notes["moved"] = False
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
        if progress:
            try:
                progress(1, 1, "Imported %s" % inst.name)
            except Exception:
                pass
        return inst, notes



    def update(self, instance_id, name=None, mc_version=None, loader=None,
               loader_version=None, custom_game_dir=None):
        """Change an existing instance's editable fields. The id (and thus the
        game directory) is kept stable so saves and mods are never orphaned."""
        inst = self.get(instance_id)
        if not inst:
            return None
        if name is not None:
            inst.data["name"] = name
        if mc_version is not None:
            inst.data["mc_version"] = mc_version
        if custom_game_dir is not None:
            inst.data["custom_game_dir"] = custom_game_dir if custom_game_dir.strip() else None
        if loader is not None:
            inst.data["loader"] = loader
            # loader_version is derived from the mc_version for our loaders, so
            # clear any stale pin when the loader or version changes.
            inst.data["loader_version"] = loader_version
        elif loader_version is not None:
            inst.data["loader_version"] = loader_version
        elif mc_version is not None:
            inst.data["loader_version"] = None
        self.save()
        return inst

    def delete(self, instance_id, remove_files=True):
        inst = self.get(instance_id)
        if not inst:
            return
        self.instances = [i for i in self.instances if i.id != instance_id]
        self.save()
        if remove_files:
            d = os.path.join(paths.INSTANCES_DIR, instance_id)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            sdir = os.path.join(paths.get_game_dir(), "servers", instance_id)
            if os.path.isdir(sdir):
                shutil.rmtree(sdir, ignore_errors=True)


def _top_level(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []
