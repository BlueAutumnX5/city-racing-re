r"""racercheck.py - is the 4/6/8-racer roll biased by the course generator?

After a successful course the race setup (0x00440520) draws, in order:
    r1 = rand()   timed race if r1 % 101 <= 40                      (0x00440799)
    r2 = rand()   % 3, a second choice                              (0x004407b3)
    r3 = rand()   opponent races only: racers = (r3 % 300)/100*2+4  (0x00440810)
so the racer count is the 3rd rand() after the walker returns. This runs the REAL walker in
racesim, takes the LCG state it leaves, and draws r1..r3 exactly like the game.
"""
import os
import random
import sys
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim


def _worker(job):
    names, jobs = job
    sim = racesim.Sim(names)
    mod = racesim.u32(sim.mu.mem_read(0x00440817, 4))      # 300 stock, 500 with `racers`
    out = []
    for start, seed, prog in jobs:
        random.seed(seed)
        r = sim.race(prog, start=start, seed=seed)
        if not r["ok"]:
            continue
        s, draws = sim.seed, []
        for _ in range(3):
            s = (s * sim.mul + sim.add) & 0xFFFFFFFF
            draws.append((s >> 16) & 0x7FFF)
        timed = draws[0] % 101 <= 40
        out.append("timed" if timed else (draws[2] % mod) // 100 * 2 + 4)
    return out


def measure(names, n=1500, seed=3):
    probe = racesim.Sim([])
    rng = random.Random(seed)
    jobs = [(rng.choice(probe.k3), rng.getrandbits(32), rng.random()) for _ in range(n)]
    w = max(1, (os.cpu_count() or 2) - 1)
    k = (n + w - 1) // w
    with Pool(w) as p:
        res = [x for part in p.map(_worker, [(names, jobs[i:i + k]) for i in range(0, n, k)])
               for x in part]
    return Counter(res), len(res)


if __name__ == "__main__":
    for label, names, n in (("stock", [], 1500),
                            ("level 7 chaos leap", racemod.LEVELS[7][1] + ["slack"], 1500),
                            ("level 7 + racers", racemod.LEVELS[7][1] + ["slack", "dataslack",
                                                                           "racers"], 6000)):
        c, total = measure(names, n)
        opp = sum(v for k, v in c.items() if k != "timed")
        print(f"{label:<20} {total} races: timed {c['timed']} ({100 * c['timed'] / total:.0f}%); "
              f"opponent races {opp}: " + ", ".join(
                  f"{k}p {c[k]} ({100 * c[k] / max(1, opp):.1f}%)" for k in (4, 6, 8, 10, 12)
                  if c[k] or k <= 8))
