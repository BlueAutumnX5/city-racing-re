@echo off
rem Live headlight sliders (cars with headlights, brightness). Needs Night Mode (live).bat first.
call "%~dp0_py.bat" || (pause & exit /b 1)
start "" "%PYW%" "%~dp0re-tools\hlslider.py"
