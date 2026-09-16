"""Per-process resource sampling for the server panel.

Deliberately dependency-free: the launcher is shipped as a single exe, so this
uses /proc on linux/mac-ish systems and the kernel32/psapi calls on Windows
rather than pulling in psutil. Everything returns None on failure - the UI shows
a dash instead of lying about a number.
"""
import os
import sys
import time

_TIME_UNITS_PER_SEC = 100.0          # Linux USER_HZ


def _win_handles():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class PMEM(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    return kernel32, psapi, PMEM


def _rss_windows(pid):
    kernel32, psapi, PMEM = _win_handles()
    h = kernel32.OpenProcess(0x0410, False, pid)     # QUERY | VM_READ
    if not h:
        return None, None
    try:
        info = PMEM()
        info.cb = ctypes.sizeof(PMEM)
        rss = None
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(info), info.cb):
            rss = int(info.WorkingSetSize)
        # cpu: kernel + user time of the process, in 100ns ticks
        creation = ctypes.c_ulonglong()
        exit_ = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        cpu_ticks100ns = None
        if kernel32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_),
                                    ctypes.byref(kernel), ctypes.byref(user)):
            cpu_ticks100ns = kernel.value + user.value
        return rss, cpu_ticks100ns
    finally:
        kernel32.CloseHandle(h)


def _rss_posix(pid):
    try:
        with open("/proc/%d/stat" % pid, "r") as f:
            parts = f.read().rsplit(") ", 1)[-1].split()
        utime = float(parts[11])
        stime = float(parts[12])
        rss_pages = float(parts[21])
        page = os.sysconf("SC_PAGE_SIZE") or 4096
        return int(rss_pages * page), (utime + stime) / _TIME_UNITS_PER_SEC
    except Exception:
        # mac has no /proc: fall back to `ps`, which is always there
        try:
            import subprocess
            out = subprocess.run(["ps", "-o", "rss=,time=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if not out:
                return None, None
            rss_kb, cputime = out.split()[:2]
            secs = 0.0
            for chunk in cputime.split(":"):
                secs = secs * 60 + float(chunk or 0)
            return int(rss_kb) * 1024, secs
        except Exception:
            return None, None


class CpuMeter:
    """Turns "total cpu seconds used" into a percentage between two samples.

    A single reading can't tell you anything, so the session keeps one of these
    and calls sample() about once a second.
    """

    def __init__(self, pid):
        self.pid = pid
        self._prev_secs = None
        self._prev_at = None
        self.percent = None

    def update(self, cpu_secs):
        now = time.time()
        if cpu_secs is None:
            return self.percent
        if self._prev_secs is not None:
            dt = now - self._prev_at
            if dt > 0:
                used = max(0.0, cpu_secs - self._prev_secs)
                self.percent = min(9999.0, round(100.0 * used / dt, 1))
        self._prev_secs = cpu_secs
        self._prev_at = now
        return self.percent


_psutil_cache = {}


def sample(pid, meter=None):
    """Return {'rss_bytes', 'cpu_percent'} for one pid; missing values are None."""
    if not pid:
        return {"rss_bytes": None, "cpu_percent": None}

    # Try psutil first if available for high-precision multi-platform telemetry
    try:
        import psutil
        if pid not in _psutil_cache or not _psutil_cache[pid].is_running():
            _psutil_cache[pid] = psutil.Process(pid)
        p = _psutil_cache[pid]
        if p.is_running():
            rss = p.memory_info().rss
            cpu = p.cpu_percent(interval=None)
            try:
                for child in p.children(recursive=True):
                    if child.is_running():
                        rss += child.memory_info().rss
                        cpu += child.cpu_percent(interval=None)
            except Exception:
                pass
            return {"rss_bytes": rss, "cpu_percent": round(cpu, 1) if cpu is not None else None}
    except Exception:
        pass

    rss = cpu_secs = None
    try:
        if sys.platform == "win32":
            rss, ticks100 = _rss_windows(pid)
            cpu_secs = (ticks100 / 1e7) if ticks100 is not None else None
        else:
            rss, cpu_secs = _rss_posix(pid)
    except Exception:
        pass
    percent = None
    if meter is not None:
        try:
            percent = meter.update(cpu_secs)
        except Exception:
            percent = None
    return {"rss_bytes": rss, "cpu_percent": percent}


def human_bytes(n):
    """Short, human-readable size for the meters."""
    if n is None:
        return "\u2014"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f GB" % n


def format_duration(seconds):
    if seconds is None:
        return "\u2014"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s
