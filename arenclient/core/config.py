"""Persistent settings for Divine Client. Everything the user tweaks is saved to disk."""
import json
import os
import shutil

from .. import paths
from . import system_info


def _default_ram():
    # Pick something sane for the machine instead of a fixed number. Half of RAM,
    # clamped so we never starve the OS and never suggest a silly-small heap.
    total = system_info.total_ram_mb()
    guess = total // 2
    return max(2048, min(guess, 8192))


DEFAULTS = {
    "ram_mb": _default_ram(),
    "resolution_width": 854,
    "resolution_height": 480,
    "fullscreen": False,
    "keep_launcher_open": True,   # keep launcher visible after the game starts
    "close_on_launch": False,
    "jvm_args": "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M",
    "custom_java_path": "",       # empty = auto-managed Java
    "theme": "divine",
    "ui_background": "divine",     # palette in Settings > Appearance (see ui/theme.py)
    "auto_performance_mods": True,  # install performance pack on Fabric instances
    "last_instance": "",
    "concurrent_downloads": 8,
    "discord_rpc": True,           # show activity on Discord
    "discord_app_id": "",          # blank = use the built-in Divine Client id
    "friends_api_base": "https://divineclient.wispbyte.org",  # Divine site + social API
    "servers_unlocked": False,    # the W.I.P Servers tab opens with the allowance code
    "auto_update": True,           # check the site's clientversion and fetch a new build
    "defender_asked": False,       # the first-open Windows Defender offer has been shown
    "defender_state": "",          # what came of it: "done", "declined", "asked"
    "defender_auto": False,        # re-add the exclusion without asking, if it goes missing
}


# Keys a previous build wrote and this one does not read. Dropping them on load is not
# tidiness for its own sake: ``animations`` and the two rail pins would otherwise sit in
# config.json forever, and ``animations`` would silently bring motion back for anyone who
# had it on, on an interface that no longer has anything to animate.
_RETIRED = ("animations", "menu_rail_pinned", "friends_rail_pinned", "companion_mod")


class Config:
    def __init__(self):
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        paths.ensure_dirs()
        if os.path.exists(paths.CONFIG_FILE):
            try:
                with open(paths.CONFIG_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                for k, v in stored.items():
                    if k in _RETIRED:
                        continue
                    self.data[k] = v
            except (json.JSONDecodeError, OSError):
                pass
        return self

    def save(self):
        paths.ensure_dirs()
        tmp = paths.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        shutil.move(tmp, paths.CONFIG_FILE)

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)
