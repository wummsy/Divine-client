"""Read (and lightly manage) the contents of an instance's game directory:
saved worlds, installed resource packs and the multiplayer server list.

Minecraft stores worlds and the server list as NBT, so this module includes a
tiny, dependency-free NBT reader good enough to pull out the handful of fields
we display (a world's display name, a server's name and address).
"""
import gzip
import os
import struct
import time


# ---- minimal NBT reader -----------------------------------------------------
# Tag ids per the NBT spec. We only need enough to walk compounds/lists and read
# strings, so the numeric readers just skip the right number of bytes.
_TAG_END = 0
_TAG_BYTE = 1
_TAG_SHORT = 2
_TAG_INT = 3
_TAG_LONG = 4
_TAG_FLOAT = 5
_TAG_DOUBLE = 6
_TAG_BYTE_ARRAY = 7
_TAG_STRING = 8
_TAG_LIST = 9
_TAG_COMPOUND = 10
_TAG_INT_ARRAY = 11
_TAG_LONG_ARRAY = 12


class _Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def _take(self, n):
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def u1(self):
        return self._take(1)[0]

    def u2(self):
        return struct.unpack(">H", self._take(2))[0]

    def i2(self):
        return struct.unpack(">h", self._take(2))[0]

    def i4(self):
        return struct.unpack(">i", self._take(4))[0]

    def i8(self):
        return struct.unpack(">q", self._take(8))[0]

    def string(self):
        n = self.u2()
        return self._take(n).decode("utf-8", "replace")

    def skip_payload(self, tag):
        if tag == _TAG_BYTE:
            self.i += 1
        elif tag == _TAG_SHORT:
            self.i += 2
        elif tag in (_TAG_INT, _TAG_FLOAT):
            self.i += 4
        elif tag in (_TAG_LONG, _TAG_DOUBLE):
            self.i += 8
        elif tag == _TAG_BYTE_ARRAY:
            n = self.i4()
            self.i += n
        elif tag == _TAG_STRING:
            n = self.u2()
            self.i += n
        elif tag == _TAG_INT_ARRAY:
            n = self.i4()
            self.i += 4 * n
        elif tag == _TAG_LONG_ARRAY:
            n = self.i4()
            self.i += 8 * n
        elif tag == _TAG_LIST:
            self.read_list(collect=False)
        elif tag == _TAG_COMPOUND:
            self.read_compound(collect=False)

    def read_value(self, tag, collect=True):
        if tag == _TAG_STRING:
            return self.string()
        if tag == _TAG_COMPOUND:
            return self.read_compound(collect=collect)
        if tag == _TAG_LIST:
            return self.read_list(collect=collect)
        if tag == _TAG_BYTE:
            return self.u1()
        if tag == _TAG_SHORT:
            return self.i2()
        if tag == _TAG_INT:
            return self.i4()
        if tag == _TAG_LONG:
            return self.i8()
        self.skip_payload(tag)
        return None

    def read_list(self, collect=True):
        item_tag = self.u1()
        length = self.i4()
        out = []
        for _ in range(length):
            v = self.read_value(item_tag, collect=collect)
            if collect:
                out.append(v)
        return out if collect else None

    def read_compound(self, collect=True):
        out = {}
        while self.i < len(self.d):
            tag = self.u1()
            if tag == _TAG_END:
                break
            name = self.string()
            v = self.read_value(tag, collect=collect)
            if collect:
                out[name] = v
        return out


def _parse_nbt_file(path):
    """Return the root compound of a gzip or raw NBT file, or {}."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        r = _Reader(raw)
        root_tag = r.u1()
        if root_tag != _TAG_COMPOUND:
            return {}
        r.string()  # root name
        return r.read_compound()
    except Exception:
        return {}


# ---- worlds -----------------------------------------------------------------
def count_worlds(game_dir):
    """How many saves exist - no level.dat parsing and no directory walking.

    The rail chips and the stats tiles only need a number, but list_worlds()
    parses every world's NBT and walks every region folder to size them. That is
    far too much to do on the UI thread, and it used to run on every section
    switch because _refresh_stats() was called from there.
    """
    saves = os.path.join(game_dir, "saves")
    try:
        names = os.listdir(saves)
    except OSError:
        return 0
    return sum(1 for n in names if os.path.isdir(os.path.join(saves, n)))


def count_resource_packs(game_dir):
    """Same entries list_resource_packs() would return, but without sizes."""
    rp = os.path.join(game_dir, "resourcepacks")
    try:
        names = os.listdir(rp)
    except OSError:
        return 0
    return sum(1 for n in names if not n.startswith(".")
               and (n.lower().endswith(".zip") or os.path.isdir(os.path.join(rp, n))))


def folder_size_mb(path):
    """Size of a folder in MB. Slow on a big world: never call it from the UI."""
    return _dir_size_mb(path)


def list_worlds(game_dir, with_sizes=True):
    """Return a list of dicts describing each saved world.

    `with_sizes=False` skips walking every world folder - that walk is the single
    slowest thing the instance editor used to do on the main thread (a real world
    is thousands of region files), and a row can say "counting..." for a moment.
    """
    saves = os.path.join(game_dir, "saves")
    out = []
    if not os.path.isdir(saves):
        return out
    for name in sorted(os.listdir(saves)):
        wdir = os.path.join(saves, name)
        if not os.path.isdir(wdir):
            continue
        level = os.path.join(wdir, "level.dat")
        display = name
        game_mode = None
        last_played = None
        if os.path.exists(level):
            data = _parse_nbt_file(level)
            d = data.get("Data", {}) if isinstance(data, dict) else {}
            if isinstance(d, dict):
                display = d.get("LevelName") or name
                gt = d.get("GameType")
                game_mode = {0: "Survival", 1: "Creative", 2: "Adventure",
                             3: "Spectator"}.get(gt)
                lp = d.get("LastPlayed")
                if isinstance(lp, int) and lp > 0:
                    last_played = lp
        out.append({
            "folder": name,
            "name": display,
            "path": wdir,
            "game_mode": game_mode,
            "last_played": last_played,
            "size_mb": _dir_size_mb(wdir) if with_sizes else None,
        })
    # newest first when we know it
    out.sort(key=lambda w: (w["last_played"] or 0), reverse=True)
    return out


def delete_world(game_dir, folder):
    import shutil
    wdir = os.path.join(game_dir, "saves", folder)
    if os.path.isdir(wdir):
        shutil.rmtree(wdir, ignore_errors=True)
        return True
    return False


# ---- resource packs ---------------------------------------------------------
def _active_packs(game_dir):
    """Read the ordered list of enabled packs from options.txt."""
    opts = os.path.join(game_dir, "options.txt")
    if not os.path.exists(opts):
        return []
    try:
        with open(opts, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("resourcePacks:"):
                    raw = line.split(":", 1)[1].strip()
                    raw = raw.strip("[]")
                    if not raw:
                        return []
                    names = []
                    for part in raw.split(","):
                        part = part.strip().strip('"')
                        if part:
                            names.append(part)
                    return names
    except OSError:
        pass
    return []


def list_resource_packs(game_dir, with_sizes=True):
    """Return dicts for each pack in resourcepacks/, marking which are enabled.

    `with_sizes=False` leaves size_mb as None instead of walking extracted pack
    folders, which for a big pack is a lot of stat() calls.
    """
    rp = os.path.join(game_dir, "resourcepacks")
    out = []
    if not os.path.isdir(rp):
        return out
    active = _active_packs(game_dir)
    active_files = {a[len("file/"):] if a.startswith("file/") else a for a in active}
    for name in sorted(os.listdir(rp)):
        full = os.path.join(rp, name)
        if name.startswith("."):
            continue
        is_zip = name.lower().endswith(".zip")
        if not is_zip and not os.path.isdir(full):
            continue
        out.append({
            "filename": name,
            "path": full,
            "enabled": name in active_files,
            "size_mb": (None if not with_sizes else
                        (_dir_size_mb(full) if os.path.isdir(full)
                         else _file_size_mb(full))),
        })
    return out


def delete_resource_pack(game_dir, filename):
    import shutil
    full = os.path.join(game_dir, "resourcepacks", filename)
    try:
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
        elif os.path.exists(full):
            os.remove(full)
        else:
            return False
        return True
    except OSError:
        return False


def resource_packs_dir(game_dir):
    d = os.path.join(game_dir, "resourcepacks")
    os.makedirs(d, exist_ok=True)
    return d


# ---- servers ----------------------------------------------------------------
def list_servers(game_dir):
    """Return dicts for each entry in servers.dat."""
    path = os.path.join(game_dir, "servers.dat")
    out = []
    if not os.path.exists(path):
        return out
    data = _parse_nbt_file(path)
    servers = data.get("servers", []) if isinstance(data, dict) else []
    if isinstance(servers, list):
        for s in servers:
            if isinstance(s, dict):
                out.append({
                    "name": s.get("name", "Minecraft Server"),
                    "ip": s.get("ip", ""),
                })
    return out


# ---- helpers ----------------------------------------------------------------
def _dir_size_mb(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return round(total / (1024 * 1024), 1)


def _file_size_mb(path):
    try:
        return round(os.path.getsize(path) / (1024 * 1024), 1)
    except OSError:
        return 0.0


def format_last_played(ms):
    if not ms:
        return "never"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))
    except (ValueError, OSError):
        return "unknown"
