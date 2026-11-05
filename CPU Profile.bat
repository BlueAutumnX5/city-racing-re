@echo off
rem City Racing CPU profile (Stage 2 #15a): start the game, drive to where the FPS is low (city centre),
rem then run this. It waits for the game, samples its main thread for 30 seconds and writes
rem cpuprofile_<time>.txt here: how much time goes to physics, traffic/AI, rendering, the driver...
rem Nothing is changed in the game. Optional: "CPU Profile.bat" 60   (seconds)
call "%~dp0_py.bat" || (pause & exit /b 1)
"%PY%" "%~dp0cpuprofile.py" %*
echo.
pause
