@echo off
rem City Racing Car Tuner - no console window, no admin needed
rem (Modify rights were granted to your account on the game folder)
call "%~dp0_py.bat" || (pause & exit /b 1)
start "" "%PYW%" "%~dp0cartuner.py"
