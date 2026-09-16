@echo off
setlocal enabledelayedexpansion
title Divine Client - Windows build
echo.
echo  Divine Client - building DivineClient.exe
echo  --------------------------------------
echo.

cd /d "%~dp0"
set "SPEC=DivineClient.spec"
set "MODE=onedir"
set "SIGN=0"
set "ZIP=1"

:args
if "%~1"=="" goto args_done
if /I "%~1"=="-onefile" (
    set "SPEC=DivineClient.onefile.spec"
    set "MODE=onefile"
    echo  Note: one-file builds are the ones antivirus dislikes. See docs\ANTIVIRUS.md
) else if /I "%~1"=="-sign" (
    set "SIGN=1"
) else if /I "%~1"=="-nozip" (
    set "ZIP=0"
) else if /I "%~1"=="-help" (
    echo Usage: build_exe.bat [ -onefile ] [ -sign ] [ -nozip ]
    echo.
    echo   default   one-dir build into dist\DivineClient\, zipped with a SHA-256 sidecar
    echo   -onefile  single dist\DivineClient.exe ^(easier to hand around, more flags^)
    echo   -sign     run signtool if a certificate is present in the store
    echo   -nozip    leave the output unpacked
    goto end
)
shift
goto args

:args_done
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from python.org and
    echo tick "Add Python to PATH" during setup.
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || (
    echo Dependency install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building (%MODE%). This takes a couple of minutes...
rem No --noupx here: PyInstaller rejects it when a .spec file is given. upx=False is
rem set on both EXE and COLLECT in the spec, which is what actually controls it.
python -m PyInstaller "%SPEC%" --noconfirm
if errorlevel 1 (
    echo The build failed. Scroll up for the error.
    pause
    exit /b 1
)

set "OUT=dist\DivineClient"
set "EXE=dist\DivineClient\DivineClient.exe"
if "%MODE%"=="onefile" (
    set "OUT=dist\DivineClient.exe"
    set "EXE=dist\DivineClient.exe"
)
if not exist "%OUT%" (
    echo Something went wrong - %OUT% was not created. Scroll up to see the error.
    pause
    exit /b 1
)

rem Read the version out of the package so the zip is named after what is inside it.
set "VERSION=0.0.0"
for /f "delims=" %%l in ('findstr /b /c:"__version__" arenclient\__init__.py') do set "LINE=%%l"
set "LINE=%LINE:"=%"
for /f "tokens=2 delims==" %%v in ("%LINE%") do set "VERSION=%%v"
set "VERSION=%VERSION: =%"

if "%SIGN%"=="1" (
    where signtool >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  Skipping signing: signtool.exe not on PATH. Install the Windows SDK
        echo  ^(or open a "Developer Command Prompt"^) and re-run with -sign.
    ) else (
        echo.
        echo  Signing DivineClient.exe...
        if defined DIVINE_CERT_SHA1 (
            signtool sign /fd SHA256 /sha1 %DIVINE_CERT_SHA1% /tr http://timestamp.digicert.com /td SHA256 "%EXE%"
        ) else (
            signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "%EXE%"
        )
        if errorlevel 1 echo   signtool failed - the build is still usable, just unsigned.
    )
) else (
    echo.
    echo  Not signed. Unsigned + a brand-new file hash is why SmartScreen shows
    echo  "unknown publisher". To sign, add -sign once you have a code-signing
    echo  certificate; instructions are in docs\ANTIVIRUS.md.
)

rem A zip of the folder is what people should download; a loose exe in Downloads is
rem what SmartScreen is tuned to catch. Also ship the run-me text + the exclusion
rem helper inside the folder so the zip explains itself.
if "%MODE%"=="onedir" (
    > "dist\DivineClient\HOW-TO-RUN.txt" (
        echo Divine Client %VERSION%
        echo ===============
        echo.
        echo 1. Unzip this folder somewhere permanent first - not "just click Run"
        echo    from inside the zip, and not straight out of your Downloads folder.
        echo    C:\Games\DivineClient or C:\Program Files\DivineClient are good.
        echo 2. Double-click DivineClient.exe.
        echo.
        echo If nothing happens, or Windows says it is a threat:
        echo    - SmartScreen: "More info" then "Run anyway". It checks the file's
        echo      reputation, not its contents. We are unsigned; that is the whole
        echo      reason it appears.
        echo    - Defender: on the first open this launcher offers "Add for me",
        echo      which needs one administrator confirmation and then excludes this
        echo      folder and the Divine data folder only. It never turns protection off,
        echo      never excludes a whole drive, and the same button is in Settings ^>
        echo      Windows Defender whenever you want it - including Remove.
        echo    - Defender already ate the file: restore it from Protection history
        echo      ^(Actions ^> Allow on device^), or double-click
        echo      add_defender_exclusions.bat in this folder instead.
        echo.
        echo This build is one-dir on purpose: the program runs from this folder and
        echo never unpacks itself into your Temp directory. It writes its settings to
        echo %%APPDATA%%\.arenclient and nothing in the registry, no startup entry.
        echo.
        echo This build comes from build_exe.bat in the source folder. There is no
        echo public repository and no installer: the folder you unzipped is the
        whole program. The .sha256.txt written next to the zip is there if you
        want to prove a copy you passed on arrived intact:
        echo     Get-FileHash .\DivineClient-windows.zip -Algorithm SHA256
    )
    copy /y "tools\add_defender_exclusions.bat" "dist\DivineClient\" >nul 2>nul
    copy /y "tools\defender_exclusions.ps1" "dist\DivineClient\" >nul 2>nul
)

if "%ZIP%"=="1" (
    echo.
    echo Packing...
    if "%MODE%"=="onedir" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\DivineClient' -DestinationPath 'dist\DivineClient-%VERSION%-windows.zip' -Force"
        set "TARGET=dist\DivineClient-%VERSION%-windows.zip"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\DivineClient.exe' -DestinationPath 'dist\DivineClient-%VERSION%-windows-onefile.zip' -Force"
        set "TARGET=dist\DivineClient-%VERSION%-windows-onefile.zip"
    )
    if exist "!TARGET!" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "$h=(Get-FileHash '!TARGET!' -Algorithm SHA256).Hash.ToLower(); Set-Content -Path '!TARGET!.sha256.txt' -Value $h -Encoding ascii; Write-Output $h"
        echo   wrote !TARGET!
        echo   and !TARGET!.sha256.txt - publish that hash next to the download link
        echo   so people can check what they got:
        echo     Get-FileHash .\DivineClient-%VERSION%-windows.zip
    ) else (
        echo   Compress-Archive did not produce a zip - copy dist\DivineClient by hand.
    )
)

echo.
echo  Done.
if "%MODE%"=="onedir" (
    echo    App folder : dist\DivineClient\   ^(run DivineClient.exe from inside it^)
    echo    Give people the zip, not the loose exe.
) else (
    echo    Single file: dist\DivineClient.exe
)
echo.
echo  Before you upload, it is worth telling Defender the build is clean - a
echo  submitted-and-cleared exe stops the "virus" reports before they start:
echo    https://www.microsoft.com/wdsi/filesubmission
echo  Full checklist: docs\ANTIVIRUS.md
echo.
pause
:end
endlocal
