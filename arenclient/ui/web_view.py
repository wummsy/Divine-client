"""Desktop WebView & Browser Launcher for Divine Client.

Runs the backend web server in a background thread and opens the modern
HTML5/CSS3 interface in a native desktop window (via PySide6 or pywebview)
or web browser.
"""

import os
import sys
import threading
import time
import webbrowser
import socket

from .. import paths
from ..web_server import app


def _find_free_port(start=8080):
    for p in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def launch_web_ui(port=None, host="0.0.0.0", desktop=True):
    """Starts the Divine Client Web UI and opens the application window."""
    if port is None:
        port = _find_free_port(8080)

    # Start Flask API backend in background thread
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False),
        daemon=True,
    )
    server_thread.start()

    url = f"http://localhost:{port}"
    print(f"[*] Divine Client WebUI active on {url}")

    if not desktop:
        # Web-only mode
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Exiting...")
            return 0

    # Desktop window mode
    # Try pywebview first
    try:
        import webview
        icon_path = os.path.join(paths.ASSETS_DIR if hasattr(paths, "ASSETS_DIR") else os.path.dirname(os.path.dirname(__file__)), "assets", "icon.ico")
        window = webview.create_window(
            "Divine Client",
            url=url,
            width=1120,
            height=740,
            min_size=(960, 600),
            background_color="#080c14",
        )
        webview.start()
        return 0
    except Exception as e:
        pass

    # Fallback: Open in default system browser
    print(f"[*] Opening Divine Client in browser: {url}")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
