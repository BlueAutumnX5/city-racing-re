@echo off
rem One-time setup on a new PC (safe to re-run any time):
rem   1. finds Python 3 (installs Python 3.14 with winget if there is none)
rem   2. makes the repo's own environment .venv and installs requirements.txt into it
rem   3. runs crsetup.py: finds the game, makes the pristine backup it rebuilds from, unpacks the archives,
rem      paints the HUD faces and checks crdrive.dll
rem Nothing in the game folder is changed by this.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :venv_ready

set "BASEPY="
for %%V in (3.14 3.13 3.12) do (
    if not defined BASEPY (
        py -%%V -c "import tkinter" >nul 2>&1 && set "BASEPY=py -%%V"
    )
)
if not defined BASEPY (
    rem "python" may be the Microsoft Store stub, which fails this check - that is fine
    python -c "import sys, tkinter; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "BASEPY=python"
)
if not defined BASEPY (
    echo No usable Python 3.12+ found. Installing Python 3.14 from python.org with winget...
    winget install -e --id Python.Python.3.14 --scope user --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo winget could not install Python. Install it from https://www.python.org/downloads/windows/
        echo ^(tick "Add python.exe to PATH" and keep "tcl/tk"^), then run setup.bat again.
        pause
        exit /b 1
    )
    set "BASEPY=py -3.14"
    py -3.14 -c "import tkinter" >nul 2>&1 || set "BASEPY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
)

echo Making .venv with %BASEPY% ...
%BASEPY% -m venv .venv
if errorlevel 1 (
    echo Could not create .venv.
    pause
    exit /b 1
)

:venv_ready
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo pip install failed - see the messages above.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" crsetup.py %*
set RC=%errorlevel%
echo.
pause
exit /b %RC%
