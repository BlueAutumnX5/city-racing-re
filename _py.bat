@echo off
rem Sets PY (console) and PYW (no console) to the repo's own Python environment (.venv, made by setup.bat).
rem Every launcher .bat calls this first.
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
    set "PYW=%~dp0.venv\Scripts\pythonw.exe"
    exit /b 0
)
echo The City Racing RE tools are not set up on this PC yet.
echo Double-click setup.bat in "%~dp0" once, then try again.
exit /b 1
