"""System metrics and live process CPU/RAM tracking."""
import os
import sys

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def total_ram_mb() -> int:
    """Best-effort total physical RAM in MB. Falls back to 8192 if unknown."""
    if _HAS_PSUTIL:
        try:
            return int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            pass
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys / (1024 * 1024))
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size / (1024 * 1024))
    except Exception:
        return 8192


def recommended_max_ram_mb() -> int:
    """Cap the RAM slider a bit below total so the OS keeps breathing room."""
    total = total_ram_mb()
    return max(2048, total - 2048)


def available_ram_mb() -> int:
    """Best-effort free physical RAM in MB right now. Falls back to total if unknown."""
    if _HAS_PSUTIL:
        try:
            return int(psutil.virtual_memory().available / (1024 * 1024))
        except Exception:
            pass
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullAvailPhys / (1024 * 1024))
        else:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(int(line.split()[1]) / 1024)
    except Exception:
        pass
    return total_ram_mb()


def system_cpu_percent() -> float:
    """System-wide CPU utilization percentage."""
    if _HAS_PSUTIL:
        try:
            return round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
    return 0.0


def system_ram_stats() -> dict:
    """Returns total, used, available MB and usage percent."""
    total = total_ram_mb()
    avail = available_ram_mb()
    used = max(0, total - avail)
    pct = round((used / total * 100.0), 1) if total > 0 else 0.0
    return {
        "total_mb": total,
        "available_mb": avail,
        "used_mb": used,
        "percent": pct
    }


def process_metrics(pid: int) -> dict:
    """Get accurate live CPU% and RAM (RSS MB) for a specific process ID."""
    if not pid:
        return {"cpu_percent": 0.0, "memory_mb": 0, "memory_percent": 0.0, "alive": False}
    if _HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return {"cpu_percent": 0.0, "memory_mb": 0, "memory_percent": 0.0, "alive": False}
            with p.oneshot():
                mem_bytes = p.memory_info().rss
                mem_mb = int(mem_bytes / (1024 * 1024))
                cpu = p.cpu_percent(interval=None)
                mem_pct = round(p.memory_percent(), 1)
                return {
                    "cpu_percent": round(cpu, 1),
                    "memory_mb": mem_mb,
                    "memory_percent": mem_pct,
                    "alive": True
                }
        except Exception:
            return {"cpu_percent": 0.0, "memory_mb": 0, "memory_percent": 0.0, "alive": False}

    return {"cpu_percent": 0.0, "memory_mb": 0, "memory_percent": 0.0, "alive": False}


def is_64bit() -> bool:
    """A 32-bit process can't give the JVM a large heap."""
    import struct
    return struct.calcsize("P") * 8 >= 64
