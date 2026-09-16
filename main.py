"""Entry point for Divine Client - Next-Gen UI & Minecraft Launcher."""
import os
import sys
import traceback

LAUNCHER_NAME = "Divine Client"


def _describe_launch():
    """One line describing how we were started - useful when triaging reports."""
    part = getattr(sys, "_MEIPASS", "")
    packed = "onefile (extracts to %s)" % part if part else \
        ("one-dir (%s)" % os.path.dirname(os.path.abspath(sys.argv[0] or ""))
         if getattr(sys, "frozen", False) else "source")
    return "%s | python %s | frozen=%s | %s" % (
        os.path.abspath(sys.argv[0] or "main.py"),
        ".".join(str(p) for p in sys.version_info[:3]),
        bool(getattr(sys, "frozen", False)), packed)


def _report(exc):
    """Log a startup failure to every place that might still be writable."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    blocks = ["%s failed to start\n%s\n%s" % (LAUNCHER_NAME, _describe_launch(), text)]

    for target in _report_targets():
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("\n".join(blocks) + "\n\n")
        except Exception:
            pass

    print("\n".join(blocks), file=sys.stderr)
    _popup(text, next(iter(_report_targets()), "logs/crash.log"))


def _data_dir():
    """The launcher's data folder, same rules as divineclient.paths."""
    try:
        from divineclient import paths
        return paths.DATA_DIR
    except Exception:
        pass
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, ".divineclient")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "divineclient")
    root = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(root, "divineclient")


def _report_targets():
    """Crash log path(s)."""
    data = _data_dir()
    yield os.path.join(data, "logs", "crash.log")
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desk):
        yield os.path.join(desk, "Divine Client - startup problem.txt")


def _popup(detail, log_path):
    """Best-effort dialog."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "%s could not start" % LAUNCHER_NAME,
            "It ran, then stopped before the window could open.\n\n"
            "The details were written to\n  %s\n\n%s"
            % (log_path, detail[:900]))
        root.destroy()
    except Exception:
        pass


def _update_mode_args(argv):
    """Pull ``--apply-update`` (and its optional ``--wait-pid``) out of argv."""
    payload = None
    wait_pid = None
    rest = list(argv)
    if "--apply-update" in rest:
        i = rest.index("--apply-update")
        rest.pop(i)
        payload = rest.pop(i) if i < len(rest) else ""
    if "--wait-pid" in rest:
        j = rest.index("--wait-pid")
        rest.pop(j)
        try:
            wait_pid = int(rest.pop(j)) if j < len(rest) else None
        except (TypeError, ValueError):
            wait_pid = None
    return (payload or None), wait_pid


def _ensure_dependencies():
    """When running from source, check and auto-install missing dependencies."""
    if getattr(sys, "frozen", False):
        return
    required = {
        "flask": "flask>=3.0.0",
        "minecraft_launcher_lib": "minecraft-launcher-lib>=8.0",
        "requests": "requests>=2.28.0",
        "nbtlib": "nbtlib>=2.0.4",
    }
    missing = []
    for mod_name in required:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(mod_name)

    if missing:
        print(f"[*] Missing Python packages: {', '.join(missing)}")
        print("[*] Automatically installing required dependencies...")
        req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        try:
            import subprocess
            if os.path.exists(req_file):
                cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
            else:
                pkgs = [required[m] for m in missing]
                cmd = [sys.executable, "-m", "pip", "install"] + pkgs
            subprocess.check_call(cmd)
            print("[*] All dependencies installed successfully!\n")
        except Exception as err:
            print(f"\n[!] Automatic dependency installation failed: {err}")
            print("[!] Please run the following command in your terminal / command prompt:")
            print("    pip install -r requirements.txt\n")


def main():
    _ensure_dependencies()

    payload, wait_pid = _update_mode_args(sys.argv[1:])
    if payload:
        from divineclient.ui.app import apply_update_and_exit
        sys.exit(apply_update_and_exit(payload, wait_pid))

    args = sys.argv[1:]
    if "--legacy-gui" in args:
        from divineclient.ui.app import run
        run()
        return

    port = 8080
    for idx, a in enumerate(args):
        if a == "--port" and idx + 1 < len(args):
            try:
                port = int(args[idx + 1])
            except ValueError:
                pass

    desktop = "--web" not in args and "--no-desktop" not in args
    from divineclient.ui.web_view import launch_web_ui
    launch_web_ui(port=port, host="0.0.0.0", desktop=desktop)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        _report(err)
        sys.exit(1)
