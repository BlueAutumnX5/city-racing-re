r"""leapcheck.py - prove leap v2 (gate on the walker's two A* calls) builds EXACTLY the same
race courses as leap v1 (gate at A*'s entry), which the player tested in-game.

Same start cell, same seed, same progress for every course; compares the outcome and every
cell of the finished route. v1 comes from leap_v1.pickle (saved before the change).
"""
import os
import pickle
import random
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import racemod
import racesim

# Module level, so every worker process (spawned, not forked, on Windows) has it too.
racemod.PATCHES["leap_v1"] = pickle.load(open(os.path.join(HERE, "leap_v1.pickle"), "rb"))["leap"]

V1 = ["leap_v1", "wander", "spread", "slack"]           # v1 carried its own A* fix
V2 = racemod.LEVELS[7][1] + ["slack"]                   # astarfix, leap, wander, spread


def _worker(jobs):
    a, b = racesim.Sim(V1), racesim.Sim(V2)
    out = []
    for start, seed, prog in jobs:
        random.seed(seed); ra = a.race(prog, start=start, seed=seed)
        random.seed(seed); rb = b.race(prog, start=start, seed=seed)
        jumps = racesim.straight_jumps(rb["cells"], a.kinds)[0] if rb["ok"] else 0
        out.append(((ra["why"], ra["cells"]) == (rb["why"], rb["cells"]), ra["why"], rb["why"],
                    jumps, len(rb["cells"])))
    return out


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 1200
    probe = racesim.Sim([])
    rng = random.Random(11)
    jobs = [(rng.choice(probe.k3), rng.getrandbits(32), rng.random()) for _ in range(n)]
    w = max(1, (os.cpu_count() or 2) - 1)
    k = (n + w - 1) // w
    with Pool(w) as p:
        res = [r for part in p.map(_worker, [jobs[i:i + k] for i in range(0, n, k)]) for r in part]
    same = sum(r[0] for r in res)
    ok = sum(r[2] == "ok" for r in res)
    with_jump = sum(r[3] > 0 for r in res if r[2] == "ok")
    print(f"leap v1 vs v2: {same}/{n} courses identical (outcome + every cell)")
    print(f"  v2 courses ok: {ok}/{n}; ok courses containing a straight-line leap: {with_jump}")
    bad = [r for r in res if not r[0]]
    for r in bad[:10]:
        print(f"  DIFF: v1 {r[1]}  v2 {r[2]}")
