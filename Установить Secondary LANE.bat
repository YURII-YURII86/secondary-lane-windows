@echo off
chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "SCRIPT=%~dp0second_lane_installer.py"
set "INSTALLER_LOG=%TEMP%\secondary-lane-installer-startup.log"
set "PYTHON_INSTALLER_URL=https://www.python.org/ftp/python/3.13.13/python-3.13.13-amd64.exe"
set "PYTHON_INSTALLER_EXE=%TEMP%\secondary-lane-python-3.13.13-amd64.exe"
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
echo 1. I will try to download the official Python 3.13 installer.
echo 2. If Windows asks for permission, approve the Python installer.
echo 3. After Python finishes, I will re-check automatically.
echo.
call :downloadpythoninstaller
if exist "!PYTHON_INSTALLER_EXE!" (
    echo.
    echo Starting Python installer. Please wait until it finishes...
    start /wait "" "!PYTHON_INSTALLER_EXE!" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0
    goto :resolvepython
)
echo.
echo Automatic download did not finish. Opening the Python page as a fallback.
start "" "https://www.python.org/downloads/latest/python3.13/"
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
echo 1. I will try to repair this with the full official Python 3.13 installer.
echo 2. If Windows asks for permission, approve the Python installer.
echo 3. Then I will re-check automatically.
echo.
call :downloadpythoninstaller
if exist "!PYTHON_INSTALLER_EXE!" (
    echo Starting Python installer. Please wait until it finishes...
    start /wait "" "!PYTHON_INSTALLER_EXE!" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0
    goto :resolvepython
)
echo Automatic download did not finish. Opening the Python page as a fallback.
start "" "https://www.python.org/downloads/latest/python3.13/"
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
goto :eof

:downloadpythoninstaller
if exist "!PYTHON_INSTALLER_EXE!" (
    for %%A in ("!PYTHON_INSTALLER_EXE!") do if %%~zA LSS 10000000 del /q "!PYTHON_INSTALLER_EXE!" >nul 2>nul
)
if exist "!PYTHON_INSTALLER_EXE!" goto :eof
echo Downloading official Python 3.13 installer from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYTHON_INSTALLER_URL%' -OutFile '%PYTHON_INSTALLER_EXE%'" >nul 2>nul
if exist "!PYTHON_INSTALLER_EXE!" goto :eof
where curl >nul 2>nul
if not errorlevel 1 (
    curl -fL --connect-timeout 15 --max-time 600 -o "!PYTHON_INSTALLER_EXE!" "!PYTHON_INSTALLER_URL!" >nul 2>nul
)
goto :eof
