@echo off
chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "SCRIPT=%~dp0second_lane_installer.py"
set "INSTALLER_LOG=%TEMP%\secondary-lane-installer-startup.log"
set "PF86=%ProgramFiles(x86)%"
set "PY313_LOCAL=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "PY313_PF=%ProgramFiles%\Python313\python.exe"
set "PY313_PF86=%PF86%\Python313\python.exe"
set "PYEXE="

:resolvepython
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
)

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

"!PYEXE!" -c "import tkinter as tk; root=tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()" >nul 2>nul
if errorlevel 1 goto :notk

"!PYEXE!" "!SCRIPT!" --self-check > "!INSTALLER_LOG!" 2>&1
if errorlevel 1 goto :installerfailed

"!PYEXE!" "!SCRIPT!"
if errorlevel 1 goto :installerfailed
goto :eof

:nopython
echo.
echo =========================================================
echo   Python not found on this computer.
echo   This installer needs Python 3.13 to show the setup window.
echo =========================================================
echo.
echo What to do:
echo 1. Browser will open the Python 3.13 download page.
echo 2. Install Python 3.13 for Windows.
echo 3. IMPORTANT: check "Add python.exe to PATH".
echo 4. After the install finishes, come back to this window.
echo 5. Press Enter here and I will try again automatically.
echo.
start "" "https://www.python.org/downloads/windows/"
:retryafterpython
set /p _retry="Press Enter to re-check Python, or type Q to quit: "
if /I "!_retry!"=="Q" goto :eof
goto :resolvepython

:notk
echo.
echo =========================================================
echo   Python was found, but its GUI components are not ready.
echo =========================================================
echo.
echo What to do:
echo 1. Reinstall Python 3.13 from python.org.
echo 2. Use the full Windows installer, not a minimal or embedded build.
echo 3. Then come back here and press Enter to try again.
echo.
start "" "https://www.python.org/downloads/windows/"
set /p _retrytk="Press Enter to re-check Python GUI, or type Q to quit: "
if /I "!_retrytk!"=="Q" goto :eof
goto :resolvepython

:installerfailed
echo.
echo =========================================================
echo   The installer could not start cleanly.
echo =========================================================
echo.
echo I did NOT close silently. This is the startup log:
echo   !INSTALLER_LOG!
echo.
if exist "!INSTALLER_LOG!" (
    type "!INSTALLER_LOG!"
) else (
    echo Startup log was not created.
)
echo.
echo What to do:
echo 1. Reinstall Python 3.13 from python.org.
echo 2. Make sure "Add python.exe to PATH" is enabled.
echo 3. Run this installer again.
echo.
pause
