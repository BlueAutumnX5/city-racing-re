"""One-shot LIVE night setup (2026-10-09; player: "make it persistent"). Memory only - run it again after
every game start (quitting the game undoes everything). The game must be RUNNING (in 3D, not alt-tabbed).
  nightmode.py        eternal midnight + realistic full-moon night (ambient 0.22, warm-grey physical moonlight, moon 2.2x) + headlights (headlights.py defaults)
  nightmode.py off    time of day runs again, stock night/moon, headlights hook removed
Not yet a Control Panel option: that needs the racemod extras (TODO in memory city-racing-headlights)."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS_ON = [("nightlock.py", "0"), ("nightlive.py", "0.22", "1.05,1.0,0.48"), ("moonlive.py", "2.2"), ("hllive.py", "on")]   # v4 2026-10-10: PHYSICAL moonlight = warm grey (tint cancels the game night table blue 2x); v3 cool cast, v2 film-blue
STEPS_OFF = [("nightlock.py", "off"), ("nightlive.py", "off"), ("moonlive.py", "off"), ("hllive.py", "off")]
for script, *args in (STEPS_OFF if sys.argv[1:2] == ["off"] else STEPS_ON):
    print(f"--- {script} {" ".join(args)}")
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], text=True, capture_output=True)
    print((r.stdout + r.stderr).strip()[:600])
