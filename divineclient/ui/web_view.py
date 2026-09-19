"""Desktop WebView & Browser Launcher for Divine Client.

Runs the backend web server in a background thread and opens the modern
HTML5/CSS3 interface in the default system browser or native desktop window.
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
    """Starts the Divine Client Web UI and opens the application."""
    if port is None or not _is_port_free(port, host):
        port = _find_free_port(port or 8080)

    # Start Flask API backend in background daemon thread
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False),
        daemon=True,
    )
    server_thread.start()

    url = f"http://localhost:{port}"
    print(f"[*] Starting Divine Client on {url} ...")

    # Ensure backend is listening before triggering browser
    server_ready = _wait_for_server(port, timeout=5.0)
    if server_ready:
        print(f"[*] Divine Client backend ready on {url}")
    else:
        print(f"[*] Note: Divine Client initialized on {url}")

    if not desktop:
        # Web-only / headless mode
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Exiting Divine Client...")
            return 0

    # Desktop mode: Open browser immediately
    try:
        print(f"[*] Opening Divine Client UI: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"[*] Browser open note: {e}")

    # Keep server running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Exiting Divine Client...")
        return 0
