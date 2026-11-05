r"""racesim.py - run City Racing's REAL race-course generator inside a CPU emulator.

Nothing here is a reimplementation of the game's logic. game.exe is loaded into a Unicorn
x86 emulator - with any racemod patches applied IN MEMORY, the real file is never touched -
together with the live GlobalRoute.dat, and the game's own machine code is executed:

    0x0042be0f   the loader's graph rebuild, so adjacency is built exactly as in-game
    0x00432b40   the course walker (random walk over yellow / kind 3)
    0x0042d260   its A* pathfinder, called by the walker's two smoothing passes
    0x0042c5d0   the nearest-kind-3-cell finder the walker starts with

The ONLY replaced function is rand() (0x0054aba3): it reads per-thread data through the
FS segment, which is awkward to emulate, so a Python hook runs the same LCG instead. The
hook reads the multiplier and increment out of emulated memory, so a `reshuffle` patch
is honoured automatically.

That pipeline is self-contained - verified by disassembly: the walker calls only the
nearest-cell finder, which calls nothing, and the pathfinder calls only memset. So what
the emulator produces is what the game produces.

WHY THIS EXISTS
The first `nostep` patch deleted every race billboard, and static reading of the patch
did not catch it. This harness would have: a walker that returns 0 on every call shows
up as 100% failures in the first second.

USAGE
    racesim.py stock                 simulate with no patches
    racesim.py level 3               simulate a racemod level
    racesim.py apply nostep wander   simulate named patches (REQUIRES is NOT enforced,
                                     so broken combinations can be studied)
    add  --n 300   courses to run (default 200)
"""

import os
import random
import struct
import sys
import time

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX,
                               UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
                               UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak
import racemod

IMG = 0x00400000
THIS = 0x012d0ce0                   # the map object - static in this build
ROUTE = THIS + 0x1b98a0             # 0x0148a580, confirmed by `add eax, 0x148a584`
WAYPT = THIS + 0x161a5c
P_ARR, P_CNT = 0x012cc418, 0x012d0cd4
B_ARR = 0x00d429b8
RAND = 0x0054aba3
WALKER = 0x00432b40
REBUILD_FROM, REBUILD_TO = 0x0042be0f, 0x0042c00d
AT_WALK_END = 0x00432cda            # edi = number of walk points
AT_PASS1_END = 0x00432d72           # ebx = number of pass-1 pathfinder points
CAP = 0x800                         # 2048 entries in each point buffer

STACK = 0x00100000                  # 1 MB stack
SCR = 0x00200000                    # 2 MB scratch: return trap, args, output
MAGIC = SCR
CNT = SCR + 0x100
POS = SCR + 0x200
OUT = SCR + 0x1000

SIDE, REC = 600, 48


def u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


def build_exe(patch_names):
    """The baseline game.exe with patches applied in memory only."""
    racemod.ensure_backup()
    buf = bytearray(open(racemod.BACKUP, "rb").read())
    for name in patch_names:
        if name.startswith("-"):
            continue                          # "-astarfix" = explicitly NOT applied
        for va, orig, new, _ in racemod.PATCHES[name]:
            if racemod.put(buf, va, orig, new) is not None:     # grows the file for .crmod
                raise SystemExit(f"baseline does not match at 0x{va:08x} - aborting")
    return bytes(buf)


class Sim:
    def __init__(self, patch_names):
        self.patches = list(patch_names)
        exe = build_exe(self.patches)
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)

        # ---- map the image exactly where Windows would
        secs = racemod.sections(exe)
        end = max(base + vsz for base, vsz, _, _ in secs)
        mu.mem_map(IMG, (end - IMG + 0xFFF) & ~0xFFF)
        mu.mem_write(IMG, exe[:0x1000])
        for base, vsz, raw, rsz in secs:
            mu.mem_write(base, exe[raw:raw + rsz])   # BSS beyond rsz stays zero
        mu.mem_map(STACK, 0x100000)
        mu.mem_map(SCR, 0x200000)

        # ---- rand(): same LCG, constants read from the (possibly patched) image
        self.mul = u32(mu.mem_read(0x0054abad, 4))
        self.add = u32(mu.mem_read(0x0054abb3, 4))
        # The race distance is computed by the setup code (0x004405c3), which the harness
        # does not execute - it hands the walker a budget directly. Read the modulus out
        # of the (possibly patched) image so `spread` is honoured. An earlier version
        # hardcoded 1001 and so silently simulated `spread` as if it were off.
        self.dist_mod = u32(mu.mem_read(0x004405c4, 4))
        self.seed = 1
        mu.hook_add(UC_HOOK_CODE, self._rand, begin=RAND, end=RAND)

        # ---- decision log for `draw`: at 0x00432cc1 the walker has just done
        # rand() % candidates, so edx = the slot it picked, edi = how many it had,
        # esi = the cell it is standing on. Also count A* calls.
        self.log = None
        self.astar = self.rand_calls = 0
        mu.hook_add(UC_HOOK_CODE, self._decide, begin=0x00432cc1, end=0x00432cc1)
        mu.hook_add(UC_HOOK_CODE, self._astar, begin=0x0042d260, end=0x0042d260)

        # ---- probes: walk length, pass-1 length. Buffer overruns are judged from these
        # counts against CAP, not from address guards: the memory right after each
        # buffer holds other live globals that the game writes legitimately, so an
        # address guard fires even on the stock game.
        self.walk_n = self.pass1_n = 0
        self.reached_end = False
        mu.hook_add(UC_HOOK_CODE, self._probe, begin=AT_WALK_END, end=AT_WALK_END)
        mu.hook_add(UC_HOOK_CODE, self._probe, begin=AT_PASS1_END, end=AT_PASS1_END)

        # ---- world data, then the GAME's own graph rebuild
        e, _, p, _ = crpak.load_archive(assets.LIVE, "World")
        files = {n: pl for (n, _, _), pl in zip(e, p)}
        self.route = files["Data/Landscape/GlobalRoute.dat"]
        mu.mem_write(ROUTE, self.route)
        mu.mem_write(WAYPT, files["Data/Landscape/WayPointsMap.dat"])
        mu.reg_write(UC_X86_REG_ESP, STACK + 0xF0000)
        mu.reg_write(UC_X86_REG_EBP, THIS)
        mu.emu_start(REBUILD_FROM, REBUILD_TO)

        # Three map fields the loader sets at runtime. Read out of the nearest-cell
        # finder (0x0042c5d0), which computes
        #     col = (x + [this+0x100]*0.5) / [this+0x110],  bounds-checked on [this+0x104]
        # and the route data's own X = -1198 + 4*col pins them down exactly.
        mu.mem_write(THIS + 0x100, struct.pack("<f", 2400.0))   # world size
        mu.mem_write(THIS + 0x104, struct.pack("<I", 600))      # grid side
        mu.mem_write(THIS + 0x110, struct.pack("<f", 4.0))      # cell size = budget divisor

        self.k3 = [i for i in range(SIDE * SIDE) if u32(self.route, i * REC) == 3]
        self.kinds = bytes(min(u32(self.route, i * REC), 4) for i in range(SIDE * SIDE))

        # Snapshot everything from the end of the point buffer up to the map object's
        # header. An overflowing course writes straight through it - over P_CNT, other
        # globals, and the world/grid/cell-size fields - which silently wrecks every
        # later course, exactly as it would in the real game. Restoring before each
        # course keeps one bad course from polluting the statistics of the next.
        self.guard_lo, self.guard_hi = P_ARR + CAP * 8, THIS + 0x1000
        self.guard = bytes(mu.mem_read(self.guard_lo, self.guard_hi - self.guard_lo))

    # --------------------------------------------------------------- hooks
    def _rand(self, mu, addr, size, _):
        self.seed = (self.seed * self.mul + self.add) & 0xFFFFFFFF
        esp = mu.reg_read(UC_X86_REG_ESP)
        mu.reg_write(UC_X86_REG_EAX, (self.seed >> 16) & 0x7FFF)
        mu.reg_write(UC_X86_REG_ESP, esp + 4)
        mu.reg_write(UC_X86_REG_EIP, u32(mu.mem_read(esp, 4)))

    def _decide(self, mu, addr, size, _):
        self.rand_calls += 1
        if self.log is not None:
            cell = (mu.reg_read(UC_X86_REG_ESI) - ROUTE) // REC
            self.log.append((cell % SIDE, cell // SIDE, mu.reg_read(UC_X86_REG_EDI),
                             mu.reg_read(UC_X86_REG_EDX)))

    def _astar(self, mu, addr, size, _):
        self.astar += 1

    def _probe(self, mu, addr, size, _):
        if addr == AT_WALK_END:
            self.walk_n = mu.reg_read(UC_X86_REG_EDI)
            self.reached_end = True
        else:
            self.pass1_n = mu.reg_read(UC_X86_REG_EBX)

    # ---------------------------------------------------------------- race
    def check_rebuild(self):
        """Compare the emulated rebuild with the rule read out of the disassembly."""
        mem = self.mu.mem_read(ROUTE, SIDE * SIDE * REC)
        bad = 0
        for i in random.sample(self.k3, 500):
            r, c = divmod(i, SIDE)
            want = [ROUTE + (rr * SIDE + cc) * REC
                    for rr in (r - 1, r, r + 1) for cc in (c - 1, c, c + 1)
                    if (rr, cc) != (r, c) and u32(self.route, (rr * SIDE + cc) * REC) == 3]
            deg = mem[i * REC + 32]
            got = list(struct.unpack_from("<4I", mem, i * REC + 16))[:deg]
            bad += (got != want)
        return bad

    def race(self, progress, start=None, seed=None):
        """One course from a billboard (random unless `start` is a cell index).
        progress 0..1 is the player's standing, which the game turns into distance."""
        if seed is not None:
            self.seed = seed
        elif "noseed" not in self.patches:
            self.seed = random.getrandbits(32)      # srand(timeGetTime()) at 0x440584
        mu = self.mu
        mu.mem_write(self.guard_lo, self.guard)
        self.rand_calls = self.astar = 0
        i = random.choice(self.k3) if start is None else start
        x, h, z = struct.unpack_from("<3f", self.route, i * REC + 4)
        mu.mem_write(POS, struct.pack("<3f", x, h, z))
        mu.mem_write(CNT, b"\0\0\0\0")
        dist = random.randrange(self.dist_mod) + min(1.0, progress) * 2500.0 + 800.0
        budget = int(dist / 4.0)                    # fdiv by the 4.0 cell size, truncated
        esp = STACK + 0xF0000
        mu.mem_write(esp, struct.pack("<5I", MAGIC, OUT, CNT, POS, budget))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_ECX, THIS)
        self.walk_n = self.pass1_n = 0
        self.reached_end = False
        try:
            mu.emu_start(WALKER, MAGIC, count=400_000_000)
        except UcError as e:
            # The game's own code touched memory that does not exist. In the real
            # process that is a crash, or - worse - a silent read of whatever happens
            # to live there. Either way the patch set is not safe.
            eip = mu.reg_read(UC_X86_REG_EIP)
            n = u32(mu.mem_read(P_CNT, 4))
            return dict(ok=False, why=f"EMU FAULT @0x{eip:08x}", count=n, budget=budget,
                        walk=self.walk_n, pass1=self.pass1_n, cells=[], start=i,
                        detail=f"{e}; walk={self.walk_n} pass1={self.pass1_n} P_CNT={n}")
        ok = mu.reg_read(UC_X86_REG_EAX) != 0
        count = u32(mu.mem_read(CNT, 4))
        n = u32(mu.mem_read(P_CNT, 4))
        raw = mu.mem_read(P_ARR, min(n, CAP + 64) * 8)
        cells = [struct.unpack_from("<2I", raw, k * 8) for k in range(min(n, CAP + 64))]
        if ok:
            why = "ok" if count >= 100 else "route<100"      # the caller's gate, 0x0044076d
        elif not self.reached_end:
            why = "dead end"                                  # 0x00432ca0: no candidate
        else:
            why = "walk<30"                                   # 0x00432cdd
        return dict(ok=why == "ok", why=why, count=count, budget=budget,
                    walk=self.walk_n, pass1=self.pass1_n, cells=cells, start=i)


# ------------------------------------------------------------------- metrics
WINDOW = 12     # back on a cell seen in the last 12 steps  = retracing = a U-turn
CIRCLE = 250    # back on a cell seen 12..250 steps ago    = drove round a block
                # further back than that                   = the course crosses itself


def analyse(cells):
    """Events are counted once per run of consecutive matching cells, so driving back
    through one junction counts once, not once per cell of the junction."""
    path = [c for k, c in enumerate(cells) if k == 0 or c != cells[k - 1]]
    last_seen = {}
    ev = {"uturn": 0, "circle": 0, "cross": 0}
    state = None
    for k, c in enumerate(path):
        prev = last_seen.get(c)
        kind = None
        if prev is not None:
            gap = k - prev
            kind = "uturn" if gap <= WINDOW else "circle" if gap <= CIRCLE else "cross"
        if kind and kind != state:
            ev[kind] += 1
        state = kind
        last_seen[c] = k
    x0, y0 = path[0] if path else (0, 0)
    spread = max((max(abs(x - x0), abs(y - y0)) for x, y in path), default=0)
    return ev, len(path), len(set(path)), spread


def straight_jumps(cells, kinds):
    """Consecutive route points that are NOT neighbours: the route cuts a straight line
    between them - the 'race line into the ocean' the A* bug produces. Returns
    (jumps, jumps that cross water, longest jump in cells). Water = route kind 0."""
    n = wet = longest = 0
    for i in range(1, len(cells)):
        (c0, r0), (c1, r1) = cells[i - 1], cells[i]
        if max(c0, r0, c1, r1) >= SIDE:
            continue                                   # garbage from an overflow
        d = max(abs(c1 - c0), abs(r1 - r0))
        if d <= 1:
            continue
        n += 1
        longest = max(longest, d)
        if any(kinds[round(r0 + (r1 - r0) * k / d) * SIDE + round(c0 + (c1 - c0) * k / d)] == 0
               for k in range(1, d)):
            wet += 1
    return n, wet, longest


def event_points(cells):
    """Where the U-turns happen: the index at which each retrace starts."""
    path = [c for k, c in enumerate(cells) if k == 0 or c != cells[k - 1]]
    last, pts, state = {}, [], False
    for k, c in enumerate(path):
        prev = last.get(c)
        retrace = prev is not None and k - prev <= WINDOW
        if retrace and not state:
            pts.append(path[max(0, k - 1)])
        state = retrace
        last[c] = k
    return path, pts


def draw(out_path, configs, boards=2, progress=0.6, panel=560):
    """Render REAL simulated courses: one row per billboard, one column per config.
    Every row uses the same billboard in every column, so the columns are comparable."""
    sims = [(label, Sim(names)) for label, names in configs]
    base = sims[0][1]
    kinds = bytes(min(u32(base.route, i * REC), 4) for i in range(SIDE * SIDE))
    rng = random.Random(3)
    chosen, tries = [], 0
    while len(chosen) < boards and tries < 300:
        tries += 1
        st, seed = rng.choice(base.k3), rng.getrandbits(32)
        res = []
        for label, s in sims:
            s.log = []
            r = s.race(progress, start=st, seed=seed)
            r.update(log=s.log, decisions=s.rand_calls, astar=s.astar, label=label)
            s.log = None
            res.append(r)
        if all(r["ok"] for r in res):
            chosen.append((st, res))

    BG = {0: (12, 14, 20), 1: (32, 36, 46), 2: (44, 58, 50), 3: (86, 78, 40), 4: (78, 48, 40)}
    gap = 10
    W = len(configs) * panel + (len(configs) + 1) * gap
    H = len(chosen) * panel + (len(chosen) + 1) * gap
    img = bytearray(bytes((16, 18, 24, 255)) * (W * H))

    def put(x, y, col):
        if 0 <= x < W and 0 <= y < H:
            o = (y * W + x) * 4
            img[o:o + 3] = bytes(col)

    report = []
    for row, (st, res) in enumerate(chosen):
        allc = [c for r in res for c in r["cells"]]
        xs = [c for c, _ in allc]
        ys = [r_ for _, r_ in allc]
        m = 14
        x0, y0 = max(0, min(xs) - m), max(0, min(ys) - m)
        span = max(max(xs) - x0, max(ys) - y0) + m
        s = panel / span
        for col, r in enumerate(res):
            ox = gap + col * (panel + gap)
            oy = gap + row * (panel + gap)
            for py in range(panel):
                cy = min(SIDE - 1, y0 + int(py / s))
                for px in range(panel):
                    cx = min(SIDE - 1, x0 + int(px / s))
                    put(ox + px, oy + py, BG[kinds[cy * SIDE + cx]])
            path, uts = event_points(r["cells"])
            n = max(1, len(path) - 1)
            sz = max(2, int(s + 0.5))

            def seg(a, b, colr, th):
                ax, ay = ox + (a[0] - x0 + .5) * s, oy + (a[1] - y0 + .5) * s
                bx_, by_ = ox + (b[0] - x0 + .5) * s, oy + (b[1] - y0 + .5) * s
                steps = int(max(abs(bx_ - ax), abs(by_ - ay))) + 1
                for k2 in range(steps + 1):
                    px_ = int(ax + (bx_ - ax) * k2 / steps)
                    py_ = int(ay + (by_ - ay) * k2 / steps)
                    for dy in range(-th, th + 1):
                        for dx in range(-th, th + 1):
                            put(px_ + dx, py_ + dy, colr)

            for k, (cx, cy) in enumerate(path):
                t = k / n                                   # green start -> magenta end
                colr = (int(60 + 175 * t), int(225 - 160 * t), int(120 + 110 * t))
                bx, by = ox + int((cx - x0) * s), oy + int((cy - y0) * s)
                for dy in range(sz):
                    for dx in range(sz):
                        put(bx + dx, by + dy, colr)
            for k in range(1, len(path)):                   # straight jumps: thick cyan
                a_, b_ = path[k - 1], path[k]
                if max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1])) > 1:
                    seg(a_, b_, (60, 230, 255), 2)
            for (cx, cy) in uts:                            # red ring on every U-turn
                bx, by = ox + int((cx - x0 + .5) * s), oy + int((cy - y0 + .5) * s)
                for a in range(0, 360, 4):
                    import math
                    for rad in (8, 9):
                        put(bx + int(rad * math.cos(math.radians(a))),
                            by + int(rad * math.sin(math.radians(a))), (255, 60, 60))
            sx, sy = st % SIDE, st // SIDE                  # billboard: white square
            bx, by = ox + int((sx - x0) * s), oy + int((sy - y0) * s)
            for dy in range(-5, 6):
                for dx in range(-5, 6):
                    if max(abs(dx), abs(dy)) >= 4:
                        put(bx + dx, by + dy, (255, 255, 255))
            report.append((row, r, len(path), len(uts)))
    assets.png_write(out_path, W, H, bytes(img))
    return chosen, report


# ------------------------------------------------------------- many courses, all cores
def _worker(job):
    """One CPU core's share of a batch. Each worker is its own process with its own
    emulator, so nothing is shared. Only compact numbers travel back, not routes."""
    names, n, seed, extra = job
    if extra:
        racemod.PATCHES.update(extra)
    random.seed(seed)
    sim = Sim(names)
    bad = sim.check_rebuild()
    out = []
    for _ in range(n):
        r = sim.race(progress=random.random())
        out.append(dict(ok=r["ok"], why=r["why"], count=r["count"], walk=r["walk"],
                        pass1=r["pass1"], detail=r.get("detail"),
                        stats=analyse(r["cells"]) if r["ok"] else None,
                        jumps=straight_jumps(r["cells"], sim.kinds) if r["ok"] else None,
                        # route points NOT on a yellow cell = a checkpoint off the road
                        offroad=sum(1 for c, rw in r["cells"]
                                    if c >= SIDE or rw >= SIDE
                                    or sim.kinds[rw * SIDE + c] != 3) if r["ok"] else 0))
    return bad, out


def run(patch_names, n, label, jobs=None, extra=None):
    """Simulate n courses spread across every CPU core.

    `extra` overrides patch definitions by name (e.g. a different cap). It must be
    passed in, not set on racemod.PATCHES: on Windows each worker is a fresh process
    that re-imports racemod from disk and would never see the change.

    Any script that calls this must guard its own top level with
    `if __name__ == "__main__":` - Windows starts workers by re-importing the main
    module, and an unguarded caller would recursively launch itself."""
    import multiprocessing as mp
    jobs = max(1, min(jobs or os.cpu_count() or 1, n))
    share = [n // jobs + (1 if k < n % jobs else 0) for k in range(jobs)]
    base = random.getrandbits(32)
    t0 = time.time()
    with mp.Pool(jobs) as pool:
        parts = pool.map(_worker, [(list(patch_names), k, base + i, extra)
                                   for i, k in enumerate(share)])
    dt = time.time() - t0
    bad = max(p[0] for p in parts)
    res = [r for p in parts for r in p[1]]

    why = {}
    for r in res:
        why[r["why"]] = why.get(r["why"], 0) + 1
    faults = [r for r in res if r["why"].startswith("EMU FAULT")]
    if faults:
        print(f"\n  !! {len(faults)} course(s) made the game read or write memory that "
              f"does not exist. First: {faults[0]['detail']}")
    good = [r for r in res if r["ok"]]
    stats = [r["stats"] for r in good]
    pct = lambda k: 100.0 * k / max(1, len(good))
    lens = sorted(s[1] for s in stats) or [0]
    over = max(max(r["walk"], r["pass1"], r["count"]) for r in res)
    print(f"\n=== {label}  ({n} courses on {jobs} cores, {dt:.1f}s, "
          f"rebuild mismatches {bad}/500) ===")
    print(f"  outcome                  " + "  ".join(
        f"{k} {v} ({100*v/n:.0f}%)" for k, v in sorted(why.items())))
    if not good:
        return {"fail": 100.0}
    out = {"fail": 100.0 * (n - len(good)) / n}
    for key, name in (("uturn", "U-turn"), ("circle", "circle (block)"),
                      ("cross", "crosses itself")):
        have = pct(sum(1 for s in stats if s[0][key]))
        avg = sum(s[0][key] for s in stats) / len(stats)
        out[key] = have
        print(f"  courses with {name:<16}{have:5.1f}%   avg {avg:.2f} per course")
    jumped = sum(1 for r in good if r["jumps"][0])
    wet = sum(1 for r in good if r["jumps"][1])
    longest = max(r["jumps"][2] for r in good)
    out["jump"], out["wet"] = pct(jumped), pct(wet)
    avgj = sum(r["jumps"][0] for r in good) / len(good)
    print(f"  courses with straight jumps {pct(jumped):5.1f}%   over water {pct(wet):5.2f}%   "
          f"avg {avgj:.2f} per course   longest {longest} cells ({longest * 4} units)")
    off = sum(r["offroad"] for r in good)
    print(f"  route points off the road   {off}"
          + ("   <-- checkpoints somewhere unreachable" if off else "   (every checkpoint on a road)"))
    print(f"  route length (cells)     median {lens[len(lens)//2]}  "
          f"min {lens[0]}  max {lens[-1]}")
    print(f"  distinct / total cells   "
          f"{sum(s[2] for s in stats)/max(1,sum(s[1] for s in stats)):.2f}")
    print(f"  furthest from billboard  median "
          f"{sorted(s[3] for s in stats)[len(stats)//2]} cells")
    n_over = sum(1 for r in res if max(r["walk"], r["pass1"], r["count"]) > CAP)
    infl = max((r["count"] / r["walk"] for r in res if r["walk"]), default=0)
    print(f"  biggest buffer fill      {over} of {CAP}"
          + (f"   <-- OVERFLOW in {n_over} course(s)" if over > CAP else ""))
    print(f"  worst route/walk ratio   {infl:.3f}")
    out["len"] = lens[len(lens) // 2]
    out["over"] = n_over
    out["fill"] = over
    return out


if __name__ == "__main__":
    # Background runs write to a file, where Python block-buffers stdout and nothing
    # appears until exit. Line buffering makes progress readable while it runs.
    sys.stdout.reconfigure(line_buffering=True)
    a = sys.argv[1:]
    n = int(a[a.index("--n") + 1]) if "--n" in a else 200
    a = [x for i, x in enumerate(a) if x != "--n" and (i == 0 or a[i - 1] != "--n")]
    if not a:
        print(__doc__)
        sys.exit(0)
    if a[0] == "draw":
        # racesim.py draw [out.png] [stock|N ...]   default: stock vs level 3
        rest = a[1:]
        out = (rest.pop(0) if rest and rest[0].lower().endswith(".png")
               else os.path.join(os.path.dirname(__file__), "courses.png"))
        picks = rest or ["stock", "3"]
        cfg = [("stock", []) if p == "stock" else
               (f"level {p}", racemod.find_level(p)[2]) for p in picks]
        chosen, rep = draw(out, cfg)
        for row, r, ln, ut in rep:
            print(f"row {row+1}  {r['label']:<8} route {ln:5d} cells  "
                  f"{r['decisions']:4d} random choices  {r['astar']:3d} A* runs  "
                  f"{ut:2d} U-turns")
        st, res = chosen[0]
        for r in res:
            log = r["log"]
            forks = [e for e in log if e[2] > 1]
            print(f"\n{r['label']}: walker decisions, row 1 - {len(log)} steps, "
                  f"{len(forks)} had a real choice. First 8 real choices:")
            for c, rw, cand, pick in forks[:8]:
                print(f"   at cell ({c:3d},{rw:3d})  {cand} ways to go  -> rand picked #{pick}")
        print(f"\nwrote {out}")
    elif a[0] == "matrix":
        F = ["astarfix"]
        cfgs = [
            ("stock",                          []),
            ("level 1  reshuffle",             F + ["reshuffle"]),
            ("wander  (stock length)",         F + ["wander"]),
            ("level 3  nostep+wander",         F + ["reshuffle", "nostep", "wander", "junction"]),
            ("wander+spread",                  F + ["wander", "spread"]),
            ("wander+reverse",                 F + ["wander", "reverse"]),
            ("wander+reverse+spread",          F + ["wander", "reverse", "spread"]),
            ("wander+reverse+nostep",          F + ["wander", "reverse", "nostep"]),
        ]
        rows = []
        for label, names in cfgs:
            t0 = time.time()
            o = run(names, n, label)
            o["rate"] = n / (time.time() - t0)
            rows.append((label, o))
        print("\n" + "=" * 100)
        print(f"{'config':<28}{'fail%':>7}{'U-turn%':>9}{'circle%':>9}{'cross%':>8}"
              f"{'median len':>12}{'max fill':>10}{'overflow':>10}{'courses/s':>11}")
        for label, o in rows:
            print(f"{label:<28}{o.get('fail', 0):7.1f}{o.get('uturn', 0):9.1f}"
                  f"{o.get('circle', 0):9.1f}{o.get('cross', 0):8.1f}{o.get('len', 0):12}"
                  f"{o.get('fill', 0):10}{o.get('over', 0):10}{o['rate']:11.1f}")
    elif a[0] == "stock":
        run([], n, "stock")
    elif a[0] == "level":
        num, nm, names = racemod.find_level(" ".join(a[1:]))
        run(names, n, f"level {num} ({nm}): {'+'.join(names)}")
    elif a[0] == "apply":
        run(a[1:], n, "+".join(a[1:]))
