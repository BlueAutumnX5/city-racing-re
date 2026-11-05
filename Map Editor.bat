@echo off
rem City Racing Map / Navigation Editor - no console, no admin needed
call "%~dp0_py.bat" || (pause & exit /b 1)
start "" "%PYW%" "%~dp0mapeditor.py"
