"""realcal.py - calibrate the realistic-gearing punch k per car (player 2026-11-01: top speed halfway to the real
car's + 0-100 "50/50" or "Real-car"). Runs the real drive code 0x004345e0 + racemod `drivetrain` + crdrive.dll
(drivesim2's rig, LINEAR drag as measured by the coast-down) with settings +16 = the mode and the tools-only
punch override at settings +20, bisecting k until 0-100 km/h hits the target. Prints the k table for
model.rs REAL and, per car, top speed / 0-100 / how long each gear lasts.
    realcal.py            (both modes)      realcal.py check   (no override: the DLL's own table)
"""
import json
import struct
import sys

import racemod
from drivesim2 import setup, run, GEARBOXES
from gearsim import BOXES, first_reach

# the 0-100 times the player approved in the options modal (2026-11-01)
TARGET = {"half": {"01": 6.2, "02": 8.2, "03": 6.8, "04": 4.7, "05": 7.7, "06": 13.2, "07": 4.5, "08": 3.8},
          "real": {"01": 9.0, "02": 10.5, "03": 9.5, "04": 6.0, "05": 10.5, "06": 16.0, "07": 5.3, "08": 4.7}}
MODE = {"half": 0, "real": 1}


def drive(model, mode, k, seconds):
    base = [n for n in racemod.load_state().get("extras", []) if n in racemod.EXTRAS and n not in GEARBOXES]
    _, d = setup(model, base, 0)
    d.w32(racemod.DT_SETTINGS + 16, MODE[mode])
    d.mu.mem_write(racemod.DT_SETTINGS + 20, struct.pack("<f", k))
    name, kind, gears = BOXES[model]
    out = run(d, kind, gears, seconds)
    shifts, last, since = [], out[0][2], 0.0
    for t, v, g, rpm, f in out:
        if g != last and g > 0:
            shifts.append(round(t - since, 1))
            since, last = t, g
    return dict(top=max(v for _, v, *_ in out), t100=first_reach(out, 100), gears=shifts)


def main():
    check = "check" in sys.argv
    table = {}
    for mode in ("half", "real"):
        print(mode)
        for model in BOXES:
            want = TARGET[mode][model]
            if check:
                k = 0.0
            else:
                lo, hi = 0.15, 1.0
                for _ in range(9):
                    k = (lo + hi) / 2
                    t = drive(model, mode, k, want * 1.6 + 2)["t100"]
                    if t is None or t > want:
                        lo = k                       # too slow: more punch
                    else:
                        hi = k
                k = round((lo + hi) / 2, 3)
            r = drive(model, mode, k, 70)
            table.setdefault(model, {})[mode] = k
            t100 = f"{r['t100']:5.1f}" if r["t100"] else "  -  "
            print(f"  {model} {BOXES[model][0]:16s} k {k:5.3f}  top {r['top']:5.1f}  0-100 {t100} (target {want})"
                  f"  gears last {r['gears'][:5]}")
    if not check:
        print(json.dumps(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
