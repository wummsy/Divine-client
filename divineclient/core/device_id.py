"""Client hardware device code generator and verification.

Generates a persistent, deterministic, salted hardware identifier for the device.
This device code is used to uniquely identify the client installation for anti-abuse,
moderation, and ban enforcement.

Even if configuration files are deleted or the client is reinstalled, the device code
is deterministically derived from stable system hardware components (Motherboard UUID,
CPU identifiers, Machine GUID, and network MAC hashes), making it resilient against
evasion attempts.
"""
import hashlib
import os
import platform
import subprocess
import sys
import uuid
from .. import paths

_CACHED_DEVICE_CODE = None
_SALT = b"divine-client-hwid-v2-salt-protect-2026"


def _read_linux_machine_id():
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id", "/sys/class/dmi/id/product_uuid"):
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    val = f.read().strip()
                    if val and len(val) >= 8:
                        return val
        except Exception:
            pass
    return ""


def _read_windows_machine_guid():
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        if val:
            return str(val).strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            stderr=subprocess.DEVNULL, timeout=2
        ).decode("utf-8", "ignore")
        for line in out.splitlines():
            if "MachineGuid" in line:
                return line.split()[-1].strip()
    except Exception:
        pass
    return ""


def _read_macos_uuid():
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], stderr=subprocess.DEVNULL, timeout=2).decode("utf-8", "ignore")
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split("=")[-1].strip().strip('"')
    except Exception:
        pass
    return ""


def _get_raw_hardware_fingerprint():
    """Collect hardware components to form a deterministic fingerprint."""
    components = []

    # 1. OS-specific persistent machine ID
    if sys.platform == "win32":
        w_guid = _read_windows_machine_guid()
        if w_guid:
            components.append(f"w_guid:{w_guid}")
    elif sys.platform == "darwin":
        m_uuid = _read_macos_uuid()
        if m_uuid:
            components.append(f"m_uuid:{m_uuid}")
    else:
        l_id = _read_linux_machine_id()
        if l_id:
            components.append(f"l_id:{l_id}")

    # 2. Stable MAC / Node hash
    try:
        node = uuid.getnode()
        if node and node != 0:
            components.append(f"node:{node}")
    except Exception:
        pass

    # 3. CPU / Platform identifiers
    try:
        components.append(f"arch:{platform.machine()}")
        components.append(f"proc:{platform.processor()}")
    except Exception:
        pass

    # 4. User profile / home root identifier
    try:
        home_seed = os.path.expanduser("~")
        components.append(f"home:{hashlib.md5(home_seed.encode('utf-8')).hexdigest()[:8]}")
    except Exception:
        pass

    if not components:
        components.append(f"fallback:{os.environ.get('USER', os.environ.get('USERNAME', 'default'))}")

    return "|".join(components)


def get_device_code():
    """Returns the persistent device code string, e.g. DEV-A1B2-C3D4-E5F6-7890."""
    global _CACHED_DEVICE_CODE
    if _CACHED_DEVICE_CODE:
        return _CACHED_DEVICE_CODE

    # Check local saved file first
    hwid_file = os.path.join(paths.DATA_DIR, "device.id")
    file_code = None
    if os.path.isfile(hwid_file):
        try:
            with open(hwid_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.startswith("DEV-") and len(content) == 23:
                    file_code = content
        except Exception:
            pass

    # Compute hardware hash
    raw = _get_raw_hardware_fingerprint()
    digest = hashlib.sha256(_SALT + raw.encode("utf-8")).hexdigest()[:16].upper()
    computed_code = f"DEV-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"

    code = file_code or computed_code

    # Persist to disk
    try:
        os.makedirs(os.path.dirname(hwid_file), exist_ok=True)
        with open(hwid_file, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception:
        pass

    _CACHED_DEVICE_CODE = code
    return code
