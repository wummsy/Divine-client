@echo off
title Divine Client
cd /d "%~dp0"

echo ===================================================
echo              DIVINE CLIENT - STARTUP
echo ===================================================
echo.

python -c "import flask, minecraft_launcher_lib, requests, nbtlib" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Checking and installing Python dependencies...
    python -m pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [!] Failed to install dependencies. Make sure Python and pip are installed.
        pause
        exit /b 1
    )
)

echo [*] Launching Divine Client...
python main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Divine Client closed or encountered an issue.
    pause
)
