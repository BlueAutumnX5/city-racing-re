@echo off
rem Live night setup for City Racing RE (memory only): start the game, get into 3D, then run this.
rem Re-run after every game start. "Night Mode (live).bat off" undoes it.
call "%~dp0_py.bat" || (pause & exit /b 1)
"%PY%" "%~dp0re-tools\nightmode.py" %1
pause
