@echo off
setlocal enabledelayedexpansion
title Divine Client Installer Builder

echo ========================================================
echo   Divine Client Setup Installer Builder (PyInstaller)
echo ========================================================

cd /d "%~dp0"

:: 1. Detect Python or Py Launcher
set "PYCMD="
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PYCMD=python"
) else (
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "PYCMD=py"
    )
)

if "%PYCMD%"=="" (
    echo [ERROR] Python was not found on your system!
    echo Please install Python 3.10+ from python.org and enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [*] Using Python executable: %PYCMD%

:: 2. Ensure PyInstaller module is available
%PYCMD% -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [*] PyInstaller not detected. Installing pyinstaller via pip...
    %PYCMD% -m pip install --upgrade pip
    %PYCMD% -m pip install pyinstaller
)

:: 3. Run PyInstaller via python module invocation (works without PATH script issues)
echo.
echo [*] Compiling DivineInstaller.exe using %PYCMD% -m PyInstaller...
%PYCMD% -m PyInstaller --clean -y DivineInstaller.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo [SUCCESS] Build succeeded! Executable generated at:
    echo           dist\DivineInstaller.exe
    echo ========================================================
    echo.
) else (
    echo.
    echo ========================================================
    echo [ERROR] Build failed with error code %ERRORLEVEL%.
    echo ========================================================
    echo.
)

pause
