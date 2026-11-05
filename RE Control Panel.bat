@echo off
rem City Racing RE Project - control panel: every extra with its values, the chaos switch,
rem Car Tuner and Map Editor, in one window (crpanel.py). Hover anything for an explanation.
call "%~dp0_py.bat" || (pause & exit /b 1)
start "" "%PYW%" "%~dp0crpanel.py"
