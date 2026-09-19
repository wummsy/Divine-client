#!/usr/bin/env python3
"""Cross-platform installer builder for Divine Client Setup using PyInstaller."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    print("=" * 60)
    print("       DIVINE CLIENT — INSTALLER BUILDER (v5.0.0)")
    print("=" * 60)

    # 1. Check & Install PyInstaller
    try:
        import PyInstaller
        print(f"[*] PyInstaller detected (version {PyInstaller.__version__})")
    except ImportError:
        print("[*] PyInstaller not installed. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Clean previous build artifacts
    build_dir = os.path.join(HERE, "build")
    dist_dir = os.path.join(HERE, "dist")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)

    spec_file = os.path.join(HERE, "DivineInstaller.spec")
    print(f"\n[*] Running PyInstaller with spec: {spec_file}...")
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "-y", spec_file]
    ret = subprocess.call(cmd, cwd=HERE)

    if ret == 0:
        print("\n" + "=" * 60)
        print(" [SUCCESS] Divine Installer build completed successfully!")
        print(f" Output executable: {os.path.join(HERE, 'dist', 'DivineInstaller.exe')}")
        print("=" * 60 + "\n")
    else:
        print(f"\n[!] Build failed with exit code {ret}")
        sys.exit(ret)


if __name__ == "__main__":
    main()
