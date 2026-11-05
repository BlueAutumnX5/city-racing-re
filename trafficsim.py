r"""trafficsim.py - run City Racing's REAL traffic route builder inside the emulator.

Why this exists: the `view` patch doubled the traffic spawn hop (48 -> 96 world units), and
the old `leap` patch refused every A* search whose endpoints were > 16 cells apart - for
EVERY caller of A*, not only the race walker. 96 units = 24 cells, so every traffic route
was refused and the city emptied (in-game 2026-09-24: "Vehicles on area: 1(30)").
racesim only exercised the race walker, so it could not see this. This harness does.

What runs (all game code, verified self-contained - only rand() is hooked):
    0x004315e0  traffic route builder: two ring hops of D from the snapped anchor, then
                the path builder between the two ring points
    0x00431350  path builder -> 0x0042d260 A* (+ whatever patches sit in front of it)
    0x0042db00  "road point on the circle of radius D"
It is called exactly as the spawner (0x00442f68) calls it:
    (path 0x02641980, &count 0x012d0cd8, &start_position, D, 3, 3, 100)
with the start position being a yellow (kind 3) cell, as after the spawner's snap.
D is read from the built image (0x00569a58 traffic, 0x00569a54 police), so `view` is
honoured automatically.

USAGE
    trafficsim.py                    the standard comparison table
    trafficsim.py --n 400            samples per configuration (default 300)
"""
import os
import random
import struct
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UcError
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

ROUTE_BUILDER = 0x004315e0
PATH_BUF, PATH_CNT = 0x02641980, 0x012d0cd8
D_TRAFFIC, D_POLICE = 0x00569a58, 0x00569a54
START = racesim.SCR + 0x300
PATH_CAP = 100                       # the spawner passes 100 as the point limit


def route(sim, cell, which, seed):
    """One spawn attempt's route from `cell`. Returns (ok, points, why)."""
    mu = sim.mu
    d = struct.unpack("<f", mu.mem_read(D_TRAFFIC if which == "traffic" else D_POLICE, 4))[0]
    x, h, z = struct.unpack_from("<3f", sim.route, cell * racesim.REC + 4)
    mu.mem_write(START, struct.pack("<3f", x, h, z))
    mu.mem_write(PATH_CNT, b"\0\0\0\0")
    mu.mem_write(sim.guard_lo, sim.guard)
    sim.seed = seed
    esp = racesim.STACK + 0xF0000
    mu.mem_write(esp, struct.pack("<4If3I", racesim.MAGIC, PATH_BUF, PATH_CNT, START, d,
                                  3, 3, PATH_CAP))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, racesim.THIS)
    try:
        mu.emu_start(ROUTE_BUILDER, racesim.MAGIC, count=200_000_000)
    except UcError as e:
        return False, 0, f"EMU FAULT @0x{mu.reg_read(UC_X86_REG_EIP):08x} {e}"
    ok = mu.reg_read(UC_X86_REG_EAX) != 0
    n = struct.unpack("<I", mu.mem_read(PATH_CNT, 4))[0]
    return ok, n, ("ok" if ok else "refused")


def _worker(job):
    names, which, cells, seeds = job
    sim = racesim.Sim(names)
    return [route(sim, c, which, s) for c, s in zip(cells, seeds)]


def measure(names, which, n, rng_seed=7, jobs=None):
    """Success rate over n spawn attempts from random yellow cells (same cells + seeds for
    every configuration, so configurations are compared like for like)."""
    sim0 = racesim.Sim([])
    rng = random.Random(rng_seed)
    cells = [rng.choice(sim0.k3) for _ in range(n)]
    seeds = [rng.getrandbits(32) for _ in range(n)]
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    k = (n + jobs - 1) // jobs
    work = [(names, which, cells[i:i + k], seeds[i:i + k]) for i in range(0, n, k)]
    with Pool(len(work)) as p:
        res = [r for part in p.map(_worker, work) for r in part]
    ok = [r for r in res if r[0]]
    faults = [r for r in res if r[2].startswith("EMU")]
    return dict(n=n, ok=len(ok), rate=len(ok) / n, faults=len(faults),
                max_pts=max((r[1] for r in ok), default=0),
                mean_pts=sum(r[1] for r in ok) / len(ok) if ok else 0, res=res)


if __name__ == "__main__":
    n = 300
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    lv = lambda k: [p for p in racemod.LEVELS[k][1] if not p.startswith("-")]
    configs = [
        ("stock", []),
        ("view", ["slack", "view"]),
        ("level 3 + view", lv(3) + ["slack", "view"]),
        ("level 6 + view", lv(6) + ["slack", "view"]),
        ("level 7 (chaos leap)", lv(7) + ["slack"]),
        ("level 7 + view", lv(7) + ["slack", "view"]),
    ]
    print(f"{'configuration':<24} {'kind':<8} {'routes built':>14} {'faults':>7} "
          f"{'mean pts':>9} {'max pts':>8}")
    for label, names in configs:
        for which in ("traffic", "police"):
            r = measure(names, which, n)
            print(f"{label:<24} {which:<8} {r['ok']:>6}/{r['n']:<4} {100*r['rate']:5.1f}% "
                  f"{r['faults']:>6} {r['mean_pts']:>9.1f} {r['max_pts']:>8}")
