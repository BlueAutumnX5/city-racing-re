@echo off
rem City Racing race-course / RNG patcher.
rem EASIER: double-click "RE Control Panel.bat" - every switch and value below in one
rem window, with sliders, explanations and previews. This file still works the same.
rem The interpreter comes from _py.bat (the repo's .venv made by setup.bat).
rem
rem   "Race Chaos.bat"            show what is patched
rem   "Race Chaos.bat" level 3    apply a level
rem        1 mild     stock feel, different routes
rem        2 twisty   random race length, ~6 U-turns
rem        3 wild     always long, ~10 U-turns
rem        4 insane   level 3 + scenery reshuffles
rem        5 anarchy  ~20 U-turns, zig-zag on a few streets
rem        6 chaos    (also: level chaos) wander + spread with the A* bug LIVE:
rem                   U-turns, lottery lengths, rare straight / ocean jumps
rem                   no astarfix, so long courses can overflow - see racesim
rem        7 chaos leap  (also: level "chaos leap") chaos + straight-line leaps
rem                   between roads; carries the A* fix, cannot overflow
rem
rem   CHAOS SWITCH - race routes only, every extra below stays as it is:
rem   "Race Chaos.bat" chaos                  is chaos on or off?
rem   "Race Chaos.bat" chaos off              STOCK race routes, the game as it was meant to be
rem   "Race Chaos.bat" chaos on               your cursed chaos level back (remembers which)
rem
rem   EXTRAS - kept on when you switch level (on/off any time the game is CLOSED):
rem   "Race Chaos.bat" extras                 what is on
rem   "Race Chaos.bat" extras on overlay      developer overlay (FPS, chunks, cars...)
rem   "Race Chaos.bat" extras on view         everything further: view 1600 m (fog from
rem                   1200), up to 60 cars spawning at 140 m / gone at 160 m and fading
rem                   in, car bodies to 150 m, streetlights + loose objects + race
rem                   billboards to 1000 m, ad screens never white; sets Distance=7
rem   "Race Chaos.bat" extras off view        back to stock distances (and Distance)
rem   "Race Chaos.bat" extras on racers       4/6/8/10/12 racers, equally likely
rem   "Race Chaos.bat" extras on shadows      shadows work again on modern GPUs
rem   "Race Chaos.bat" extras on nodamage     GOD MODE: your car takes no damage
rem   "Race Chaos.bat" extras off nodamage    normal damage again (repair once after
rem                   turning it on - old dents stay until then)
rem   "Race Chaos.bat" extras on panini       Panini wide view 160 x 100 deg, 2x
rem                   supersampling, closer chase camera, sky fix (tuning: panini.py)
rem   "Race Chaos.bat" extras off panini      the stock camera and lens again
rem   "Race Chaos.bat" extras on fixedstep    physics at a fixed rate whatever the FPS
rem                   (stock: one step per frame, so low FPS let cars sink into each
rem                   other and get launched). Remembers the last rate (default 60).
rem   "Race Chaos.bat" extras on fixedstep 60 the same at 60 Hz - any rate 10..288. Higher
rem                   = finer physics but more CPU: 144 dropped the city centre to
rem                   17 FPS. Below ~30 it gets coarser than stock at high FPS.
rem   "Race Chaos.bat" extras on engineloop   engine sound loops with no silent gap at
rem                   any pitch (stock DirectMusic restarted it on the unpitched length)
rem   --- STAGE 2 (2026-10-04, all OFF until you switch them on) ---
rem   "Race Chaos.bat" extras on awdfix       AWD cars no longer get DOUBLE power (stock bug:
rem                   every driven wheel got the full engine force; all stock cars are RWD)
rem   "Race Chaos.bat" extras on revboost     reverse gets the same low-speed boost as first
rem                   gear, so cars can back up steep hills (stock: under 1/3 of the push)
rem   "Race Chaos.bat" extras on gravity      MOON gravity, 1.62 m/s2 (stock 10)
rem   "Race Chaos.bat" extras on gravity 3.71 any gravity 0.5..30 (Mars 3.71, Jupiter 24.8)
rem   "Race Chaos.bat" extras on policeeyes   police notice you from 100 m (stock 40)
rem   "Race Chaos.bat" extras on policeeyes 150   any distance 40..160 m
rem   "Race Chaos.bat" extras on morepolice   fixes "only 4 police per race" (stock bug) and
rem                   makes police twice as common; up to 8 at once
rem   "Race Chaos.bat" extras on morepolice 12    any count 1..20 at once
rem   "Race Chaos.bat" extras on evade        wanted level drops only beyond 80 m from chasers (stock 60)
rem   "Race Chaos.bat" extras on evade 100    any distance 20..160 m
rem   "Race Chaos.bat" extras on milkyway     the real Milky Way (ESO photo) in the night sky
rem   "Race Chaos.bat" extras on milkyway 0.6 any brightness 0.1..1 (1 = full)
rem   "Race Chaos.bat" extras on rayfast      wheel ground checks skip far objects (big CPU saving, same physics)
rem   "Race Chaos.bat" extras on policefix    original chase AI, only its backwards route aim fixed
rem                   (pick ONE: policefix or smartpolice)
rem   "Race Chaos.bat" extras on smartpolice  chasing police follow the roads and brake for corners
rem   "Race Chaos.bat" extras on wantedhits   hitting a pedestrian +4 wanted bars (stock 2),
rem                   hitting a police car at least 5 bars (stock 3)
rem   "Race Chaos.bat" extras on adaptive     the physics rate becomes a FLOOR: above it,
rem                   one step per frame at your FPS (144 FPS = 144 Hz); below it, fixedstep
rem   "Race Chaos.bat" extras on laa          the game may use 4 GB of memory instead of 2
rem   Several at once:  extras off nodamage panini
rem
rem   From PowerShell, put & in front:  & "...\Race Chaos.bat" level 3
rem   "Race Chaos.bat" restore    back to stock races AND switches the extras off
rem   The game must be CLOSED for level / extras / restore.
rem
rem Editing game.exe needs write access to Program Files (it has had it since the
rem folder permissions were fixed; if you ever see "access denied", run as admin).
rem Every change rebuilds game.exe from the clean backup, so nothing stacks, and the
rem Car Tuner (Objects.pak) never touches game.exe - the two are independent.
call "%~dp0_py.bat" || (pause & exit /b 1)


if "%~1"=="" (
    "%PY%" "%~dp0racemod.py" show
) else (
    "%PY%" "%~dp0racemod.py" %*
)

echo.
pause
