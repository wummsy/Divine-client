"""Dedicated Server Management.

Dedicated servers are standalone headless Minecraft server environments
(PaperMC, Purpur, Fabric, Forge, NeoForge, or Vanilla) with their own dedicated
directories, server.properties, eula.txt, plugins/mods, worlds, and tunneling.

Dedicated servers are completely separate from client game instances.
"""
import json
import os
import re
import shutil
import time

from .. import paths


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "server").strip().lower()).strip("-")
    return slug or "dedicated-server"


class DedicatedServer:
    def __init__(self, data):
        self.data = dict(data)

    @property
    def id(self):
        return self.data.get("id") or "server"

    @property
    def name(self):
        return self.data.get("name") or "Dedicated Server"

    @property
    def mc_version(self):
        return self.data.get("mc_version") or "1.21.1"

    @property
    def loader(self):
        return (self.data.get("loader") or "paper").lower()

    @property
    def loader_version(self):
        return self.data.get("loader_version") or None

    @property
    def ram_mb(self):
        try:
            return int(self.data.get("ram_mb", 2048))
        except (ValueError, TypeError):
            return 2048

    @property
    def port(self):
        try:
            return int(self.data.get("server_port") or self.data.get("port") or 25565)
        except (ValueError, TypeError):
            return 25565

    @property
    def server_port(self):
        return self.port

    @property
    def static_domain(self):
        return self.data.get("static_domain") or ""

    @property
    def bore_static_port(self):
        return self.data.get("bore_static_port") or None

    @property
    def playit_secret(self):
        return self.data.get("playit_secret") or ""

    @property
    def tunnel_provider(self):
        return self.data.get("tunnel_provider") or "bore"

    @property
    def icon(self):
        return self.data.get("icon") or self.data.get("custom_icon") or "/assets/icon_mono.png"

    @property
    def custom_icon(self):
        return self.icon

    @property
    def server_dir(self):
        return os.path.join(paths.get_game_dir(), "servers", self.id)

    @property
    def game_dir(self):
        """Compatibility property matching instance protocol for server sessions."""
        return self.server_dir

    def to_dict(self):
        out = dict(self.data)
        out["id"] = self.id
        out["instance_id"] = self.id  # Compatibility alias
        out["name"] = self.name
        out["mc_version"] = self.mc_version
        out["loader"] = self.loader
        out["ram_mb"] = self.ram_mb
        out["port"] = self.port
        out["server_port"] = self.port
        out["static_domain"] = self.static_domain
        out["bore_static_port"] = self.bore_static_port
        out["playit_secret"] = self.playit_secret
        out["tunnel_provider"] = self.tunnel_provider
        out["icon"] = self.icon
        out["custom_icon"] = self.custom_icon
        out["server_dir"] = self.server_dir
        out["is_server"] = True
        return out


class ServerManager:
    def __init__(self):
        paths.ensure_dirs()
        self.servers = []
        self.load()

    @property
    def servers_root(self):
        d = os.path.join(paths.get_game_dir(), "servers")
        os.makedirs(d, exist_ok=True)
        return d

    @property
    def index_file(self):
        return os.path.join(self.servers_root, "servers.json")

    def load(self):
        paths.ensure_dirs()
        self.servers = []
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                server_list = raw.get("servers", [])
                for d in server_list:
                    if isinstance(d, dict) and d.get("id"):
                        srv = DedicatedServer(d)
                        self.servers.append(srv)
            except (json.JSONDecodeError, OSError):
                self.servers = []
        return self

    def save(self):
        paths.ensure_dirs()
        os.makedirs(self.servers_root, exist_ok=True)
        tmp = self.index_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"servers": [s.to_dict() for s in self.servers]}, f, indent=2)
        shutil.move(tmp, self.index_file)

    def get(self, server_id):
        for s in self.servers:
            if s.id == server_id:
                return s
        return None

    def list(self):
        return list(self.servers)

    def create(self, name, mc_version="1.21.1", loader="paper", ram_mb=2048, port=25565,
               server_port=None, static_domain="", tunnel_provider="bore", extra=None):
        effective_port = int(server_port if server_port is not None else port)
        base = _slugify(name)
        sid = base
        n = 1
        existing = {s.id for s in self.servers}
        while sid in existing:
            n += 1
            sid = f"{base}-{n}"

        data = {
            "id": sid,
            "name": name,
            "mc_version": str(mc_version).strip() or "1.21.1",
            "loader": str(loader).strip().lower() or "paper",
            "ram_mb": int(ram_mb),
            "server_port": effective_port,
            "static_domain": str(static_domain or "").strip(),
            "tunnel_provider": str(tunnel_provider or "bore").strip(),
            "created_at": int(time.time()),
            "is_server": True,
        }
        if extra and isinstance(extra, dict):
            data.update(extra)

        srv = DedicatedServer(data)
        self.servers.append(srv)
        self.save()

        # Initialize server directory, server.properties and eula.txt
        sdir = srv.server_dir
        os.makedirs(sdir, exist_ok=True)
        sp_path = os.path.join(sdir, "server.properties")
        if not os.path.isfile(sp_path):
            with open(sp_path, "w", encoding="utf-8") as f:
                f.write(
                    f"motd={name}\n"
                    f"server-port={port}\n"
                    "max-players=20\n"
                    "gamemode=survival\n"
                    "difficulty=normal\n"
                    "pvp=true\n"
                    "online-mode=true\n"
                )
        with open(os.path.join(sdir, "eula.txt"), "w", encoding="utf-8") as f:
            f.write("eula=true\n")

        return srv

    def delete(self, server_id, remove_files=True):
        self.servers = [s for s in self.servers if s.id != server_id]
        self.save()
        if remove_files:
            sdir = os.path.join(self.servers_root, server_id)
            if os.path.isdir(sdir):
                for _ in range(3):
                    try:
                        shutil.rmtree(sdir, ignore_errors=True)
                        if not os.path.exists(sdir):
                            break
                        time.sleep(0.05)
                    except Exception:
                        pass
                if os.path.exists(sdir):
                    try:
                        for root, dirs, files in os.walk(sdir):
                            for f in files:
                                try:
                                    os.chmod(os.path.join(root, f), 0o777)
                                    os.remove(os.path.join(root, f))
                                except Exception:
                                    pass
                        shutil.rmtree(sdir, ignore_errors=True)
                    except Exception:
                        pass
        return True

    def clear_all(self):
        self.servers = []
        self.save()
        if os.path.isdir(self.servers_root):
            for item in os.listdir(self.servers_root):
                if item == "servers.json":
                    continue
                ipath = os.path.join(self.servers_root, item)
                try:
                    if os.path.isdir(ipath):
                        shutil.rmtree(ipath, ignore_errors=True)
                    else:
                        os.remove(ipath)
                except OSError:
                    pass
        self.save()
        return True
