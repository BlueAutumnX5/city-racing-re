@echo off
rem Puts this project's archive edits into the installed game (close City Racing first):
rem the Map Editor route edits (mods\GlobalRoute.patch.json) and the Milky Way sky texture.
rem Run once on a new PC after setup.bat. Safe to re-run: it skips what is already in.
call "%~dp0_py.bat" || (pause & exit /b 1)
"%PY%" "%~dp0crsetup.py" data
echo.
pause
