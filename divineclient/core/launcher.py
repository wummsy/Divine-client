"""Launch engine.

Handles the whole chain of getting a version onto disk and starting it:
downloading Minecraft, making sure a working Java is available, installing
Fabric when asked, dropping in the performance mods, then building and running
the actual java command.
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
    """Clamp the requested heap so the JVM can actually allocate it.

    "Could not create the Java VM" almost always means Xmx was bigger than the
    memory the machine can hand out right now. We keep the heap under total RAM
    (leaving room for the OS) and under what's currently free, so the game starts
    instead of dying on launch.
    """
    requested = max(512, int(requested))
    total = system_info.total_ram_mb()
    avail = system_info.available_ram_mb()

    # Never ask for more than total minus a cushion for the OS and native memory.
    hard_cap = max(1024, total - 1024)
    # Prefer to stay within what's free right now, but always allow at least 1 GB.
    soft_cap = max(1024, avail - 512)

    ceiling = min(hard_cap, soft_cap) if soft_cap >= 1024 else hard_cap
    safe = min(requested, ceiling)
    # A 32-bit Java can't address a big heap; keep it modest just in case.
    if not system_info.is_64bit():
        safe = min(safe, 1024)

    if safe < requested and progress:
        progress.set_status(
            "Lowered memory to %d MB so Java can start (you asked for %d MB, "
            "the PC has %d MB free)." % (safe, requested, avail)
        )
    return int(safe)


class Progress:
    """Passes status/percent updates back to the UI.

    minecraft-launcher-lib expects a dict with setStatus / setProgress / setMax,
    so as_callback() adapts to that shape.
    """
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
    """Thin pass-through to the java_runtime module, which does the heavy lifting."""
    return java_runtime.ensure_java(mc_version_id, progress, custom_java_path)



def is_version_installed(version_id):
    """Check if Minecraft or Fabric version JSON exists on disk."""
    if not version_id:
        return False
    vdir = os.path.join(paths.MINECRAFT_DIR, "versions", version_id)
    vjson = os.path.join(vdir, f"{version_id}.json")
    return os.path.isfile(vjson) and os.path.getsize(vjson) > 0

def install_instance(instance, config, progress):
    """Fast-install: skips re-downloading if already present on disk."""
    paths.ensure_dirs()
    mc_version = instance.mc_version

    if not is_version_installed(mc_version):
        progress.set_status("Verifying Minecraft " + mc_version + "...")
        mll.install.install_minecraft_version(
            mc_version, paths.MINECRAFT_DIR, callback=progress.as_callback()
        )

    launch_version_id = mc_version

    if instance.loader == "fabric":
        fabric_id = _find_fabric_version_id(mc_version)
        if not is_version_installed(fabric_id):
            progress.set_status("Installing Fabric for " + mc_version + "...")
            java_for_install = ensure_java(mc_version, progress, config.get("custom_java_path", ""))
            mll.fabric.install_fabric(
                mc_version, paths.MINECRAFT_DIR,
                callback=progress.as_callback(),
                java=java_for_install,
            )
            fabric_id = _find_fabric_version_id(mc_version)

        launch_version_id = fabric_id
        instance.data["loader_version"] = launch_version_id

        mods_dir = os.path.join(instance.game_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        if "builder" in instance.id.lower() or "builder" in instance.name.lower():
            progress.set_status("Deploying Axiom, WorldEdit, and Flashback builder tools...")
            mods_module.ensure_builder_suite(mods_dir, mc_version)
        else:
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

    progress.set_status("Ready to launch")
    return launch_version_id


def _find_fabric_version_id(mc_version):
    """Fabric installs under a folder like fabric-loader-<ver>-<mc>. Find the newest."""
    versions_dir = os.path.join(paths.MINECRAFT_DIR, "versions")
    candidates = []
    if os.path.isdir(versions_dir):
        for name in os.listdir(versions_dir):
            if name.startswith("fabric-loader-") and name.endswith("-" + mc_version):
                candidates.append(name)
    if candidates:
        candidates.sort()
        return candidates[-1]
    return mc_version


def build_command(instance, config, account_store, progress):
    launch_version_id = install_instance(instance, config, progress)

    inst_data = getattr(instance, "data", {}) or {}

    progress.set_status("Checking Java...")
    java_custom = inst_data.get("custom_java_path") or config.get("custom_java_path", "")
    java_path = ensure_java(instance.mc_version, progress, java_custom)

    account = account_store.get_active()
    if account is None:
        account = account_store.add_offline("Player")
    # Microsoft access tokens expire after ~24h; refresh before launching so a
    # premium login doesn't silently fall back to a rejected session.
    if account.get("type") == "microsoft" and account.get("refresh_token"):
        progress.set_status("Refreshing Microsoft session...")
        try:
            from . import accounts as acc_mod
            account = acc_mod.try_refresh(account)
            account_store.save()
        except Exception:
            # keep the cached token; the game will prompt if it's truly invalid
            pass
    auth = account_store.launch_options(account)

    requested_ram = inst_data.get("ram_mb") or config.get("ram_mb", 4096)
    ram = _safe_heap_mb(int(requested_ram), progress)
    # Xms must never exceed Xmx or the VM refuses to start.
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
        "launcherVersion": "1.0.0",
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

    progress.set_status("Building launch command...")
    command = mll.command.get_minecraft_command(launch_version_id, paths.MINECRAFT_DIR, options)
    return command


def _jvm_starts_ok(java_exe, jvm_args):
    """Run a tiny 'java -version' with the same heap args to prove the VM boots."""
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
    """Split a full minecraft command into (java_exe, jvm_args_before_the_mainclass).

    The heap/GC flags are everything between the java exe and the first non-dash
    token that isn't a value - close enough: we only need the -X/-XX flags to test.
    """
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
        # Almost always a memory problem. Rebuild with a small, guaranteed-safe heap.
        progress.set_status("Adjusting memory so the game can start...")
        command = _rebuild_with_safe_memory(instance, config, account_store, progress)
        java_exe, jvm_args = _extract_java_and_jvm(command)
        ok2, err2 = _jvm_starts_ok(java_exe, jvm_args)
        if not ok2:
            raise RuntimeError(
                "Java could not start (\"Could not create the Java VM\"). This is a "
                "memory setting problem. Lower the RAM slider in Settings and try "
                "again. Details: " + (err2 or err).strip().splitlines()[-1][:150]
                if (err2 or err).strip() else "Java could not start."
            )

    log_path = os.path.join(paths.LOG_DIR, instance.id + ".log")
    logf = open(log_path, "w", encoding="utf-8", errors="replace")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008  # DETACHED_PROCESS - let the game outlive us

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
    """Build the launch command again but force a conservative, known-good heap."""
    launch_version_id = _find_fabric_version_id(instance.mc_version) \
        if instance.loader == "fabric" else instance.mc_version
    java_path = ensure_java(instance.mc_version, progress, config.get("custom_java_path", ""))

    account = account_store.get_active() or account_store.add_offline("Player")
    auth = account_store.launch_options(account)

    # Small heap that will fit almost anywhere: at most 2 GB, and within free RAM.
    avail = system_info.available_ram_mb()
    safe_ram = max(1024, min(2048, avail - 512))
    jvm_args = ["-Xmx%dM" % safe_ram, "-Xms%dM" % min(512, safe_ram)]

    options = {
        "username": auth["username"],
        "uuid": auth["uuid"],
        "token": auth["token"],
        "jvmArguments": jvm_args,
        "launcherName": "DivineClient",
        "launcherVersion": "1.0.0",
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
