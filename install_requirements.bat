@echo off
title Install Divine Client Requirements
cd /d "%~dp0"
echo ===================================================
echo     Installing Dependencies for Divine Client
echo ===================================================
echo.
python -m pip install -r requirements.txt
echo.
echo ===================================================
echo  All dependencies installed! You can run start.bat
echo ===================================================
pause
