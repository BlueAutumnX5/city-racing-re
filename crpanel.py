r"""crpanel.py - the City Racing RE Project control panel (player request 2026-09-27).

"Can you make a GUI app so I can turn on or turn off every single thing that we make? Like turn on
the Panini, turn on the Fixed Physics Rate with an input of what value, etc. All of them. So I never
open your chat, search for values, and put it on PowerShell every time. Make sure Car Tuner and the
Path editor thing is in there too." + "a default value as ghost text when a box is empty" + "a
tooltip that explains everything, understandable by normal gamers" + "a slider, but keep the text
box too".

Every extra with its settings (slider + text box, the default as grey ghost text when the box is
empty), the race-route (chaos) switch, and the tools, in one window; hover anything for a plain
explanation. Apply runs `racemod.py setup <json>`: ONE rebuild of game.exe from the pristine backup,
the same code path as `Race Chaos.bat` (which still works). Settings are checked first and saved
only after a verified write. Preview = the same build in memory, nothing written. The game must be
CLOSED to apply; the panel watches for it. Launch: `RE Control Panel.bat`.
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import importlib
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panini    # noqa: E402  (the saved Panini settings are applied at import)
import racemod   # noqa: E402

PYDIR = os.path.dirname(sys.executable)              # the interpreter running the panel (.venv or python.org)
PY = os.path.join(PYDIR, "python.exe")
PYW = os.path.join(PYDIR, "pythonw.exe")
CFG = os.path.join(HERE, "crpanel_apply.json")
LOGFILE = os.path.join(HERE, "crpanel.log")
BACKUPS = os.path.join(HERE, "backups")
NOWIN = 0x08000000                                    # CREATE_NO_WINDOW
GHOST, INK, BAD_BG, OK_BG = "#9a9a9a", "#000000", "#ffe3e3", "#ffffff"
PREFS = os.path.join(HERE, "crpanel_prefs.json")
# ---------------------------------------------------------------- light / dark colours
THEMES = {
    "light": dict(bg=None, fg="#000000", small="#555555", field="#ffffff", ghost="#9a9a9a", ink="#000000",
                  bad_bg="#ffe3e3", tip_bg="#fffbe0", tip_fg="#000000", log_bg="#fbfbfb", log_fg="#000000",
                  canvas="#fbfbfb", good="#1b7a1b", bad="#b00020", warn="#b36b00"),
    "dark": dict(bg="#1f2228", fg="#e6e6e6", small="#a8adb5", field="#2b2f37", ghost="#7d828b", ink="#f2f2f2",
                 bad_bg="#5a2a2e", tip_bg="#2f343d", tip_fg="#eeeeee", log_bg="#17191d", log_fg="#d8d8d8",
                 canvas="#1b1e23", good="#5fd068", bad="#ff6b6b", warn="#ffb347",
                 panel="#272b33", border="#3a3f48", accent="#3d7be0", trough="#3a3f48"),
}
# the light-mode drawing colours on the two chart canvases -> their dark-mode stand-ins
CANVAS_DARK = {"#555555": "#b4b8bf", "#9a9a9a": "#8c9099", "#e3e3e3": "#363b44", "#bdbdbd": "#575d67",
               "#111111": "#f0f0f0", "#8a8a8a": "#9da2aa", "black": "#e6e6e6", "#000000": "#e6e6e6"}
TIP_COLOURS = ["#fffbe0", "#000000"]


def windows_dark():
    """True when Windows apps are set to dark (Settings > Personalization > Colors)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def load_prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except Exception:
        return {}


def save_prefs(p):
    try:
        with open(PREFS, "w") as f:
            json.dump(p, f, indent=2)
    except OSError:
        pass

# ---------------------------------------------------------------- words for gamers
EXTRA = {
    "view": ("See further",
             "View 1600 m, up to 60 cars around you, far cars keep their bodies and collisions.",
             "Pushes everything further out.\n\n"
             "- You see 1600 m instead of about 600 m (fog starts at 1200 m).\n"
             "- Up to 60 cars around you. They appear about 140 m away and fade in smoothly "
             "instead of popping in.\n"
             "- Far cars keep their bodies (no more 'lights only' ghosts) and still bump into "
             "things up to 250 m away.\n"
             "- Streetlights, loose objects and race billboards stay visible to 1000 m.\n"
             "- Ad screens never turn white.\n\n"
             "Costs some FPS in the busy city centre. Off = the stock distances."),
    "overlay": ("Developer overlay", "FPS, loaded chunks and car count on screen.",
                "Shows the developers' info in a corner of the screen: FPS, loaded map chunks, number "
                "of cars and more.\n\nGreat for testing. Turn it off for clean videos and screenshots."),
    "racers": ("More racers", "4, 6, 8, 10 or 12 opponents per race.",
               "Every race picks 4, 6, 8, 10 or 12 opponents (equally likely) instead of the stock "
               "number. Opponents don't take away from the normal traffic."),
    "shadows": ("Working shadows", "Shadows render again on modern graphics cards.",
                "Cars and objects cast shadows again.\n\nThe original shadows used an image format "
                "that modern graphics cards don't support, so they silently disappeared."),
    "nodamage": ("God mode", "Your car takes no damage.",
                 "Crashes don't dent YOUR car, pop its tyres or hurt its engine. Other cars still take "
                 "damage, and you still hear the crash.\n\nIf your car was already damaged, repair it "
                 "once in the garage after turning this on."),
    "panini": ("Panini wide view", "Wide lens without stretched edges, sharper image, closer camera.",
               "A special wide-angle lens (the 'Panini' projection, used by photographers for wide "
               "shots of streets and rooms).\n\n"
               "You see much more to the sides, but without the ugly stretched edges of a normal wide "
               "field of view: straight up-and-down lines stay straight.\n\n"
               "Also includes: supersampling (smooth, sharp edges), a fix for the sky and sea being "
               "cut off at the sides, the 3D arrow drawn at the right size, and a closer chase camera.\n\n"
               "Off = the stock camera (113 deg wide, slightly stretched)."),
    "fixedstep": ("Fixed physics rate", "Car physics runs the same at any FPS.",
                  "Makes the physics (crashes, bumps, suspension) run at the same speed no matter "
                  "your FPS.\n\nIn the original game the physics took one big step per frame, so at "
                  "low FPS cars could sink into each other and get launched into the air. Now it "
                  "always runs at the rate set below."),
    "engineloop": ("Gapless engine sound", "The engine sound never cuts out when it loops.",
                   "Fixes the engine sound going silent for a moment every time it loops, which "
                   "happened more the higher the revs (up to a few seconds on some cars).\n\n"
                   "The engine sounds the same as before, just without the gaps."),
    # ---- Stage 2 (2026-10-04)
    "awdfix": ("AWD fix", "All-wheel-drive cars no longer get double power.",
               "Bug in the original game: an AWD car (front AND rear 'Tyre Driving' set to 1 in the Car "
               "Tuner) pushed every one of its four wheels with the car's FULL engine force, so it had "
               "twice the power of the same car with 2-wheel drive.\n\n"
               "With this fix an AWD car has the same power as a 2-wheel-drive one, spread over four "
               "tyres: better grip off the line, not double the speed.\n\n"
               "All stock cars are rear-wheel drive, so this only changes cars you set to AWD - right "
               "now your police cars and cars 03 and 05. They will feel weaker: raise their Engine "
               "Force in the Car Tuner if you want them as fast as before."),
    "revboost": ("Stronger reverse", "Reverse pulls like first gear, so you can back up hills.",
                 "In the original game, pressing the gas gets a big 'launch boost' at low speed (up "
                 "to 3.5x the engine force), but reverse never gets it - so reverse has under a third "
                 "of the push, and a normal car can't even back up a steep hill.\n\n"
                 "With this, reverse gets the same boost as driving forward. Reverse top speed is "
                 "unchanged. Other cars (traffic, police, racers) also back out of crashes faster."),
    "gravity": ("Custom gravity", "Moon gravity - or any gravity you like.",
                "Changes gravity for the whole physics world: your car, traffic, police and every "
                "loose object.\n\nThe original game uses 10 (Earth). The Moon is 1.62: huge, slow "
                "jumps and floaty crashes. Mars is 3.71. Jupiter is 24.8 (cars feel glued down).\n\n"
                "Sparks and pedestrians are not physics objects, so they don't change."),
    "policeeyes": ("Sharper police", "Police notice you from further away.",
                   "In the original game a police car only starts chasing you when it is within 40 m "
                   "of you (and you are wanted). With this they spot you from the distance set "
                   "below."),
    "evade": ("Evade distance", "How far you must get from chasing police before your wanted level drops.",
              "The original game lets your wanted level drain whenever no CHASING police car is within "
              "60 m of you. Set your own distance below: bigger = harder to escape.\n\n"
              "Tip: keep it below 'Police sight', or a chase can never be shaken off."),
    "boardkeep": ("Keep race billboards", "A race billboard you drive away from no longer vanishes at 175 m.",
                  "The original game DELETES the race billboard once you are 175 m from it (so a new one can "
                  "appear elsewhere) - with the long view distance you see it vanish, e.g. when you look back "
                  "after accepting a race - and during a race it deletes it the moment it leaves your view. Both are fixed; the race end still removes it. Set the distance below. Bigger = it stays in view longer, but new race "
                  "offers appear less often (a new board only spawns once the old one is gone)."),
    "racereset": ("Free racing line", "In races you are no longer put back on the route 24 m away from it.",
                  "The original game teleports YOU (never the opponents) back onto the racing line as soon as "
                  "you are 24 m from your next route point - one wide drift or detour is enough. Set your own "
                  "distance below. Note: the race still counts the route points in order, so if you skip one "
                  "you must go back to it; the reset is what rescues you when lost. 2000 = practically off."),
    "rayfast": ("Faster physics", "Car wheels stop checking every object in the city, every step.",
                "Your CPU profiles showed 65-75% of the game's main thread going to one thing: every car "
                "checks the ground under each wheel every physics step, and the 2005 physics library "
                "answers each check by testing EVERY object in the world.\n\n"
                "With this, the game remembers where each object is once per step and skips the ones that "
                "are clearly far away. Anything near a wheel is still tested exactly as before, so the "
                "driving and crashes do not change - only the CPU work drops (about 3-4x less for those "
                "checks)."),
    "smartpolice": ("Smart police", "Chasing police follow the roads and brake for corners.",
                    "In the original game a chasing police car steers straight at you: it does work out a "
                    "route along the roads, but then aims at the end of it nearest to YOU (a bug), so it "
                    "cuts corners into buildings. Within 22 m it ignores the roads completely.\n\n"
                    "With this, police drive along the road route (looking ahead about half a second), "
                    "plan it twice as often, and slow down in time for corners. Within 8 m of you they "
                    "still ram you as before.\n\n"
                    "Tested on the real city map: 186 of 200 test chases reached you without hitting a "
                    "building (original: 56)."),
    "policefix": ("Police: original + road fix", "The original chase AI, with only its backwards-route bug fixed.",
                  "The 2005 chase AI exactly as it was (its speed, its ramming, going straight at you when "
                  "close) - except that in route mode it now aims along the road from its own end instead "
                  "of at the end next to YOU (the original bug that made it cut through buildings).\n\n"
                  "Pick ONE: this or 'Smart police' (they change the same code - Apply refuses both)."),
    "milkyway": ("Milky Way night sky", "A real photo of the Milky Way in the sky at night.",
                 "Adds the whole Milky Way to the night sky, as you would see it far from any city lights. "
                 "It fades in after sunset and is gone by day; buildings, clouds and the moon still cover it.\n\n"
                 "Photo: ESO/S. Brunier (CC BY 4.0) - credit it if it appears in a video.\n\n"
                 "Brightness: the slider below (1.0 = full strength)."),
    "wantedhits": ("Harsher wanted level", "Hitting people or police raises your wanted level more.",
                   "The wanted bar has 10 bars.\n\nHitting a pedestrian: +4 bars (original +2).\n"
                   "Hitting a police car: at least 5 bars (original at least 3). Like the original, "
                   "this is a minimum, not an addition - otherwise one long scrape along a police car "
                   "would fill the bar instantly. Every crash also adds a little by itself, as before."),
    "morepolice": ("More police", "Fixes the 'police disappear' bug and adds more patrols.",
                   "Bug in the original game: it only allows 4 police cars to appear EVER until the "
                   "next race or reset - when they drive away, no new police come.\n\n"
                   "With this, the limit counts the police that are actually around you right now "
                   "(set below), and a new car is police twice as often (about 1 in 5).\n\n"
                   "Police replace normal traffic, so the total number of cars stays the same."),
    "adaptive": ("Physics follows FPS", "The physics rate is a minimum; above it, it matches your FPS.",
                 "Your idea: the 'Physics rate' becomes a FLOOR.\n\n"
                 "- FPS above it (say 144): the physics runs once per frame at your FPS (144 Hz) - "
                 "perfectly smooth, in step with the screen.\n"
                 "- FPS below it (say 40 in the city centre): exactly like now, fixed steps at the "
                 "physics rate.\n\n"
                 "It never costs more CPU than the higher of the two. Needs 'Fixed physics rate' (it "
                 "is switched on with it)."),
    "nightlock": ("Eternal night", "The clock stops: always the time you set (midnight by default).",
                  "Freezes the time of day. Everything follows it: sun, moon, sky colours, stars, the Milky Way "
                  "and the street lamps.\n\n"
                  "Set the hour below: 0 = midnight (the default), 12 = noon. Handy for looking at cars in "
                  "daylight too.\n\n"
                  "This is the live 'nightlock 0' from Night Mode (live).bat, built into game.exe."),
    "darknight": ("Realistic dark nights", "A darker night lit only by a full moon, in its real colour.",
                  "The original night is bright and blue. With this the night is dark, and the moon light is "
                  "warm grey like a real full moon (the game's blue night tint is cancelled). The moon is a bit "
                  "stronger than before, so lit and shadowed sides still differ.\n\n"
                  "Only the night changes: the day is untouched, and the street lamps, windows, glows and "
                  "headlights keep their brightness.\n\n"
                  "Night brightness below: 0.22 = what you tuned live (Night Mode). Higher = brighter."),
    "headlights": ("Headlights light the world", "Every car's headlights light the road, buildings, cars and trees.",
                   "Real per-pixel headlight beams for the nearest cars (yours included), like the street lamps "
                   "do: roads, bridges, buildings, lamp posts, loose objects, trees, rocks and other cars' bodies. "
                   "Leaky reflector beams with a soft top; overlapping beams add up like real light. No shadows.\n\n"
                   "Works at night only (from dusk). Best with 'Realistic dark nights'.\n\n"
                   "This is version v15c, the one you tuned live with Night Mode (live).bat - now built into "
                   "game.exe, so it is there every time the game starts.\n\n"
                   "Brightness below: 40 = what you tuned. The live sliders (Headlight Sliders (live).bat) still "
                   "work on top of it while the game runs."),
    "hlcars": ("Limit lit cars", "Only the nearest cars light the world (for FPS).",
               "Without this, the 16 nearest cars light the world. Each lit car costs a little FPS in busy "
               "streets, so set a smaller number below if the game gets slow.\n\n"
               "Needs 'Headlights light the world' (it is switched on with it)."),
    "manual": ("Manual gearbox", "Shift gears yourself: X = up, Z = down, Shift = clutch. Real RPM, tachometer, engine sound.",
               "Your car gets a real manual gearbox (traffic, police and racers keep the original drive).\n\n"
               "X shifts up, Z shifts down, hold Shift for the clutch. You start in 1st. N (neutral) is "
               "below 1st.\n"
               "- Full power the moment you press the gas (no slow build-up).\n"
               "- The speedometer's small needle shows the engine revs and blinks red when it's time to "
               "shift up.\n"
               "- Clutch (hold Shift): the engine is disconnected - no pull, no engine braking, and you can "
               "rev it with the gas. Shifting also works without it.\n"
               "- Each gear has its own speed range; the engine has a torque curve (strongest at about 60% "
               "of the revs) and a rev limiter - stay too long in a gear and it stops pulling.\n"
               "- Shifting takes a quarter of a second without power, like pressing the clutch.\n"
               "- Let go of the gas in gear and the engine brakes the car a little.\n"
               "- Starting in 2nd or higher bogs down (weak), like a real car.\n"
               "- The engine sound follows the real revs: it drops when you shift up.\n"
               "- Reverse is a gear: Z from N into R (only when nearly stopped), X back to N. In R the gas "
               "drives you backwards. The Down arrow only brakes - it never reverses on its own.\n\n"
               "1st gear pulls exactly like the original launch, and top gear reaches the original top "
               "speed - the difference is in between, and that you choose when to shift.\n\n"
               "Number of gears: the slider below (4, 5 or 6)."),
    "manpower": ("Gearbox power", "How strong the manual gearbox's engine is (100 % = realistic).",
                 "100 % = a realistic engine: in the right gear it keeps pulling hard all the way up "
                 "(constant power). The original game's engine is weak between 50 km/h and top speed, so "
                 "100 % is clearly quicker than the original car - most of all on cars with high "
                 "acceleration, like the Uber Atom-2000.\n\n"
                 "0 % = never stronger than the original car: the best gear matches the original pull at "
                 "every speed, the wrong gear is weaker.\n\n"
                 "Top speed is the same at every setting. Needs 'Manual gearbox' (switched on with it)."),
    "drivetrain": ("Real gearboxes (every car its own)", "Each car gets its own gearbox and engine - "
                   "manual, automatic or F1. Replaces 'Manual gearbox'.",
                   "Every car model gets the gearbox and engine that suits it (your car for now; traffic, "
                   "police and racers keep the original drive):\n\n"
                   "- Galant S500: 4-speed automatic, 4th is the overdrive. Big torquey V8.\n"
                   "- Clio NSX: 5-speed manual, revvy little engine.\n"
                   "- Rover H1200: 6-speed quick-shift automatic.\n"
                   "- Cosmo R200: 6-speed close-ratio manual.\n"
                   "- Thunder-1960: 3-speed automatic, lazy V8.\n"
                   "- Accord Z8: 5-speed manual, tiny kei engine.\n"
                   "- Alpha GRX8: 6-speed manual with a ROTARY engine: weak low down, screams to the top, "
                   "hardly any engine braking.\n"
                   "- Uber Atom-2000: 6-speed F1-style box: you shift, it shifts in a tenth of a second; "
                   "the clutch button still works.\n\n"
                   "Manual / F1: X = up, Z = down, hold Shift = clutch. The small needle shows the revs and "
                   "blinks red when it's time to shift.\n"
                   "Automatic: X / Z move the lever P R N D 2 1 (2 = only 1st and 2nd, 1 = stays in 1st). "
                   "It shifts by itself and shows the lever and the gear, e.g. 'D 3'. P only when "
                   "(nearly) stopped, R at any speed. Down only brakes - it never reverses by itself.\n\n"
                   "Realistic gearing, 50/50: top speeds go halfway to the real cars' (Galant 155, Clio 129, "
                   "Rover 146, Cosmo 189, Thunder 146, Accord 106, Alpha 191, Uber 222 km/h; police +10 %), "
                   "every gear gets longer with them, and the punch comes down halfway to the real cars' 0-100 "
                   "(Galant 6.2 s, Cosmo 4.7 s, Uber 3.8 s...). Tick 'Real-car acceleration' for the full "
                   "real-car feel.\n\n"
                   "Needs crdrive.dll (built from the rust folder; Apply copies it next to game.exe). "
                   "Ticking this switches 'Manual gearbox' and 'Gearbox power' off."),
    "realcar": ("Real-car acceleration", "The real cars' 0-100 times instead of the 50/50 middle way.",
                "With 'Real gearboxes' every car already has realistic gearing in a 50/50 mix: top speed "
                "halfway to the real car's, acceleration halfway between the original game and the real "
                "car. Tick this for the REAL cars' acceleration (same top speeds, every gear lasts longer):\n\n"
                "  0-100 km/h     50/50    real car\n"
                "  Galant         6.2 s    9.0 s\n"
                "  Clio           8.2 s   10.5 s\n"
                "  Rover          6.8 s    9.5 s\n"
                "  Cosmo          4.7 s    6.0 s\n"
                "  Thunder        7.7 s   10.5 s\n"
                "  Accord        15.4 s   16.0 s\n"
                "  Alpha          4.5 s    5.3 s\n"
                "  Uber           3.8 s    4.7 s\n\n"
                "Untick it for the 50/50 mix again. AI cars (with 'AI gearboxes') get the same. "
                "Needs 'Real gearboxes' (switched on with it)."),
    "aigears": ("AI gearboxes", "Traffic, police and racers drive through their own gearboxes too.",
                "Every AI car gets the same gearbox and engine as its model has for you (Galant police = "
                "4-speed automatic, Rover police = 6-speed automatic, racers in a Cosmo = 6-speed manual, "
                "and so on). They shift by themselves - automatics in D, manual cars near the redline - and "
                "their engine sound follows the real revs.\n\n"
                "With 'Engine power' at 100 % they pull as hard in the mid-range as you do, which evens out "
                "the realistic engines. Their braking and reversing stay exactly as in the original game.\n\n"
                "Needs 'Real gearboxes' (switched on with it)."),
    "carsounds": ("Fixed engine sounds", "Every car model always has the same engine sound - you pick which.",
                  "The original game gives every car a RANDOM one of its 8 engine sounds each time the car is "
                  "built - so your own car sounds different after every Continue, and two cars of the same "
                  "model sound different.\n\n"
                  "With this on, each model (and the two police cars) always uses the sound you pick below; "
                  "press \u25b6 to hear it rev. 'random' keeps the original behaviour for that car. Traffic, "
                  "police and racers use the same choice as your car of that model."),
    "keeplivery": ("Keep your livery", "Your car keeps its paint and decal after Save + Continue.",
                   "In the original game a loaded save shows your car with random paint and a random decal: the "
                   "save keeps the colours but the game never repaints the car with them, and the decal is not "
                   "saved at all.\n\n"
                   "With this on, loading repaints your car with its saved colour, and saving also remembers "
                   "the decal (a small extra block at the end of the save file - the original game ignores it).\n\n"
                   "The first Save after switching this on stores the decal you have at that moment."),
    "hudfix": ("Widescreen HUD", "The driving HUD is no longer stretched on wide screens: a round speedometer.",
               "The game draws its interface for an 800x600 screen and stretches it to yours, so on a 16:9 "
               "screen everything is a third too wide (the speedometer is an oval).\n\n"
               "With this on, the driving HUD keeps its real shape and stays pinned to its corner or edge. "
               "Menus and shops are left as they are, so their buttons still line up with the mouse.\n\n"
               "Needs the per-car gearboxes (it lives in the same crdrive.dll)."),
    "rpmdial": ("RPM dial", "Each car's speedometer shows its own rpm scale and red zone; the speed needle reads true.",
                "The small needle is the rev counter. With this on, every car gets its own speedometer face: "
                "an rpm scale (x1000 RPM) from 0 to the car's dial max, with the red zone starting at its "
                "redline, plus 'Km/h' and a tick every 5 km/h on the speed scale.\n\n"
                "It also fixes an original-game bug: the speed needle turned too little, so it read about 5 % "
                "low (95 at a true 100).\n\n"
                "Needs the Widescreen HUD. Apply also copies the 8 dial pictures into the game's Data folder."),
    "racergod": ("God mode for racers", "Race opponents take no crash damage; traffic and police still do.",
                 "Like the god mode for your own car, but for the cars you race against: they still crash "
                 "(and you hear it), they just never dent, lose tyres or hurt their engine.\n\n"
                 "Traffic and police are not affected. Works with or without your own car's god mode."),
    "policedmg": ("Weaker police cars", "Police cars take 1x, 2x or 3x crash damage - disabled sooner.",
                  "Every crash hits a police car this many times as hard: each dent, burst tyre and engine "
                  "hit is 2x or 3x, so they are wrecked (and turn into harmless traffic, with your +200 bonus) "
                  "in about half or a third of the hits.\n\n"
                  "1x = the original game. Only police cars: traffic, racers and your car are unchanged. Works "
                  "with 'God mode for racers' and your own god mode."),
    "markskeep": ("Marks stay", "Tyre marks and blood splats stay for an hour (or as long as you set).",
                  "In the original game a tyre mark lasts 10 seconds (6 dark, then a 4-second fade) and a blood "
                  "splat 10-20 seconds - so they are always gone by the time you come back (driving away only "
                  "hides them; they were simply used up).\n\n"
                  "With this both stay at full colour for the minutes you set (60 = one hour), then fade as "
                  "before. The game now keeps up to 8192 tyre-mark strips and 1024 splats (originally 64 and "
                  "512): when they are all used, the newest replaces the oldest instead of not appearing at all."),
    "camfix": ("Camera: higher, close view farther", "Both chase views sit a bit higher; the close one a bit farther back.",
               "The close chase view moves 10 % farther back (the far view stays). Both views are lifted by a "
               "tenth of their distance - the camera and the point it looks at move up together, so the angle "
               "is the same, you just see over tall roofs (Accord Z8, Rover).\n\n"
               "Works with the Panini chase-distance slider (that one moves both views)."),
    "quietexit": ("Quiet exit", "Quitting the game opens nothing (no Explorer window on the game folder).",
                  "The original game opens a gametop.com web page when you quit. That address was blanked "
                  "long ago so the game cannot phone home, but Windows then opens the current folder instead "
                  "- the game folder pops up in Explorer every time you exit.\n\n"
                  "With this on, the game simply skips that step and closes."),
    "newaudio": ("New music + ambience", "Adds your race music track and the new city / night countryside ambience.",
                 "Adds the sounds from your music folder (local.ini music=, built by newaudio.py):\n"
                 "- race music: a 9th track, picked at random with the game's 8 originals;\n"
                 "- city sounds: a 5th city ambience, day and night;\n"
                 "- dirt roads night: a 4th countryside ambience at night.\n\n"
                 "Apply copies the 4 files into the game's Data folder; the game's own archives stay untouched."),
    "laa": ("Use 4 GB of memory", "Lets the game use 4 GB of RAM instead of 2 GB.",
            "The game is a 32-bit program, which normally only gets 2 GB of memory. With all the "
            "extras (long view distance, 60 cars, big supersampling) it has used up to about 1.7 GB, "
            "close to that limit; running out would crash it.\n\n"
            "This flag lets it use up to 4 GB. It changes no game code. Very old games sometimes "
            "dislike it - if the game acts strange with it on, turn it off."),
}
STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "evade", "morepolice", "smartpolice", "policefix", "wantedhits", "rayfast", "milkyway", "boardkeep", "racereset", "adaptive", "laa", "manual", "manpower",
          "drivetrain", "aigears", "realcar", "carsounds", "keeplivery", "hudfix", "rpmdial", "racergod", "policedmg", "markskeep", "camfix", "quietexit", "newaudio")
NIGHT_TAB = ("nightlock", "darknight", "headlights", "hlcars")      # Stage 2 #9, own tab (2026-10-31)
# slider settings for valued extras besides the physics rate: label, step, format
VALUE_ROWS = {
    "gravity": ("Gravity", 0.01, "%.2f"),
    "policeeyes": ("Police sight", 5, "%.0f"),
    "evade": ("Evade distance", 5, "%.0f"),
    "milkyway": ("Milky Way brightness", 0.1, "%.1f"),
    "morepolice": ("Police at once", 1, "%.0f"),
    "policedmg": ("Police damage x", 1, "%.0f"),
    "markskeep": ("Marks stay (minutes)", 5, "%.0f"),
    "boardkeep": ("Billboard keep distance", 25, "%.0f"),
    "racereset": ("Race reset distance", 25, "%.0f"),
    "nightlock": ("Locked time of day", 0.5, "%.1f"),
    "darknight": ("Night brightness", 0.01, "%.2f"),
    "headlights": ("Headlight brightness", 1, "%.0f"),
    "hlcars": ("Cars with headlights", 1, "%.0f"),
    "manual": ("Gears", 1, "%.0f"),
    "manpower": ("Engine power", 5, "%.0f"),
    "drivetrain": ("Engine power", 5, "%.0f"),
}
VALUE_TIPS = {
    "fov": "How WIDE you see, left to right, in degrees.\n\nStock game: about 113. Higher = you see more "
           "to the sides, but things near the edges get squeezed. 160 is a good wide view; 170 is the "
           "maximum that has been tested.",
    "vfov": "How TALL the view is in the middle of the screen, in degrees.\n\nLower = things in the "
            "middle look bigger and sharper. Higher = more sky and road visible, but the sides get "
            "stretched more.\n\nThe allowed range depends on the width: the slider adjusts itself.",
    "scale": "Supersampling: the 3D world is drawn bigger than your screen and then shrunk down, for "
             "smooth, sharp edges.\n\n1.00 = off (fastest). 2.00 = 4 times the pixels (sharp; your RTX "
             "handles it easily). 4.00 = 16 times the pixels: the sharpest middle of the screen, but "
             "heavy - the graphics card may become the limit and FPS can drop a lot. The far left and "
             "right edges gain little above about 2.5. In between works too.",
    "chase": "How far the chase camera sits behind your car.\n\n1.00 = the stock distance. Lower = "
             "closer, so your car looks bigger. 0.84 makes the car look the same size as in the "
             "original game, with the wide lens.",
    "gravity": "How strong gravity is, in m/s2.\n\n10 = the original game (Earth). 1.62 = the Moon. "
               "3.71 = Mars. 24.8 = Jupiter.",
    "policeeyes": "How close (in metres) a police car must be to notice you and start a chase - if you "
                  "are wanted.\n\nOriginal game: 40 m. Police only exist up to about 160 m from you, "
                  "so higher would do nothing.",
    "milkyway": "How bright the Milky Way is at full night.\n\n1.0 = full strength (the maximum). Lower is "
                "subtler.",
    "evade": "Your wanted level starts dropping once every chasing police car is farther than this "
             "(in metres).\n\nOriginal game: 60 m. Default here: 80 m.",
    "boardkeep": "How far (in metres) you can get from a race billboard before the game removes it."
                 "\n\nOriginal game: 175 m. Things are drawn up to 1000 m, so at 175 you can see it vanish. "
                 "Default here: 175 m (= original; bigger means fewer new race offers).",
    "racereset": "How far (in metres) you may get from your next route point in a race before the game "
                 "puts you back on the line.\n\nOriginal game: 24 m. Default here: 150 m. 2000 = practically off.",
    "nightlock": "The hour the clock is frozen at.\n\n0 = midnight (the default). 6 = dawn. 12 = noon. "
                 "18 = dusk.",
    "darknight": "How bright the night is.\n\n0.22 = what you tuned live (dark, full moon). Higher = "
                 "brighter, still in the realistic moon colour.",
    "headlights": "How strong the headlight beams are.\n\n40 = what you tuned live. Higher = brighter "
                  "beams on everything they hit.",
    "hlcars": "How many of the nearest cars light the world (yours always counts).\n\nMore = more real, "
              "but costs FPS in busy streets. 16 = the most.",
    "drivetrain": "100 % = realistic engines (strong mid-range). 0 % = never stronger than the original car. "
                  "Top speed is the same either way.",
    "manpower": "100 % = realistic (strong mid-range). 0 % = never stronger than the original car. "
                "Top speed is the same either way.",
    "manual": "How many forward gears the gearbox has.\n\n5 = a normal car. 4 = longer gears (fewer shifts). "
              "6 = closer gears (more shifts, the engine stays nearer its best revs).",
    "markskeep": "How many minutes tyre marks and blood splats stay at full colour before they fade.\n\n"
                 "The original game: about 6-10 seconds.",
    "policedmg": "How many times as hard every crash hits a police car.\n\n1 = the original game, 2 = "
                 "wrecked in about half the hits, 3 = about a third.",
    "morepolice": "The most police cars allowed around you at the same time.\n\nThe original game "
                  "meant 4 (but its bug made it 4 per race). More = busier chases.",
    "hz": "How many times per second the physics is calculated.\n\nHigher = more precise crashes, but "
          "it costs CPU. If it's too high for your CPU, the FPS collapses in busy areas (144 dropped the "
          "city centre to 17 FPS). 60 is tested and smooth. Below about 30 the physics gets coarser "
          "than the original game.",
}
LEVEL_TIPS = {
    1: "mild - races feel normal, the routes are just different.",
    2: "twisty - random race length, a few U-turns.",
    3: "wild - always long races, about 10 U-turns.",
    4: "insane - like wild, and the scenery can reshuffle as you drive.",
    5: "anarchy - about 20 U-turns, frantic zig-zags on a few streets.",
    6: "chaos - U-turns and random lengths, with the original game's route bug switched ON (rare "
       "straight lines across water). Long races can crash the game.",
    7: "chaos leap - chaos plus deliberate straight-line leaps between roads. Safe: it can't crash.",
}


# ---------------------------------------------------------------- is OUR game.exe running?
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


def game_running():
    """True when THIS install's game.exe runs (the other GameTop games also call theirs game.exe).
    A game.exe whose path can't be read counts as ours - the safe side. If the Windows calls fail,
    racemod's name-only check decides."""
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        k32.OpenProcess.restype = wt.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if not snap or snap == wt.HANDLE(-1).value:
            raise OSError("no snapshot")
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        pids = []
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == "game.exe":
                pids.append(e.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
        k32.CloseHandle(snap)
        want = os.path.normcase(os.path.abspath(racemod.GAME))
        for pid in pids:
            h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return True
            buf = ctypes.create_unicode_buffer(1024)
            n = wt.DWORD(1024)
            got = k32.QueryFullProcessImageNameW(wt.HANDLE(h), 0, buf, ctypes.byref(n))
            k32.CloseHandle(wt.HANDLE(h))
            if not got or os.path.normcase(buf.value) == want:
                return True
        return False
    except Exception:
        return racemod.game_running()


# ---------------------------------------------------------------- widgets
class Tip:
    """A hover tooltip."""
    def __init__(self, widget, text, wrap=440):
        self.w, self.text, self.wrap, self.top, self.job = widget, text, wrap, None, None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, e):
        self._hide()
        self.job = self.w.after(450, self._show)

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        self.top = t = tk.Toplevel(self.w)
        t.wm_overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=text, justify="left", wraplength=self.wrap, background=TIP_COLOURS[0],
                 foreground=TIP_COLOURS[1], relief="solid", borderwidth=1, font=("Segoe UI", 9),
                 padx=8, pady=6).pack()
        t.update_idletasks()
        x = self.w.winfo_pointerx() + 16
        y = self.w.winfo_pointery() + 18
        x = min(x, self.w.winfo_screenwidth() - t.winfo_reqwidth() - 8)
        if y + t.winfo_reqheight() > self.w.winfo_screenheight() - 40:
            y = self.w.winfo_pointery() - t.winfo_reqheight() - 12
        t.wm_geometry(f"+{x}+{y}")

    def _hide(self, e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.top:
            self.top.destroy()
            self.top = None


class ValueControl:
    """A slider and a text box for one bounded number, kept in step with each other. An empty text
    box shows the default in grey ghost text and means "use the default"."""
    def __init__(self, parent, row, label, lo, hi, step, fmt, default, unit, tip, on_change):
        self.lo, self.hi, self.step, self.fmt = lo, hi, step, fmt
        self.default, self.unit, self.on_change = default, unit, on_change
        self.ghost, self._quiet = False, False
        self.lbl = ttk.Label(parent, text=label)
        self.lbl.grid(row=row, column=0, sticky="e", padx=(24, 6), pady=1)
        self.scale = ttk.Scale(parent, from_=lo, to=hi, orient="horizontal", length=240,
                               command=self._slid)
        self.scale.grid(row=row, column=1, sticky="w", pady=1)
        self.var = tk.StringVar()
        self.entry = tk.Entry(parent, width=8, textvariable=self.var, justify="right",
                              font=("Segoe UI", 10), relief="solid", borderwidth=1)
        self.entry.grid(row=row, column=2, sticky="w", padx=6, pady=1)
        self.rng = ttk.Label(parent, text="", style="Small.TLabel")
        self.rng.grid(row=row, column=3, sticky="w", pady=1)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<KeyRelease>", self._typed)
        for w in (self.lbl, self.scale, self.entry, self.rng):
            Tip(w, lambda: f"{tip}\n\nRange {self.fmt % self.lo} to {self.fmt % self.hi}, default "
                           f"{self.fmt % self.default_value()}. Drag the slider or type a number; "
                           f"an empty box = the default.")
        self._label()

    def default_value(self):
        return self.default() if callable(self.default) else self.default

    def _label(self):
        self.rng.configure(text=f"{self.unit}  ({self.fmt % self.lo} - {self.fmt % self.hi}, "
                                f"default {self.fmt % self.default_value()})")

    def _snap(self, v):
        v = round(round(float(v) / self.step) * self.step, 6)
        return min(max(v, self.lo), self.hi)

    def _set_scale(self, v):
        self._quiet = True
        try:
            self.scale.set(min(max(v, self.lo), self.hi))
        finally:
            self._quiet = False

    def _show_ghost(self):
        self.ghost = True
        self.var.set(self.fmt % self.default_value())
        self.entry.configure(fg=GHOST, bg=OK_BG)
        self._set_scale(self.default_value())

    def _ink(self):
        self.ghost = False
        self.entry.configure(fg=INK)

    def _focus_in(self, e):
        if self.ghost:
            self.var.set("")
            self._ink()

    def _focus_out(self, e):
        if not self.var.get().strip():
            self._show_ghost()
            self.on_change()

    def _typed(self, e):
        if self.ghost:
            self._ink()
        v = self._parse()
        ok = v is not None and self.lo - 1e-9 <= v <= self.hi + 1e-9
        self.entry.configure(bg=OK_BG if ok or not self.var.get().strip() else BAD_BG)
        if ok:
            self._set_scale(v)
        self.on_change()

    def _slid(self, v):
        if self._quiet:
            return
        v = self._snap(v)
        self._ink()
        self.var.set(self.fmt % v)
        self.entry.configure(bg=OK_BG)
        self.on_change()

    def _parse(self):
        t = self.var.get().strip().replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None

    def set(self, v):
        if v is None:
            self._show_ghost()
            return
        self._ink()
        self.var.set(self.fmt % v)
        self.entry.configure(bg=OK_BG)
        self._set_scale(v)

    def set_range(self, lo, hi):
        """New limits (the vertical FOV follows the width). A typed value outside them is pulled in."""
        self.lo, self.hi = lo, hi
        self.scale.configure(from_=lo, to=hi)
        self._label()
        if self.ghost:
            self._show_ghost()
            return
        v = self._parse()
        if v is not None and not lo <= v <= hi:
            self.set(min(max(v, lo), hi))
        elif v is not None:
            self._set_scale(v)

    def value(self):
        """The number to use: the default when empty, None when it isn't a number."""
        if self.ghost or not self.var.get().strip():
            return float(self.default_value())
        return self._parse()

    def valid(self):
        v = self.value()
        return v is not None and self.lo - 1e-9 <= v <= self.hi + 1e-9


# ---------------------------------------------------------------- the window
class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("City Racing RE Project - Control Panel")
        self.minsize(1000, 600)
        self.q = queue.Queue()
        self.busy = False
        self.running = None
        self._loading = True
        self.check, self.inst, self.v_extra, self.cbs = {}, {}, {}, {}
        self.cs_box = {}
        self._ticks = set()
        self.custom_chaos = None
        prefs = load_prefs()
        self.dark = tk.BooleanVar(value=prefs.get("dark", windows_dark()))
        self.T = THEMES["light"]
        self._styles()
        self._build()
        self.apply_theme()
        self.load_saved()
        self.refresh_installed()
        self._fit_screen()
        threading.Thread(target=self._watch_game, daemon=True).start()
        self.after(50, self._pump)
        self.after(400, self._tick)

    def _styles(self):
        st = ttk.Style(self)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
        st.configure("Name.TCheckbutton", font=("Segoe UI", 10, "bold"))
        st.configure("Small.TLabel", font=("Segoe UI", 9), foreground="#555555")
        st.configure("Apply.TButton", font=("Segoe UI", 10, "bold"))

    # ---------- layout
    def _build(self):
        pad = dict(padx=8, pady=3)
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="City Racing RE Project", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="   hover anything for an explanation", style="Small.TLabel").pack(side="left")
        self.game_lbl = tk.Label(top, text="checking the game...", font=("Segoe UI", 10, "bold"))
        self.game_lbl.pack(side="right")
        dm = ttk.Checkbutton(top, text="Dark mode", variable=self.dark, command=self._toggle_dark)
        dm.pack(side="right", padx=14)
        Tip(dm, "Dark colours for this window. Remembered for next time.")
        Tip(self.game_lbl, "The panel checks every 2 seconds whether City Racing is running. Changes "
                           "to game.exe can only be applied while the game is closed.")
        self.exe_lbl = ttk.Label(self, text="", style="Small.TLabel")
        self.exe_lbl.pack(fill="x", padx=10)
        Tip(self.exe_lbl, "The game.exe that is installed right now: a short fingerprint of the file, "
                          "its size, and when it was last written.")

        nb = self.nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)
        page1, tab2 = ttk.Frame(nb), ttk.Frame(nb)
        page3, page4 = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(page1, text="  Settings  ")
        nb.add(page3, text="  Gameplay  ")
        nb.add(page4, text="  Night & lights  ")
        nb.add(tab2, text="  What it looks like  ")
        self._scrollers = []
        tab1, tab3, tab4 = (self._scroll_page(pg) for pg in (page1, page3, page4))
        self._build_pictures(tab2)

        # race routes
        rf = ttk.LabelFrame(tab1, text="Race routes")
        rf.pack(fill="x", **pad)
        self.race_mode = tk.StringVar(value="stock")
        rb1 = ttk.Radiobutton(rf, text="Stock routes (chaos OFF) - the game as it was meant to be",
                              variable=self.race_mode, value="stock", command=self._changed)
        rb1.grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=2)
        Tip(rb1, "Races use the original route generator, exactly like the unmodified game - "
                 "including its very rare weird route (a straight line over water).")
        rb2 = ttk.Radiobutton(rf, text="Chaos:", variable=self.race_mode, value="chaos",
                              command=self._changed)
        rb2.grid(row=1, column=0, sticky="w", padx=6, pady=2)
        levels_tip = ("Our 'cursed' race generator: routes can U-turn, loop back on themselves and "
                      "vary wildly in length. Pick how wild:\n\n"
                      + "\n".join(f"{n}  {t}" for n, t in LEVEL_TIPS.items()))
        Tip(rb2, levels_tip)
        self.levels = [f"{n} - {v[0]}" for n, v in racemod.LEVELS.items()]
        self.level_box = ttk.Combobox(rf, values=self.levels, state="readonly", width=46)
        self.level_box.grid(row=1, column=1, sticky="w", pady=2)
        self.level_box.bind("<<ComboboxSelected>>",
                            lambda e: (self.race_mode.set("chaos"), self._changed()))
        Tip(self.level_box, levels_tip)

        # extras
        ef = ttk.LabelFrame(tab1, text="Extras")
        ef.pack(fill="x", **pad)
        self._extra_rows(ef, [n for n in racemod.EXTRAS if n not in STAGE2 + NIGHT_TAB])
        self._build_calc(tab1)
        s2 = ttk.LabelFrame(tab3, text="Gameplay extras")
        s2.pack(fill="x", **pad)
        self._extra_rows(s2, [n for n in racemod.EXTRAS if n in STAGE2])
        nf = ttk.LabelFrame(tab4, text="Night and headlights (Stage 2 #9 - what you tuned live with Night Mode, built into game.exe)")
        nf.pack(fill="x", **pad)
        self._extra_rows(nf, [n for n in racemod.EXTRAS if n in NIGHT_TAB])
        ttk.Label(tab4, style="Small.TLabel", wraplength=900, justify="left",
                  text="Tick what you want and press Apply - then Night Mode (live).bat is not needed any more "
                       "(the live Headlight Sliders still work on top while the game runs). All four were "
                       "checked in the emulator against the game's own code; the headlight code itself is the "
                       "live v15c you played with. The headlight shader compiles when the first night frame "
                       "is drawn, so the very first night frame can stutter for a moment."
                  ).pack(fill="x", padx=12, pady=4)
        ttk.Label(tab3, style="Small.TLabel", wraplength=900, justify="left",
                  text="Everything here is OFF until you tick it and press Apply. Each one was tested in "
                       "an emulator against the game's own code, but not yet in a real drive - so try "
                       "them one at a time. Untick + Apply puts it back exactly as before."
                  ).pack(fill="x", padx=12, pady=4)
        self._build_actions(pad)

    def _scroll_page(self, page):
        """A tab whose contents scroll (mouse wheel or scrollbar), so the window still fits on the
        screen when a tab gets many rows. Returns the frame to put the tab's contents in."""
        c = tk.Canvas(page, highlightthickness=0, borderwidth=0, yscrollincrement=20)
        sb = ttk.Scrollbar(page, command=c.yview)
        c.configure(yscrollcommand=sb.set)
        c.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(c)
        item = c.create_window(0, 0, window=inner, anchor="nw")

        def fit(_e=None):
            c.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight()),
                        width=inner.winfo_reqwidth())
            if inner.winfo_reqheight() > c.winfo_height() + 1:
                if not sb.winfo_ismapped():
                    sb.pack(side="right", fill="y", before=c)
            elif sb.winfo_ismapped():
                sb.pack_forget()
                c.yview_moveto(0)
        inner.bind("<Configure>", fit)
        c.bind("<Configure>", lambda e: (c.itemconfigure(item, width=e.width), fit()))
        self._scrollers.append((c, inner))
        return inner

    def _wheel(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        for c, inner in self._scrollers:
            if w is not None and str(w).startswith(str(c)) and inner.winfo_reqheight() > c.winfo_height():
                c.yview_scroll(-3 if e.delta > 0 else 3, "units")

    def _fit_screen(self):
        """Size the scrolling tabs so the whole window (Apply, Tools and Log included) fits above the
        taskbar, then put the window where all of it is visible."""
        self.update_idletasks()
        need = max(inner.winfo_reqheight() for _, inner in self._scrollers)
        other = self.winfo_reqheight() - max(self.nametowidget(t).winfo_reqheight() for t in self.nb.tabs())
        sh = self.winfo_screenheight()
        h = max(220, min(need, sh - 100 - other))        # 100: taskbar + title bar + a little air
        for c, _ in self._scrollers:
            c.configure(height=h)
        self.update_idletasks()
        x = max(0, (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2)
        y = max(0, (sh - 60 - self.winfo_reqheight()) // 2)
        self.geometry(f"+{x}+{y}")
        self.bind_all("<MouseWheel>", self._wheel)
        self.unbind_class("TCombobox", "<MouseWheel>")   # scrolling over a dropdown must not change it

    def _extra_rows(self, ef, names):
        ef.columnconfigure(1, weight=1)
        r = 0
        for name in names:
            title, short, long = EXTRA.get(name, (name, "", ""))
            v = tk.BooleanVar()
            self.check[name] = v
            cb = self.cbs[name] = ttk.Checkbutton(ef, text=title, variable=v, style="Name.TCheckbutton",
                                                  command=self._changed)
            cb.grid(row=r, column=0, sticky="w", padx=6, pady=(3, 0))
            dl = ttk.Label(ef, text=short, style="Small.TLabel")
            dl.grid(row=r, column=1, sticky="w", pady=(3, 0))
            il = ttk.Label(ef, text="", style="Small.TLabel", width=24)
            il.grid(row=r, column=2, sticky="e", padx=6, pady=(3, 0))
            for w in (cb, dl):
                Tip(w, long)
            Tip(il, "What the installed game.exe has right now. 'installed: other values' means this "
                    "extra is in game.exe, but built with different settings than the saved ones.")
            self.inst[name] = il
            r += 1
            if name in ("panini", "fixedstep", "carsounds") or name in VALUE_ROWS:
                sub = ttk.Frame(ef)
                sub.grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 3))
                if name == "panini":
                    self._panini_rows(sub)
                elif name == "fixedstep":
                    self._fixed_rows(sub)
                elif name == "carsounds":
                    self._carsound_rows(sub)
                else:
                    self._valued_row(sub, name)
                r += 1

    def _valued_row(self, f, name):
        key, setter, cur, unit, (lo, hi), dflt = racemod.VALUED[name]
        label, step, fmt = VALUE_ROWS[name]
        f.columnconfigure(0, minsize=150)
        unit = {"m/s2": "m/s\u00b2", "m": "metres", "cars": "police cars", "h": "o'clock"}.get(unit, unit)
        self.v_extra[name] = ValueControl(f, 0, label, lo, hi, step, fmt, dflt, unit,
                                          VALUE_TIPS[name], self._changed)

    def _build_actions(self, pad):
        # actions
        af = ttk.Frame(self)
        af.pack(fill="x", **pad)
        self.apply_btn = ttk.Button(af, text="Apply to game.exe", style="Apply.TButton",
                                    command=lambda: self.run_setup(dry=False))
        self.apply_btn.pack(side="left")
        Tip(self.apply_btn, "Rebuilds game.exe from the clean original with everything ticked above "
                            "and these values. The game must be closed. It takes a few seconds; the "
                            "log below says when it's done. Your settings are saved only if it worked.")
        self.dirty_lbl = tk.Label(af, text="", font=("Segoe UI", 9, "bold"), fg=self.T["warn"])
        self.dirty_lbl.pack(side="left", padx=10)
        for text, cmd, tip in (
                ("Restore stock game...", self.restore,
                 "Puts back the original, unmodified game.exe: no extras, stock race routes. Your "
                 "values are remembered for next time. Asks before doing anything."),
                ("Patch details", lambda: self.run_racemod(["show"], "patch details"),
                 "Lists every single change inside game.exe, with addresses (technical)."),
                ("Undo changes", self.load_saved,
                 "Throws away what you changed in this window and shows the saved settings again."),
                ("Preview (no write)", lambda: self.run_setup(dry=True),
                 "Checks your settings and builds the result in memory only - game.exe is not "
                 "touched, so it works while playing. Tells you whether it would be identical to "
                 "what's installed.")):
            b = ttk.Button(af, text=text, command=cmd)
            b.pack(side="right", padx=4)
            Tip(b, tip)

        # tools
        tf = ttk.LabelFrame(self, text="Tools")
        tf.pack(fill="x", **pad)
        for text, cmd, tip in (
                ("Car Tuner", lambda: self.launch("cartuner.py"),
                 "Opens the Car Tuner: edit car stats like engine power, speed, grip and weight. It "
                 "edits the car data, not game.exe, so it works together with everything here."),
                ("Map Editor (race paths)", lambda: self.launch("mapeditor.py"),
                 "Opens the Map Editor: draw new yellow race lines on the map. Races can only drive "
                 "on yellow lines, so new lines = new race routes."),
                ("CPU profile (30 s)", lambda: os.startfile(os.path.join(HERE, "CPU Profile.bat")),
                 "Measures where the game spends its CPU time (physics, traffic, rendering, the graphics "
                 "driver...). Start the game and drive somewhere slow (the city centre), then press this: "
                 "a window counts 30 seconds and saves a report in the work folder. Changes nothing."),
                ("Open work folder", lambda: os.startfile(HERE),
                 "Opens the folder with all the project's tools and notes."),
                ("Open backups", lambda: os.startfile(BACKUPS),
                 "Opens the folder with a backup of game.exe from before every change."),
                ("Open game folder", lambda: os.startfile(os.path.dirname(racemod.GAME)),
                 "Opens the game's install folder.")):
            b = ttk.Button(tf, text=text, command=cmd)
            b.pack(side="left", padx=4, pady=4)
            Tip(b, tip)

        # log
        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(lf, height=8, wrap="word", font=("Consolas", 9), state="disabled",
                           background="#fbfbfb")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("bad", foreground="#b00020")
        self.log.tag_configure("good", foreground="#1b7a1b")

    def _panini_rows(self, f):
        d = panini.DEFAULTS
        lo, hi = panini.LIMITS["fov"]
        self.v_fov = ValueControl(f, 0, "Width", lo, hi, 1, "%.0f", d["fov"], "deg",
                                  VALUE_TIPS["fov"], self._fov_changed)
        vlo, vhi = panini.vfov_range(d["fov"])
        self.v_vfov = ValueControl(f, 1, "Height (centre)", vlo, vhi, 0.5, "%.1f", self._vfov_default,
                                   "deg", VALUE_TIPS["vfov"], self._changed)
        lo, hi = panini.LIMITS["scale"]
        self.v_scale = ValueControl(f, 2, "Supersampling", lo, hi, 0.05, "%.2f", d["scale"], "x",
                                    VALUE_TIPS["scale"], self._changed)
        lo, hi = panini.LIMITS["chase"]
        self.v_chase = ValueControl(f, 3, "Chase camera", lo, hi, 0.01, "%.2f", d["chase"], "x",
                                    VALUE_TIPS["chase"], self._changed)

    def _fixed_rows(self, f):
        lo, hi = racemod.FIXED_HZ_RANGE
        self.v_hz = ValueControl(f, 0, "Physics rate", lo, hi, 1, "%.0f", racemod.FIXED_HZ_DEFAULT,
                                 "per second (Hz)", VALUE_TIPS["hz"], self._changed)

    def _vfov_default(self):
        fov = self.v_fov.value() if hasattr(self, "v_fov") else panini.DEFAULTS["fov"]
        lo_f, hi_f = panini.LIMITS["fov"]
        fov = min(max(fov if fov is not None else panini.DEFAULTS["fov"], lo_f), hi_f)
        lo, hi = panini.vfov_range(fov)
        return min(max(panini.DEFAULTS["vfov"], lo), hi)

    def _fov_changed(self):
        if not hasattr(self, "v_vfov"):
            return
        fov = self.v_fov.value()
        lo_f, hi_f = panini.LIMITS["fov"]
        if fov is not None and lo_f <= fov <= hi_f:
            self.v_vfov.set_range(*panini.vfov_range(fov))
        self._changed()

    CS_NAMES = {"01": "Galant S500", "02": "Clio NSX", "03": "Rover H1200", "04": "Cosmo R200",
                "05": "Thunder-1960", "06": "Accord Z8", "07": "Alpha GRX8", "08": "Uber Atom-2000",
                "01P": "Galant police", "03P": "Rover police"}
    CS_CHOICES = [f"E{k:02d}" for k in range(1, 9)] + ["random"]

    def _carsound_rows(self, f):
        """One dropdown + a play button per car model (2 columns of 5)."""
        for i, slot in enumerate(racemod.CAR_SOUND_SLOTS):
            r, c = i % 5, (i // 5) * 3
            ttk.Label(f, text=self.CS_NAMES[slot], style="Small.TLabel").grid(
                row=r, column=c, sticky="e", padx=(24 if c else 30, 4), pady=1)
            box = ttk.Combobox(f, values=self.CS_CHOICES, state="readonly", width=8)
            box.grid(row=r, column=c + 1, sticky="w", pady=1)
            box.bind("<<ComboboxSelected>>", lambda e: self._changed())
            Tip(box, f"The engine sound of every {self.CS_NAMES[slot]} (yours and the AI's). E01..E08 are the "
                     "game's 8 engine sounds; 'random' = the original random pick.")
            b = ttk.Button(f, text="\u25b6", width=3, command=lambda bx=box: self._play_engine(bx.get()))
            b.grid(row=r, column=c + 2, sticky="w", padx=(2, 0), pady=1)
            Tip(b, "Play this engine: idle, revving up, revving down (about 7 seconds). Click again to "
                   "restart; pick 'random' and click to stop.")
            self.cs_box[slot] = box

    def _play_engine(self, choice):
        import winsound
        if not choice.startswith("E"):
            winsound.PlaySound(None, 0)
            return
        path = os.path.join(HERE, "Engine sounds", f"{choice} - preview (idle, rev up, rev down).wav")
        if not os.path.exists(path):
            self.say(f"no preview for {choice} - run engine_previews.py once to make them", "bad")
            return
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def _cs_values(self):
        return {slot: (self.CS_CHOICES.index(b.get()) if b.get().startswith("E") else -1)
                for slot, b in self.cs_box.items()}

    def _values(self):
        return {"fov": self.v_fov, "vfov": self.v_vfov, "scale": self.v_scale, "chase": self.v_chase,
                "hz": self.v_hz, **self.v_extra}

    # ---------- sharpness calculator (Settings tab, under the extras)
    def _build_calc(self, parent):
        cf = ttk.LabelFrame(parent, text="Sharpness calculator (Panini)")
        cf.pack(fill="x", padx=8, pady=3)
        top = ttk.Frame(cf)
        top.pack(fill="x", padx=6, pady=(3, 0))
        ttk.Label(top, text="Your screen:").pack(side="left")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        res = [f"{sw} x {sh} (this screen)"] + [f"{w} x {h}" for w, h in (
            (1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)) if (w, h) != (sw, sh)]
        self.calc_res = ttk.Combobox(top, values=res, width=24)
        self.calc_res.set(res[0])
        self.calc_res.pack(side="left", padx=4)
        self.calc_res.bind("<<ComboboxSelected>>", lambda e: self._update_calc())
        self.calc_res.bind("<KeyRelease>", lambda e: self._update_calc())
        Tip(self.calc_res, "The resolution the game runs at. Pick one or type it like 1920 x 1080. Only used "
                           "for these numbers - it doesn't change the game.")
        self.calc_lines = []
        tips = ("How big the image is that the game draws before bending it, and what that costs. Bigger = "
                "sharper but more work for the graphics card and more video memory.",
                "The middle of the screen is where you look most. The lens enlarges the middle of the drawn "
                "image; if it's enlarged more than the supersampling makes up for, the middle looks soft "
                "(like playing at a lower resolution). 1:1 or less = pin-sharp.",
                "At the far left and right the lens squeezes a lot of the drawn image into each screen pixel. "
                "The smoothing filter reads up to 8 points per pixel; if a pixel covers more than 8 drawn "
                "pixels, fine details at the edges can shimmer a little when you move.")
        for t in tips:
            lb = ttk.Label(cf, text="", wraplength=820, justify="left")
            lb.pack(fill="x", padx=6, pady=1)
            Tip(lb, t)
            self.calc_lines.append(lb)
        bf = ttk.Frame(cf)
        bf.pack(fill="x", padx=6, pady=(2, 4))
        self.calc_ss_btn = ttk.Button(bf, text="", command=self._calc_use_ss)
        self.calc_ss_btn.pack(side="left")
        Tip(self.calc_ss_btn, "Sets the supersampling so the middle is pin-sharp with your current width and "
                              "height. Costs graphics card power: check your FPS after applying.")
        self.calc_v_btn = ttk.Button(bf, text="", command=self._calc_use_vfov)
        self.calc_v_btn.pack(side="left", padx=6)
        Tip(self.calc_v_btn, "Keeps your supersampling (no extra GPU cost) and instead picks the height that "
                             "makes the middle pin-sharp. A taller view shows more sky and road, and the lens "
                             "enlarges the middle less.")
        ttk.Label(bf, text="(the buttons only fill in the values - press Apply to use them)",
                  style="Small.TLabel").pack(side="left", padx=6)
        self._calc_ss = self._calc_vfov = None

    def _screen(self):
        import re
        m = re.search(r"(\d{3,5})\s*[x*]\s*(\d{3,5})", self.calc_res.get())
        return (int(m.group(1)), int(m.group(2))) if m else (self.winfo_screenwidth(), self.winfo_screenheight())

    def _update_calc(self):
        import math
        if not hasattr(self, "calc_lines"):
            return
        fov, vfov, ss = self.v_fov.value(), self.v_vfov.value(), self.v_scale.value()
        w, h = self._screen()
        self._calc_ss = self._calc_vfov = None
        try:
            ratio = panini.centre_ratio(fov, vfov)
            p = panini.params(fov, panini.d_for_vertical(fov, vfov))
            squeeze = panini.edge_squeeze(p)
        except (ValueError, TypeError, ZeroDivisionError):
            for lb in self.calc_lines:
                lb.configure(text="")
            self.calc_lines[0].configure(text="Fix the Panini width / height values first.")
            for b in (self.calc_ss_btn, self.calc_v_btn):
                b.configure(text="-")
                b.state(["disabled"])
            return
        rw, rh = round(w * ss), round(h * ss)
        vram = rw * rh * 8 / 2 ** 20
        self.calc_lines[0].configure(
            text=f"Drawn image: {rw} x {rh} ({ss:.2f}x your screen) - {ss * ss:.1f}x the pixels of native, "
                 f"about {vram:.0f} MB of video memory." + ("  Above 16384 px: too big for the graphics card, "
                                                           "the game would fall back to no supersampling."
                                                           if max(rw, rh) > 16384 else ""))
        up = ratio / ss
        if up > 1.005:
            mid = (f"Middle of the screen: enlarged {up:.2f}x - soft, it looks like {w / up:.0f} x {h / up:.0f} "
                   f"in the middle. Pin-sharp needs {ratio:.2f}x supersampling at this width and height.")
        else:
            mid = (f"Middle of the screen: PIN-SHARP ({1 / up:.2f} drawn pixels per screen pixel; 1:1 needs "
                   f"{ratio:.2f}x). Supersampling above that only makes it smoother.")
        self.calc_lines[1].configure(text=mid)
        edge = squeeze * ss
        self.calc_lines[2].configure(
            text=f"Far left/right edges: {edge:.1f} drawn pixels squeezed into each screen pixel - "
                 + ("clean (the filter covers up to 8)." if edge <= 8.05 else
                    "more than the filter's 8 reads: tiny details at the edges may shimmer a little."))
        lo, hi = panini.LIMITS["scale"]
        need = math.ceil(ratio * 20 - 1e-9) / 20                       # up to the slider's 0.05 steps
        if up > 1.005 and need <= hi:
            self._calc_ss = need
            self.calc_ss_btn.configure(text=f"Pin-sharp: set supersampling to {need:.2f}x")
        elif up > 1.005:
            self.calc_ss_btn.configure(text=f"Pin-sharp would need {ratio:.2f}x (max {hi:g}x)")
        else:
            self.calc_ss_btn.configure(text="Middle already pin-sharp")
        vlo, vhi = panini.vfov_range(fov)
        v = panini.vfov_for_ratio(fov, ss)
        if up <= 1.005:
            self.calc_v_btn.configure(text="Height is fine")
        elif v is not None:
            v = min(max(math.ceil(v * 2 - 1e-9) / 2, vlo), vhi)        # up to the slider's 0.5 steps
            self._calc_vfov = v
            self.calc_v_btn.configure(text=f"Or keep {ss:.2f}x: set the height to {v:.1f} deg")
        else:
            self.calc_v_btn.configure(text="No height gives a pin-sharp middle at this supersampling")
        self.calc_ss_btn.state(["!disabled"] if self._calc_ss else ["disabled"])
        self.calc_v_btn.state(["!disabled"] if self._calc_vfov else ["disabled"])

    def _calc_use_ss(self):
        if self._calc_ss:
            self.v_scale.set(self._calc_ss)
            self._changed()

    def _calc_use_vfov(self):
        if self._calc_vfov:
            self.v_vfov.set(self._calc_vfov)
            self._changed()

    # ---------- pictures ("What it looks like" tab)
    def _build_pictures(self, tab):
        W, H = 440, 248
        self.pic = {}
        for col, (key, title, tip) in enumerate((
                ("stock", "Stock lens (113 deg wide, a bit stretched)",
                 "A simple street as the original game shows it: 113 degrees wide, and the whole "
                 "picture is stretched about 18% sideways (a mistake in the original game's maths)."),
                ("yours", "Your lens",
                 "The same street with your settings. With Panini on you see much wider, and "
                 "up-and-down lines (building edges, lamp posts) stay straight. Lines crossing your "
                 "view bend a little - that's the price of seeing so wide without stretched edges."))):
            f = ttk.Frame(tab)
            f.grid(row=0, column=col, padx=6, pady=(6, 2), sticky="n")
            lbl = ttk.Label(f, text=title, font=("Segoe UI", 9, "bold"))
            lbl.pack(anchor="w")
            c = tk.Canvas(f, width=W, height=H, background="#1d2430", highlightthickness=0)
            c.pack()
            self.pic[key] = (c, lbl)
            Tip(c, tip)
        f = ttk.Frame(tab)
        f.grid(row=1, column=0, padx=6, pady=(4, 6), sticky="n")
        ttk.Label(f, text="Distances around you (top view)", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.dist = tk.Canvas(f, width=W, height=292, background="#fbfbfb", highlightthickness=0)
        self.dist.pack()
        Tip(self.dist, "Seen from above, you are the dot at the bottom. Each ring is how far something "
                       "reaches. The scale shrinks further out so near and far both fit. Colours = with "
                       "'See further' on; grey = the original game.")
        f = ttk.Frame(tab)
        f.grid(row=1, column=1, padx=6, pady=(4, 6), sticky="n")
        ttk.Label(f, text="Physics steps vs frames (0.1 s of play)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.steps = tk.Canvas(f, width=W, height=292, background="#fbfbfb", highlightthickness=0)
        self.steps.pack()
        Tip(self.steps, "Each grey line is a frame drawn on screen; each dot is one physics "
                        "calculation. With a fixed rate the blue dots stay evenly spaced whatever the "
                        "FPS, so cars behave the same at 20 or 144 FPS. In the original game (red) "
                        "there is one step per frame, and at low FPS each step is huge - that's when "
                        "cars went through each other.")

    def draw_pictures(self):
        self._redraw_due = False
        self._update_calc()
        try:
            self._draw_lens("stock", None)
            c, lbl = self.pic["yours"]
            if not self.check["panini"].get():
                lbl.configure(text="Your lens: Panini is off = the stock lens")
                self._draw_lens("yours", None)
            else:
                fov, vfov = self.v_fov.value(), self.v_vfov.value()
                try:
                    d = panini.d_for_vertical(fov, vfov)
                    panini.params(fov, d)
                    lbl.configure(text=f"Your lens: Panini {fov:.0f} deg wide, {vfov:.1f} tall")
                    self._draw_lens("yours", (fov, d))
                except (ValueError, TypeError):
                    c.delete("all")
                    lbl.configure(text="Your lens: (fix the Width / Height values)")
            self._draw_distances()
            self._draw_steps()
            if self.dark.get():
                for c in (self.dist, self.steps):
                    self._darken_canvas(c)
        except tk.TclError:
            pass

    def _darken_canvas(self, c):
        """Swap the chart's light-mode greys/black for dark-mode ones (the colours of the data stay)."""
        for item in c.find_all():
            kind = c.type(item)
            for opt in ("fill", "outline"):
                try:
                    v = c.itemcget(item, opt)
                except tk.TclError:
                    continue
                if kind == "text" and opt == "fill" and v in ("", "black", "#000000", "SystemButtonText",
                                                              "SystemWindowText"):
                    c.itemconfigure(item, fill=CANVAS_DARK["black"])
                elif v in CANVAS_DARK:
                    c.itemconfigure(item, **{opt: CANVAS_DARK[v]})

    def _toggle_dark(self):
        p = load_prefs()
        p["dark"] = bool(self.dark.get())
        save_prefs(p)
        self.apply_theme()
        self.draw_pictures()

    def apply_theme(self):
        """Light = the Windows 'vista' look as before; dark = the 'clam' theme recoloured."""
        global GHOST, INK, BAD_BG, OK_BG
        dark = bool(self.dark.get())
        T = self.T = THEMES["dark" if dark else "light"]
        st = ttk.Style(self)
        try:
            st.theme_use("clam" if dark else "vista")
        except tk.TclError:
            pass
        if dark:
            bg, fg, panel, border, field = T["bg"], T["fg"], T["panel"], T["border"], T["field"]
            st.configure(".", background=bg, foreground=fg, fieldbackground=field, bordercolor=border,
                         lightcolor=panel, darkcolor=bg, troughcolor=T["trough"], focuscolor=T["accent"],
                         selectbackground=T["accent"], selectforeground="#ffffff", insertcolor=fg)
            st.map(".", foreground=[("disabled", "#6c717a")])
            st.configure("TFrame", background=bg)
            st.configure("TLabel", background=bg, foreground=fg)
            st.configure("TLabelframe", background=bg, bordercolor=border)
            st.configure("TLabelframe.Label", background=bg, foreground=fg)
            st.configure("TNotebook", background=bg, bordercolor=border)
            st.configure("TNotebook.Tab", background=panel, foreground=fg, bordercolor=border, padding=(10, 3))
            st.map("TNotebook.Tab", background=[("selected", "#353a44")], foreground=[("selected", "#ffffff")])
            st.configure("TButton", background=panel, foreground=fg, bordercolor=border, padding=(8, 3))
            st.map("TButton", background=[("disabled", bg), ("pressed", "#2f6bd0"), ("active", "#353a44")],
                   foreground=[("disabled", "#6c717a")])
            for w in ("TCheckbutton", "TRadiobutton"):
                st.configure(w, background=bg, foreground=fg, indicatorbackground=field,
                             indicatorforeground=fg, upperbordercolor=border, lowerbordercolor=border)
                st.map(w, background=[("active", bg)], indicatorbackground=[("selected", T["accent"]),
                                                                           ("active", "#353a44")])
            st.configure("TCombobox", fieldbackground=field, background=panel, foreground=fg,
                         arrowcolor=fg, bordercolor=border)
            st.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)],
                   selectbackground=[("readonly", field)], selectforeground=[("readonly", fg)])
            self.option_add("*TCombobox*Listbox.background", field)
            self.option_add("*TCombobox*Listbox.foreground", fg)
            st.configure("Horizontal.TScale", background=T["accent"], troughcolor=T["trough"], bordercolor=border)
            for sb in ("TScrollbar", "Vertical.TScrollbar"):
                st.configure(sb, background="#3a3f48", troughcolor=T["log_bg"], arrowcolor=fg, bordercolor=border,
                             lightcolor="#3a3f48", darkcolor="#3a3f48", gripcount=0)
                st.map(sb, background=[("active", "#4a505b"), ("disabled", panel)])
        st.configure("Title.TLabel", font=("Segoe UI", 14, "bold"), foreground=T["fg"])
        st.configure("Name.TCheckbutton", font=("Segoe UI", 10, "bold"))
        st.configure("Small.TLabel", font=("Segoe UI", 9), foreground=T["small"])
        st.configure("Apply.TButton", font=("Segoe UI", 10, "bold"))
        root_bg = T["bg"] or ttk.Style(self).lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(background=root_bg)
        GHOST, INK, BAD_BG, OK_BG = T["ghost"], T["ink"], T["bad_bg"], T["field"]
        TIP_COLOURS[:] = [T["tip_bg"], T["tip_fg"]]
        for w in (self.game_lbl, self.dirty_lbl):
            w.configure(background=root_bg)
        self.dirty_lbl.configure(fg=T["warn"])
        if self.running is not None:
            self.game_lbl.configure(fg=T["bad"] if self.running else T["good"])
        self.log.configure(background=T["log_bg"], foreground=T["log_fg"], insertbackground=T["log_fg"])
        self.log.tag_configure("bad", foreground=T["bad"])
        self.log.tag_configure("good", foreground=T["good"])
        for c in (self.dist, self.steps):
            c.configure(background=T["canvas"])
        for c, _ in self._scrollers:
            c.configure(background=root_bg)
        for ctl in self._values().values():
            ctl.entry.configure(insertbackground=INK, disabledbackground=OK_BG)
            if ctl.ghost:
                ctl.entry.configure(fg=GHOST, bg=OK_BG)
            else:
                ctl.entry.configure(fg=INK, bg=OK_BG if ctl.valid() or not ctl.var.get().strip() else BAD_BG)

    def _scene(self):
        """A simple street, in metres (camera 1.4 m up, looking down the road = +z): ground layer
        (road, sidewalks, centre dashes) and solid things (building fronts and end walls with floor
        lines, lamp posts, one building across the road far ahead)."""
        g = -1.4
        ground = [([(-3.5, g, 1), (-3.5, g, 300), (3.5, g, 300), (3.5, g, 1)], "#4b5059"),
                  ([(-7.5, g, 1), (-7.5, g, 300), (-3.5, g, 300), (-3.5, g, 1)], "#7c828c"),
                  ([(3.5, g, 1), (3.5, g, 300), (7.5, g, 300), (7.5, g, 1)], "#7c828c")]
        for k in range(1, 45):
            z = k * 6.0
            ground.append(([(-0.12, g, z), (-0.12, g, z + 3), (0.12, g, z + 3), (0.12, g, z)], "#eeeeee"))
        solid = []                                     # (depth, kind, points, colour)
        pal = ["#c9a878", "#b98d6a", "#a9b3bf", "#d6c59e", "#9fa98f"]
        dark = ["#8f7652", "#83624a", "#77808a", "#9a8c6f", "#707863"]
        for side in (-7.5, 7.5):
            out = side + (12 if side > 0 else -12)
            for i, z0 in enumerate(range(2, 170, 17)):
                top = g + 9 + (i * 7 % 3) * 4 + (2 if side > 0 else 0)
                z1 = z0 + 14
                col = (i + (1 if side > 0 else 0)) % len(pal)
                solid.append((z0, "quad", [(side, g, z0), (side, top, z0), (out, top, z0), (out, g, z0)], dark[col]))
                face = [(side, g, z0), (side, top, z0), (side, top, z1), (side, g, z1)]
                floors = [[(side, g + fl * 3.2, z0), (side, g + fl * 3.2, z1)]
                          for fl in range(1, int((top - g) // 3.2))]
                solid.append((z0 + 7, "bld", (face, floors), pal[col]))
        far = 175.0
        solid.append((far, "bld", ([(-16, g, far), (-16, 26, far), (16, 26, far), (16, g, far)],
                                   [[(-16, g + y, far), (16, g + y, far)] for y in range(3, 27, 4)]),
                      "#a9b3bf"))
        for z in (12.0, 34.0, 60.0, 95.0):
            for side in (-5.6, 5.6):
                solid.append((z, "lamp", [(side, g, z), (side, g + 6, z)], "#d7dde5"))
        solid.sort(key=lambda s: -s[0])
        return ground, solid

    def _draw_lens(self, key, pan):
        import math
        c, _ = self.pic[key]
        c.delete("all")
        W, H = int(c.cget("width")), int(c.cget("height"))
        if pan is None:                       # stock: straight-line lens 113 x 90 deg, stretched to 16:9
            th, tv = 1.5111, 1.0

            def proj(x, y, z):
                z = max(z, 0.3)
                return W / 2 + (x / z) / th * W / 2, H / 2 - (y / z) / tv * H / 2
        else:
            fov, d = pan
            sc = (W / 2) / panini.params(fov, d)["xe"]

            def proj(x, y, z):
                phi = math.atan2(x, z)
                dist = math.hypot(x, z)
                S = (d + 1) / (d + math.cos(phi))
                return W / 2 + S * math.sin(phi) * sc, H / 2 - S * (y / dist) * sc

        def outline(pts, n=16):
            out = []
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                for k in range(n):
                    t = k / n
                    out.extend(proj(*(a[j] + (b[j] - a[j]) * t for j in range(3))))
            return out

        def line(a, b, n=24):
            out = []
            for k in range(n + 1):
                t = k / n
                out.extend(proj(*(a[j] + (b[j] - a[j]) * t for j in range(3))))
            return out
        for i in range(12):                                             # sky, then ground
            t = i / 11
            colr = "#%02x%02x%02x" % (int(28 + 70 * t), int(44 + 80 * t), int(74 + 100 * t))
            c.create_rectangle(0, H / 2 * i / 12, W, H / 2 * (i + 1) / 12 + 1, fill=colr, outline="")
        c.create_rectangle(0, H / 2, W, H, fill="#35412f", outline="")
        ground, solid = self._scene()
        for pts, colr in ground:
            c.create_polygon(*outline(pts), fill=colr, outline="")
        for depth, kind, data, colr in solid:
            if kind == "quad":
                c.create_polygon(*outline(data), fill=colr, outline="")
            elif kind == "bld":
                face, floors = data
                c.create_polygon(*outline(face), fill=colr, outline="#5a4a36")
                for a, b in floors:
                    c.create_line(*line(a, b), fill="#6d5c45")
            else:
                a, b = data
                c.create_line(*line(a, b, 6), fill=colr, width=2)
                x, y = proj(*b)
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#fff3b0", outline="")

    def _draw_distances(self):
        import math
        c = self.dist
        c.delete("all")
        W, H = int(c.cget("width")), int(c.cget("height"))
        cx, cy, R = 138, H - 22, 128
        r = lambda m: R * math.sqrt(m / 1600.0)
        for m in (100, 250, 500, 1000, 1600):
            c.create_arc(cx - r(m), cy - r(m), cx + r(m), cy + r(m), start=0, extent=180,
                         style="arc", outline="#e3e3e3")
            c.create_text(cx + r(m), cy + 10, text=f"{m}", fill="#9a9a9a", font=("Segoe UI", 7))
        view_on = self.check["view"].get()
        ours = [("View distance", 1600, None, "#2f6fd6"), ("Fog", 1200, 1600, "#9aa8bd"),
                ("Streetlights, loose objects, billboards (fade)", 800, 1000, "#e0a100"),
                ("Collision: cars, buildings, trees, rocks", 250, None, "#d23c3c"),
                ("Collision: loose objects, lamps", 160, None, "#f07b3f"),
                ("Traffic fades in / is removed", 140, 160, "#2e9e4f")]
        stock = [(600, None), (300, 600), (64, 80), (20, None), (20, None), (39, 60)]
        rows = []
        for (name, a, b, colr), (sa, sb) in zip(ours, stock):
            if view_on:
                self._ring(c, cx, cy, r, a, b, colr)
                rows.append((name, a, b, sa, sb, colr))
            else:
                self._ring(c, cx, cy, r, sa, sb, "#8a8a8a")
                rows.append((name, sa, sb, None, None, "#8a8a8a"))
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#111111")
        c.create_text(cx, cy + 12, text="you", font=("Segoe UI", 8))
        x0, y = cx + R + 14, 8
        c.create_text(x0, y, anchor="nw", font=("Segoe UI", 8, "bold"),
                      text="'See further' ON" if view_on else "'See further' OFF (stock)")
        y += 18
        fmt = lambda a, b: f"{a:g}" if b is None else f"{a:g}-{b:g}"
        for name, a, b, sa, sb, colr in rows:
            c.create_rectangle(x0, y + 3, x0 + 9, y + 12, fill=colr, outline="")
            tid = c.create_text(x0 + 14, y, anchor="nw", width=W - x0 - 16, font=("Segoe UI", 8),
                                text=f"{name}: {fmt(a, b)} m" + (f"  (stock {fmt(sa, sb)})" if sa is not None else ""))
            y = c.bbox(tid)[3] + 6

    def _ring(self, c, cx, cy, r, a, b, colr):
        if b is None:
            c.create_arc(cx - r(a), cy - r(a), cx + r(a), cy + r(a), start=0, extent=180, style="arc",
                         outline=colr, width=2)
        else:
            mid = (r(a) + r(b)) / 2
            c.create_arc(cx - mid, cy - mid, cx + mid, cy + mid, start=0, extent=180, style="arc",
                         outline=colr, width=max(2, int(r(b) - r(a))))

    def _draw_steps(self):
        c = self.steps
        c.delete("all")
        W = int(c.cget("width"))
        ad = self.check["adaptive"].get()
        hz = self.v_hz.value() if (self.check["fixedstep"].get() or ad) else None
        ad = ad and bool(hz)
        x0, x1, span = 64, W - 10, 100.0
        xs = lambda ms: x0 + (x1 - x0) * ms / span
        c.create_text(8, 8, anchor="nw", font=("Segoe UI", 8, "bold"),
                      text=(f"Follows FPS, floor {hz:g} Hz: 1 step per frame above it" if ad else
                            f"Fixed rate {hz:g} Hz: one physics step every {1000 / hz:.1f} ms"
                            if hz else "Fixed rate OFF: one step per frame, as long as the frame (stock)"))
        y = 40
        for fps in (20, 60, 120, 144):
            frame = 1000.0 / fps
            c.create_text(8, y + 8, anchor="w", text=f"{fps} FPS", font=("Segoe UI", 8, "bold"))
            t = 0.0
            while t <= span + 1e-6:
                c.create_line(xs(t), y - 6, xs(t), y + 22, fill="#bdbdbd")
                t += frame
            follow = ad and fps >= hz
            step = 1000.0 / hz if (hz and not follow) else frame
            t = step
            while t <= span + 1e-6:
                c.create_oval(xs(t) - 3, y + 5, xs(t) + 3, y + 11, outline="",
                              fill="#2e9e4f" if follow else "#2f6fd6" if hz else "#d23c3c")
                t += step
            if follow:
                txt = f"1 step per frame = {fps} Hz (follows your FPS)"
            elif hz:
                per = hz / fps
                if abs(per - round(per)) < 1e-6:
                    txt = f"{round(per)} step{'s' if round(per) != 1 else ''} per frame"
                elif per < 1:
                    txt = "0-1 steps per frame (some frames need none)"
                else:
                    txt = f"{int(per)}-{int(per) + 1} steps per frame"
            else:
                txt = f"1 step of {frame:.0f} ms per frame"
            c.create_text(x1, y + 24, anchor="ne", text=txt, fill="#555555", font=("Segoe UI", 8))
            y += 52

    # ---------- saved state <-> widgets
    def saved(self):
        s = racemod.load_state()
        pan = dict(panini.DEFAULTS)
        pan.update({k: v for k, v in (s.get("panini") or {}).items() if k in pan})
        race = s.get("race") or []
        return dict(extras=list(s.get("extras", [])), race=race,
                    chaos=any(n not in ("astarfix",) for n in race),
                    chaos_race=s.get("chaos_race") or racemod.LEVELS[7][1],
                    hz=float(s.get("fixedstep_hz", racemod.FIXED_HZ_DEFAULT)), panini=pan,
                    vals={n: float(s.get(v[0], v[5])) for n, v in racemod.VALUED.items() if n in VALUE_ROWS},
                    carsounds={k: int((s.get("carsounds") or {}).get(k, d))
                               for k, d in racemod.CARSOUNDS_DEFAULT.items()})

    def _level_of(self, names):
        for n, (nm, lv) in racemod.LEVELS.items():
            if list(lv) == list(names):
                return n
        return None

    def load_saved(self):
        sv = self.saved()
        self._loading = True
        for name, v in self.check.items():
            v.set(name in sv["extras"])
        self._ticks = {n for n in sv["extras"] if n in self.check}
        self.race_mode.set("chaos" if sv["chaos"] else "stock")
        chosen = sv["race"] if sv["chaos"] else sv["chaos_race"]
        lv = self._level_of(chosen)
        if lv is not None:
            self.custom_chaos = None
            self.level_box.configure(values=self.levels)
            self.level_box.set(self.levels[lv - 1])
        else:
            self.custom_chaos = "your remembered mix: " + ", ".join(chosen)
            self.level_box.configure(values=[self.custom_chaos] + self.levels)
            self.level_box.set(self.custom_chaos)
        p = sv["panini"]
        self.v_fov.set(p["fov"])
        self.v_vfov.set_range(*panini.vfov_range(p["fov"]))
        self.v_vfov.set(p["vfov"])
        self.v_scale.set(p["scale"])
        self.v_chase.set(p["chase"])
        self.v_hz.set(sv["hz"])
        for n, ctl in self.v_extra.items():
            ctl.set(sv["vals"][n])
        for slot, box in self.cs_box.items():
            v = sv["carsounds"][slot]
            box.set(self.CS_CHOICES[v] if 0 <= v <= 7 else "random")
        self._loading = False
        self._changed()
        self.draw_pictures()

    def config(self, dry=False):
        if self.race_mode.get() == "stock":
            race = "stock"
        else:
            sel = self.level_box.get()
            race = "chaos" if (self.custom_chaos and sel == self.custom_chaos) \
                else f"level:{sel.split(' ')[0]}"
        return {"extras": [n for n in racemod.EXTRAS if self.check[n].get()], "race": race,
                "fixedstep_hz": self.v_hz.value(),
                **{racemod.VALUED[n][0]: ctl.value() for n, ctl in self.v_extra.items()},
                "panini": {k: self._values()[k].value() for k in ("fov", "vfov", "scale", "chase")},
                "carsounds": self._cs_values(),
                "dry_run": dry}

    def _changed(self):
        if self._loading or not hasattr(self, "v_hz"):
            return
        if not getattr(self, "_redraw_due", False):
            self._redraw_due = True
            self.after(60, self.draw_pictures)
        self._links()
        sv = self.saved()
        c = self.config()
        diffs = []
        if set(c["extras"]) != set(sv["extras"]):
            diffs.append("extras")
        if (c["race"] == "stock") == sv["chaos"]:
            diffs.append("race routes")
        elif c["race"].startswith("level:") and sv["chaos"]:
            if list(racemod.LEVELS[int(c["race"][6:])][1]) != list(sv["race"]):
                diffs.append("chaos level")
        if c["fixedstep_hz"] is None or abs(c["fixedstep_hz"] - sv["hz"]) > 1e-6:
            diffs.append("physics rate")
        for n, ctl in self.v_extra.items():
            v = ctl.value()
            if v is None or abs(v - sv["vals"][n]) > 1e-6:
                diffs.append(VALUE_ROWS[n][0].lower())
        if any(c["panini"][k] is None or abs(c["panini"][k] - float(sv["panini"][k])) > 1e-6
               for k in sv["panini"]):
            diffs.append("Panini values")
        if c["carsounds"] != sv["carsounds"]:
            diffs.append("engine sounds")
        self.dirty_lbl.configure(text=("changed, not applied yet: " + ", ".join(diffs)) if diffs else "")

    def _links(self):
        """Keep the ticks the way Apply would build them, so what you see is what you get: ticking an
        extra ticks what it needs, unticking a needed one unticks what needs it, of two extras that
        change the same code the one you just ticked wins, and an extra replaced by a newer ticked one
        is unticked and greyed out."""
        now = {n for n, v in self.check.items() if v.get()}
        new, gone = now - self._ticks, self._ticks - now
        for a, others in racemod.CONFLICTS.items():
            for b in others:
                if a in new:
                    now.discard(b)
                elif b in new:
                    now.discard(a)
        add = set(new)
        while add:
            add = {d for n in add for d in racemod.REQUIRES.get(n, ()) if d in self.check and d not in now}
            now |= add
        drop = set(gone)
        while drop:
            drop = {n for n, deps in racemod.REQUIRES.items() if n in now and any(d in drop for d in deps)}
            now -= drop
        for newer, olds in racemod.SUPERSEDES.items():
            for o in olds:
                if o in self.cbs:
                    if newer in now:
                        now.discard(o)
                    self.cbs[o].state(["disabled"] if newer in now else ["!disabled"])
        for n, v in self.check.items():
            if v.get() != (n in now):
                v.set(n in now)
        self._ticks = now

    # ---------- installed status
    def refresh_installed(self):
        try:
            buf = open(racemod.GAME, "rb").read()
            st = racemod.state(buf)
            sha = racemod.hashlib.sha256(buf).hexdigest()[:16]
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(racemod.GAME)).strftime("%Y-%m-%d %H:%M")
            self.exe_lbl.configure(text=f"installed game.exe: {sha}...  {len(buf):,} bytes, "
                                        f"written {mt}")
            for name, lbl in self.inst.items():
                s = st.get(name, "?")
                lbl.configure(text={"on": "installed: on", "off": "installed: off"}.get(
                    s, "installed: other values"))
        except OSError as e:
            self.exe_lbl.configure(text=f"cannot read game.exe: {e}")

    def _watch_game(self):
        while True:
            self.q.put(("game", game_running()))
            threading.Event().wait(2.0)

    def _tick(self):
        blocked = self.running is not False or self.busy
        self.apply_btn.configure(state="disabled" if blocked else "normal")
        self.after(400, self._tick)

    # ---------- running racemod
    def say(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "game":
                    if val != self.running:
                        self.running = val
                        self.game_lbl.configure(
                            text="GAME IS RUNNING - close it to apply" if val else "Game closed - ready",
                            fg=self.T["bad"] if val else self.T["good"])
                elif kind == "line":
                    self.say(*val)
                elif kind == "done":
                    self._finished(*val)
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def run_racemod(self, args, label, after=None):
        if self.busy:
            return
        self.busy = True
        self.say(f"\n=== {label}  ({datetime.datetime.now():%H:%M:%S})")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")

        def work():
            patched = notes = 0
            rc = 1
            with open(LOGFILE, "a", encoding="utf-8") as lg:
                lg.write(f"\n=== {label} {datetime.datetime.now()}  racemod.py {' '.join(args)}\n")
                try:
                    p = subprocess.Popen([PY, "-u", os.path.join(HERE, "racemod.py")] + args, cwd=HERE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                         creationflags=NOWIN)
                except OSError as e:
                    self.q.put(("line", (f"could not start python: {e}", "bad")))
                    self.q.put(("done", (1, label, after)))
                    return
                for raw in p.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    lg.write(line + "\n")
                    if line.startswith("  patched 0x") and args[0] != "show":
                        patched += 1
                        continue
                    if line.startswith("note: '"):
                        notes += 1
                        continue
                    bad = any(w in line for w in ("REFUSED", "ABORT", "FAILED", "Traceback", "rror"))
                    good = any(w in line for w in ("verification: OK", "IDENTICAL", "settings saved"))
                    self.q.put(("line", (line, "bad" if bad else "good" if good else None)))
                rc = p.wait()
            if patched or notes:
                self.q.put(("line", (f"({patched} patch entries, {notes} parts added automatically "
                                     f"because other parts need them - full list in crpanel.log)", None)))
            self.q.put(("done", (rc, label, after)))

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, rc, label, after):
        self.busy = False
        self.say(f"=== {label}: {'done' if rc == 0 else f'FAILED (exit code {rc})'}",
                 "good" if rc == 0 else "bad")
        if after and rc == 0:
            after()

    def _reload(self):
        global panini, racemod
        panini = importlib.reload(panini)
        racemod = importlib.reload(racemod)
        self.load_saved()
        self.refresh_installed()

    def run_setup(self, dry):
        bad = [c.lbl.cget("text") for c in self._values().values() if not c.valid()]
        if bad:
            messagebox.showerror("Check the values",
                                 "These boxes hold something that isn't a number in range:\n\n- "
                                 + "\n- ".join(bad) + "\n\nEmpty a box to use its default.")
            return
        if not dry and self.running:
            messagebox.showwarning("Close the game first",
                                   "City Racing is running. Close the game, then press Apply again.")
            return
        with open(CFG, "w") as f:
            json.dump(self.config(dry), f, indent=2)
        self.run_racemod(["setup", CFG], "preview (nothing written)" if dry else "apply",
                         after=None if dry else self._reload)

    def restore(self):
        if self.running:
            messagebox.showwarning("Close the game first", "City Racing is running. Close it first.")
            return
        if not messagebox.askyesno(
                "Restore the stock game?",
                "This puts game.exe back to the ORIGINAL game: every extra off, stock race routes.\n"
                "Your values (physics rate, Panini) stay remembered for next time.\n\nContinue?"):
            return
        self.run_racemod(["restore"], "restore stock game", after=self._reload)

    def launch(self, script):
        exe = PYW if os.path.exists(PYW) else PY
        try:
            subprocess.Popen([exe, os.path.join(HERE, script)], cwd=HERE)
            self.say(f"launched {script}")
        except OSError as e:
            messagebox.showerror("Could not launch", f"{script}: {e}")

    def report_callback_exception(self, exc, val, tb):
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        with open(LOGFILE, "a", encoding="utf-8") as lg:
            lg.write(text)
        self.say(text, "bad")


def dpi_aware():
    """Crisp text on a scaled laptop screen (125 %/150 %) instead of a blurry stretched window."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


if __name__ == "__main__":
    dpi_aware()
    Panel().mainloop()
