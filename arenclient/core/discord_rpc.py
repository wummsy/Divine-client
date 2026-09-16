# Divine Client - Discord Rich Presence with Animated Rotating Sun Logo.

import os
import threading
import time

try:
    from pypresence import Presence
    _HAVE_PYPRESENCE = True
except Exception:
    _HAVE_PYPRESENCE = False

DEFAULT_APP_ID = os.environ.get("DIVINE_DISCORD_APP_ID", os.environ.get("DIVINE_DISCORD_APP_ID", "1544313910096560128"))

# Animated Rotating Sun Logo asset keys registered in Discord Developer Portal
LARGE_IMAGE_KEY = "divine_discord_animated_icon"
SMALL_IMAGE_KEY = "divine_badge"
DISCORD_INVITE_URL = "https://discord.gg/ER2haQtach"
WEBSITE_URL = "https://divineclient.net"


class DiscordPresence:
    def __init__(self, app_id=None, enabled=True):
        self.app_id = (app_id or DEFAULT_APP_ID or "").strip()
        self.enabled = enabled
        self.rpc = None
        self.connected = False
        self._start_time = int(time.time())
        self._lock = threading.Lock()
        self._last_state = "In Launcher Menus"
        self._last_details = "Divine Client 1.21.11"
        self._last_large_text = "Divine Client — Animated Edition"
        self._last_small_image = SMALL_IMAGE_KEY
        self._last_small_text = "Verified Divine Player"
        self._stop_event = threading.Event()
        self._bg_thread = None

    def start(self):
        if not self.enabled or not self.app_id or not _HAVE_PYPRESENCE:
            return
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._stop_event.clear()
        self._bg_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._bg_thread.start()

    def _worker_loop(self):
        frame_idx = 0
        while not self._stop_event.is_set():
            if self.enabled and self.app_id and _HAVE_PYPRESENCE:
                if not self.connected:
                    self._connect_once()
                elif self.connected:
                    # Animated Rich Presence Status Cycle
                    frames_idle = [
                        ("Divine Client 1.21.11", "In Launcher Menus ✨", "Divine Client — Animated Edition"),
                        ("Ultra Performance & Cloaks", "⚡ 240+ FPS | Axiom Ready", "Verified Divine Player"),
                        ("Celestial Obsidian Edition", "🌌 Exploring Instances", "Divine Client 1.21.11"),
                        ("Divine Network", "👑 Verified Player", "High Performance Client"),
                    ]
                    if "In Launcher" in self._last_state or "Menus" in self._last_state:
                        d, s, lt = frames_idle[frame_idx % len(frames_idle)]
                        self._last_details = d
                        self._last_state = s
                        self._last_large_text = lt
                        self._push_current()
                        frame_idx += 1
            self._stop_event.wait(4.0)

    def _connect_once(self):
        with self._lock:
            if self.connected:
                return
            try:
                self.rpc = Presence(self.app_id)
                self.rpc.connect()
                self.connected = True
            except Exception:
                self.rpc = None
                self.connected = False
        if self.connected:
            self._push_current()

    def set_idle(self):
        self.update(
            details="Divine Client 1.21.11",
            state="In Launcher Menus",
            large_text="Divine Client — Animated Edition",
            small_image=SMALL_IMAGE_KEY,
            small_text="Verified Divine Player",
            reset_timer=False,
        )

    def set_playing(self, instance_name="Divine Client 1.21.11", mc_version="1.21.11", loader="fabric", server_ip=None):
        details_txt = f"Playing Divine Client ({mc_version})"
        state_txt = f"Online on {server_ip}" if server_ip else f"Instance: {instance_name}"
        self.update(
            details=details_txt,
            state=state_txt,
            large_text="Divine Client 1.21.11 — Ultra High Performance",
            small_image=SMALL_IMAGE_KEY,
            small_text="Verified Divine Player",
            reset_timer=True,
        )

    def update(self, details, state, large_text="Divine Client 1.21.11", small_image=SMALL_IMAGE_KEY, small_text="Verified Divine Player", reset_timer=False):
        self._last_details = details
        self._last_state = state
        self._last_large_text = large_text
        self._last_small_image = small_image
        self._last_small_text = small_text
        if reset_timer:
            self._start_time = int(time.time())

        if not self.enabled or not self.app_id or not _HAVE_PYPRESENCE:
            return

        if not self.connected:
            self.start()
            return

        self._push_current()

    def _push_current(self):
        if not self.rpc or not self.connected:
            return
        try:
            buttons = [
                {"label": "Divine Client", "url": WEBSITE_URL},
                {"label": "Join Discord", "url": DISCORD_INVITE_URL},
            ]
            kwargs = {
                "details": self._last_details,
                "state": self._last_state,
                "start": self._start_time,
                "large_image": LARGE_IMAGE_KEY,
                "large_text": self._last_large_text,
                "buttons": buttons,
            }
            if self._last_small_image:
                kwargs["small_image"] = self._last_small_image
            if self._last_small_text:
                kwargs["small_text"] = self._last_small_text

            self.rpc.update(**kwargs)
        except Exception:
            self.connected = False
            self.rpc = None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.close()
        else:
            self.start()
            self._push_current()

    def set_app_id(self, app_id):
        new_id = (app_id or DEFAULT_APP_ID or "").strip()
        if new_id != self.app_id:
            self.close()
            self.app_id = new_id
            self.start()

    def close(self):
        with self._lock:
            if self.rpc:
                try:
                    self.rpc.clear()
                except Exception:
                    pass
                try:
                    self.rpc.close()
                except Exception:
                    pass
            self.rpc = None
            self.connected = False
