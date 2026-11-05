"""Sweep the smartpolice corner settings in chasesim: catch rate, crashes, time, mean speed on the way."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import racemod, chasesim

VARIANTS = [  # (label, bend points, grip m/s2, straight threshold t, decel m/s2)
    ("grip 10, brake 7", 5, 10.0, 0.20, 7.0),
    ("grip 7, brake 7", 5, 7.0, 0.20, 7.0),
    ("grip 5.5, brake 7", 5, 5.5, 0.20, 7.0),
    ("grip 4.5, brake 7", 5, 4.5, 0.20, 7.0),
    ("grip 5.5, brake 5", 5, 5.5, 0.20, 5.0),
]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
cases = None
for label, bend, grip, straight, decel in VARIANTS:
    racemod.SMART_BEND, racemod.SMART_GRIP, racemod.SMART_DECEL = bend, grip, decel
    c = dict(racemod._SMART_CONSTS)
    c.update(GRIP=grip * 3.6 ** 2, STRAIGHT=straight, A2=2 * decel * 3.6 ** 2)
    racemod._SMART_CONSTS[:] = [(k, c[k]) for k, _ in racemod._SMART_CONSTS]
    racemod.PATCHES["smartpolice"] = racemod._smartpolice()
    ch = chasesim.Chase(chasesim.BASE + ["smartpolice"])
    if cases is None:
        cases = chasesim.cases(ch, N)
    tally, times, speeds = {}, [], []
    for C, ang, P, L in cases:
        r = ch.run(C, ang, P)
        tally[r["result"]] = tally.get(r["result"], 0) + 1
        if r["result"] == "CAUGHT":
            times.append(r["t"])
        speeds += [p[2] for p in r["trace"]]
    print(f"{label:<48} caught {tally.get('CAUGHT', 0):3}/{len(cases)}  crash {tally.get('CRASH', 0):3}  "
          f"time {sum(times) / max(1, len(times)):4.1f} s  mean speed {sum(speeds) / len(speeds):5.1f} km/h", flush=True)
