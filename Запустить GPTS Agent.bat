@echo off
REM Second Lane
REM Copyright (c) 2026 Yurii Slepnev
REM Licensed under the Apache License, Version 2.0.
REM Official: https://t.me/yurii_yurii86 | https://youtube.com/@yurii_yurii86

chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist "%~dp0.env" goto :runinstaller
findstr /B /C:"AGENT_TOKEN=replace-this-with-a-long-random-secret-token" "%~dp0.env" >nul 2>nul && goto :runinstaller
findstr /B /C:"NGROK_DOMAIN=your-domain.ngrok-free.dev" "%~dp0.env" >nul 2>nul && goto :runinstaller
if not exist "%~dp0.venv\Scripts\uvicorn.exe" goto :runinstaller

REM ---------------------------------------------------------------
REM Launch gpts_agent_control.py using pythonw.exe (GUI subsystem)
REM so NO console window appears alongside the Tkinter panel.
REM Falls back to python.exe if pythonw.exe is not found.
REM ---------------------------------------------------------------

set "SCRIPT=%~dp0gpts_agent_control.py"
set "PANEL_LOG=%TEMP%\secondary-lane-panel-startup.log"
set "PF86=%ProgramFiles(x86)%"
set "PY313_LOCAL=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "PY313_PF=%ProgramFiles%\Python313\python.exe"
set "PY313_PF86=%PF86%\Python313\python.exe"
set "PYEXE="

REM --- Try only confirmed Python 3.13. Older/default Python can crash the GUI silently. ---
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYEXE=%~dp0.venv\Scripts\python.exe"
)

where py >nul 2>nul
if not defined PYEXE (
    if not errorlevel 1 (
        for /f "delims=" %%i in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
    )
)

REM --- Fallback: plain "python" only if it is exactly Python 3.13 ---
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
        if not errorlevel 1 (
            for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
        )
    )
)

if not defined PYEXE (
    for %%P in ("!PY313_LOCAL!" "!PY313_PF!" "!PY313_PF86!") do (
        if exist "%%~P" (
            "%%~P" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
            if not errorlevel 1 if not defined PYEXE set "PYEXE=%%~P"
        )
    )
)

if not defined PYEXE goto :nopython

REM --- Verify the control panel before pythonw.exe hides any startup error. ---
"!PYEXE!" "%~dp0gpts_agent_control.py" --self-check > "!PANEL_LOG!" 2>&1
if errorlevel 1 goto :panelfailed

REM --- Prefer pythonw.exe (no console window) after the self-check passes. ---
set "PYWEXE=!PYEXE:python.exe=pythonw.exe!"

"!PYEXE!" "%~dp0second_lane_installer.py" --needs-repair >nul 2>nul
if errorlevel 1 goto :runinstaller

if exist "!PYWEXE!" (
    start "" "!PYWEXE!" "!SCRIPT!"
    goto :eof
)

REM --- Fallback: python.exe (console window will appear briefly) ---
start "" "!PYEXE!" "!SCRIPT!"
goto :eof

:runinstaller
echo.
echo =========================================================
echo   Secondary LANE is not configured yet.
echo   Opening the installer first so setup stays simple.
echo =========================================================
echo.
if exist "%~dp0Установить Secondary LANE.bat" (
    start "" "%~dp0Установить Secondary LANE.bat"
    goto :eof
)
echo Installer file not found:
echo   %~dp0Установить Secondary LANE.bat
echo.
pause
goto :eof

:panelfailed
echo.
echo =========================================================
echo   Secondary LANE control panel could not start cleanly.
echo =========================================================
echo.
echo I did NOT close silently. This is the startup log:
echo   !PANEL_LOG!
echo.
if exist "!PANEL_LOG!" (
    type "!PANEL_LOG!"
) else (
    echo Startup log was not created.
)
echo.
echo What to do:
echo 1. Run "Установить Secondary LANE.bat" once more.
echo 2. If this repeats, send the startup log to the person helping you.
echo.
pause
goto :eof

:nopython
echo.
echo =========================================================
echo   Python not found on this computer.
echo   Secondary LANE requires Python 3.13 for Windows.
echo =========================================================
echo.
echo What to do:
echo 1. Open:  https://www.python.org/downloads/windows/
echo 2. Download Python 3.13 for Windows (64-bit installer).
echo 3. IMPORTANT: check "Add python.exe to PATH" during install.
echo 4. Reboot.
echo 5. Double-click this .bat again.
echo.
echo To verify the install, open a new cmd window and run:
echo   py -3.13 --version
echo.
pause
goto :eof
