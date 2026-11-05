@echo off
rem City Racing RE stutter profiler: run this when the game starts stuttering (game running, then drive).
rem For 10 minutes it logs the FPS every second and profiles the main thread ONLY while the FPS is under 25
rem (pausing / other windows are left out), then writes "Stutter reports\<date_time>\" with summary.txt:
rem CPU-bound or waiting, when, how many cars. Nothing in the game is changed.
rem Optional: "Stutter Profiler.bat" 5   (minutes)
call "%~dp0_py.bat" || (pause & exit /b 1)
"%PY%" "%~dp0stutter.py" %*
echo.
pause
