"""Launch engine.

Handles the whole chain of getting a version onto disk and starting it:
downloading Minecraft, making sure a working Java is available, installing
Fabric, Forge, or Quilt when asked, dropping in instance-specific mods,
then building and running the actual java command with per-instance isolation.
"""
import os
import subprocess
import sys

import minecraft_launcher_lib as mll

from .. import paths
from . import mods as mods_module
from . import java_runtime
from . import system_info


def _safe_heap_mb(requested, progress=None):
    """Clamp the requested heap so the JVM can actually allocate it."""
    requested = max(512, int(requested))
    total = system_info.total_ram_mb()
    avail = system_info.available_ram_mb()

    hard_cap = max(1024, total - 1024)
    soft_cap = max(1024, avail - 512)

    ceiling = min(hard_cap, soft_cap) if soft_cap >= 1024 else hard_cap
    safe = min(requested, ceiling)
    if not system_info.is_64bit():
        safe = min(safe, 1024)

    if safe < requested and progress:
        progress.set_status(
            "Lowered memory to %d MB so Java can start (you asked for %d MB, "
            "the PC has %d MB free)." % (safe, requested, avail)
        )
    return int(safe)


class Progress:
    """Passes status/percent updates back to the UI."""
    def __init__(self, on_update=None):
        self.on_update = on_update
        self._status = ""
        self._max = 0
        self._value = 0

    def _emit(self):
        if self.on_update:
            frac = (self._value / self._max) if self._max else 0.0
            self.on_update(self._status, min(max(frac, 0.0), 1.0))

    def set_status(self, text):
        self._status = text
        self._emit()

    def set_max(self, m):
        self._max = m or 1
        self._emit()

    def set_progress(self, v):
        self._value = v
        self._emit()

    def as_callback(self):
        return {
            "setStatus": self.set_status,
            "setProgress": self.set_progress,
            "setMax": self.set_max,
        }


def get_version_list():
    return mll.utils.get_version_list()


def get_fabric_supported_versions():
    try:
        return {v["version"] for v in mll.fabric.get_all_minecraft_versions()}
    except Exception:
        return set()


def ensure_java(mc_version_id, progress, custom_java_path=""):
    """Thin pass-through to the java_runtime module."""
    return java_runtime.ensure_java(mc_version_id, progress, custom_java_path)


def is_version_installed(version_id):
    """Check if Minecraft or mod loader version JSON exists on disk."""
    if not version_id:
        return False
    vdir = os.path.join(paths.MINECRAFT_DIR, "versions", version_id)
    vjson = os.path.join(vdir, f"{version_id}.json")
    return os.path.isfile(vjson) and os.path.getsize(vjson) > 0


def _find_fabric_version_id(mc_version, requested_loader_ver=None):
    """Find the newest or requested installed Fabric loader version directory."""
    versions_dir = os.path.join(paths.MINECRAFT_DIR, "versions")
    candidates = []
    if os.path.isdir(versions_dir):
        for name in os.listdir(versions_dir):
            if name.startswith("fabric-loader-") and name.endswith("-" + mc_version):
                if requested_loader_ver and requested_loader_ver in name:
                    return name
                candidates.append(name)
    if candidates:
        candidates.sort()
        return candidates[-1]
    return None


def _find_forge_version_id(mc_version):
    """Find installed Forge version directory for this Minecraft version."""
    versions_dir = os.path.join(paths.MINECRAFT_DIR, "versions")
    candidates = []
    if os.path.isdir(versions_dir):
        for name in os.listdir(versions_dir):
            if "forge" in name.lower() and mc_version in name:
                candidates.append(name)
    if candidates:
        candidates.sort()
        return candidates[-1]
    return None


def _find_quilt_version_id(mc_version):
    """Find installed Quilt loader version directory for this Minecraft version."""
    versions_dir = os.path.join(paths.MINECRAFT_DIR, "versions")
    candidates = []
    if os.path.isdir(versions_dir):
        for name in os.listdir(versions_dir):
            if name.startswith("quilt-loader-") and name.endswith("-" + mc_version):
                candidates.append(name)
    if candidates:
        candidates.sort()
        return candidates[-1]
    return None


def _find_loader_version_id(mc_version, loader="vanilla"):
    """Find the specific loader version ID for an instance, fallback to mc_version."""
    loader = (loader or "vanilla").lower()
    if loader == "fabric":
        return _find_fabric_version_id(mc_version) or mc_version
    elif loader == "forge":
        return _find_forge_version_id(mc_version) or mc_version
    elif loader == "quilt":
        return _find_quilt_version_id(mc_version) or mc_version
    return mc_version


def install_instance(instance, config, progress):
    """Ensure base Minecraft and instance mod loader are installed and prepared."""
    paths.ensure_dirs()
    mc_version = instance.mc_version
    loader = (instance.loader or "vanilla").lower()
    inst_data = getattr(instance, "data", {}) or {}

    # 1. Base Minecraft Version
    if not is_version_installed(mc_version):
        progress.set_status(f"Downloading base Minecraft {mc_version}...")
        mll.install.install_minecraft_version(
            mc_version, paths.MINECRAFT_DIR, callback=progress.as_callback()
        )

    launch_version_id = mc_version

    # 2. Mod Loader Installation
    if loader == "fabric":
        req_loader = inst_data.get("loader_version")
        fabric_id = _find_fabric_version_id(mc_version, req_loader)

        if not fabric_id or not is_version_installed(fabric_id):
            progress.set_status(f"Installing Fabric Loader for Minecraft {mc_version}...")
            java_for_install = ensure_java(mc_version, progress, config.get("custom_java_path", ""))
            
            clean_loader = req_loader if req_loader and req_loader.count(".") >= 1 and not req_loader.startswith("fabric") else None
            try:
                mll.fabric.install_fabric(
                    mc_version, paths.MINECRAFT_DIR,
                    loader_version=clean_loader,
                    callback=progress.as_callback(),
                    java=java_for_install,
                )
                fabric_id = _find_fabric_version_id(mc_version, clean_loader)
            except Exception as fe:
                progress.set_status(f"Fabric installation notice: {fe}")

        if fabric_id and is_version_installed(fabric_id):
            launch_version_id = fabric_id
            instance.data["loader_version"] = launch_version_id
        else:
            launch_version_id = mc_version

        # 3. Instance-specific Mods & Addons
        mods_dir = os.path.join(instance.game_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        if "builder" in instance.id.lower() or "builder" in instance.name.lower():
            progress.set_status("Deploying Axiom, WorldEdit, and Flashback builder tools...")
            mods_module.ensure_builder_suite(mods_dir, mc_version)
        elif getattr(instance, "is_divine_exclusive", False) or "divine" in instance.id.lower():
            progress.set_status("Deploying Divine Client Fabric mod suite...")
            mods_module.ensure_divine_client_mod(mods_dir)

        if config.get("auto_performance_mods", True) and not getattr(instance, "_perf_installed", False):
            def modprog(text, frac):
                progress.set_status(text)
                progress.set_max(100)
                progress.set_progress(int(frac * 100))

            mods_module.install_performance_pack(
                mc_version, mods_dir,
                loader="fabric", progress=modprog,
            )
            instance._perf_installed = True

    elif loader == "forge":
        forge_id = _find_forge_version_id(mc_version)
        if not forge_id or not is_version_installed(forge_id):
            progress.set_status(f"Installing Forge Loader for Minecraft {mc_version}...")
            java_for_install = ensure_java(mc_version, progress, config.get("custom_java_path", ""))
            try:
                forge_ver = mll.forge.find_forge_version(mc_version)
                if forge_ver:
                    mll.forge.install_forge_version(
                        forge_ver, paths.MINECRAFT_DIR,
                        callback=progress.as_callback(),
                        java=java_for_install,
                    )
                    forge_id = _find_forge_version_id(mc_version)
            except Exception as fe:
                progress.set_status(f"Forge installation notice: {fe}")

        if forge_id and is_version_installed(forge_id):
            launch_version_id = forge_id
            instance.data["loader_version"] = launch_version_id
        else:
            launch_version_id = mc_version

    elif loader == "quilt":
        quilt_id = _find_quilt_version_id(mc_version)
        if not quilt_id or not is_version_installed(quilt_id):
            progress.set_status(f"Installing Quilt Loader for Minecraft {mc_version}...")
            java_for_install = ensure_java(mc_version, progress, config.get("custom_java_path", ""))
            try:
                mll.quilt.install_quilt(
                    mc_version, paths.MINECRAFT_DIR,
                    callback=progress.as_callback(),
                    java=java_for_install,
                )
                quilt_id = _find_quilt_version_id(mc_version)
            except Exception as qe:
                progress.set_status(f"Quilt installation notice: {qe}")

        if quilt_id and is_version_installed(quilt_id):
            launch_version_id = quilt_id
            instance.data["loader_version"] = launch_version_id
        else:
            launch_version_id = mc_version

    progress.set_status(f"Ready to launch ({launch_version_id})")
    return launch_version_id


def build_command(instance, config, account_store, progress):
    launch_version_id = install_instance(instance, config, progress)

    inst_data = getattr(instance, "data", {}) or {}

    progress.set_status("Checking Java...")
    java_custom = inst_data.get("custom_java_path") or config.get("custom_java_path", "")
    java_path = ensure_java(instance.mc_version, progress, java_custom)

    account = account_store.get_active()
    if account is None:
        account = account_store.add_offline("Player")

    if account.get("type") == "microsoft" and account.get("refresh_token"):
        progress.set_status("Refreshing Microsoft session...")
        try:
            from . import accounts as acc_mod
            account = acc_mod.try_refresh(account)
            account_store.save()
        except Exception:
            pass
    auth = account_store.launch_options(account)

    requested_ram = inst_data.get("ram_mb") or config.get("ram_mb", 4096)
    ram = _safe_heap_mb(int(requested_ram), progress)
    xms = min(max(512, ram // 2), ram)
    jvm_args = ["-Xmx%dM" % ram, "-Xms%dM" % xms]
    extra = (inst_data.get("jvm_args") or config.get("jvm_args", "")).strip()
    if extra:
        jvm_args += extra.split()

    options = {
        "username": auth["username"],
        "uuid": auth["uuid"],
        "token": auth["token"],
        "jvmArguments": jvm_args,
        "launcherName": "DivineClient",
        "launcherVersion": "4.0.0",
        "gameDirectory": instance.game_dir,
    }
    if java_path:
        options["executablePath"] = java_path
    
    is_fullscreen = inst_data.get("fullscreen") if "fullscreen" in inst_data else config.get("fullscreen")
    if is_fullscreen:
        options["customResolution"] = False
        options["fullscreen"] = True
    else:
        options["customResolution"] = True
        options["resolutionWidth"] = str(inst_data.get("resolution_width") or config.get("resolution_width", 854))
        options["resolutionHeight"] = str(inst_data.get("resolution_height") or config.get("resolution_height", 480))

    progress.set_status(f"Building launch command for {launch_version_id}...")
    command = mll.command.get_minecraft_command(launch_version_id, paths.MINECRAFT_DIR, options)
    return command


def _jvm_starts_ok(java_exe, jvm_args):
    """Run a tiny 'java -version' with the heap args to prove the VM boots."""
    try:
        env = java_runtime.get_java_env(java_exe)
        result = subprocess.run(
            [java_exe] + jvm_args + ["-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            env=env,
            **java_runtime._no_window_kwargs(),
        )
        text = result.stdout.decode("utf-8", "replace")
        return result.returncode == 0, text
    except Exception as e:
        return False, str(e)


def _extract_java_and_jvm(command):
    """Split a full minecraft command into (java_exe, jvm_args)."""
    java_exe = command[0]
    jvm_args = []
    for tok in command[1:]:
        if tok.startswith("-X") or tok.startswith("-D") or tok.startswith("-XX"):
            jvm_args.append(tok)
    return java_exe, jvm_args


def launch(instance, config, account_store, progress):
    """Install anything missing, then start the game as its own process."""
    command = build_command(instance, config, account_store, progress)

    # Pre-flight: make sure the JVM can actually start with these memory args.
    java_exe, jvm_args = _extract_java_and_jvm(command)
    progress.set_status("Checking the game can start...")
    ok, err = _jvm_starts_ok(java_exe, jvm_args)
    if not ok:
        progress.set_status("Adjusting memory so the game can start...")
        command = _rebuild_with_safe_memory(instance, config, account_store, progress)
        java_exe, jvm_args = _extract_java_and_jvm(command)
        ok2, err2 = _jvm_starts_ok(java_exe, jvm_args)
        if not ok2:
            raise RuntimeError(
                "Java could not start (\"Could not create the Java VM\"). "
                "Please lower the RAM slider in Settings and try again. Details: " +
                (err2 or err).strip().splitlines()[-1][:150]
                if (err2 or err).strip() else "Java could not start."
            )

    log_path = os.path.join(paths.LOG_DIR, instance.id + ".log")
    logf = open(log_path, "w", encoding="utf-8", errors="replace")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008  # DETACHED_PROCESS

    progress.set_status("Launching " + instance.name + "...")
    env = java_runtime.get_java_env(java_exe)
    proc = subprocess.Popen(
        command,
        cwd=instance.game_dir,
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    return proc, log_path


def _rebuild_with_safe_memory(instance, config, account_store, progress):
    """Build the launch command again forcing a conservative heap."""
    launch_version_id = _find_loader_version_id(instance.mc_version, instance.loader)
    java_path = ensure_java(instance.mc_version, progress, config.get("custom_java_path", ""))

    account = account_store.get_active() or account_store.add_offline("Player")
    auth = account_store.launch_options(account)

    avail = system_info.available_ram_mb()
    safe_ram = max(1024, min(2048, avail - 512))
    jvm_args = ["-Xmx%dM" % safe_ram, "-Xms%dM" % min(512, safe_ram)]

    options = {
        "username": auth["username"],
        "uuid": auth["uuid"],
        "token": auth["token"],
        "jvmArguments": jvm_args,
        "launcherName": "DivineClient",
        "launcherVersion": "4.0.0",
        "gameDirectory": instance.game_dir,
    }
    if java_path:
        options["executablePath"] = java_path
    if config.get("fullscreen"):
        options["fullscreen"] = True
    else:
        options["customResolution"] = True
        options["resolutionWidth"] = str(config.get("resolution_width", 854))
        options["resolutionHeight"] = str(config.get("resolution_height", 480))

    return mll.command.get_minecraft_command(launch_version_id, paths.MINECRAFT_DIR, options)
