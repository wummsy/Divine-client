#!/usr/bin/env python3
"""Divine Client v4 Official Installer & Setup Tool.

Fetches the latest published release of Divine Client from the official update
servers, verifies the SHA-256 cryptographic checksum, safely unpacks the client
files to the selected install directory, creates system shortcuts (Desktop & Start Menu),
and optionally launches the application.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

# Primary and fallback release metadata endpoints
SITE_CANDIDATES = [
    "https://divineclient.wispbyte.org",
    "http://78.154.103.46:10230",
]

VERSION_ENDPOINT = "/api/client/version"
DEFAULT_APP_NAME = "Divine Client"
DEFAULT_EXE_NAME = "DivineClient.exe"


def get_default_install_dir():
    """Determine the standard per-user installation directory."""
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            return os.path.join(local_app, "Programs", "DivineClient")
        app_data = os.environ.get("APPDATA")
        if app_data:
            return os.path.join(app_data, "DivineClient")
        return os.path.expanduser(r"~\AppData\Local\Programs\DivineClient")
    else:
        return os.path.expanduser("~/.divineclient/app")


def fetch_latest_release_info(candidates=None, timeout=12):
    """Query release endpoints for the latest version metadata."""
    if candidates is None:
        candidates = list(SITE_CANDIDATES)

    headers = {"User-Agent": "DivineClient-Installer/4.0.0"}
    last_err = None

    for base in candidates:
        url = base.rstrip("/") + VERSION_ENDPOINT
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, dict) and data.get("version"):
                        return {
                            "version": str(data.get("version") or "4.0.0"),
                            "url": str(data.get("url") or "").strip(),
                            "sha256": str(data.get("sha256") or "").strip().lower(),
                            "size": int(data.get("size") or 0),
                            "notes": str(data.get("notes") or "Official Divine Client Release"),
                            "file": str(data.get("file") or ""),
                            "source_endpoint": base,
                        }
        except Exception as e:
            last_err = e
            continue

    return {
        "error": f"Could not reach update servers ({last_err or 'offline'}).",
        "version": "2.0.0",
        "url": "",
        "sha256": "",
        "size": 0,
        "notes": "",
    }


def compute_file_sha256(filepath, chunk_size=1 << 20):
    """Compute standard SHA-256 hexadecimal digest for a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def format_bytes(n):
    """Human-readable byte size."""
    n = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024.0 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} MB"


def safe_extract_zip(zip_path, target_dir, progress_cb=None):
    """Extract zip archive safely, preventing zip-slip path traversal."""
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = len(members)

        # Detect top-level root folder prefix (e.g. "divine-client/" or "DivineClient/")
        top_dirs = set()
        for m in members:
            parts = m.filename.replace("\\", "/").strip("/").split("/")
            if len(parts) > 1:
                top_dirs.add(parts[0])
            elif not m.is_dir():
                top_dirs.add("")

        prefix_to_strip = None
        if len(top_dirs) == 1 and "" not in top_dirs:
            prefix_to_strip = list(top_dirs)[0] + "/"

        resolved_target = os.path.abspath(target_dir)

        for idx, m in enumerate(members):
            name = m.filename.replace("\\", "/")
            if prefix_to_strip and name.startswith(prefix_to_strip):
                name = name[len(prefix_to_strip):]

            if not name or name.startswith("/") or ".." in name.split("/"):
                continue

            dest_path = os.path.abspath(os.path.join(target_dir, name))
            if not dest_path.startswith(resolved_target + os.sep) and dest_path != resolved_target:
                continue  # Skip unsafe path traversal

            if m.is_dir() or name.endswith("/"):
                os.makedirs(dest_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with zf.open(m) as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

            if progress_cb:
                progress_cb((idx + 1) / max(1, total), f"Extracting {os.path.basename(name)}...")


def create_windows_shortcut(target_path, shortcut_path, description="Divine Client Minecraft Launcher", icon_path=None):
    """Create a Windows .lnk shortcut using PowerShell."""
    if sys.platform != "win32":
        return False
    try:
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        work_dir = os.path.dirname(target_path)
        icon_arg = f'$s.IconLocation = "{icon_path}";' if icon_path and os.path.isfile(icon_path) else ""
        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{target_path}"; '
            f'$s.WorkingDirectory = "{work_dir}"; '
            f'$s.Description = "{description}"; '
            f'{icon_arg} '
            f'$s.Save()'
        )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
        subprocess.run(cmd, capture_output=True, timeout=10)
        return os.path.isfile(shortcut_path)
    except Exception:
        return False


def create_linux_desktop_file(exec_path, desktop_file_path=None, icon_path=None):
    """Create a Linux XDG .desktop application launcher file."""
    if desktop_file_path is None:
        desktop_file_path = os.path.expanduser("~/.local/share/applications/divine-client.desktop")
    try:
        os.makedirs(os.path.dirname(desktop_file_path), exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Divine Client\n"
            "Comment=Modern Next-Gen Minecraft Launcher & Server Hub\n"
            f"Exec=\"{exec_path}\"\n"
            f"Path={os.path.dirname(exec_path)}\n"
            f"Icon={icon_path or 'divine-client'}\n"
            "Terminal=false\n"
            "Categories=Game;\n"
        )
        with open(desktop_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            os.chmod(desktop_file_path, 0o755)
        except OSError:
            pass
        return True
    except Exception:
        return False


class InstallerEngine:
    """Core installation controller for downloading, validating, and configuring."""

    def __init__(self, target_dir=None, release_info=None):
        self.target_dir = os.path.abspath(target_dir or get_default_install_dir())
        self.release_info = release_info or fetch_latest_release_info()
        self.downloaded_archive = None
        self.installed_exe = None

    def download_release(self, progress_cb=None, cancel_event=None):
        """Download latest release zip with streaming chunk updates."""
        url = self.release_info.get("url")
        if not url:
            # Check for local fallback packages in the current working directory
            for candidate in ("DivineClient-v4.0.0.zip", "DivineClient-v4.0.zip", "DivineClient-v4.0.0.zip", "DivineClient-v4.0.zip", "DivineClient-v3.0.zip", "client.zip"):
                if os.path.isfile(candidate):
                    self.downloaded_archive = os.path.abspath(candidate)
                    if progress_cb:
                        progress_cb(1.0, f"Using local package: {candidate}")
                    return self.downloaded_archive
            raise RuntimeError("No download URL provided by the update server and no local package found.")

        temp_dir = os.path.join(self.target_dir, ".temp_install")
        os.makedirs(temp_dir, exist_ok=True)
        filename = self.release_info.get("file") or os.path.basename(url.split("?")[0]) or "DivineClient-latest.zip"
        if not filename.endswith(".zip"):
            filename += ".zip"
        dest_path = os.path.join(temp_dir, filename)
        part_path = dest_path + ".part"

        if progress_cb:
            progress_cb(0.0, f"Connecting to {url}...")

        headers = {"User-Agent": "DivineClient-Installer/4.0.0"}
        req = urllib.request.Request(url, headers=headers)

        start_time = time.time()
        downloaded = 0

        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("Content-Length") or self.release_info.get("size") or 0)
            with open(part_path, "wb") as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        f.close()
                        try:
                            os.remove(part_path)
                        except OSError:
                            pass
                        raise RuntimeError("Installation cancelled by user.")

                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    elapsed = max(0.1, time.time() - start_time)
                    speed = downloaded / elapsed
                    fraction = min(1.0, downloaded / max(1, total_size)) if total_size > 0 else 0.5
                    status_text = (
                        f"Downloading: {format_bytes(downloaded)} / {format_bytes(total_size)} "
                        f"({format_bytes(speed)}/s)"
                        if total_size > 0 else f"Downloading: {format_bytes(downloaded)} ({format_bytes(speed)}/s)"
                    )
                    if progress_cb:
                        progress_cb(fraction, status_text)

        # Integrity Check
        expected_sha = self.release_info.get("sha256", "").strip().lower()
        if expected_sha:
            if progress_cb:
                progress_cb(0.98, "Verifying SHA-256 checksum...")
            actual_sha = compute_file_sha256(part_path)
            if actual_sha != expected_sha:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                raise RuntimeError(
                    f"Integrity check failed: Expected checksum {expected_sha[:12]}..., got {actual_sha[:12]}..."
                )

        if os.path.isfile(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        os.replace(part_path, dest_path)
        self.downloaded_archive = dest_path
        return dest_path

    def install(self, create_desktop=True, create_startmenu=True, progress_cb=None, cancel_event=None):
        """Perform full download, extraction, shortcut setup."""
        if not self.downloaded_archive or not os.path.isfile(self.downloaded_archive):
            self.download_release(progress_cb=progress_cb, cancel_event=cancel_event)

        if progress_cb:
            progress_cb(0.5, "Extracting client files...")

        safe_extract_zip(self.downloaded_archive, self.target_dir, progress_cb=progress_cb)

        # Locate launcher executable or python entry
        candidate_exes = [
            os.path.join(self.target_dir, "DivineClient.exe"),
            os.path.join(self.target_dir, "DivineClient.exe"),
            os.path.join(self.target_dir, "main.py"),
            os.path.join(self.target_dir, "divine-client", "DivineClient.exe"),
            os.path.join(self.target_dir, "divine-client", "DivineClient.exe"),
            os.path.join(self.target_dir, "divine-client", "main.py"),
        ]

        main_executable = None
        for c in candidate_exes:
            if os.path.isfile(c):
                main_executable = c
                break

        if not main_executable:
            main_executable = os.path.join(self.target_dir, "DivineClient.exe")

        self.installed_exe = main_executable

        # Find Icon
        icon_path = None
        for icon_cand in (
            os.path.join(self.target_dir, "assets", "emblem.ico"),
            os.path.join(self.target_dir, "assets", "emblem.png"),
            os.path.join(self.target_dir, "divine-client", "assets", "emblem.ico"),
            os.path.join(self.target_dir, "divine-client", "assets", "emblem.png"),
        ):
            if os.path.isfile(icon_cand):
                icon_path = icon_cand
                break

        # Create Shortcuts
        if progress_cb:
            progress_cb(0.9, "Creating application shortcuts...")

        if sys.platform == "win32":
            if create_desktop:
                desktop_folder = os.path.expanduser(r"~\Desktop")
                shortcut_path = os.path.join(desktop_folder, f"{DEFAULT_APP_NAME}.lnk")
                create_windows_shortcut(main_executable, shortcut_path, icon_path=icon_path)

            if create_startmenu:
                appdata = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
                start_menu_folder = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
                shortcut_path = os.path.join(start_menu_folder, f"{DEFAULT_APP_NAME}.lnk")
                create_windows_shortcut(main_executable, shortcut_path, icon_path=icon_path)
        else:
            if create_desktop or create_startmenu:
                create_linux_desktop_file(main_executable, icon_path=icon_path)

        # Cleanup temp archive
        temp_dir = os.path.join(self.target_dir, ".temp_install")
        shutil.rmtree(temp_dir, ignore_errors=True)

        if progress_cb:
            progress_cb(1.0, "Installation complete!")

        return main_executable

    def launch_installed_client(self):
        """Launch the installed Divine Client instance."""
        if not self.installed_exe or not os.path.isfile(self.installed_exe):
            return False
        try:
            if self.installed_exe.endswith(".py"):
                cmd = [sys.executable, self.installed_exe]
            else:
                cmd = [self.installed_exe]

            flags = 0
            if sys.platform == "win32":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            subprocess.Popen(
                cmd,
                cwd=os.path.dirname(self.installed_exe),
                close_fds=True,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False


# ===================================================================== GUI Mode
def run_gui_installer():
    """Launch the modern graphical setup wizard."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("[!] Tkinter not available in this environment. Falling back to CLI installer.")
        return run_cli_installer()

    root = tk.Tk()
    root.title(f"{DEFAULT_APP_NAME} Setup Wizard")
    root.geometry("620x520")
    root.minsize(580, 480)
    root.configure(bg="#0a0c12")

    engine = InstallerEngine()
    cancel_event = threading.Event()

    # Colors
    BG = "#080705"
    BG_CARD = "#120f0a"
    BG_CARD2 = "#1c1810"
    BORDER = "#332712"
    TEXT = "#ffffff"
    DIM = "#d1c9b8"
    GOLD = "#FFC72C"
    GOLD_HOVER = "#FFE066"

    # Style ttk widgets
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Divine.Horizontal.TProgressbar",
        troughcolor=BG_CARD2,
        background=GOLD,
        bordercolor=BORDER,
        lightcolor=GOLD,
        darkcolor=GOLD,
    )

    # Main container
    container = tk.Frame(root, bg=BG)
    container.pack(fill="both", expand=True, padx=24, pady=20)

    # State variables
    path_var = tk.StringVar(value=engine.target_dir)
    desktop_var = tk.BooleanVar(value=True)
    startmenu_var = tk.BooleanVar(value=True)
    launch_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="Ready to install.")
    progress_val = tk.DoubleVar(value=0.0)

    # --- Header ---
    hdr_frame = tk.Frame(container, bg=BG)
    hdr_frame.pack(fill="x", pady=(0, 16))

    title_label = tk.Label(
        hdr_frame,
        text="DIVINE CLIENT",
        font=("Segoe UI", 20, "bold"),
        fg=TEXT,
        bg=BG,
        anchor="w",
    )
    title_label.pack(anchor="w")

    ver_text = f"Version {engine.release_info.get('version', '4.0.0')} — Next-Gen Minecraft Launcher & Server Hub"
    sub_label = tk.Label(
        hdr_frame,
        text=ver_text,
        font=("Segoe UI", 10),
        fg=GOLD,
        bg=BG,
        anchor="w",
    )
    sub_label.pack(anchor="w", pady=(2, 0))

    # --- Content Card ---
    card = tk.Frame(container, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=20, pady=18)
    card.pack(fill="both", expand=True)

    # Initial Step: Configuration
    step_config = tk.Frame(card, bg=BG_CARD)
    step_config.pack(fill="both", expand=True)

    tk.Label(
        step_config,
        text="Installation Location",
        font=("Segoe UI", 11, "bold"),
        fg=TEXT,
        bg=BG_CARD,
    ).pack(anchor="w", pady=(0, 6))

    path_row = tk.Frame(step_config, bg=BG_CARD)
    path_row.pack(fill="x", pady=(0, 16))

    path_entry = tk.Entry(
        path_row,
        textvariable=path_var,
        font=("Segoe UI", 10),
        bg=BG_CARD2,
        fg=TEXT,
        insertbackground=TEXT,
        highlightbackground=BORDER,
        highlightthickness=1,
        relief="flat",
    )
    path_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

    def browse_folder():
        chosen = filedialog.askdirectory(initialdir=path_var.get(), title="Select Installation Folder")
        if chosen:
            path_var.set(chosen)

    browse_btn = tk.Button(
        path_row,
        text="Browse...",
        font=("Segoe UI", 9, "bold"),
        bg=BG_CARD2,
        fg=TEXT,
        activebackground=BORDER,
        activeforeground=TEXT,
        relief="flat",
        padx=12,
        pady=4,
        command=browse_folder,
    )
    browse_btn.pack(side="right")

    tk.Label(
        step_config,
        text="Shortcut Options",
        font=("Segoe UI", 11, "bold"),
        fg=TEXT,
        bg=BG_CARD,
    ).pack(anchor="w", pady=(4, 6))

    chk_desktop = tk.Checkbutton(
        step_config,
        text="Create Desktop Shortcut",
        variable=desktop_var,
        font=("Segoe UI", 10),
        fg=TEXT,
        bg=BG_CARD,
        activebackground=BG_CARD,
        activeforeground=TEXT,
        selectcolor=BG_CARD2,
    )
    chk_desktop.pack(anchor="w", pady=2)

    chk_start = tk.Checkbutton(
        step_config,
        text="Create Start Menu Shortcut",
        variable=startmenu_var,
        font=("Segoe UI", 10),
        fg=TEXT,
        bg=BG_CARD,
        activebackground=BG_CARD,
        activeforeground=TEXT,
        selectcolor=BG_CARD2,
    )
    chk_start.pack(anchor="w", pady=2)

    chk_launch = tk.Checkbutton(
        step_config,
        text="Launch Divine Client after installation finishes",
        variable=launch_var,
        font=("Segoe UI", 10),
        fg=TEXT,
        bg=BG_CARD,
        activebackground=BG_CARD,
        activeforeground=TEXT,
        selectcolor=BG_CARD2,
    )
    chk_launch.pack(anchor="w", pady=2)

    # Step: Progress (hidden initially)
    step_prog = tk.Frame(card, bg=BG_CARD)

    prog_title = tk.Label(
        step_prog,
        text="Installing Divine Client...",
        font=("Segoe UI", 12, "bold"),
        fg=TEXT,
        bg=BG_CARD,
    )
    prog_title.pack(anchor="w", pady=(10, 8))

    progressbar = ttk.Progressbar(
        step_prog,
        variable=progress_val,
        maximum=1.0,
        style="Divine.Horizontal.TProgressbar",
    )
    progressbar.pack(fill="x", pady=(10, 10), ipady=4)

    status_lbl = tk.Label(
        step_prog,
        textvariable=status_var,
        font=("Segoe UI", 9),
        fg=DIM,
        bg=BG_CARD,
        anchor="w",
    )
    status_lbl.pack(anchor="w")

    # Step: Done (hidden initially)
    step_done = tk.Frame(card, bg=BG_CARD)

    done_title = tk.Label(
        step_done,
        text="Installation Successfully Completed!",
        font=("Segoe UI", 14, "bold"),
        fg=GOLD,
        bg=BG_CARD,
    )
    done_title.pack(anchor="w", pady=(20, 10))

    done_msg = tk.Label(
        step_done,
        text=f"Divine Client is ready to use.\nYou can launch it now or find it on your Desktop / Start Menu.",
        font=("Segoe UI", 10),
        fg=DIM,
        bg=BG_CARD,
        justify="left",
    )
    done_msg.pack(anchor="w", pady=(0, 20))

    # --- Footer Controls ---
    ftr_frame = tk.Frame(container, bg=BG)
    ftr_frame.pack(fill="x", pady=(16, 0))

    def on_install_click():
        step_config.pack_forget()
        step_prog.pack(fill="both", expand=True)
        install_btn.config(state="disabled")

        target = path_var.get().strip() or get_default_install_dir()
        engine.target_dir = os.path.abspath(target)

        def worker():
            def update_ui(frac, text):
                def _apply():
                    progress_val.set(frac if frac is not None else 0.5)
                    status_var.set(text)
                root.after(0, _apply)

            try:
                engine.install(
                    create_desktop=desktop_var.get(),
                    create_startmenu=startmenu_var.get(),
                    progress_cb=update_ui,
                    cancel_event=cancel_event,
                )

                def show_finish():
                    step_prog.pack_forget()
                    step_done.pack(fill="both", expand=True)
                    install_btn.config(
                        text="Launch Client" if launch_var.get() else "Close",
                        state="normal",
                        command=on_finish_click,
                    )
                root.after(0, show_finish)

            except Exception as ex:
                def show_err():
                    messagebox.showerror("Installation Error", str(ex))
                    step_prog.pack_forget()
                    step_config.pack(fill="both", expand=True)
                    install_btn.config(state="normal")
                root.after(0, show_err)

        threading.Thread(target=worker, daemon=True).start()

    def on_finish_click():
        if launch_var.get():
            engine.launch_installed_client()
        root.destroy()

    def on_cancel_click():
        cancel_event.set()
        root.destroy()

    cancel_btn = tk.Button(
        ftr_frame,
        text="Cancel",
        font=("Segoe UI", 10),
        bg=BG_CARD,
        fg=DIM,
        activebackground=BORDER,
        activeforeground=TEXT,
        relief="flat",
        padx=18,
        pady=8,
        command=on_cancel_click,
    )
    cancel_btn.pack(side="left")

    install_btn = tk.Button(
        ftr_frame,
        text="Install Now",
        font=("Segoe UI", 10, "bold"),
        bg=GOLD,
        fg="#080705",
        activebackground=GOLD_HOVER,
        activeforeground="#080705",
        relief="flat",
        padx=24,
        pady=8,
        command=on_install_click,
    )
    install_btn.pack(side="right")

    # Center window on screen
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"+{x}+{y}")

    root.mainloop()


# ===================================================================== CLI Mode
def run_cli_installer(args=None):
    """Run interactive or silent command-line installation."""
    parser = argparse.ArgumentParser(description="Divine Client Official Setup & Installer")
    parser.add_argument("--dir", "-d", help="Installation directory path", default=None)
    parser.add_argument("--silent", "-s", action="store_true", help="Run silent installation without prompts")
    parser.add_argument("--no-launch", action="store_true", help="Do not launch client after installation")
    parser.add_argument("--no-shortcuts", action="store_true", help="Do not create desktop or start menu shortcuts")
    parser.add_argument("--check-only", action="store_true", help="Check and print latest release version only")
    parser.add_argument("--cli", action="store_true", help="Force command line interface")

    parsed = parser.parse_args(args)

    print("=" * 60)
    print(f"  {DEFAULT_APP_NAME} Official Installer")
    print("=" * 60)

    print("[*] Contacting update server for latest release information...")
    info = fetch_latest_release_info()

    if parsed.check_only:
        print(f"Latest Version : {info.get('version', 'Unknown')}")
        print(f"Download URL   : {info.get('url', 'None')}")
        print(f"SHA-256 Hash   : {info.get('sha256', 'None')}")
        print(f"Package Size   : {format_bytes(info.get('size', 0))}")
        return 0

    target_dir = parsed.dir or get_default_install_dir()
    print(f"[*] Target Directory: {target_dir}")
    print(f"[*] Release Version : {info.get('version', '4.0.0')}")

    if not parsed.silent:
        try:
            choice = input(f"\nInstall Divine Client to '{target_dir}'? [Y/n]: ").strip().lower()
            if choice and choice != "y":
                print("Installation aborted.")
                return 1
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 1

    engine = InstallerEngine(target_dir=target_dir, release_info=info)

    def print_progress(frac, text):
        bar_len = 30
        filled = int(bar_len * (frac if frac is not None else 0.5))
        bar = "█" * filled + "-" * (bar_len - filled)
        pct = f"{int((frac or 0) * 100):3d}%"
        print(f"\r[{bar}] {pct} {text}", end="", flush=True)

    print("\n[*] Starting download and installation...")
    try:
        engine.install(
            create_desktop=not parsed.no_shortcuts,
            create_startmenu=not parsed.no_shortcuts,
            progress_cb=print_progress,
        )
        print("\n\n[OK] Divine Client has been successfully installed!")
        print(f"[OK] Executable location: {engine.installed_exe}")

        if not parsed.no_launch:
            print("[*] Launching Divine Client...")
            engine.launch_installed_client()

        return 0
    except Exception as e:
        print(f"\n\n[ERROR] Installation failed: {e}")
        return 2


def main():
    """Main entrypoint: choose GUI or CLI based on arguments and platform."""
    if "--cli" in sys.argv or "--silent" in sys.argv or "-s" in sys.argv or "--check-only" in sys.argv:
        sys.exit(run_cli_installer())

    # If running headless without display on Linux, fall back to CLI
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        sys.exit(run_cli_installer())

    try:
        run_gui_installer()
    except Exception:
        sys.exit(run_cli_installer())


if __name__ == "__main__":
    main()
