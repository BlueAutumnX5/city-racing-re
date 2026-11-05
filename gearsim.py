"""gearsim.py - how long does each gear last? (player 2026-11-01: "some cars have unreasonably short lower gears,
1st to 3rd feels very short"). Full-throttle runs from a standstill through the REAL drive code 0x004345e0 +
racemod `drivetrain` + crdrive.dll (drivesim2's rig: drivesim's 1-D car, mass / drag calibrated to each car's
stock top speed, grip 1.1 g). Manual / F1 shift at 95 % revs, automatics in D. Prints per car: the speed and time
of every upshift, time spent in each gear, 0-50 / 0-100 km/h and the stock game's for comparison.

    gearsim.py [seconds=40] [upgrades=0] [launch=1.0]   launch: scales every car's acceleration stat = the
                                                       gearbox's low-gear pull (a 'what if', top speed untouched)
"""
import sys
import racemod
import drivesim
from drivesim2 import setup, run, GEARBOXES

# model: name, box kind (drivesim2.run), gears - as rust/crdrive/src/model.rs
BOXES = {"01": ("Galant S500", "auto", 4), "02": ("Clio NSX", "manual", 5), "03": ("Rover H1200", "auto", 6),
         "04": ("Cosmo R200", "manual", 6), "05": ("Thunder-1960", "auto", 3), "06": ("Accord Z8", "manual", 5),
         "07": ("Alpha GRX8", "manual", 6), "08": ("Uber Atom-2000", "f1", 6)}


def first_reach(out, kmh):
    return next((t for t, v, *_ in out if v >= kmh), None)


def fmt(t):
    return f"{t:5.1f}s" if t is not None else "   -  "


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    upgrades = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    launch = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    for k, (n, mass, fb, acc, drive) in list(drivesim.CARS.items()):
        drivesim.CARS[k] = (n, mass, fb, acc * launch, drive)
    base = [n for n in racemod.load_state().get("extras", []) if n in racemod.EXTRAS and n not in GEARBOXES]
    print(f"full throttle from 0, {seconds:.0f} s, engine/transmission upgrades {upgrades}, launch x{launch}")
    for model, (name, kind, gears) in BOXES.items():
        s, d = setup(model, base, upgrades)
        stock = run(s, kind, gears, seconds, drivetrain=False)
        out = run(d, kind, gears, seconds)
        shifts, last, since = [], out[0][2], 0.0
        for t, v, g, rpm, f in out:
            if g != last and g > 0:
                shifts.append((last, t, v, t - since))
                since, last = t, g
        top = max(v for _, v, *_ in out)
        print(f"\n{name} ({kind}, {gears} gears): top {top:5.1f} km/h | 0-50 {fmt(first_reach(out, 50))} "
              f"0-100 {fmt(first_reach(out, 100))} | stock game 0-50 {fmt(first_reach(stock, 50))} "
              f"0-100 {fmt(first_reach(stock, 100))}")
        for g, t, v, dur in shifts:
            print(f"   {g} -> {g + 1}  at {v:5.1f} km/h, t {t:5.2f} s  (gear {g} lasted {dur:4.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
