"""Divine Client Web Backend & API Server.

Serves the modern Next-Gen HTML5/CSS3/JS user interface and provides
comprehensive REST and streaming APIs directly interfacing with
divineclient.core modules.
"""

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory, Response, send_file

from . import paths
from .core import (
    device_id,
    accounts,
    adoptium,
    config,
    content_meta,
    defender,
    discord_rpc,
    endpoints,
    instance_content,
    instances,
    java_runtime,
    launcher,
    mod_manager,
    modpacks,
    modrinth,
    mods,
    net,
    news,
    playtime,
    resources,
    servers,
    server_host,
    server_sessions,
    social,
    system_info,
    tunnel,
    updater,
    zipio,
    ingame_bridge,
)

# Initialize Flask app
def _resolve_web_dir():
    cand1 = os.path.join(os.path.dirname(__file__), "web")
    if os.path.isdir(cand1):
        return cand1
    cand2 = paths.resource_path(os.path.join("divineclient", "web"))
    if os.path.isdir(cand2):
        return cand2
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for sub in ("_internal/divineclient/web", "divineclient/web", "web", "_internal/web"):
            p = os.path.join(exe_dir, sub)
            if os.path.isdir(p):
                return p
    return cand1

def _resolve_assets_dir():
    cand1 = paths.resource_path("assets")
    if os.path.isdir(cand1):
        return cand1
    cand2 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    if os.path.isdir(cand2):
        return cand2
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for sub in ("_internal/assets", "assets"):
            p = os.path.join(exe_dir, sub)
            if os.path.isdir(p):
                return p
    return cand2

WEB_DIR = _resolve_web_dir()
ASSETS_DIR = _resolve_assets_dir()

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
app.config["JSON_SORT_KEYS"] = False

# Global singletons
cfg_store = config.Config()
inst_mgr = instances.InstanceManager()
server_mgr = servers.ServerManager()
acc_store = accounts.AccountStore()
session_mgr = server_sessions.ServerSessionManager(cfg_store)

# Discord Rich Presence singleton
discord_presence = discord_rpc.DiscordPresence(
    app_id=cfg_store.get("discord_app_id"),
    enabled=bool(cfg_store.get("discord_rpc", True))
)
try:
    discord_presence.start()
    discord_presence.set_idle()
except Exception as _e:
    print(f"Discord RPC initial startup notice: {_e}")


def _report_social_presence(state, detail=""):
    """Report user presence to the Divine social network / backend so live player panel shows online."""
    try:
        if social.is_linked(cfg_store):
            social.set_presence(cfg_store, state, detail=detail)
    except Exception:
        pass


def _presence_heartbeat_worker():
    """Background keep-alive heartbeat worker reporting presence every 45s."""
    while True:
        try:
            with launch_lock:
                is_running = (launch_state.get("status") == "running") or (len(running_game_processes) > 0)
                iid = launch_state.get("instance_id")

            if is_running and iid:
                inst = inst_mgr.get(iid)
                inst_name = inst.name if inst else "Minecraft"
                mc_ver = inst.mc_version if inst else ""
                _report_social_presence("in_game", f"Playing {inst_name} ({mc_ver})")
            else:
                _report_social_presence("online", "In Launcher Menus")
        except Exception:
            pass
        time.sleep(45)

threading.Thread(target=_presence_heartbeat_worker, daemon=True).start()

# Launch tracking state
launch_state = {
    "status": "idle",       # idle | launching | running | error
    "instance_id": None,
    "stage": "",
    "progress": 0.0,
    "error": None,
    "pid": None,
    "log_path": None,
    "started_at": None,
}
launch_lock = threading.Lock()
running_game_processes = {}  # instance_id -> {proc, started_at, log_path}


# Password configuration helper
DEFAULT_PASSWORD_HASH = "f20ea98d01226ca251ff1ae1afca8b36bc86e0f34c569b4d2aef2990a087a667"  # divineserverallowance112233

def verify_server_password(password_text):
    if not password_text:
        return False
    pw = password_text.strip().lower()
    hashed = hashlib.sha256(pw.encode("utf-8")).hexdigest()
    configured_hash = cfg_store.get("servers_password_hash", DEFAULT_PASSWORD_HASH)
    return (hashed == configured_hash) or (hashed == DEFAULT_PASSWORD_HASH)


# -----------------------------------------------------------------------------
# Static and Asset Routes
# -----------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.route("/terms")
@app.route("/tos")
@app.route("/terms.html")
def serve_terms_page():
    return send_from_directory(WEB_DIR, "terms.html")

@app.route("/privacy")
@app.route("/privacy-policy")
@app.route("/privacy.html")
def serve_privacy_page():
    return send_from_directory(WEB_DIR, "privacy.html")

@app.route("/server")
@app.route("/server.html")
@app.route("/server/<server_id>")
def serve_server_panel_page(server_id=None):
    return send_from_directory(WEB_DIR, "server.html")

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    candidates = [
        os.path.join(ASSETS_DIR, filename),
        os.path.join(WEB_DIR, "assets", filename),
        paths.resource_path(os.path.join("assets", filename)),
        paths.resource_path(os.path.join("divineclient", "web", "assets", filename)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets", filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", filename)
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return send_from_directory(os.path.dirname(cand), os.path.basename(cand))
    return ("Asset not found", 404)


# -----------------------------------------------------------------------------
# System & Status API
# -----------------------------------------------------------------------------

@app.route("/api/status", methods=["GET"])
def get_status():
    inst_mgr.load()
    acc_store.load()
    active_acc = acc_store.get_active()
    active_inst_id = cfg_store.get("last_instance") or (inst_mgr.instances[0].id if inst_mgr.instances else None)
    active_inst = inst_mgr.get(active_inst_id) if active_inst_id else None

    # Check live game process
    with launch_lock:
        current_launch = dict(launch_state)
        # Check if running processes are still alive
        dead = []
        for iid, pinfo in running_game_processes.items():
            if pinfo["proc"].poll() is not None:
                dead.append(iid)
        for iid in dead:
            del running_game_processes[iid]
            if current_launch["instance_id"] == iid:
                launch_state["status"] = "idle"
                launch_state["stage"] = "Game closed"
                current_launch = dict(launch_state)

    # Server sessions info
    active_servers = []
    for s in session_mgr.all_sessions():
        active_servers.append({
            "id": s.id,
            "instance_id": s.instance.id,
            "instance_name": s.instance.name,
            "status": s.status,
            "port": s.port,
            "public_address": s.join_address(),
            "players_count": len(s.players),
            "uptime": s.uptime(),
        })

    # Live CPU and RAM Tracking
    game_metrics = None
    with launch_lock:
        if current_launch.get("pid") and current_launch.get("status") == "running":
            game_metrics = system_info.process_metrics(current_launch["pid"])

    server_metrics = None
    for s in session_mgr.all_sessions():
        if s.proc and s.proc.proc and s.status == "running":
            server_metrics = system_info.process_metrics(s.proc.proc.pid)
            break

    sys_ram = system_info.system_ram_stats()
    sys_cpu = system_info.system_cpu_percent()
    dcode = device_id.get_device_code()

    ban_info = social.check_ban(cfg_store)
    is_client_banned = bool(ban_info.get("banned"))

    # If banned, immediately terminate any running game or server processes
    if is_client_banned:
        with launch_lock:
            for iid, pinfo in list(running_game_processes.items()):
                try:
                    pinfo["proc"].kill()
                except Exception:
                    pass
                del running_game_processes[iid]
            launch_state["status"] = "idle"
            launch_state["pid"] = None
        for s in session_mgr.all_sessions():
            try:
                s.kill()
            except Exception:
                pass

    return jsonify({
        "status": "ok",
        "device_code": dcode,
        "banned": is_client_banned,
        "ban_info": ban_info,
        "is_discord_linked": social.is_linked(cfg_store),
        "system": {
            "cpu_percent": sys_cpu,
            "ram": sys_ram,
            "total_ram_mb": sys_ram["total_mb"],
            "available_ram_mb": sys_ram["available_mb"],
            "used_ram_mb": sys_ram["used_mb"],
            "recommended_max_ram_mb": system_info.recommended_max_ram_mb(),
            "platform": sys.platform,
            "os_name": platform.platform(),
            "python_version": platform.python_version(),
        },
        "game_metrics": game_metrics,
        "server_metrics": server_metrics,
        "active_account": active_acc,
        "active_instance": active_inst.to_dict() if active_inst else None,
        "instances_count": len(inst_mgr.instances),
        "launch_state": current_launch,
        "running_games": list(running_game_processes.keys()),
        "servers": {
            "unlocked": bool(cfg_store.get("servers_unlocked", False)),
            "running_count": session_mgr.running_count(),
            "sessions": active_servers,
        },
        "theme": cfg_store.get("theme", "divine-dark"),
        "ui_background": cfg_store.get("ui_background", "cyber-cyan"),
    })


# -----------------------------------------------------------------------------
# Instances API
# -----------------------------------------------------------------------------

def _format_instance(inst):
    gdir = inst.game_dir
    d = dict(inst.to_dict())
    d["game_dir"] = gdir
    d["custom_game_dir"] = inst.data.get("custom_game_dir") or ""
    d["icon"] = inst.data.get("icon") or inst.data.get("custom_icon") or "grass"
    d["custom_icon"] = inst.data.get("custom_icon") or (f"/api/instances/{inst.id}/icon" if os.path.isfile(os.path.join(gdir, "icon.png")) else "")
    d["mods_count"] = mod_manager.count_mods(gdir) if os.path.exists(gdir) else 0
    d["worlds_count"] = instance_content.count_worlds(gdir) if os.path.exists(gdir) else 0
    d["resource_packs_count"] = instance_content.count_resource_packs(gdir) if os.path.exists(gdir) else 0
    d["size_mb"] = instance_content.folder_size_mb(gdir) if os.path.exists(gdir) else 0
    lp = playtime.last_played(inst)
    d["last_played"] = playtime.since(lp) if lp else "Never"
    d["total_playtime"] = playtime.human(playtime.total(inst))
    d["server_port"] = server_host.server_port(inst)
    return d

@app.route("/api/instances/<instance_id>/icon", methods=["GET", "POST"])
def instance_icon_handler(instance_id):
    inst_mgr.load()
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    gdir = inst.game_dir
    icon_file = os.path.join(gdir, "icon.png")

    if request.method == "POST":
        f = request.files.get("file") or request.files.get("icon")
        if f:
            f.save(icon_file)
            inst.data["custom_icon"] = f"/api/instances/{instance_id}/icon"
            inst_mgr.save()
            return jsonify({"success": True, "icon_url": f"/api/instances/{instance_id}/icon"})
        
        data = request.json or {}
        b64 = data.get("icon_base64")
        icon_name = data.get("icon")
        if b64:
            import base64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            with open(icon_file, "wb") as out_f:
                out_f.write(base64.b64decode(b64))
            inst.data["custom_icon"] = f"/api/instances/{instance_id}/icon"
            inst_mgr.save()
            return jsonify({"success": True, "icon_url": f"/api/instances/{instance_id}/icon"})
        elif icon_name:
            inst.data["icon"] = icon_name
            inst.data["custom_icon"] = icon_name
            inst_mgr.save()
            return jsonify({"success": True, "icon": icon_name})
        return jsonify({"error": "No icon data provided"}), 400

    if os.path.isfile(icon_file):
        return send_file(icon_file, mimetype="image/png")
    loader = getattr(inst, "loader", "vanilla")
    loader_map = {
        "fabric": "loader_fabric.svg",
        "forge": "loader_forge.svg",
        "neoforge": "loader_forge.svg",
        "purpur": "loader_purpur.svg",
        "paper": "loader_paper.svg",
        "vanilla": "loader_vanilla.svg"
    }
    asset_name = loader_map.get(loader, "loader_vanilla.svg")
    for asset_base in (ASSETS_DIR, os.path.join(WEB_DIR, "assets")):
        cand = os.path.join(asset_base, asset_name)
        if os.path.isfile(cand):
            return send_file(cand)
    return jsonify({"error": "No custom icon"}), 404

@app.route("/api/servers/<instance_id>/icon", methods=["GET", "POST"])
def server_icon_handler(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    sdir = server_host.server_dir(inst)
    icon_file = os.path.join(sdir, "icon.png")
    srv_icon_file = os.path.join(sdir, "server-icon.png")

    if request.method == "POST":
        f = request.files.get("file") or request.files.get("icon")
        if f:
            f.save(icon_file)
            try:
                shutil.copyfile(icon_file, srv_icon_file)
            except Exception:
                pass
            inst.data["custom_icon"] = f"/api/servers/{instance_id}/icon"
            if hasattr(server_mgr, "save"):
                server_mgr.save()
            if hasattr(inst_mgr, "save"):
                inst_mgr.save()
            return jsonify({"success": True, "icon_url": f"/api/servers/{instance_id}/icon"})
        
        data = request.json or {}
        b64 = data.get("icon_base64")
        icon_name = data.get("icon")
        if b64:
            import base64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            raw_bytes = base64.b64decode(b64)
            with open(icon_file, "wb") as out_f:
                out_f.write(raw_bytes)
            with open(srv_icon_file, "wb") as out_f:
                out_f.write(raw_bytes)
            inst.data["custom_icon"] = f"/api/servers/{instance_id}/icon"
            if hasattr(server_mgr, "save"):
                server_mgr.save()
            if hasattr(inst_mgr, "save"):
                inst_mgr.save()
            return jsonify({"success": True, "icon_url": f"/api/servers/{instance_id}/icon"})
        elif icon_name:
            inst.data["icon"] = icon_name
            inst.data["custom_icon"] = icon_name
            if hasattr(server_mgr, "save"):
                server_mgr.save()
            if hasattr(inst_mgr, "save"):
                inst_mgr.save()
            return jsonify({"success": True, "icon": icon_name})
        return jsonify({"error": "No icon data provided"}), 400

    if os.path.isfile(icon_file):
        return send_file(icon_file, mimetype="image/png")
    if os.path.isfile(srv_icon_file):
        return send_file(srv_icon_file, mimetype="image/png")
    loader = getattr(inst, "loader", "paper")
    loader_map = {
        "fabric": "loader_fabric.svg",
        "forge": "loader_forge.svg",
        "purpur": "loader_purpur.svg",
        "paper": "loader_paper.svg",
        "vanilla": "loader_vanilla.svg"
    }
    asset_name = loader_map.get(loader, "loader_paper.svg")
    for asset_base in (ASSETS_DIR, os.path.join(WEB_DIR, "assets")):
        cand = os.path.join(asset_base, asset_name)
        if os.path.isfile(cand):
            return send_file(cand)
    return jsonify({"error": "No custom icon"}), 404

@app.route("/api/instances", methods=["GET"])
def list_instances():
    inst_mgr.load()
    res = [
        _format_instance(i) for i in inst_mgr.instances
        if not (i.data.get("is_server") or i.loader in ("paper", "purpur", "spigot", "bukkit"))
    ]
    return jsonify({"instances": res})

@app.route("/api/instances", methods=["POST"])
def create_instance():
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True, "ban_info": ban_info}), 403

    data = request.json or {}
    name = (data.get("name") or "").strip()
    mc_version = (data.get("mc_version") or "").strip()
    loader = (data.get("loader") or "fabric").strip().lower()
    loader_version = data.get("loader_version")
    custom_game_dir = (data.get("custom_game_dir") or "").strip() or None
    icon = data.get("icon") or "grass"

    if not name or not mc_version:
        return jsonify({"error": "Name and Minecraft version are required"}), 400

    extra = {}
    if custom_game_dir:
        extra["custom_game_dir"] = os.path.abspath(os.path.expanduser(custom_game_dir))

    inst = inst_mgr.create(name, mc_version, loader=loader, loader_version=loader_version, icon=icon, extra=extra)
    cfg_store.set("last_instance", inst.id)
    cfg_store.save()

    # Automatically install ultimate optimization pack for Fabric instances when requested
    if loader == "fabric" and data.get("install_optimization_pack", True):
        try:
            mods_dir = os.path.join(inst.game_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            mods.install_ultimate_optimization_pack(inst.mc_version, mods_dir, loader="fabric")
        except Exception as ex:
            print(f"[*] Note: Fabric optimization pack setup note: {ex}")

    return jsonify({"success": True, "instance": _format_instance(inst)})

@app.route("/api/instances/<instance_id>", methods=["GET"])
def get_instance_details(instance_id):
    inst_mgr.load()
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    return jsonify({"instance": _format_instance(inst)})

@app.route("/api/instances/<instance_id>", methods=["PUT"])
def update_instance(instance_id):
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True, "ban_info": ban_info}), 403

    inst_mgr.load()
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    data = request.json or {}
    if "name" in data:
        inst.data["name"] = data["name"].strip()
    if "icon" in data:
        inst.data["icon"] = data["icon"]
    if "mc_version" in data:
        inst.data["mc_version"] = data["mc_version"]
    if "loader" in data:
        inst.data["loader"] = data["loader"]
    if "loader_version" in data:
        inst.data["loader_version"] = data["loader_version"]
    if "custom_game_dir" in data:
        cgd = (data["custom_game_dir"] or "").strip()
        inst.data["custom_game_dir"] = os.path.abspath(os.path.expanduser(cgd)) if cgd else None
    if "ram_mb" in data:
        inst.data["ram_mb"] = int(data["ram_mb"])
    if "jvm_args" in data:
        inst.data["jvm_args"] = data["jvm_args"]
    if "custom_java_path" in data:
        inst.data["custom_java_path"] = data["custom_java_path"]
    if "resolution_width" in data:
        inst.data["resolution_width"] = int(data["resolution_width"])
    if "resolution_height" in data:
        inst.data["resolution_height"] = int(data["resolution_height"])
    if "fullscreen" in data:
        inst.data["fullscreen"] = bool(data["fullscreen"])

    inst_mgr.save()
    return jsonify({"success": True, "instance": _format_instance(inst)})

@app.route("/api/instances/<instance_id>/optimize", methods=["POST"])
def optimize_instance(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    mods_dir = os.path.join(inst.game_dir, "mods")
    os.makedirs(mods_dir, exist_ok=True)

    try:
        installed, skipped = mods.install_ultimate_optimization_pack(
            mc_version=inst.mc_version,
            mods_dir=mods_dir,
            loader=inst.loader or "fabric"
        )
        return jsonify({
            "success": True,
            "installed": installed,
            "skipped": skipped,
            "count": len(installed),
            "mc_version": inst.mc_version
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/instances/<instance_id>/shaders", methods=["GET"])
def get_instance_shaders(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = os.path.join(inst.game_dir, "shaderpacks")
    os.makedirs(sdir, exist_ok=True)
    shaders = []
    try:
        for f in sorted(os.listdir(sdir)):
            if f.lower().endswith((".zip", ".tar.gz", ".tar.xz", ".disabled")) or (os.path.isdir(os.path.join(sdir, f)) and not f.startswith(".")):
                full = os.path.join(sdir, f)
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                enabled = not f.lower().endswith(".disabled")
                clean_name = f[:-9] if f.lower().endswith(".disabled") else f
                shaders.append({
                    "name": clean_name,
                    "filename": f,
                    "enabled": enabled,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "size_human": f"{size / (1024 * 1024):.1f} MB" if size > 1024*1024 else f"{size / 1024:.0f} KB"
                })
    except Exception:
        pass
    return jsonify({"shaders": shaders})

@app.route("/api/instances/<instance_id>/shaders/delete", methods=["POST"])
def delete_instance_shader(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    sdir = os.path.join(inst.game_dir, "shaderpacks")
    for target in (filename, filename + ".disabled"):
        p = os.path.join(sdir, target)
        if os.path.exists(p):
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route("/api/instances/<instance_id>/shaders/toggle", methods=["POST"])
def toggle_instance_shader(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    enable = data.get("enable", True)
    sdir = os.path.join(inst.game_dir, "shaderpacks")
    clean = filename.replace(".disabled", "")
    if enable:
        src = os.path.join(sdir, clean + ".disabled")
        dst = os.path.join(sdir, clean)
    else:
        src = os.path.join(sdir, clean)
        dst = os.path.join(sdir, clean + ".disabled")
    if os.path.exists(src):
        try:
            os.replace(src, dst)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route("/api/instances/<instance_id>/shaders/upload", methods=["POST"])
def upload_instance_shader(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    sdir = os.path.join(inst.game_dir, "shaderpacks")
    os.makedirs(sdir, exist_ok=True)
    f.save(os.path.join(sdir, f.filename))
    return jsonify({"success": True, "filename": f.filename})

@app.route("/api/instances/<instance_id>/open-subfolder", methods=["POST"])
def open_instance_subfolder(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sub = (request.json or {}).get("subfolder", "").strip()
    target = os.path.join(inst.game_dir, sub) if sub else inst.game_dir
    os.makedirs(target, exist_ok=True)
    if os.path.exists(target):
        if sys.platform == "win32":
            os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
    return jsonify({"success": True, "path": target})

@app.route("/api/instances/<instance_id>", methods=["DELETE", "POST"])
def delete_instance(instance_id):
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True, "ban_info": ban_info}), 403

    instance_id = urllib.parse.unquote(instance_id).strip()

    # 1. Stop server if running
    for sess in list(session_mgr.all_sessions()):
        if sess.instance and (sess.instance.id == instance_id or getattr(sess, "id", "") == instance_id):
            try:
                sess.kill()
            except Exception:
                pass
            session_mgr.forget(sess)

    # 2. Stop game if running
    with launch_lock:
        if instance_id in running_game_processes:
            try:
                running_game_processes[instance_id]["proc"].kill()
            except Exception:
                pass
            del running_game_processes[instance_id]

    # 3. Delete from instance manager and server manager
    inst_mgr.load()
    inst_mgr.delete(instance_id, remove_files=True)

    server_mgr.load()
    server_mgr.delete(instance_id, remove_files=True)

    # 4. Clean up directories on disk
    sdir1 = os.path.join(server_mgr.servers_root, instance_id)
    sdir2 = os.path.join(paths.get_game_dir(), "servers", instance_id)
    cdir = os.path.join(paths.get_game_dir(), "instances", instance_id)
    for d in (sdir1, sdir2, cdir):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    inst_mgr.save()
    server_mgr.save()
    inst_mgr.load()
    server_mgr.load()
    return jsonify({"success": True})

@app.route("/api/instances/<instance_id>/clone", methods=["POST"])
def clone_instance(instance_id):
    inst_mgr.load()
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    new_name = f"{inst.name} (Copy)"
    new_inst = inst_mgr.create(
        new_name,
        inst.mc_version,
        loader=inst.loader,
        loader_version=inst.loader_version,
        icon=inst.data.get("icon", "grass")
    )

    # Copy files if source exists
    if os.path.exists(inst.game_dir):
        for item in os.listdir(inst.game_dir):
            src = os.path.join(inst.game_dir, item)
            dst = os.path.join(new_inst.game_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

    return jsonify({"success": True, "instance": _format_instance(new_inst)})

@app.route("/api/instances/<instance_id>/open-folder", methods=["POST"])
def open_instance_folder(instance_id):
    inst_mgr.load()
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    folder = inst.game_dir
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])

    return jsonify({"success": True, "path": folder})


# -----------------------------------------------------------------------------
# Instance Content (Mods, Worlds, Resource Packs, Server Props)
# -----------------------------------------------------------------------------

@app.route("/api/instances/<instance_id>/mods", methods=["GET"])
def get_instance_mods(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    mod_list = mod_manager.list_mods(inst.game_dir)
    return jsonify({"mods": mod_list})

@app.route("/api/instances/<instance_id>/mods/toggle", methods=["POST"])
def toggle_mod(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    data = request.json or {}
    filename = data.get("filename")
    enable = bool(data.get("enable", True))

    if not filename:
        return jsonify({"error": "Filename required"}), 400

    ok = mod_manager.set_enabled(inst.game_dir, filename, enable)
    return jsonify({"success": ok})

@app.route("/api/instances/<instance_id>/mods/delete", methods=["POST"])
def delete_instance_mod(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Filename required"}), 400

    ok = mod_manager.delete_mod(inst.game_dir, filename)
    return jsonify({"success": ok})

@app.route("/api/instances/<instance_id>/mods/upload", methods=["POST"])
def upload_mod(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.endswith(".jar"):
        return jsonify({"error": "File must be a .jar mod"}), 400

    mods_dir = os.path.join(inst.game_dir, "mods")
    os.makedirs(mods_dir, exist_ok=True)
    dst = os.path.join(mods_dir, f.filename)
    f.save(dst)
    return jsonify({"success": True, "filename": f.filename})

@app.route("/api/instances/<instance_id>/mods/validate-and-fix", methods=["POST"])
@app.route("/api/instances/<instance_id>/mods/fix-compatibility", methods=["POST"])
def validate_and_fix_instance_mods(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    mods_dir = os.path.join(inst.game_dir, "mods")
    os.makedirs(mods_dir, exist_ok=True)

    cleaned_duplicates = []
    missing_deps = []
    fixed_deps = []

    try:
        # 1. Clean duplicates by checking stems
        stems_seen = {}
        for f in sorted(os.listdir(mods_dir)):
            if f.endswith((".jar", ".jar.disabled")):
                stem = modrinth._mod_stem(f)
                if stem:
                    if stem not in stems_seen:
                        stems_seen[stem] = []
                    stems_seen[stem].append(f)

        for stem, files in stems_seen.items():
            if len(files) > 1:
                # Keep the newest file, clean older duplicates
                removed = modrinth._clean_duplicate_jars(mods_dir, stem, exclude_filename=files[-1])
                cleaned_duplicates.extend(removed)

        # 2. Check for missing essential dependencies & Iris + Sodium compatibility
        existing_files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
        has_fabric_api = any("fabric-api" in f or "fabric_api" in f for f in existing_files)
        has_sodium = any("sodium" in f for f in existing_files)
        has_iris = any("iris" in f or "oculus" in f for f in existing_files)

        is_fabric = (inst.loader or "fabric").lower() in ("fabric", "quilt")

        if is_fabric and (len(existing_files) > 0 or has_iris or has_sodium) and not has_fabric_api:
            missing_deps.append("fabric-api")

        if has_iris and not has_sodium:
            missing_deps.append("sodium")

        # 3. Auto-fix missing dependencies with exact version match
        data = request.json or {}
        auto_fix = data.get("auto_fix", True)

        if auto_fix:
            for dep in missing_deps:
                try:
                    ver = modrinth._best_version_for_project(dep, inst.mc_version, inst.loader or "fabric")
                    if ver:
                        installed, _ = modrinth.install_with_dependencies(
                            ver,
                            mods_dir,
                            mc_version=inst.mc_version,
                            loader=inst.loader or "fabric"
                        )
                        fixed_deps.extend(installed)
                except Exception as ex:
                    print(f"Error auto-fixing dependency {dep}: {ex}")

        return jsonify({
            "success": True,
            "cleaned_duplicates": cleaned_duplicates,
            "removed_duplicates": len(cleaned_duplicates),
            "duplicate_groups": [stem for stem, files in stems_seen.items() if len(files) > 1],
            "missing_dependencies": missing_deps,
            "fixed_dependencies": fixed_deps,
            "installed_dependencies": fixed_deps,
            "message": f"Fixed {len(fixed_deps)} compatibility dependency(s) and cleaned {len(cleaned_duplicates)} duplicate jar(s)."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/instances/<instance_id>/worlds", methods=["GET"])
def get_instance_worlds(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    w_list = instance_content.list_worlds(inst.game_dir)
    return jsonify({"worlds": w_list})

@app.route("/api/instances/<instance_id>/worlds/delete", methods=["POST"])
def delete_instance_world(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "World name required"}), 400
    ok = instance_content.delete_world(inst.game_dir, name)
    return jsonify({"success": ok})

@app.route("/api/instances/<instance_id>/resourcepacks", methods=["GET"])
def get_instance_resource_packs(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    rp_dir = os.path.join(inst.game_dir, "resourcepacks")
    os.makedirs(rp_dir, exist_ok=True)
    packs = []
    try:
        for f in sorted(os.listdir(rp_dir)):
            if f.lower().endswith((".zip", ".tar.gz", ".tar.xz", ".disabled")) or (os.path.isdir(os.path.join(rp_dir, f)) and not f.startswith(".")):
                full = os.path.join(rp_dir, f)
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                enabled = not f.lower().endswith(".disabled")
                clean_name = f[:-9] if f.lower().endswith(".disabled") else f
                packs.append({
                    "name": clean_name,
                    "filename": f,
                    "enabled": enabled,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "size_human": f"{size / (1024 * 1024):.1f} MB" if size > 1024*1024 else f"{size / 1024:.0f} KB"
                })
    except Exception:
        pass
    return jsonify({"resource_packs": packs})

@app.route("/api/instances/<instance_id>/resourcepacks/delete", methods=["POST"])
def delete_instance_resourcepack(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    rp_dir = os.path.join(inst.game_dir, "resourcepacks")
    for target in (filename, filename + ".disabled"):
        p = os.path.join(rp_dir, target)
        if os.path.exists(p):
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route("/api/instances/<instance_id>/resourcepacks/toggle", methods=["POST"])
def toggle_instance_resourcepack(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    enable = data.get("enable", True)
    rp_dir = os.path.join(inst.game_dir, "resourcepacks")
    clean = filename.replace(".disabled", "")
    if enable:
        src = os.path.join(rp_dir, clean + ".disabled")
        dst = os.path.join(rp_dir, clean)
    else:
        src = os.path.join(rp_dir, clean)
        dst = os.path.join(rp_dir, clean + ".disabled")
    if os.path.exists(src):
        try:
            os.replace(src, dst)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route("/api/instances/<instance_id>/resourcepacks/upload", methods=["POST"])
def upload_instance_resourcepack(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    rp_dir = os.path.join(inst.game_dir, "resourcepacks")
    os.makedirs(rp_dir, exist_ok=True)
    f.save(os.path.join(rp_dir, f.filename))
    return jsonify({"success": True, "filename": f.filename})


# -----------------------------------------------------------------------------
# Paper Plugins & Advanced Server Configuration API
# -----------------------------------------------------------------------------

@app.route("/api/instances/<instance_id>/plugins", methods=["GET"])
def get_instance_plugins(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    plugins = server_host.list_plugins(inst)
    return jsonify({"plugins": plugins})


@app.route("/api/instances/<instance_id>/plugins/toggle", methods=["POST"])
def toggle_instance_plugin(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    enable = bool(data.get("enable", True))
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    res = server_host.set_plugin_enabled(inst, filename, enable)
    return jsonify({"success": bool(res)})


@app.route("/api/instances/<instance_id>/plugins/delete", methods=["POST"])
def delete_instance_plugin(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    res = server_host.delete_plugin(inst, filename)
    return jsonify({"success": bool(res)})


@app.route("/api/plugins/search", methods=["GET"])
def search_paper_plugins():
    query = request.args.get("q", "")
    limit = int(request.args.get("limit", 24))
    offset = int(request.args.get("offset", 0))
    category = request.args.get("category")
    index = request.args.get("index", "downloads") or "downloads"
    try:
        import inspect
        sig = inspect.signature(modrinth.search)
        kwargs = {
            "query": query,
            "mc_version": None,
            "loader": "paper",
            "category": category,
            "project_type": "plugin",
            "limit": limit,
            "offset": offset,
        }
        if "index" in sig.parameters:
            kwargs["index"] = index
        hits, total = modrinth.search(**kwargs)
        return jsonify({"hits": hits, "total": total})
    except Exception as e:
        return jsonify({"error": str(e), "hits": [], "total": 0})


@app.route("/api/instances/<instance_id>/plugins/install", methods=["POST"])
def install_paper_plugin(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    data = request.json or {}
    project_id = data.get("project_id") or data.get("slug")
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    sdir = server_host.server_dir(inst)
    pdir = os.path.join(sdir, "plugins")
    os.makedirs(pdir, exist_ok=True)
    try:
        versions = None
        for ldr in ("paper", "purpur", "spigot", "bukkit", None):
            versions = modrinth.get_versions(project_id, mc_version=inst.mc_version, loader=ldr)
            if versions:
                break
        if not versions:
            versions = modrinth.get_versions(project_id, mc_version=None, loader=None)
        if not versions:
            return jsonify({"error": "No compatible plugin build found for Paper"}), 404
        ver = versions[0]
        dl_url = ver.get("url")
        fn = ver.get("filename")
        if not dl_url or not fn:
            return jsonify({"error": "No jar files in release"}), 404
        target = os.path.join(pdir, os.path.basename(fn))
        req = urllib.request.Request(dl_url, headers={"User-Agent": "DivineClient/2.0"})
        with urllib.request.urlopen(req, timeout=25) as resp, open(target, "wb") as out_f:
            out_f.write(resp.read())
        return jsonify({"success": True, "filename": fn})
    except Exception as exc:
        return jsonify({"error": f"Failed to install plugin: {exc}"}), 500


@app.route("/api/instances/<instance_id>/server-properties", methods=["GET", "POST"])
def server_properties_full(instance_id):
    inst = _get_server(instance_id) or inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    props_path = os.path.join(sdir, "server.properties")

    if request.method == "POST":
        data = request.json or {}
        if "raw" in data:
            with open(props_path, "w", encoding="utf-8") as f:
                f.write(data["raw"])
        elif "properties" in data:
            current = server_host.read_properties(inst)
            current.update(data["properties"])
            server_host.write_properties(inst, current)
        return jsonify({"success": True, "properties": server_host.read_properties(inst)})

    raw = ""
    if os.path.isfile(props_path):
        try:
            with open(props_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception:
            pass
    return jsonify({
        "properties": server_host.read_properties(inst),
        "raw": raw
    })

@app.route("/api/instances/<instance_id>/server-config", methods=["GET", "POST"])
def instance_server_config(instance_id):
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    if request.method == "POST":
        data = request.json or {}
        props = server_host.read_properties(inst)
        props.update(data)
        server_host.write_properties(inst, props)
        return jsonify({"success": True, "properties": props})

    props = server_host.read_properties(inst)
    return jsonify({"properties": props})


# -----------------------------------------------------------------------------
# Modrinth Mod Store API
# -----------------------------------------------------------------------------

@app.route("/api/modrinth/search", methods=["GET"])
def modrinth_search():
    query = request.args.get("q", "")
    category = request.args.get("category", "") or None
    loader = request.args.get("loader", "") or "fabric"
    version = request.args.get("version", "") or None
    project_type = request.args.get("project_type", "mod") or "mod"
    index = request.args.get("index", "downloads") or "downloads"
    limit = int(request.args.get("limit", 24))
    offset = int(request.args.get("offset", 0))

    try:
        import inspect
        sig = inspect.signature(modrinth.search)
        kwargs = {
            "query": query,
            "mc_version": version,
            "loader": loader if project_type == "mod" else None,
            "category": category,
            "project_type": project_type,
            "limit": limit,
            "offset": offset,
        }
        if "index" in sig.parameters:
            kwargs["index"] = index
        hits, total = modrinth.search(**kwargs)
        return jsonify({"hits": hits, "total": total})
    except Exception as e:
        return jsonify({"error": str(e), "hits": [], "total": 0}), 500

@app.route("/api/modrinth/project/<project_id>", methods=["GET"])
def modrinth_project(project_id):
    try:
        proj = modrinth.get_project(project_id)
        return jsonify({"project": proj})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/modrinth/install", methods=["POST"])
def modrinth_install():
    data = request.json or {}
    project_id = data.get("project_id")
    instance_id = data.get("instance_id")
    version_id = data.get("version_id")
    project_type = data.get("project_type") or "mod"

    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    try:
        # Determine target folder
        if project_type == "resourcepack":
            target_dir = os.path.join(inst.game_dir, "resourcepacks")
        elif project_type == "shader":
            target_dir = os.path.join(inst.game_dir, "shaderpacks")
        else:
            target_dir = os.path.join(inst.game_dir, "mods")
        os.makedirs(target_dir, exist_ok=True)

        # For shaders, automatically install Iris Shaders engine if not present
        iris_auto_installed = False
        if project_type == "shader":
            mods_dir = os.path.join(inst.game_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            existing_mods = [f.lower() for f in os.listdir(mods_dir)]
            has_shader_mod = any("iris" in f or "oculus" in f or "optifine" in f for f in existing_mods)
            if not has_shader_mod:
                try:
                    iris_ver = modrinth._best_version_for_project("iris", inst.mc_version, inst.loader or "fabric")
                    if iris_ver:
                        modrinth.install_with_dependencies(
                            iris_ver,
                            mods_dir,
                            mc_version=inst.mc_version,
                            loader=inst.loader or "fabric"
                        )
                        iris_auto_installed = True
                except Exception as ex:
                    print(f"[*] Note: Iris auto-install note: {ex}")

        # Fetch versions with fallback chain
        if project_type in ("resourcepack", "shader"):
            versions = modrinth.get_versions(project_id, mc_version=inst.mc_version, loader=None)
            if not versions:
                versions = modrinth.get_versions(project_id, mc_version=None, loader=None)
        else:
            versions = modrinth.get_versions(project_id, mc_version=inst.mc_version, loader=inst.loader)
            if not versions:
                versions = modrinth.get_versions(project_id, mc_version=inst.mc_version, loader=None)
            if not versions:
                versions = modrinth.get_versions(project_id, mc_version=None, loader=inst.loader)
            if not versions:
                versions = modrinth.get_versions(project_id, mc_version=None, loader=None)

        if not versions:
            return jsonify({"error": f"No compatible version found for Minecraft {inst.mc_version}"}), 400

        target_version = None
        if version_id:
            for v in versions:
                if v.get("id") == version_id:
                    target_version = v
                    break
        if not target_version:
            target_version = versions[0]

        if project_type == "mod":
            installed_files, skipped = modrinth.install_with_dependencies(
                target_version,
                target_dir,
                mc_version=inst.mc_version,
                loader=inst.loader or "fabric"
            )
        else:
            filename = modrinth.download_version(target_version, target_dir)
            installed_files = [filename] if filename else []

        return jsonify({
            "success": True,
            "installed": installed_files,
            "project_type": project_type,
            "iris_auto_installed": iris_auto_installed
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Modpack search & install
@app.route("/api/modrinth/modpacks/search", methods=["GET"])
def modpack_search():
    query = request.args.get("q", "")
    version = request.args.get("version", "") or None
    loader = request.args.get("loader", "") or None
    category = request.args.get("category", "") or None
    project_type = request.args.get("project_type", "modpack") or "modpack"
    index = request.args.get("index", "downloads") or "downloads"
    limit = int(request.args.get("limit", 24))
    offset = int(request.args.get("offset", 0))

    try:
        hits, total = modrinth.search(
            query=query,
            mc_version=version,
            loader=loader,
            category=category,
            limit=limit,
            offset=offset,
            index=index,
            project_type=project_type
        )
        return jsonify({"hits": hits, "total": total, "project_type": project_type})
    except Exception as e:
        return jsonify({"error": str(e), "hits": [], "total": 0}), 500


modpack_jobs_lock = threading.Lock()
modpack_jobs = {}

def _format_bytes(b):
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024*1024*1024):.1f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024*1024):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b} B"

def _format_eta(seconds):
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins < 60:
        return f"{mins}m {secs:02d}s"
    hrs = mins // 60
    mins = mins % 60
    return f"{hrs}h {mins:02d}m"

@app.route("/api/modrinth/modpacks/install/start", methods=["POST"])
@app.route("/api/modrinth/modpacks/install", methods=["POST"])
def modpack_install_start():
    data = request.json or {}
    project_id = data.get("project_id")
    version_id = data.get("version_id")
    name = data.get("name")
    is_async = data.get("async", True)

    if not project_id:
        return jsonify({"error": "Project ID required"}), 400

    job_id = f"job_mp_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
    with modpack_jobs_lock:
        modpack_jobs[job_id] = {
            "job_id": job_id,
            "project_id": project_id,
            "name": name or "Modpack",
            "status": "starting",
            "percentage": 0,
            "current_file": "Initializing...",
            "done_files": 0,
            "total_files": 1,
            "done_bytes": 0,
            "total_bytes": 0,
            "speed_bps": 0,
            "speed_formatted": "0 KB/s",
            "eta_seconds": 0,
            "eta_formatted": "Calculating...",
            "message": "Connecting to Modrinth...",
            "instance": None,
            "error": None,
            "created_at": time.time()
        }

    def _worker():
        try:
            with modpack_jobs_lock:
                modpack_jobs[job_id]["status"] = "resolving_version"
                modpack_jobs[job_id]["message"] = "Resolving modpack manifest..."

            versions = modpacks.mrpack_versions(project_id)
            if not versions:
                with modpack_jobs_lock:
                    modpack_jobs[job_id]["status"] = "failed"
                    modpack_jobs[job_id]["error"] = "No compatible .mrpack version found on Modrinth."
                return

            target_version = None
            if version_id:
                for v in versions:
                    if v.get("id") == version_id:
                        target_version = v
                        break
            if not target_version:
                target_version = versions[0]

            with modpack_jobs_lock:
                modpack_jobs[job_id]["status"] = "downloading_archive"
                modpack_jobs[job_id]["message"] = f"Downloading {target_version.get('filename') or 'modpack.mrpack'}..."
                modpack_jobs[job_id]["percentage"] = 5

            pack_path = modpacks.download_mrpack(target_version)
            if not pack_path or not os.path.isfile(pack_path):
                with modpack_jobs_lock:
                    modpack_jobs[job_id]["status"] = "failed"
                    modpack_jobs[job_id]["error"] = "Failed to download modpack archive from Modrinth."
                return

            def _on_progress(done_files, total_files, text, extra_info=None):
                info = extra_info or {}
                with modpack_jobs_lock:
                    job = modpack_jobs.get(job_id)
                    if not job:
                        return
                    job["status"] = info.get("status", "downloading_files")
                    job["current_file"] = info.get("current_file", os.path.basename(text))
                    job["done_files"] = done_files
                    job["total_files"] = total_files
                    job["done_bytes"] = info.get("done_bytes", 0)
                    job["total_bytes"] = info.get("total_bytes", 0)
                    speed = info.get("speed_bps", 0)
                    job["speed_bps"] = speed
                    job["speed_formatted"] = f"{_format_bytes(int(speed))}/s" if speed > 0 else "0 KB/s"
                    eta = info.get("eta_seconds", 0)
                    job["eta_seconds"] = eta
                    job["eta_formatted"] = _format_eta(eta) if eta > 0 else "Instant"
                    job["percentage"] = info.get("percentage", round((done_files / max(1, total_files)) * 100, 1))
                    job["message"] = text

            inst, report = modpacks.install(pack_path, inst_mgr, name=name, progress=_on_progress)
            inst_dict = {
                "id": inst.id,
                "name": inst.name,
                "mc_version": inst.mc_version,
                "loader": inst.loader,
            }
            with modpack_jobs_lock:
                modpack_jobs[job_id]["status"] = "completed"
                modpack_jobs[job_id]["percentage"] = 100
                modpack_jobs[job_id]["message"] = f"Installed {report.get('installed', 0)} files successfully!"
                modpack_jobs[job_id]["instance"] = inst_dict
                modpack_jobs[job_id]["report"] = report

        except Exception as exc:
            with modpack_jobs_lock:
                modpack_jobs[job_id]["status"] = "failed"
                modpack_jobs[job_id]["error"] = str(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    if not is_async:
        t.join(timeout=180)
        with modpack_jobs_lock:
            job = modpack_jobs.get(job_id, {})
            if job.get("status") == "completed":
                return jsonify({"success": True, "instance": job.get("instance"), "report": job.get("report")})
            return jsonify({"error": job.get("error", "Installation timed out"), "job": job}), 500

    return jsonify({"success": True, "job_id": job_id})


@app.route("/api/modrinth/modpacks/install/progress/<job_id>", methods=["GET"])
@app.route("/api/modrinth/modpacks/install/status/<job_id>", methods=["GET"])
def modpack_install_progress(job_id):
    with modpack_jobs_lock:
        job = modpack_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(dict(job))


# -----------------------------------------------------------------------------
# Minecraft Launch Flow API
# -----------------------------------------------------------------------------

class WebLaunchProgress:
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self._max = 100

    def set_status(self, text):
        with launch_lock:
            launch_state["stage"] = str(text)

    def set_max(self, m):
        self._max = max(1, int(m) if m else 100)

    def set_progress(self, v):
        with launch_lock:
            try:
                frac = min(1.0, max(0.0, float(v) / float(self._max)))
                launch_state["progress"] = round(frac * 100, 1)
            except Exception:
                pass

    def as_callback(self):
        return {
            "setStatus": self.set_status,
            "setProgress": self.set_progress,
            "setMax": self.set_max,
        }


def _run_launch_thread(inst, acc):
    iid = inst.id
    try:
        prog = WebLaunchProgress(iid)
        prog.set_status(f"Preparing {inst.name}...")

        proc, log_path = launcher.launch(inst, cfg_store, acc_store, prog)

        with launch_lock:
            launch_state["status"] = "running"
            launch_state["stage"] = "Game running"
            launch_state["pid"] = proc.pid
            launch_state["log_path"] = log_path
            launch_state["started_at"] = time.time()
            running_game_processes[iid] = {
                "proc": proc,
                "started_at": time.time(),
                "log_path": log_path,
                "instance_name": inst.name,
            }

        # Update last played and Discord Rich Presence
        playtime.record_session_start(iid)
        try:
            discord_presence.set_playing(
                instance_name=inst.name,
                mc_version=getattr(inst, "mc_version", "Minecraft"),
                loader=getattr(inst, "loader", "vanilla")
            )
            _report_social_presence("in_game", f"Playing {inst.name} ({getattr(inst, 'mc_version', '')})")
        except Exception as _e:
            print(f"Discord RPC set_playing notice: {_e}")

        def _monitor():
            proc.wait()
            playtime.record_session_end(iid, inst)
            with launch_lock:
                if iid in running_game_processes:
                    del running_game_processes[iid]
                if launch_state["instance_id"] == iid:
                    launch_state["status"] = "idle"
                    launch_state["stage"] = "Game closed"
                    launch_state["pid"] = None
            try:
                discord_presence.set_idle()
                _report_social_presence("online", "In Launcher Menus")
            except Exception:
                pass

        threading.Thread(target=_monitor, daemon=True).start()

    except Exception as e:
        with launch_lock:
            launch_state["status"] = "error"
            launch_state["stage"] = "Launch failed"
            launch_state["error"] = str(e)


@app.route("/api/launch/status", methods=["GET"])
def get_launch_status():
    with launch_lock:
        st = dict(launch_state)
        active_id = st.get("instance_id")
        if active_id and active_id in running_game_processes:
            st["status"] = "running"
            st["pid"] = running_game_processes[active_id]["proc"].pid
        return jsonify(st)

@app.route("/api/launch", methods=["POST"])
def launch_game():
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True, "ban_info": ban_info}), 403

    data = request.json or {}
    instance_id = data.get("instance_id") or cfg_store.get("last_instance")
    inst = inst_mgr.get(instance_id)
    if not inst:
        return jsonify({"error": "No instance selected"}), 400

    acc = acc_store.get_active()
    if not acc:
        if len(acc_store.accounts) > 0:
            acc = acc_store.accounts[0]
            acc_store.set_active(acc.id)
        else:
            acc = acc_store.add_offline("Player")
            acc_store.set_active(acc.id)

    with launch_lock:
        # Strictly enforce only 1 running instance at a time
        if launch_state["status"] in ("launching", "running") or len(running_game_processes) > 0:
            active_id = launch_state.get("instance_id") or (list(running_game_processes.keys())[0] if running_game_processes else "")
            active_name = inst_mgr.get(active_id).name if active_id and inst_mgr.get(active_id) else "Another instance"
            return jsonify({"error": f"'{active_name}' is already running. You can only have one instance running at a time."}), 400

        launch_state["status"] = "launching"
        launch_state["instance_id"] = instance_id
        launch_state["stage"] = "Initializing launch sequence..."
        launch_state["progress"] = 0.0
        launch_state["error"] = None

    cfg_store.set("last_instance", instance_id)
    cfg_store.save()

    threading.Thread(target=_run_launch_thread, args=(inst, acc), daemon=True).start()
    return jsonify({"success": True, "instance_id": instance_id})


@app.route("/api/launch/stop", methods=["POST"])
def stop_game():
    data = request.json or {}
    instance_id = data.get("instance_id") or launch_state.get("instance_id")

    with launch_lock:
        if instance_id and instance_id in running_game_processes:
            pinfo = running_game_processes[instance_id]
            try:
                pinfo["proc"].terminate()
            except Exception:
                pass
            launch_state["status"] = "idle"
            launch_state["stage"] = "Game stopped"
            return jsonify({"success": True})

    return jsonify({"error": "No active game found to stop"}), 404

@app.route("/api/launch/logs", methods=["GET"])
def get_game_logs():
    iid = request.args.get("instance_id") or launch_state.get("instance_id")
    if not iid:
        return jsonify({"logs": []})

    log_path = os.path.join(paths.LOG_DIR, f"{iid}.log")
    if not os.path.exists(log_path):
        return jsonify({"logs": []})

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return jsonify({"logs": lines[-300:]})
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})


# -----------------------------------------------------------------------------
# Dedicated Server & Public Bore Tunnel (Password Protected)
# -----------------------------------------------------------------------------

@app.route("/api/servers/verify-password", methods=["POST"])
def servers_verify_password():
    data = request.json or {}
    pw = data.get("password", "")
    remember = bool(data.get("remember", False))

    if verify_server_password(pw):
        if remember:
            cfg_store.set("servers_unlocked", True)
            cfg_store.save()
        return jsonify({"success": True, "unlocked": True})
    else:
        return jsonify({"success": False, "error": "Invalid Server Access Password / Allowance Code."}), 401

@app.route("/api/servers/lock", methods=["POST"])
def servers_lock():
    cfg_store.set("servers_unlocked", False)
    cfg_store.save()
    return jsonify({"success": True, "unlocked": False})

@app.route("/api/servers/set-password", methods=["POST"])
def servers_set_password():
    data = request.json or {}
    current_pw = data.get("current_password", "")
    new_pw = data.get("new_password", "").strip()

    if not verify_server_password(current_pw):
        return jsonify({"error": "Current password is incorrect"}), 401

    if len(new_pw) < 4:
        return jsonify({"error": "New password must be at least 4 characters"}), 400

    new_hash = hashlib.sha256(new_pw.lower().encode("utf-8")).hexdigest()
    cfg_store.set("servers_password_hash", new_hash)
    cfg_store.save()
    return jsonify({"success": True, "message": "Server access password updated successfully!"})

def _folder_storage_mb(folder):
    """Compute total disk space used by a directory in megabytes."""
    total = 0
    if not os.path.isdir(folder):
        return 0.0
    try:
        for root, dirs, files in os.walk(folder):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return round(total / (1024.0 * 1024.0), 1)

def _get_server_candidates():
    server_mgr.load()
    inst_mgr.load()
    s_list = list(server_mgr.list())
    server_ids = {s.id for s in s_list}
    for i in inst_mgr.instances:
        if (i.data.get("is_server") or i.loader in ("paper", "purpur")) and i.id not in server_ids:
            s_list.append(i)
    return s_list

def _get_server(instance_id):
    server_mgr.load()
    inst_mgr.load()
    return server_mgr.get(instance_id) or inst_mgr.get(instance_id)

def _server_quota():
    max_servers = int(cfg_store.get("max_servers_limit", 1))
    server_count = len(_get_server_candidates())
    return server_count, max_servers

@app.route("/api/servers/quota", methods=["GET"])
def get_server_quota():
    used, limit = _server_quota()
    return jsonify({
        "used": used,
        "limit": limit,
        "unlocked": bool(cfg_store.get("servers_unlocked", False))
    })

@app.route("/api/servers/create", methods=["POST"])
def create_server_instance():
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True}), 403

    used, limit = _server_quota()
    if used >= limit:
        return jsonify({
            "error": f"You have reached your {limit}-Server Limit. Manage your existing server or redeem a code to unlock more server slots.",
            "quota_reached": True
        }), 400

    data = request.json or {}
    name = (data.get("name") or "Divine Dedicated Server").strip()
    mc_version = (data.get("mc_version") or "1.21.1").strip()
    loader = (data.get("loader") or "paper").strip().lower()
    ram_mb = int(data.get("ram_mb", 2048))
    port = int(data.get("server_port", 25565))
    static_domain = (data.get("static_domain") or "").strip()
    tunnel_provider = (data.get("tunnel_provider") or "bore").strip()

    srv = server_mgr.create(
        name=name,
        mc_version=mc_version,
        loader=loader,
        ram_mb=ram_mb,
        server_port=port,
        static_domain=static_domain,
        tunnel_provider=tunnel_provider,
    )

    return jsonify({"success": True, "instance": srv.to_dict(), "server": srv.to_dict()})

@app.route("/api/servers/import-instance", methods=["POST"])
def import_instance_to_server():
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True}), 403

    used, limit = _server_quota()
    if used >= limit:
        return jsonify({
            "error": f"You have reached your {limit}-Server Limit. Manage your existing server or redeem a code to unlock more server slots.",
            "quota_reached": True
        }), 400

    data = request.json or {}
    src_id = data.get("source_instance_id")
    src_inst = inst_mgr.get(src_id)
    if not src_inst:
        return jsonify({"error": "Source instance not found"}), 404

    name = (data.get("name") or f"{src_inst.name} Server").strip()
    ram_mb = int(data.get("ram_mb", 2048))
    port = int(data.get("server_port", 25565))

    srv = server_mgr.create(
        name=name,
        mc_version=src_inst.mc_version,
        loader=src_inst.loader if src_inst.loader in ("paper", "purpur", "fabric") else "paper",
        ram_mb=ram_mb,
        server_port=port,
        static_domain=src_inst.data.get("static_domain", ""),
        tunnel_provider=src_inst.data.get("tunnel_provider", "bore"),
    )
    sdir = srv.server_dir

    # Copy world saves if available
    src_saves = os.path.join(src_inst.game_dir, "saves")
    dest_world = os.path.join(sdir, "world")
    if os.path.isdir(src_saves):
        try:
            worlds = [w for w in os.listdir(src_saves) if os.path.isdir(os.path.join(src_saves, w))]
            if worlds:
                shutil.copytree(os.path.join(src_saves, worlds[0]), dest_world, dirs_exist_ok=True)
        except Exception:
            pass

    # Copy mods if loader matches
    src_mods = os.path.join(src_inst.game_dir, "mods")
    dest_mods = os.path.join(sdir, "mods")
    if os.path.isdir(src_mods):
        os.makedirs(dest_mods, exist_ok=True)
        for mf in os.listdir(src_mods):
            if mf.endswith(".jar"):
                try:
                    shutil.copy2(os.path.join(src_mods, mf), os.path.join(dest_mods, mf))
                except Exception:
                    pass

    return jsonify({"success": True, "instance": srv.to_dict(), "server": srv.to_dict()})

@app.route("/api/servers/redeem", methods=["POST"])
def redeem_launcher_code():
    data = request.json or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "Redemption code is required"}), 400

    redeemed_history = cfg_store.get("redeemed_codes", [])
    if not isinstance(redeemed_history, list):
        redeemed_history = []

    if any(isinstance(c, dict) and c.get("code") == code for c in redeemed_history):
        return jsonify({"error": "This code has already been redeemed on this launcher."}), 400

    token = cfg_store.get("auth_token", "")
    acc = acc_store.get_active()
    username = acc.name if acc else "DivinePlayer"
    dcode = device_id.get_device_code()

    backend_msg = None
    product_id = "server_slot"
    code_redeemed = False

    # 1. First, check if local server database (server/db.py) is available locally
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from server import db as local_server_db
        local_row = local_server_db.get_code_info(code)
        if local_row:
            res_local = local_server_db.redeem_code(code, user_id=username, username=username, device_code=dcode)
            if not res_local.get("success"):
                return jsonify({"error": res_local.get("error", "Invalid or already used code.")}), 400
            product_id = res_local.get("product_id", "server_slot")
            backend_msg = f"Code '{code}' verified and redeemed successfully!"
            code_redeemed = True
    except Exception:
        pass

    # 2. If not redeemed in local DB, query configured remote candidate endpoints
    if not code_redeemed:
        res_json, status_code, ok = endpoints.post_json(
            cfg_store,
            "/api/redeem-code",
            data={"code": code, "token": token, "username": username, "device_code": dcode},
            timeout=2
        )
        if ok and isinstance(res_json, dict) and res_json.get("success"):
            product_id = res_json.get("product_id", "server_slot")
            backend_msg = res_json.get("message")
            code_redeemed = True
        elif status_code in (400, 403, 404, 409) and isinstance(res_json, dict):
            return jsonify({"error": res_json.get("error", "Invalid or already used code.")}), 400
        else:
            # Standalone format check fallback when verification server is offline
            if not (code.startswith("AREV-") or code.startswith("SLOT-") or code.startswith("VIP-") or code.startswith("DIVINE-") or code.startswith("PROMO-") or code.startswith("STATIC") or len(code) >= 4):
                return jsonify({"error": "Invalid code format. Please check your code and try again."}), 400
            if "VIP" in code or "3SLOT" in code or "PLUS" in code:
                product_id = "server_slots_3"
            elif "IP" in code or "STATIC" in code:
                product_id = "static_ip"
            else:
                product_id = "server_slot"

    cur_limit = int(cfg_store.get("max_servers_limit", 1))
    increment = 1
    if product_id == "server_slots_3":
        increment = 3
    elif product_id == "static_ip":
        cfg_store.set("static_ip_unlocked", True)
        increment = 0

    new_limit = cur_limit + increment
    cfg_store.set("max_servers_limit", new_limit)
    cfg_store.set("servers_unlocked", True)

    redeemed_entry = {
        "code": code,
        "product_id": product_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "active"
    }
    redeemed_history.append(redeemed_entry)
    cfg_store.set("redeemed_codes", redeemed_history)
    cfg_store.save()

    if product_id == "static_ip":
        msg = backend_msg or f"Static IP code '{code}' claimed! Dedicated static IP routing unlocked."
    else:
        msg = backend_msg or f"Code '{code}' successfully claimed! Your server hosting capacity increased to {new_limit} dedicated server slot{'s' if new_limit > 1 else ''}."

    return jsonify({
        "success": True,
        "message": msg,
        "new_limit": new_limit,
        "product_id": product_id,
        "codes": redeemed_history
    })

@app.route("/api/user/redeemed-codes", methods=["GET"])
def get_user_redeemed_codes():
    redeemed_history = cfg_store.get("redeemed_codes", [])
    if not isinstance(redeemed_history, list):
        redeemed_history = []

    # Sync with backend server database
    token = cfg_store.get("auth_token", "")
    if token:
        try:
            res_json, status_code, ok = endpoints.get_json_response(
                cfg_store,
                "/api/user/codes",
                params={"token": token},
                timeout=3
            )
            if ok and isinstance(res_json, dict):
                s_codes = res_json.get("codes", [])
                existing_codes = {c.get("code") for c in redeemed_history if isinstance(c, dict)}
                for sc in s_codes:
                    if sc.get("code") not in existing_codes:
                        redeemed_history.append({
                            "code": sc.get("code"),
                            "product_id": sc.get("product_id", "server_slot"),
                            "date": datetime.fromtimestamp(sc.get("redeemed_at", time.time())).strftime("%Y-%m-%d %H:%M:%S") if sc.get("redeemed_at") else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "status": "active"
                        })
                cfg_store.set("redeemed_codes", redeemed_history)
                cfg_store.save()
        except Exception:
            pass

    return jsonify({
        "codes": redeemed_history,
        "max_servers_limit": int(cfg_store.get("max_servers_limit", 1))
    })

@app.route("/api/servers/instances", methods=["GET"])
def list_server_instances():
    """Return all dedicated server instances with live session telemetry & quota."""
    unlocked = bool(cfg_store.get("servers_unlocked", False))
    server_candidates = _get_server_candidates()
    used_quota, limit_quota = _server_quota()

    res = []
    for inst in server_candidates:
        sdir = server_host.server_dir(inst)
        active_sess = session_mgr.running_for(inst)
        storage_mb = _folder_storage_mb(sdir)

        if active_sess:
            snap = active_sess.resource_snapshot()
            status = active_sess.status
            message = active_sess.message
            address = active_sess.join_address()
            cpu_pct = snap.get("cpu_percent") or 0.0
            ram_used = snap.get("ram_used_mb") or 0
            ram_alloc = active_sess.ram_mb
            players = list(active_sess.players)
            uptime = active_sess.uptime()
            session_id = active_sess.id
        else:
            status = "stopped"
            message = "Server is stopped"
            address = f"localhost:{server_host.server_port(inst)}"
            cpu_pct = 0.0
            ram_used = 0
            ram_alloc = inst.data.get("ram_mb", 2048)
            players = []
            uptime = None
            session_id = None

        acc_data = _read_server_access(sdir)
        access_users = acc_data.get("users", [])

        res.append({
            "id": inst.id,
            "instance_id": inst.id,
            "name": inst.name,
            "mc_version": inst.mc_version,
            "loader": inst.loader,
            "server_type": inst.loader,
            "status": status,
            "message": message,
            "port": server_host.server_port(inst),
            "public_address": inst.data.get("static_domain") or address,
            "tunnel_address": inst.data.get("static_domain") or address,
            "static_domain": inst.data.get("static_domain", ""),
            "bore_static_port": inst.data.get("bore_static_port", ""),
            "playit_secret": inst.data.get("playit_secret", ""),
            "tunnel_provider": inst.data.get("tunnel_provider", "bore"),
            "icon": inst.data.get("icon") or inst.data.get("custom_icon") or "/assets/icon_mono.png",
            "custom_icon": inst.data.get("custom_icon") or (f"/api/servers/{inst.id}/icon" if os.path.isfile(os.path.join(sdir, "icon.png")) or os.path.isfile(os.path.join(sdir, "server-icon.png")) else "/assets/icon_mono.png"),
            "players": players,
            "players_count": len(players),
            "max_players": 20,
            "uptime": uptime,
            "cpu_percent": cpu_pct,
            "ram_used_mb": ram_used,
            "ram_allocated_mb": ram_alloc,
            "storage_mb": storage_mb,
            "session_id": session_id,
            "server_dir": sdir,
            "is_paper": inst.loader in ("paper", "purpur", "spigot"),
            "access_users": access_users,
        })
    return jsonify({
        "servers": res,
        "unlocked": unlocked,
        "quota": {
            "used": len(server_candidates),
            "limit": limit_quota,
        }
    })

@app.route("/api/servers/<instance_id>/open-window", methods=["POST", "GET"])
def open_server_panel_window(instance_id):
    """Opens dedicated server management window in a native pywebview window if desktop mode is active."""
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server instance not found"}), 404

    server_title = f"Divine Server Panel — {inst.name} ({inst.loader.upper()} {inst.mc_version})"
    opened_native = False

    try:
        import webview
        if hasattr(webview, "create_window") and hasattr(webview, "windows") and len(webview.windows) > 0:
            port = int(request.host.split(":")[-1]) if ":" in request.host else 8080
            url = f"http://127.0.0.1:{port}/server.html?id={inst.id}"
            webview.create_window(
                server_title,
                url=url,
                width=1220,
                height=800,
                min_size=(960, 600),
                background_color="#080c14",
            )
            opened_native = True
    except Exception:
        opened_native = False

    return jsonify({
        "success": True,
        "instance_id": inst.id,
        "name": inst.name,
        "opened_native": opened_native,
        "url": f"/server.html?id={inst.id}"
    })

@app.route("/api/servers/sessions", methods=["GET"])
def list_server_sessions():
    res = []
    for s in session_mgr.all_sessions():
        snap = s.resource_snapshot()
        sdir = server_host.server_dir(s.instance)
        storage_mb = _folder_storage_mb(sdir)
        res.append({
            "id": s.id,
            "instance_id": s.instance.id,
            "instance_name": s.instance.name,
            "mc_version": s.instance.mc_version,
            "loader": s.instance.loader,
            "status": s.status,
            "message": s.message,
            "error": s.error,
            "port": s.port,
            "public_address": s.instance.data.get("static_domain") or s.join_address(),
            "players": list(s.players),
            "uptime": s.uptime(),
            "cpu_percent": snap.get("cpu_percent", 0.0),
            "ram_used_mb": snap.get("ram_used_mb", 0),
            "ram_allocated_mb": s.ram_mb,
            "storage_mb": storage_mb,
        })
    return jsonify({"sessions": res, "unlocked": bool(cfg_store.get("servers_unlocked", False))})

@app.route("/api/servers/clear-data", methods=["POST"])
def clear_all_servers_data():
    """Stop all running server sessions, delete dedicated server files, and reset server instances."""
    # 1. Stop all active server sessions
    for sess in list(session_mgr.all_sessions()):
        try:
            sess.kill()
        except Exception:
            pass

    # 2. Clear server manager
    server_mgr.clear_all()

    # 3. Clear server directories from servers_root
    s_root = server_host.servers_root()
    if os.path.isdir(s_root):
        for item in os.listdir(s_root):
            ipath = os.path.join(s_root, item)
            try:
                if os.path.isdir(ipath):
                    shutil.rmtree(ipath, ignore_errors=True)
                else:
                    os.remove(ipath)
            except OSError:
                pass

    # 4. Remove dedicated server instances from inst_mgr
    inst_mgr.load()
    inst_mgr.instances = [
        i for i in inst_mgr.instances
        if not (i.data.get("is_server") or i.loader in ("paper", "purpur", "spigot", "bukkit"))
    ]
    inst_mgr.save()

    return jsonify({
        "success": True,
        "message": "All dedicated server data, files, and running sessions cleared successfully."
    })

@app.route("/api/servers/<instance_id>/delete", methods=["POST", "DELETE"])
def delete_dedicated_server(instance_id):
    instance_id = urllib.parse.unquote(instance_id).strip()

    # 1. Stop and kill any active server session
    for sess in list(session_mgr.all_sessions()):
        if sess.instance and (sess.instance.id == instance_id or getattr(sess, "id", "") == instance_id):
            try:
                sess.kill()
            except Exception:
                pass
            session_mgr.forget(sess)

    inst = _get_server(instance_id)
    if inst:
        sess = session_mgr.running_for(inst)
        if sess:
            try:
                sess.kill()
            except Exception:
                pass
            session_mgr.forget(sess)

    # 2. Delete from server manager & disk
    server_mgr.load()
    server_mgr.delete(instance_id, remove_files=True)

    # 3. If also in instance manager, remove it
    inst_mgr.load()
    if inst_mgr.get(instance_id):
        inst_mgr.delete(instance_id, remove_files=True)

    # 4. Forcefully delete all possible server directories on disk
    sdir1 = os.path.join(server_mgr.servers_root, instance_id)
    sdir2 = os.path.join(paths.get_game_dir(), "servers", instance_id)
    cdir = os.path.join(paths.get_game_dir(), "instances", instance_id)
    for d in (sdir1, sdir2, cdir):
        if os.path.exists(d):
            for _ in range(3):
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    if not os.path.exists(d):
                        break
                    time.sleep(0.05)
                except Exception:
                    pass
            if os.path.exists(d):
                try:
                    for root, dirs, files in os.walk(d):
                        for f in files:
                            try:
                                os.chmod(os.path.join(root, f), 0o777)
                                os.remove(os.path.join(root, f))
                            except Exception:
                                pass
                    shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass

    # 5. Reload server manager and instance manager
    server_mgr.save()
    inst_mgr.save()
    server_mgr.load()
    inst_mgr.load()

    return jsonify({"success": True})

@app.route("/api/servers/<instance_id>/open-folder", methods=["POST"])
def open_server_folder(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    os.makedirs(sdir, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(sdir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", sdir])
        else:
            subprocess.Popen(["xdg-open", sdir])
        return jsonify({"success": True, "path": sdir})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files", methods=["GET"])
def list_server_directory_files(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    sub = (request.args.get("sub") or "").replace("\\", "/").strip("/")
    target = os.path.abspath(os.path.join(sdir, sub)) if sub else sdir

    if not target.startswith(sdir):
        return jsonify({"error": "Access denied"}), 403

    os.makedirs(target, exist_ok=True)
    items = []
    try:
        for entry in sorted(os.listdir(target)):
            if entry.startswith("."):
                continue
            full = os.path.join(target, entry)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if not is_dir else 0
            mtime = os.path.getmtime(full)
            rel = os.path.relpath(full, sdir).replace(os.sep, "/")
            items.append({
                "name": entry,
                "rel_path": rel,
                "is_dir": is_dir,
                "size_bytes": size,
                "size_human": f"{size / 1024:.1f} KB" if size < 1024*1024 else f"{size / (1024*1024):.1f} MB",
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"files": items, "current_sub": sub, "server_dir": sdir})

@app.route("/api/servers/<instance_id>/files/read", methods=["GET"])
def read_server_file_content(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    rel = (request.args.get("file") or "").replace("\\", "/").lstrip("/")
    target = os.path.abspath(os.path.join(sdir, rel))

    if not target.startswith(sdir) or not os.path.isfile(target):
        return jsonify({"error": "File not found"}), 404

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(500000)  # max 500KB text
        return jsonify({"content": content, "filename": os.path.basename(target), "file": rel})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files/write", methods=["POST"])
def write_server_file_content(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    data = request.json or {}
    rel = (data.get("file") or "").replace("\\", "/").lstrip("/")
    content = data.get("content", "")
    target = os.path.abspath(os.path.join(sdir, rel))

    if not target.startswith(sdir):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files/delete", methods=["POST"])
def delete_server_file(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    data = request.json or {}
    rel = (data.get("file") or "").replace("\\", "/").lstrip("/")
    target = os.path.abspath(os.path.join(sdir, rel))

    if not target.startswith(sdir) or target == sdir:
        return jsonify({"error": "Access denied"}), 403

    try:
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.isfile(target):
            os.remove(target)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files/create-folder", methods=["POST"])
def create_server_folder(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    data = request.json or {}
    rel = (data.get("folder") or data.get("path") or "").replace("\\", "/").strip("/")
    if not rel:
        return jsonify({"error": "Folder name is required"}), 400
    target = os.path.abspath(os.path.join(sdir, rel))
    if not target.startswith(sdir):
        return jsonify({"error": "Access denied"}), 403
    try:
        os.makedirs(target, exist_ok=True)
        return jsonify({"success": True, "created": rel})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files/rename", methods=["POST"])
def rename_server_file(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    data = request.json or {}
    old_rel = (data.get("old_path") or "").replace("\\", "/").lstrip("/")
    new_rel = (data.get("new_path") or "").replace("\\", "/").lstrip("/")
    if not old_rel or not new_rel:
        return jsonify({"error": "Both old_path and new_path are required"}), 400
    src = os.path.abspath(os.path.join(sdir, old_rel))
    dest = os.path.abspath(os.path.join(sdir, new_rel))
    if not src.startswith(sdir) or not dest.startswith(sdir):
        return jsonify({"error": "Access denied"}), 403
    if not os.path.exists(src):
        return jsonify({"error": "Source item does not exist"}), 404
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/servers/<instance_id>/files/upload", methods=["POST"])
def upload_server_file(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    sub = (request.form.get("sub") or request.args.get("sub") or "").replace("\\", "/").strip("/")
    target_dir = os.path.abspath(os.path.join(sdir, sub)) if sub else sdir
    if not target_dir.startswith(sdir):
        return jsonify({"error": "Access denied"}), 403
    os.makedirs(target_dir, exist_ok=True)

    # 1. Handle multipart files
    uploaded_files = request.files.getlist("file")
    if uploaded_files:
        saved = []
        for f in uploaded_files:
            if f.filename:
                fn = os.path.basename(f.filename)
                fp = os.path.join(target_dir, fn)
                f.save(fp)
                saved.append(fn)
        return jsonify({"success": True, "files": saved})

    # 2. Handle base64 / json upload
    data = request.json or {}
    fn = data.get("filename")
    content_b64 = data.get("content_base64")
    content_str = data.get("content")
    if fn:
        fn = os.path.basename(fn)
        fp = os.path.join(target_dir, fn)
        if content_b64:
            import base64
            with open(fp, "wb") as f:
                f.write(base64.b64decode(content_b64))
        elif content_str is not None:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content_str)
        return jsonify({"success": True, "file": fn})

    return jsonify({"error": "No file uploaded"}), 400

@app.route("/api/servers/<instance_id>/files/download", methods=["GET"])
def download_server_file(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    rel = (request.args.get("file") or "").replace("\\", "/").lstrip("/")
    target = os.path.abspath(os.path.join(sdir, rel))
    if not target.startswith(sdir) or not os.path.isfile(target):
        return jsonify({"error": "File not found"}), 404
    return send_file(target, as_attachment=True, download_name=os.path.basename(target))

def _read_server_access(sdir):
    acc_file = os.path.join(sdir, "access.json")
    if os.path.isfile(acc_file):
        try:
            with open(acc_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {"users": []}

def _write_server_access(sdir, data):
    acc_file = os.path.join(sdir, "access.json")
    os.makedirs(sdir, exist_ok=True)
    with open(acc_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@app.route("/api/servers/<instance_id>/access", methods=["GET"])
def get_server_access_list(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"users": [], "owner": "Server Owner", "success": True, "error": None})
    try:
        sdir = server_host.server_dir(inst)
        os.makedirs(sdir, exist_ok=True)
        acc_data = _read_server_access(sdir)
        active_acc = acc_store.get_active()
        owner = active_acc.name if active_acc else "Server Owner"
        return jsonify({"users": acc_data.get("users", []), "owner": owner, "success": True})
    except Exception as e:
        return jsonify({"users": [], "owner": "Server Owner", "success": True, "error": str(e)})

@app.route("/api/servers/<instance_id>/access/add", methods=["POST"])
def add_server_sub_user(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server instance not found", "success": False}), 404
    try:
        sdir = server_host.server_dir(inst)
        os.makedirs(sdir, exist_ok=True)
        data = request.json or {}
        username = (data.get("username") or "").strip()
        if not username:
            return jsonify({"error": "Username or Discord ID is required", "success": False}), 400

        permissions = data.get("permissions", ["power", "console", "files", "players", "network"])
        acc_data = _read_server_access(sdir)
        users = acc_data.get("users", [])

        existing = next((u for u in users if u.get("username") == username), None)
        if existing:
            existing["permissions"] = permissions
            existing["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            users.append({
                "username": username,
                "permissions": permissions,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        acc_data["users"] = users
        _write_server_access(sdir, acc_data)
        return jsonify({"success": True, "users": users, "message": f"Access granted to '{username}'."})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/api/servers/<instance_id>/access/remove", methods=["POST"])
def remove_server_sub_user(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server instance not found", "success": False}), 404
    try:
        sdir = server_host.server_dir(inst)
        data = request.json or {}
        username = (data.get("username") or "").strip()
        if not username:
            return jsonify({"error": "Username is required", "success": False}), 400

        acc_data = _read_server_access(sdir)
        users = [u for u in acc_data.get("users", []) if u.get("username") != username]
        acc_data["users"] = users
        _write_server_access(sdir, acc_data)
        return jsonify({"success": True, "users": users, "message": f"Access revoked for '{username}'."})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/api/servers/<instance_id>/whitelist", methods=["GET", "POST"])
def server_whitelist_handler(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    wfile = os.path.join(sdir, "whitelist.json")

    if request.method == "POST":
        data = request.json or {}
        players = data.get("players", [])
        try:
            formatted = []
            for p in players:
                if isinstance(p, dict):
                    formatted.append(p)
                elif isinstance(p, str) and p.strip():
                    formatted.append({"name": p.strip(), "uuid": ""})
            with open(wfile, "w", encoding="utf-8") as f:
                json.dump(formatted, f, indent=2)
            return jsonify({"success": True, "players": formatted})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # GET
    players = []
    if os.path.isfile(wfile):
        try:
            with open(wfile, "r", encoding="utf-8") as f:
                players = json.load(f)
        except Exception:
            players = []
    return jsonify({"players": players})

@app.route("/api/servers/<instance_id>/ops", methods=["GET", "POST"])
def server_ops_handler(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404
    sdir = server_host.server_dir(inst)
    ofile = os.path.join(sdir, "ops.json")

    if request.method == "POST":
        data = request.json or {}
        ops = data.get("ops", [])
        try:
            formatted = []
            for o in ops:
                if isinstance(o, dict):
                    formatted.append(o)
                elif isinstance(o, str) and o.strip():
                    formatted.append({"name": o.strip(), "uuid": "", "level": 4, "bypassesPlayerLimit": False})
            with open(ofile, "w", encoding="utf-8") as f:
                json.dump(formatted, f, indent=2)
            return jsonify({"success": True, "ops": formatted})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # GET
    ops = []
    if os.path.isfile(ofile):
        try:
            with open(ofile, "r", encoding="utf-8") as f:
                ops = json.load(f)
        except Exception:
            ops = []
    return jsonify({"ops": ops})

@app.route("/api/servers/start", methods=["POST"])
def start_server_session():
    ban_info = social.check_ban(cfg_store)
    if ban_info.get("banned"):
        return jsonify({"error": ban_info.get("reason", "Your client device is banned."), "banned": True, "ban_info": ban_info}), 403

    data = request.json or {}
    instance_id = data.get("instance_id")
    ram_mb = int(data.get("ram_mb", 2048))
    tunnel_provider = data.get("tunnel_provider", "bore")

    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Instance not found"}), 404

    try:
        session = session_mgr.start(inst, ram_mb=ram_mb, tunnel_provider=tunnel_provider, open_window=False)
        return jsonify({
            "success": True,
            "session_id": session.id,
            "status": session.status,
            "port": session.port,
            "join_address": session.join_address(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

def _resolve_session(target_id):
    if not target_id:
        return None
    sess = session_mgr.get(target_id)
    if sess:
        return sess
    # Check by instance_id
    inst = _get_server(target_id)
    if inst:
        return session_mgr.running_for(inst)
    for s in session_mgr.all_sessions():
        if s.instance and (s.instance.id == target_id or getattr(s, "id", "") == target_id):
            return s
    return None

@app.route("/api/servers/<session_id>/stop", methods=["POST"])
def stop_server_session(session_id):
    session = _resolve_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    session.stop()
    return jsonify({"success": True})

@app.route("/api/servers/<session_id>/restart", methods=["POST"])
def restart_server_session(session_id):
    session = _resolve_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    session.restart()
    return jsonify({"success": True})

@app.route("/api/servers/<session_id>/kill", methods=["POST"])
def kill_server_session(session_id):
    session = _resolve_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    session.kill()
    return jsonify({"success": True})

@app.route("/api/servers/<session_id>/command", methods=["POST"])
def send_server_command(session_id):
    session = _resolve_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    data = request.json or {}
    cmd = data.get("command", "").strip()
    if not cmd:
        return jsonify({"error": "Command required"}), 400
    session.send(cmd)
    return jsonify({"success": True})

@app.route("/api/servers/<session_id>/console", methods=["GET"])
def get_server_console(session_id):
    session = _resolve_session(session_id)
    if not session:
        return jsonify({"error": "Session not found", "lines": [], "status": "stopped"}), 200
    lines = session.history()
    return jsonify({
        "lines": lines,
        "status": session.status,
        "message": session.message,
        "error": session.error,
        "public_address": session.join_address(),
        "players": list(session.players),
        "uptime": session.uptime(),
    })

@app.route("/api/servers/<instance_id>/info", methods=["GET"])
def get_server_detail_info(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    sdir = server_host.server_dir(inst)
    active_sess = session_mgr.running_for(inst)
    storage_mb = _folder_storage_mb(sdir)

    if active_sess:
        snap = active_sess.resource_snapshot()
        status = active_sess.status
        message = active_sess.message
        address = active_sess.join_address()
        cpu_pct = snap.get("cpu_percent") or 0.0
        ram_used = snap.get("ram_used_mb") or 0
        ram_alloc = active_sess.ram_mb
        players = list(active_sess.players)
        uptime = active_sess.uptime()
        session_id = active_sess.id
    else:
        status = "stopped"
        message = "Server is stopped"
        address = f"localhost:{server_host.server_port(inst)}"
        cpu_pct = 0.0
        ram_used = 0
        ram_alloc = inst.data.get("ram_mb", 2048)
        players = []
        uptime = None
        session_id = None

    return jsonify({
        "success": True,
        "id": inst.id,
        "instance_id": inst.id,
        "name": inst.name,
        "mc_version": inst.mc_version,
        "loader": inst.loader,
        "status": status,
        "message": message,
        "port": server_host.server_port(inst),
        "public_address": inst.data.get("static_domain") or address,
        "static_domain": inst.data.get("static_domain", ""),
        "bore_static_port": inst.data.get("bore_static_port", ""),
        "playit_secret": inst.data.get("playit_secret", ""),
        "tunnel_provider": inst.data.get("tunnel_provider", "bore"),
        "icon": inst.data.get("icon") or inst.data.get("custom_icon") or "/assets/icon_mono.png",
        "custom_icon": inst.data.get("custom_icon") or (f"/api/servers/{inst.id}/icon" if os.path.isfile(os.path.join(sdir, "icon.png")) or os.path.isfile(os.path.join(sdir, "server-icon.png")) else "/assets/icon_mono.png"),
        "players": players,
        "players_count": len(players),
        "max_players": int(server_host.read_properties(inst).get("max-players", 20)),
        "uptime": uptime,
        "cpu_percent": cpu_pct,
        "ram_used_mb": ram_used,
        "ram_allocated_mb": ram_alloc,
        "storage_mb": storage_mb,
        "session_id": session_id,
        "server_dir": sdir,
        "is_paper": inst.loader in ("paper", "purpur", "spigot"),
    })

@app.route("/api/servers/<instance_id>/properties", methods=["GET", "POST"])
def server_properties_api(instance_id):
    return server_properties_full(instance_id)

@app.route("/api/servers/<instance_id>/plugins", methods=["GET"])
def server_plugins_api(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    sdir = server_host.server_dir(inst)
    pdir = os.path.join(sdir, "plugins")
    os.makedirs(pdir, exist_ok=True)
    items = []
    try:
        for f in sorted(os.listdir(pdir)):
            if f.endswith(".jar") or f.endswith(".jar.disabled"):
                fp = os.path.join(pdir, f)
                items.append({
                    "filename": f,
                    "enabled": not f.endswith(".disabled"),
                    "size_bytes": os.path.getsize(fp),
                    "size_human": f"{os.path.getsize(fp) / 1024:.1f} KB",
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"plugins": items, "server_dir": sdir})

@app.route("/api/servers/<instance_id>/plugins/install", methods=["POST"])
def server_plugin_install_api(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    sdir = server_host.server_dir(inst)
    pdir = os.path.join(sdir, "plugins")
    os.makedirs(pdir, exist_ok=True)
    data = request.json or {}
    project_id = data.get("project_id") or data.get("slug")
    if not project_id:
        return jsonify({"error": "Project ID required"}), 400
    try:
        import urllib.request
        from .core import modrinth
        versions = None
        for ldr in ("paper", "purpur", "spigot", "bukkit", None):
            versions = modrinth.get_versions(project_id, mc_version=inst.mc_version, loader=ldr)
            if versions:
                break
        if not versions:
            versions = modrinth.get_versions(project_id, mc_version=None, loader=None)
        if not versions:
            return jsonify({"error": "No compatible build found on Modrinth"}), 404
        ver = versions[0]
        dl_url = ver.get("url")
        fn = ver.get("filename")
        if not dl_url or not fn:
            return jsonify({"error": "Invalid download URL for plugin"}), 500
        target = os.path.join(pdir, os.path.basename(fn))
        req = urllib.request.Request(dl_url, headers={"User-Agent": "DivineClient/2.0"})
        with urllib.request.urlopen(req, timeout=25) as resp, open(target, "wb") as out_f:
            out_f.write(resp.read())
        return jsonify({"success": True, "filename": fn, "message": f"Plugin '{fn}' installed successfully!"})
    except Exception as exc:
        return jsonify({"error": f"Failed to install plugin: {exc}"}), 500

@app.route("/api/servers/<instance_id>/plugins/delete", methods=["POST"])
def server_plugin_delete_api(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    sdir = server_host.server_dir(inst)
    pdir = os.path.join(sdir, "plugins")
    data = request.json or {}
    fn = data.get("filename")
    if not fn:
        return jsonify({"error": "Filename required"}), 400
    target = os.path.join(pdir, os.path.basename(fn))
    if os.path.isfile(target):
        try:
            os.remove(target)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route("/api/servers/<instance_id>/network", methods=["GET", "POST"])
def server_network_settings(instance_id):
    inst = _get_server(instance_id)
    if not inst:
        return jsonify({"error": "Server not found"}), 404
    if request.method == "POST":
        data = request.json or {}
        inst.data["tunnel_provider"] = data.get("tunnel_provider", "bore")
        inst.data["static_domain"] = data.get("static_domain", "").strip()
        inst.data["bore_static_port"] = data.get("bore_static_port", "").strip()
        inst.data["playit_secret"] = data.get("playit_secret", "").strip()
        if hasattr(server_mgr, "save"):
            server_mgr.save()
        if hasattr(inst_mgr, "save"):
            inst_mgr.save()
        return jsonify({"success": True, "server": inst.to_dict()})

    return jsonify({
        "tunnel_provider": inst.data.get("tunnel_provider", "bore"),
        "static_domain": inst.data.get("static_domain", ""),
        "bore_static_port": inst.data.get("bore_static_port", ""),
        "playit_secret": inst.data.get("playit_secret", ""),
    })


# -----------------------------------------------------------------------------
# Accounts API
# -----------------------------------------------------------------------------

@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    acc_store.load()
    return jsonify({
        "accounts": acc_store.accounts,
        "active_id": acc_store.active_id,
    })

@app.route("/api/accounts/active", methods=["POST"])
def set_active_account():
    data = request.json or {}
    acc_id = data.get("account_id")
    if not acc_id:
        return jsonify({"error": "Account ID required"}), 400
    acc_store.set_active(acc_id)
    return jsonify({"success": True, "active_id": acc_store.active_id})

@app.route("/api/accounts/offline", methods=["POST"])
def add_offline_account():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username required"}), 400
    acc = acc_store.add_offline(username)
    return jsonify({"success": True, "account": acc})

@app.route("/api/accounts/microsoft/start", methods=["POST"])
def start_ms_auth():
    try:
        data = accounts.start_device_login()
        return jsonify({
            "success": True,
            "data": data,
            "user_code": data.get("user_code"),
            "device_code": data.get("device_code"),
            "verification_uri": data.get("verification_uri", "https://www.microsoft.com/link"),
            "interval": data.get("interval", 5),
            "expires_in": data.get("expires_in", 900),
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/api/accounts/microsoft/poll", methods=["POST"])
def poll_ms_auth():
    data = request.json or {}
    device_code = data.get("device_code")
    if not device_code:
        return jsonify({"status": "error", "error": "device_code is required"}), 400

    try:
        token = accounts._poll_device_token(device_code)
        if token is None:
            return jsonify({"status": "pending"})
        mc_login = accounts._minecraft_from_ms_token(token)
        acc = acc_store.add_microsoft(mc_login)
        acc_store.set_active(acc["id"])
        return jsonify({"status": "complete", "account": acc, "active_id": acc["id"]})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route("/api/accounts/<account_id>", methods=["DELETE"])
def delete_account(account_id):
    acc_store.load()
    acc_store.remove(account_id)
    return jsonify({"success": True, "accounts": acc_store.accounts, "active_id": acc_store.active_id})


# -----------------------------------------------------------------------------
# News & Social Presence API
# -----------------------------------------------------------------------------

@app.route("/api/news", methods=["GET"])
def get_news_feed():
    try:
        feed = news.get_news(cfg_store)
        return jsonify({"news": feed})
    except Exception as e:
        return jsonify({"news": [
            {"title": "Divine Client 2.0 WebUI", "tag": "Update", "body": "Welcome to the all-new ultra-fast web-powered Divine Client interface!", "url": ""},
            {"title": "Dedicated Server Hosting", "tag": "Feature", "body": "Host worlds directly with built-in Bore tunnels for zero-config multiplayer.", "url": ""},
        ]})

LOCAL_FRIENDS_PATH = os.path.join(paths.DATA_DIR, "local_friends.json")
LOCAL_REQUESTS_PATH = os.path.join(paths.DATA_DIR, "friend_requests.json")

# Divine Network Registered Player Database
DEFAULT_COMMUNITY_PLAYERS = []

def _load_player_database():
    """Load all registered players from verified registry, local accounts, and SQLite database."""
    players = {}
    
    # 1. Include verified Divine Network players
    for uname, p in ingame_bridge.VERIFIED_DIVINE_PLAYERS.items():
        players[uname.lower()] = {
            "username": p["username"],
            "status": p.get("status", "online"),
            "presence_detail": p.get("presence_detail", "Online in Divine Client"),
            "avatar_url": f"https://minotar.net/helm/{p['username']}/36.png",
            "badge": p.get("badge", "badge_divine_sun_white"),
            "badge_name": p.get("badge_name", "Divine Pure White Sun"),
            "rank": p.get("rank", "Divine User"),
            "verified": True
        }

    # 2. Include all local saved launcher accounts
    try:
        acc_store.load()
        for acc in acc_store.accounts:
            name = acc.name or acc.username
            if name and name.lower() not in players:
                players[name.lower()] = {
                    "username": name,
                    "status": "online",
                    "presence_detail": "Online in Divine Client",
                    "avatar_url": f"https://minotar.net/helm/{name}/36.png",
                    "badge": "badge_divine_sun_white",
                    "badge_name": "Divine Pure White Sun",
                    "rank": "Divine Player",
                    "verified": True
                }
    except Exception:
        pass

    # 3. Include database users from server/db.py if available
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from server import db as server_db
        conn = server_db.get_conn()
        rows = conn.execute("SELECT username, presence, presence_detail, avatar_url FROM users").fetchall()
        for r in rows:
            uname = r["username"]
            if uname and uname.lower() not in players:
                players[uname.lower()] = {
                    "username": uname,
                    "status": r["presence"] or "online",
                    "presence_detail": r["presence_detail"] or "Online",
                    "avatar_url": r["avatar_url"] or f"https://minotar.net/helm/{uname}/36.png",
                    "badge": "badge_divine_sun_white",
                    "badge_name": "Divine Pure White Sun",
                    "rank": "Divine User",
                    "verified": True
                }
    except Exception:
        pass

    return players

def _load_friend_requests():
    try:
        if os.path.isfile(LOCAL_REQUESTS_PATH):
            with open(LOCAL_REQUESTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "incoming": data.get("incoming", []),
                        "outgoing": data.get("outgoing", [])
                    }
    except Exception:
        pass
    return {"incoming": [], "outgoing": []}

def _save_friend_requests(data):
    try:
        paths.ensure_dirs()
        with open(LOCAL_REQUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _load_local_friends():
    try:
        if os.path.isfile(LOCAL_FRIENDS_PATH):
            with open(LOCAL_FRIENDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [f for f in data if f.get("username") not in ("Solaris", "Divine Community Bot")]
    except Exception:
        pass
    return []

def _save_local_friends(friends_list):
    try:
        paths.ensure_dirs()
        clean_list = [f for f in friends_list if f.get("id") != "discord_divine_bot" and f.get("username") != "Divine Community Bot"]
        with open(LOCAL_FRIENDS_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_list, f, indent=2)
    except Exception:
        pass

@app.route("/api/social/friends", methods=["GET"])
def get_friends_list():
    friends = _load_local_friends()
    reqs = _load_friend_requests()
    incoming = reqs.get("incoming", [])
    outgoing = reqs.get("outgoing", [])

    return jsonify({
        "friends": friends,
        "incoming": incoming,
        "outgoing": outgoing,
        "linked": True,
        "discord_profile": None
    })

@app.route("/api/social/players/search", methods=["GET"])
def search_players_db():
    q = (request.args.get("q") or "").strip().lower()
    db = _load_player_database()
    results = []
    for k, p in db.items():
        if not q or q in k:
            results.append(p)
    return jsonify({"players": results[:20]})

@app.route("/api/social/friends/add", methods=["POST"])
def add_friend_route():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Enter a player username."}), 400
    
    # Check verified user database
    db = _load_player_database()
    target = db.get(username.lower())
    
    # Strictly enforce that target player must have a linked Divine account
    if not target or not target.get("verified", False):
        # Look up via bridge in case of recent sync
        bridge_info = ingame_bridge.lookup_player_badge(username)
        if bridge_info.get("verified"):
            target = {
                "username": bridge_info["username"],
                "status": bridge_info.get("status", "online"),
                "presence_detail": bridge_info.get("presence_detail", "Online in Divine Client"),
                "avatar_url": f"https://minotar.net/helm/{bridge_info['username']}/36.png",
                "badge": bridge_info.get("badge", "badge_divine_sun_white"),
                "verified": True
            }
        else:
            return jsonify({
                "error": f"Player '{username}' does not have a linked Divine Client account. Only players registered on the Divine Network can be added as friends.",
                "found": False
            }), 404

    target_name = target["username"]
    friends = _load_local_friends()
    if any(f.get("username", "").lower() == target_name.lower() for f in friends):
        return jsonify({"success": True, "message": f"{target_name} is already in your friends list!"})

    reqs = _load_friend_requests()
    if any(r.get("username", "").lower() == target_name.lower() for r in reqs.get("outgoing", [])):
        return jsonify({"success": True, "message": f"Friend request to {target_name} is already pending."})

    # Add to outgoing requests & local friends
    new_req = {
        "id": f"req_{int(time.time()*1000)}",
        "username": target_name,
        "avatar_url": target.get("avatar_url") or f"https://minotar.net/helm/{target_name}/36.png",
        "badge": target.get("badge", "badge_divine_sun_white"),
        "sent_at": time.time()
    }
    reqs["outgoing"].append(new_req)
    _save_friend_requests(reqs)

    new_friend = {
        "id": "fr_" + target_name.lower().replace(" ", "_"),
        "username": target_name,
        "online": True,
        "status": target.get("status", "online"),
        "presence": target.get("status", "online"),
        "presence_detail": target.get("presence_detail", "Online in Divine Client"),
        "avatar_url": target.get("avatar_url") or f"https://minotar.net/helm/{target_name}/36.png",
        "badge": target.get("badge", "badge_divine_sun_white"),
        "added_at": time.time()
    }
    friends.append(new_friend)
    _save_local_friends(friends)

    if social.is_linked(cfg_store):
        try:
            social.add_friend(cfg_store, username)
        except Exception:
            pass

    return jsonify({
        "success": True,
        "request": new_req,
        "friend": new_friend,
        "message": f"Friend request sent to {target_name}!"
    })

@app.route("/api/social/friends/accept", methods=["POST"])
def accept_friend_route():
    data = request.json or {}
    user_id = (data.get("user_id") or data.get("id") or "").strip()
    username = (data.get("username") or "").strip()
    
    reqs = _load_friend_requests()
    incoming = reqs.get("incoming", [])
    matched_req = None
    for r in incoming:
        if (user_id and str(r.get("id")) == str(user_id)) or (username and r.get("username", "").lower() == username.lower()):
            matched_req = r
            break

    target_name = matched_req.get("username") if matched_req else (username or user_id)
    if not target_name:
        return jsonify({"error": "User identifier required."}), 400

    # Remove from incoming
    reqs["incoming"] = [r for r in incoming if r != matched_req]
    _save_friend_requests(reqs)

    # Add to friends
    friends = _load_local_friends()
    fid = "fr_" + target_name.lower().replace(" ", "_")
    if not any(f.get("username", "").lower() == target_name.lower() for f in friends):
        new_friend = {
            "id": fid,
            "username": target_name,
            "online": True,
            "status": "online",
            "presence": "online",
            "presence_detail": "Online in Divine Client",
            "avatar_url": matched_req.get("avatar_url") if matched_req else f"https://minotar.net/helm/{target_name}/36.png",
            "added_at": time.time()
        }
        friends.append(new_friend)
        _save_local_friends(friends)

    return jsonify({"success": True, "message": f"Accepted friend request from {target_name}!"})

@app.route("/api/social/friends/decline", methods=["POST"])
def decline_friend_route():
    data = request.json or {}
    user_id = (data.get("user_id") or data.get("id") or "").strip()
    username = (data.get("username") or "").strip()

    reqs = _load_friend_requests()
    reqs["incoming"] = [r for r in reqs.get("incoming", []) if str(r.get("id")) != str(user_id) and r.get("username", "").lower() != username.lower()]
    reqs["outgoing"] = [r for r in reqs.get("outgoing", []) if str(r.get("id")) != str(user_id) and r.get("username", "").lower() != username.lower()]
    _save_friend_requests(reqs)

    return jsonify({"success": True, "message": "Friend request declined."})

@app.route("/api/social/friends/remove", methods=["POST"])
def remove_friend_route():
    data = request.json or {}
    user_id = (data.get("user_id") or data.get("id") or "").strip()
    if not user_id:
        return jsonify({"error": "User ID is required."}), 400
    
    friends = _load_local_friends()
    friends = [f for f in friends if str(f.get("id")) != str(user_id) and str(f.get("username", "")).lower() != str(user_id).lower()]
    _save_local_friends(friends)

    return jsonify({"success": True, "message": "Friend removed."})

@app.route("/api/social/link", methods=["GET"])
def get_social_link():
    return jsonify({
        "linked": social.is_linked(cfg_store),
        "profile": social.get_link() or {}
    })

@app.route("/api/social/discord/local-detect", methods=["GET"])
def detect_discord_local_endpoint():
    det = social.detect_local_discord()
    return jsonify(det)


@app.route("/api/social/discord/auto-link", methods=["POST"])
def auto_link_discord_endpoint():
    data = request.json or {}
    acc = acc_store.get_active()
    default_name = acc.name if acc else "DivinePlayer"
    res = social.auto_link_local_discord(cfg_store, fallback_username=default_name)
    return jsonify(res)


@app.route("/api/social/link/start", methods=["POST"])
def start_social_link():
    try:
        data = social.start_link(cfg_store)
        return jsonify({"success": True, **data})
    except Exception as e:
        # If remote server is offline, generate local link code
        code = f"DIVINE-{secrets.token_hex(2).upper()}"
        link_id = secrets.token_urlsafe(16)
        return jsonify({
            "success": True,
            "code": code,
            "link_id": link_id,
            "verification_url": f"https://discord.gg/ER2haQtach",
            "interval": 2,
            "expires_in": 600
        })

@app.route("/api/social/link/quick-auth", methods=["POST"])
def quick_discord_auth():
    data = request.json or {}
    username = (data.get("username") or "DivinePlayer").strip()
    # Strip any leading @ or invalid characters for Minecraft username compatibility
    clean_username = username.lstrip("@").split("#")[0].strip() or "DivinePlayer"
    discord_id = str(data.get("discord_id") or int(time.time() * 1000) % 1000000000000000000).strip()
    avatar_url = data.get("avatar_url") or f"https://cdn.discordapp.com/embed/avatars/{int(discord_id) % 5 if discord_id.isdigit() else 0}.png"
    
    token = "divine_tok_" + secrets.token_hex(16)
    link = {
        "token": token,
        "id": discord_id,
        "username": username,
        "clean_username": clean_username,
        "avatar_url": avatar_url,
        "linked_at": time.time()
    }
    social._save(link)

    # Auto-register and activate local offline profile for this Discord username if needed
    try:
        acc_store.load()
        existing = [a for a in acc_store.accounts if a.get("name", "").lower() == clean_username.lower()]
        if not existing:
            new_acc = acc_store.add_offline(clean_username)
            acc_store.set_active(new_acc["id"])
        elif not acc_store.active_id:
            acc_store.set_active(existing[0]["id"])
    except Exception as _acc_err:
        print(f"Auto-link profile notice: {_acc_err}")

    _report_social_presence("online", "In Launcher Menus")
    
    return jsonify({
        "success": True,
        "linked": True,
        "profile": link,
        "message": f"Successfully authenticated Discord as {username}!"
    })

@app.route("/api/social/link/poll", methods=["POST"])
def poll_social_link():
    data = request.json or {}
    link_id = data.get("link_id")
    try:
        res = social._request("GET", cfg_store, "/api/link/poll", params={"link_id": link_id})
        status = res.get("status")
        if status == "linked":
            raw_uname = res.get("username", "DivinePlayer")
            clean_uname = raw_uname.lstrip("@").split("#")[0].strip() or "DivinePlayer"
            link = {
                "token": res.get("token", ""),
                "id": res.get("id", ""),
                "username": raw_uname,
                "clean_username": clean_uname,
                "avatar_url": res.get("avatar_url", ""),
                "linked_at": time.time()
            }
            social._save(link)

            try:
                acc_store.load()
                existing = [a for a in acc_store.accounts if a.get("name", "").lower() == clean_uname.lower()]
                if not existing:
                    new_acc = acc_store.add_offline(clean_uname)
                    acc_store.set_active(new_acc["id"])
                elif not acc_store.active_id:
                    acc_store.set_active(existing[0]["id"])
            except Exception:
                pass

            _report_social_presence("online", "In Launcher Menus")
            return jsonify({"success": True, "status": "linked", "profile": link})
        return jsonify({"success": True, "status": status or "pending"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/social/link/unlink", methods=["POST"])
def unlink_social_link():
    social.clear_link()
    return jsonify({"success": True, "linked": False})


# -----------------------------------------------------------------------------
# In-Game Client Mod & Cosmetics Bridge API
# -----------------------------------------------------------------------------

@app.route("/api/ingame/mods", methods=["GET"])
def get_ingame_mods():
    cfg = ingame_bridge.load_mods_config()
    return jsonify({"success": True, "mods": cfg, "count": len(cfg)})

@app.route("/api/ingame/mods/<mod_id>/toggle", methods=["POST"])
def toggle_ingame_mod(mod_id):
    data = request.json or {}
    cfg = ingame_bridge.load_mods_config()
    if mod_id not in cfg:
        return jsonify({"error": f"Mod '{mod_id}' not found."}), 404
    
    current_enabled = cfg[mod_id].get("enabled", False)
    new_state = data.get("enabled", not current_enabled)
    updated = ingame_bridge.set_mod_state(mod_id, enabled=new_state)
    return jsonify({"success": True, "mod": updated})

@app.route("/api/ingame/mods/<mod_id>/options", methods=["POST"])
def update_ingame_mod_options(mod_id):
    data = request.json or {}
    options = data.get("options", data)
    updated = ingame_bridge.set_mod_state(mod_id, options=options)
    if not updated:
        return jsonify({"error": f"Mod '{mod_id}' not found."}), 404
    return jsonify({"success": True, "mod": updated})

@app.route("/api/ingame/cosmetics", methods=["GET"])
@app.route("/api/cosmetics/catalog", methods=["GET"])
def get_cosmetics_catalog():
    data = ingame_bridge.get_full_catalog_with_status()
    redeemed = ingame_bridge.load_redeemed_codes()
    return jsonify({
        "success": True,
        "categories": data["categories"],
        "equipped": data["equipped"],
        "unlocked_count": data["unlocked_count"],
        "redeemed_codes": redeemed
    })

@app.route("/api/ingame/cosmetics/equip", methods=["POST"])
@app.route("/api/cosmetics/equip", methods=["POST"])
def equip_cosmetic_endpoint():
    data = request.json or {}
    slot = data.get("slot")
    item_id = data.get("item_id")
    if not slot:
        return jsonify({"error": "Slot is required (cloak, wings, halo, aura, badge)."}), 400
    try:
        updated = ingame_bridge.equip_cosmetic_item(slot, item_id)
        return jsonify({"success": True, "equipped": updated["equipped"], "state": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/ingame/cosmetics/redeem", methods=["POST"])
@app.route("/api/cosmetics/redeem", methods=["POST"])
def redeem_cosmetic_code_endpoint():
    data = request.json or {}
    code = data.get("code")
    uname = data.get("username") or data.get("user_id") or "local_user"
    res = ingame_bridge.redeem_promo_code(code, user_id=uname)
    if not res.get("success"):
        return jsonify(res), 400
    return jsonify(res)

@app.route("/api/ingame/badge-lookup", methods=["GET"])
def lookup_player_badge_endpoint():
    uname = request.args.get("username") or ""
    info = ingame_bridge.lookup_player_badge(uname)
    return jsonify(info)

@app.route("/api/ingame/sync", methods=["GET"])
def sync_ingame_endpoint():
    uname = request.args.get("username")
    state = ingame_bridge.sync_ingame_state(uname)
    return jsonify(state)

@app.route("/api/ingame/friends", methods=["GET"])
def get_ingame_friends_endpoint():
    friends = _load_local_friends()
    return jsonify({
        "success": True,
        "friends": friends,
        "count": len(friends),
        "sync_note": "Friends are synchronized from Divine Launcher. Use the launcher to add new friends."
    })

@app.route("/api/codes/generate", methods=["POST"])
def generate_code_endpoint():
    data = request.json or {}
    item_type = data.get("item_type", "cloak")
    item_id = data.get("item_id", "cloak_solaris_white")
    title = data.get("title")
    description = data.get("description")
    max_uses = int(data.get("max_uses", 1))
    creator = data.get("creator", "Divine API")

    code_data = ingame_bridge.generate_promo_code(
        item_type=item_type,
        item_id=item_id,
        title=title,
        description=description,
        max_uses=max_uses,
        creator=creator
    )
    return jsonify({"success": True, "code_data": code_data})

@app.route("/api/codes/list", methods=["GET"])
def list_codes_endpoint():
    codes = ingame_bridge.load_generated_codes()
    return jsonify({"success": True, "codes": list(codes.values()), "count": len(codes)})

@app.route("/api/rpc/status", methods=["GET"])
def get_rpc_status_endpoint():
    return jsonify({
        "enabled": bool(discord_presence.enabled),
        "connected": bool(discord_presence.connected),
        "app_id": discord_presence.app_id,
        "details": getattr(discord_presence, "_last_details", "Divine Client"),
        "state": getattr(discord_presence, "_last_state", "Main Menu")
    })

@app.route("/api/rpc/update", methods=["POST"])
def update_rpc_endpoint():
    data = request.json or {}
    details = data.get("details", "Divine Client")
    state = data.get("state", "In Game")
    large_text = data.get("large_text", "Divine Client v4.0.0")
    discord_presence.update(details=details, state=state, large_text=large_text)
    return jsonify({"success": True, "details": details, "state": state})


# -----------------------------------------------------------------------------
# Settings & Java Runtime API
# -----------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
@app.route("/api/config", methods=["GET"])
def get_settings():
    cfg_store.load()
    res = dict(cfg_store.data or {})
    res["settings"] = dict(cfg_store.data or {})
    return jsonify(res)

@app.route("/api/settings", methods=["POST"])
@app.route("/api/config", methods=["POST"])
def save_settings():
    data = request.json or {}
    for k, v in data.items():
        if k != "settings":
            cfg_store.set(k, v)
    cfg_store.save()
    if "discord_rpc" in data:
        try:
            discord_presence.set_enabled(bool(data["discord_rpc"]))
        except Exception:
            pass
    if "discord_app_id" in data:
        try:
            discord_presence.set_app_id(str(data["discord_app_id"]))
        except Exception:
            pass
    return jsonify({"success": True, "settings": cfg_store.data})


@app.route("/api/system/fix-java", methods=["POST", "GET"])
def fix_java_runtime_endpoint():
    """Automatically repairs the Java 21 runtime and fixes missing DLL issues."""
    try:
        existing_21 = adoptium.find_java_exe(21)
        if existing_21 and not java_runtime.runtime_files_ok(existing_21):
            bin_dir = os.path.dirname(existing_21)
            home_dir = os.path.dirname(bin_dir)
            try:
                shutil.rmtree(home_dir, ignore_errors=True)
            except Exception:
                pass

        new_exe = adoptium.install(21)
        if not new_exe or not os.path.isfile(new_exe):
            new_exe = java_runtime.find_system_java(21) or java_runtime.find_system_java(17)

        if new_exe:
            cfg_store.set("custom_java_path", new_exe)
            cfg_store.save()

        return jsonify({
            "success": True,
            "java_exe": new_exe,
            "version": 21,
            "message": "Java 21 LTS runtime successfully verified and repaired."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/launch/logs", methods=["GET"])
def get_launch_logs():
    iid = request.args.get("instance_id") or launch_state.get("instance_id") or ""
    log_path = os.path.join(paths.LOG_DIR, iid + ".log") if iid else ""
    if not log_path or not os.path.isfile(log_path):
        try:
            log_files = [os.path.join(paths.LOG_DIR, f) for f in os.listdir(paths.LOG_DIR) if f.endswith(".log")]
            if log_files:
                log_path = max(log_files, key=os.path.getmtime)
        except Exception:
            pass

    logs = ""
    if log_path and os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                logs = f.read()[-50000:]
        except Exception:
            pass
    return jsonify({
        "instance_id": iid,
        "logs": logs,
        "status": launch_state.get("status", "idle"),
        "stage": launch_state.get("stage", "")
    })

@app.route("/api/java/runtimes", methods=["GET"])
def get_java_runtimes():
    system_j = java_runtime.find_system_java(21) or java_runtime.find_system_java(17) or java_runtime.find_system_java(8)
    adoptium_8 = adoptium.find_java_exe(8)
    adoptium_17 = adoptium.find_java_exe(17)
    adoptium_21 = adoptium.find_java_exe(21)

    return jsonify({
        "system_java": system_j,
        "adoptium": {
            "jdk8": adoptium_8,
            "jdk17": adoptium_17,
            "jdk21": adoptium_21,
        }
    })

@app.route("/api/java/install", methods=["POST"])
def install_adoptium_java():
    data = request.json or {}
    version = int(data.get("version", 21))
    try:
        java_exe = adoptium.install(version)
        return jsonify({"success": True, "java_exe": java_exe})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/minecraft/versions", methods=["GET"])
def get_mc_versions():
    try:
        raw = launcher.get_version_list()
        releases = []
        snapshots = []
        betas = []
        alphas = []
        for v in raw:
            vid = v.get("id")
            vtype = v.get("type", "release")
            if vtype == "release":
                releases.append(vid)
            elif vtype == "snapshot":
                snapshots.append(vid)
            elif vtype == "old_beta":
                betas.append(vid)
            elif vtype == "old_alpha":
                alphas.append(vid)
            else:
                snapshots.append(vid)

        fab_supported = list(launcher.get_fabric_supported_versions())
        for ev in ["26.2", "26.1", "1.21.11", "1.21.10", "1.21.4", "1.21.1", "1.20.4"]:
            if ev not in fab_supported:
                fab_supported.insert(0, ev)
        
        paper_all = _get_paper_versions()
        return jsonify({
            "releases": releases,
            "snapshots": snapshots,
            "betas": betas,
            "alphas": alphas,
            "fabric_supported": fab_supported,
            "paper_supported": paper_all or releases,
        })
    except Exception as e:
        fallback_releases = ["26.2", "26.1.2", "26.1.1", "26.1", "1.21.11", "1.21.10", "1.21.9", "1.21.8", "1.21.7", "1.21.6", "1.21.5", "1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21", "1.20.6", "1.20.5", "1.20.4", "1.20.3", "1.20.2", "1.20.1", "1.20", "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19", "1.18.2", "1.18.1", "1.18", "1.17.1", "1.17", "1.16.5", "1.16.4", "1.16.3", "1.16.2", "1.16.1", "1.15.2", "1.15.1", "1.15", "1.14.4", "1.14.3", "1.14.2", "1.14.1", "1.14", "1.13.2", "1.13.1", "1.13", "1.12.2", "1.12.1", "1.12", "1.11.2", "1.10.2", "1.9.4", "1.8.9", "1.8.8"]
        return jsonify({
            "releases": fallback_releases,
            "snapshots": ["26.3-rc-2", "26.3-pre-3", "26.3-snapshot-10", "25w10a", "24w46a"],
            "betas": ["b1.8.1", "b1.7.3"],
            "alphas": ["a1.2.6", "a1.1.2_01"],
            "fabric_supported": fallback_releases[:10],
            "paper_supported": _get_paper_versions(),
            "error": str(e)
        })

_PAPER_VERSIONS_CACHE = {"timestamp": 0, "versions": []}

def _get_paper_versions():
    now = time.time()
    if _PAPER_VERSIONS_CACHE["versions"] and (now - _PAPER_VERSIONS_CACHE["timestamp"] < 1800):
        return _PAPER_VERSIONS_CACHE["versions"]

    # Comprehensive list of all PaperMC release versions in descending order
    default_paper = [
        "1.21.4", "1.21.3", "1.21.1", "1.21",
        "1.20.6", "1.20.5", "1.20.4", "1.20.2", "1.20.1", "1.20",
        "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
        "1.18.2", "1.18.1", "1.18",
        "1.17.1", "1.17",
        "1.16.5", "1.16.4", "1.16.3", "1.16.2", "1.16.1",
        "1.15.2", "1.15.1", "1.15",
        "1.14.4", "1.14.3", "1.14.2", "1.14.1", "1.14",
        "1.13.2", "1.13.1", "1.13",
        "1.12.2", "1.12.1", "1.12",
        "1.11.2", "1.10.2", "1.9.4", "1.8.8", "1.7.10"
    ]
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://fill.papermc.io/v3/projects/paper",
            headers={"User-Agent": "DivineClient/4.0"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.load(resp)
            v_dict = data.get("versions", {})
            fetched = []
            for major_k in sorted(v_dict.keys(), reverse=True):
                minor_list = v_dict[major_k]
                if isinstance(minor_list, list):
                    for v in minor_list:
                        if v not in fetched and not v.endswith("-rc") and not "-pre" in v and not "-rc" in v:
                            fetched.append(v)
            if fetched:
                default_paper = fetched
    except Exception:
        pass

    _PAPER_VERSIONS_CACHE["versions"] = default_paper
    _PAPER_VERSIONS_CACHE["timestamp"] = now
    return default_paper

@app.route("/api/servers/paper-versions", methods=["GET"])
def get_paper_server_versions():
    return jsonify({
        "success": True,
        "versions": _get_paper_versions()
    })

# -----------------------------------------------------------------------------
# Storage & Directory Locations API
# -----------------------------------------------------------------------------

@app.route("/api/storage/locations", methods=["GET"])
def get_storage_locations():
    return jsonify({
        "game_dir": paths.get_game_dir(),
        "instances_dir": paths.get_instances_dir(),
        "data_dir": paths.DATA_DIR,
        "is_default_game_dir": paths.is_default_game_dir(),
        "is_default_instances_dir": paths.is_default_instances_dir(),
        "subs": paths.subs_under_game_dir()
    })

@app.route("/api/storage/locations", methods=["POST"])
def set_storage_locations():
    data = request.json or {}
    new_game_dir = (data.get("game_dir") or "").strip()
    new_instances_dir = (data.get("instances_dir") or "").strip()
    move_files = bool(data.get("move_files", True))

    if not new_game_dir:
        return jsonify({"error": "Game directory path is required"}), 400

    new_game_dir = os.path.abspath(os.path.expanduser(new_game_dir))
    old_game_dir = paths.get_game_dir()

    try:
        os.makedirs(new_game_dir, exist_ok=True)
        if move_files and os.path.normpath(new_game_dir) != os.path.normpath(old_game_dir):
            subs = paths.subs_under_game_dir()
            for sub_name, old_sub_path in subs.items():
                if os.path.exists(old_sub_path):
                    new_sub_path = os.path.join(new_game_dir, sub_name)
                    if not os.path.exists(new_sub_path):
                        try:
                            shutil.move(old_sub_path, new_sub_path)
                        except Exception:
                            pass

        paths.set_game_dir(new_game_dir)
        if new_instances_dir:
            new_instances_dir = os.path.abspath(os.path.expanduser(new_instances_dir))
            os.makedirs(new_instances_dir, exist_ok=True)
            paths.set_instances_dir(new_instances_dir)

        inst_mgr.load()
        return jsonify({
            "success": True,
            "game_dir": paths.get_game_dir(),
            "instances_dir": paths.get_instances_dir()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/storage/open-folder", methods=["POST"])
def open_storage_folder():
    data = request.json or {}
    target_path = data.get("path") or paths.get_game_dir()
    target_path = os.path.abspath(os.path.expanduser(target_path))
    os.makedirs(target_path, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(target_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_path])
        else:
            subprocess.Popen(["xdg-open", target_path])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Auto-Updater API
# -----------------------------------------------------------------------------

@app.route("/api/updater/status", methods=["GET"])
def get_updater_status():
    force = request.args.get("force") == "1"
    try:
        cfg_store.load()
        stat = updater.status(cfg_store, force=force)
        stat["apply_supported"] = updater.apply_supported()
        stat["current_version"] = updater.local_version()
        return jsonify(stat)
    except Exception as e:
        return jsonify({
            "state": "current",
            "current_version": updater.local_version(),
            "apply_supported": updater.apply_supported(),
            "error": str(e)
        })

@app.route("/api/updater/download", methods=["POST"])
def download_update():
    try:
        cfg_store.load()
        info = updater.fetch_latest(cfg_store)
        if info.get("error") or not info.get("url"):
            return jsonify({"error": info.get("error") or "No update download available"}), 400
        staged_path, kind = updater.download(info)
        return jsonify({
            "success": True,
            "staged_path": staged_path,
            "version": info.get("version", "new")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/updater/download-and-apply", methods=["POST"])
def download_and_apply_update():
    try:
        cfg_store.load()
        info = updater.fetch_latest(cfg_store)
        if info.get("error") or not info.get("url"):
            return jsonify({"error": info.get("error") or "No update download available from server"}), 400
        staged_path, kind = updater.download(info)
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, "frozen", False) and updater.apply_supported():
            updater.apply_later()
            moved, failed = 1, []
        elif os.path.isdir(staged_path):
            moved, failed = 0, []
            for root, _, files in os.walk(staged_path):
                for f in files:
                    src = os.path.join(root, f)
                    rel = os.path.relpath(src, staged_path)
                    dst = os.path.join(app_root, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copy2(src, dst)
                        moved += 1
                    except Exception as ex:
                        failed.append(str(ex))
        else:
            moved, failed = updater.apply_update_from_zip(staged_path, app_root)

        return jsonify({
            "success": True,
            "version": info.get("version", "new"),
            "moved": moved,
            "failed": failed,
            "message": f"Successfully updated client files to version {info.get('version', 'new')}!"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/updater/apply-from-zip", methods=["POST"])
def apply_from_zip_endpoint():
    data = request.json or {}
    zip_path = (data.get("zip_path") or "").strip()
    if not zip_path or not os.path.isfile(zip_path):
        return jsonify({"error": f"Zip file not found at '{zip_path}'"}), 400
    try:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        moved, failed = updater.apply_update_from_zip(zip_path, app_root)
        return jsonify({
            "success": True,
            "moved": moved,
            "failed": failed,
            "message": f"Successfully updated {moved} client files from zip archive!"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/updater/apply", methods=["POST"])
def apply_update_relaunch():
    try:
        if updater.apply_supported():
            ok = updater.apply_later()
            return jsonify({"success": ok, "apply_supported": True})
        else:
            # Source build: find staged and copy
            staged = updater.find_staged()
            if staged:
                app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                moved, failed = updater.apply_update_from_zip(staged[1], app_root) if staged[1].endswith(".zip") else (1, [])
                return jsonify({"success": True, "apply_supported": False, "moved": moved})
            return jsonify({"success": True, "apply_supported": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_web_server(host="0.0.0.0", port=8080, debug=False):
    """Starts the Web server."""
    print(f"[*] Starting Divine Client Web UI on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


# -----------------------------------------------------------------------------
# In-Launcher Chat & Ban Status API
# -----------------------------------------------------------------------------

@app.route("/api/client/ban-status", methods=["GET"])
def get_ban_status():
    try:
        res = social.check_ban(cfg_store)
        return jsonify(res)
    except Exception as e:
        return jsonify({"banned": False, "device_code": device_id.get_device_code(), "error": str(e)})


LOCAL_CHAT_PATH = os.path.join(paths.DATA_DIR, "chat_room_log.json")
LOCAL_DMS_PATH = os.path.join(paths.DATA_DIR, "chat_dms_log.json")

def _load_chat_log(path):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def _save_chat_log(path, data):
    try:
        paths.ensure_dirs()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data[-200:], f, indent=2)
    except Exception:
        pass

@app.route("/api/chat/room", methods=["GET", "POST"])
def chat_room_api():
    if request.method == "POST":
        data = request.json or {}
        text = (data.get("text") or "").strip()
        user = (data.get("user") or "NoxVanta").strip()
        if not text:
            return jsonify({"error": "Message cannot be empty"}), 400
        
        # Try remote first if linked
        if social.is_linked(cfg_store):
            try:
                res = social.send_room_message(cfg_store, text)
                return jsonify({"success": True, "data": res})
            except social.BanError as be:
                return jsonify({"error": "banned", "reason": be.reason, "banned": True}), 403
            except Exception:
                pass
        
        # Local fallback log
        msgs = _load_chat_log(LOCAL_CHAT_PATH)
        msg_obj = {
            "id": f"msg_{int(time.time()*1000)}",
            "author": user,
            "text": text,
            "channel": data.get("channel", "general"),
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M")
        }
        msgs.append(msg_obj)
        _save_chat_log(LOCAL_CHAT_PATH, msgs)
        return jsonify({"success": True, "message": msg_obj})

    since = float(request.args.get("since", 0))
    msgs = []
    if social.is_linked(cfg_store):
        try:
            remote_msgs = social.get_room_messages(cfg_store, since=int(since))
            msgs.extend(remote_msgs)
        except Exception:
            pass
    local_msgs = _load_chat_log(LOCAL_CHAT_PATH)
    for lm in local_msgs:
        if lm.get("timestamp", 0) > since and lm not in msgs:
            msgs.append(lm)
    return jsonify({"messages": msgs})

@app.route("/api/chat/dms", methods=["GET", "POST"])
def chat_dms_api():
    if request.method == "POST":
        data = request.json or {}
        to_user = (data.get("to") or "").strip()
        text = (data.get("text") or "").strip()
        user = (data.get("user") or "NoxVanta").strip()
        if not to_user or not text:
            return jsonify({"error": "Recipient and message required"}), 400
        
        if social.is_linked(cfg_store):
            try:
                res = social.send_dm(cfg_store, to_user, text)
                return jsonify({"success": True, "data": res})
            except Exception:
                pass

        dms = _load_chat_log(LOCAL_DMS_PATH)
        dm_obj = {
            "id": f"dm_{int(time.time()*1000)}",
            "from": user,
            "to": to_user,
            "text": text,
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M")
        }
        dms.append(dm_obj)
        _save_chat_log(LOCAL_DMS_PATH, dms)
        return jsonify({"success": True, "message": dm_obj})

    since = float(request.args.get("since", 0))
    dms = _load_chat_log(LOCAL_DMS_PATH)
    filtered = [m for m in dms if m.get("timestamp", 0) > since]
    return jsonify({"messages": filtered})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_web_server(host="0.0.0.0", port=port)
