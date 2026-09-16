#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! python3 -c "import flask, minecraft_launcher_lib, requests, nbtlib" >/dev/null 2>&1; then
    echo "[*] Installing dependencies from requirements.txt..."
    python3 -m pip install -r requirements.txt
fi

echo "[*] Starting Divine Client..."
python3 main.py "$@"
