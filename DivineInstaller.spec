# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build file for Divine Client Setup Installer (DivineInstaller.exe)."""
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(SPEC))
ICON = os.path.join(PROJECT_ROOT, "assets", "icon.ico")

def _app_version():
    init = os.path.join(PROJECT_ROOT, "arenclient", "__init__.py")
    try:
        with open(init, "r", encoding="utf-8") as handle:
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', handle.read())
        if match:
            return match.group(1).strip()
    except OSError:
        pass
    return "2.0.0"

VERSION = _app_version()

datas = []
for asset_name in ("emblem.png", "logo.png", "icon.ico"):
    p = os.path.join(PROJECT_ROOT, "assets", asset_name)
    if os.path.isfile(p):
        datas.append((p, "assets"))

a = Analysis(
    [os.path.join(PROJECT_ROOT, "installer.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox", "urllib.request", "zipfile", "hashlib"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "scipy", "pandas", "matplotlib", "PyQt5", "PyQt6"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DivineInstaller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=ICON if os.path.isfile(ICON) else None,
    uac_admin=False,
)
