"""Dedicated Custom Desktop Window Launcher for Divine Client.

Runs the backend web server in a background thread and opens the modern
HTML5/CSS3 interface in a dedicated native desktop application window
(via pywebview EdgeChromium/Qt/GTK) without browser chrome or tabs.
"""

import os
import sys
import threading
import time
import webbrowser
import socket
import urllib.request

from .. import paths
from ..web_server import app


def _is_port_free(port, host="0.0.0.0"):
    """Check if a TCP port is free to bind."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, int(port)))
            return True
    except OSError:
        return False


def _find_free_port(start=8080):
    """Find the next available open port starting from start."""
    for p in range(start, start + 200):
        if _is_port_free(p):
            return p
    return start


def _wait_for_server(port, timeout=5.0):
    """Poll until the Flask server is answering HTTP requests."""
    start = time.time()
    url = f"http://127.0.0.1:{port}/api/status"
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DivineClientLauncher/5.0.0"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.08)
    return False


def launch_web_ui(port=None, host="0.0.0.0", desktop=True):
    """Starts Divine Client in a dedicated custom native desktop window."""
    if port is None or not _is_port_free(port, host):
        port = _find_free_port(port or 8080)

    # Start Flask API backend in background daemon thread
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False),
        daemon=True,
    )
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    print(f"[*] Starting Divine Client on {url} ...")

    # Ensure backend is listening before launching window
    _wait_for_server(port, timeout=6.0)
    print(f"[*] Divine Client backend ready on {url}")

    if not desktop:
        # Web-only / headless mode
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Exiting Divine Client...")
            return 0

    # Dedicated Native Custom Window (No browser bars or tabs)
    try:
        import webview
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        icon_path = os.path.join(root_dir, "assets", "icon.ico")
        if not os.path.isfile(icon_path):
            icon_path = None

        window = webview.create_window(
            title="Divine Client",
            url=url,
            width=1280,
            height=800,
            min_size=(1024, 640),
            background_color="#080c14",
            resizable=True,
            confirm_close=False,
            easy_drag=True,
        )

        # On Windows, EdgeChromium provides native hardware-accelerated rendering
        if sys.platform == "win32":
            try:
                webview.start(gui="edgechromium", debug=False)
                return 0
            except Exception:
                webview.start(debug=False)
                return 0
        else:
            webview.start(debug=False)
            return 0

    except Exception as ex:
        print(f"[*] Native window initialization fallback: {ex}")
        try:
            webbrowser.open(url)
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Exiting Divine Client...")
            return 0
