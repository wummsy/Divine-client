@echo off
setlocal
title Divine Client - allow it in Windows Defender
rem Double-click this. It re-launches itself elevated (one UAC prompt) and then
rem runs defender_exclusions.ps1 next to it, which adds exclusions for the Divine
rem folders only. Nothing else about your protection settings is touched.

set "PS1=%~dp0defender_exclusions.ps1"
if not exist "%PS1%" (
    if exist "%~dp0..\tools\defender_exclusions.ps1" set "PS1=%~dp0..\tools\defender_exclusions.ps1"
)
if not exist "%PS1%" (
    echo Could not find defender_exclusions.ps1 next to this file.
    echo It lives in tools\ in the repository - put them together and run again.
    pause
    exit /b 1
)

net session >nul 2>nul
if errorlevel 1 (
    echo Requesting administrator rights - Defender settings need them.
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs"
    if errorlevel 1 echo The elevation prompt was declined. Run this file as Administrator.
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -AppPath "%~dp0."
echo.
pause
endlocal
