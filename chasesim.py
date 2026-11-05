r"""chasesim.py - a police chase on the REAL city map, driven by the game's REAL chase code (2026-10-04).

Each frame runs the police chase-state handler 0x0043cda0 (state 4) in Unicorn - its re-route through
the real path builder 0x00431350 / A* on GlobalRoute.dat, target choice, target speed, steering,
throttle and brake - up to 0x0043d556, where every driving output is set (the rest is stuck/wreck
bookkeeping and sounds). A simple car model then moves the police car from those outputs:
  steering +0x7fa0 (-1..1, max 0.6 rad wheel, 2.6 m wheelbase), grip-limited yaw (8 m/s2 sideways),
  throttle +0x7f8c (0..100 -> 4.5 m/s2), brake +0x7f94 (0..100 -> 9 m/s2), handbrake +0x7f98 (7 m/s2).
You stand still on a road cell; the police start on a road cell 40..70 m away, facing along their own
route, at 50 km/h. A case is chosen only when the road route is clearly bent (route >= 1.15 x the
straight line), i.e. there is a corner to take. The police car "crashes" when its centre enters a
non-road map cell (a building block).
Usage: chasesim.py [--n 200]      compares stock (installed extras) vs + smartpolice
"""
import math
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racesim
from racesim import REC, SIDE, SCR, STACK, MAGIC, u32
from unicorn import UcError, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP)

BASE = ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach",
        "view", "overlay", "racers", "shadows", "nodamage", "modsect", "astarfix", "policeeyes"]
COP, ME = SCR + 0x100000, SCR + 0x140000
PLAYER, WANTED, DT_ADDR = 0x012D0C88, 0x012D044C, 0x012D04A8
DT = 1 / 30
END_FRAME, BRAKE_RET = 0x0043D556, 0x0043CE9F


def cell_of(x, z):
    col, row = int((x + 1200.0) / 4.0), int((1200.0 - z) / 4.0)
    if 0 <= col < SIDE and 0 <= row < SIDE:
        return row * SIDE + col
    return None


class Chase:
    def __init__(self, names):
        self.sim = racesim.Sim(names)
        self.mu = self.sim.mu
        e, _, p, _ = racesim.crpak.load_archive(racesim.assets.LIVE, "World")
        self.place = dict(((n, pl) for (n, _, _), pl in zip(e, p)))["Data/Landscape/StaticObjectsPlaceMap.dat"]
        self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.emu_stop(), begin=END_FRAME, end=END_FRAME)
        self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.emu_stop(), begin=BRAKE_RET, end=BRAKE_RET)
        # 0x00408db0 world -> car-local (thiscall ecx = matrix; out, in; ret 8) goes through D3DX's
        # CPU-dispatch table (0x00598238), filled at startup by CPUID code the harness never runs. The
        # car matrix is rigid (rows right/up/forward/position), so local = rows . (p - position), exact.
        self.mu.hook_add(UC_HOOK_CODE, self._to_local, begin=0x00408DB0, end=0x00408DB0)

    def _to_local(self, uc, a, s, u):
        sp = uc.reg_read(UC_X86_REG_ESP)
        ret, out, inp = struct.unpack("<3I", uc.mem_read(sp, 12))
        m = struct.unpack("<16f", uc.mem_read(uc.reg_read(UC_X86_REG_ECX), 64))
        p = struct.unpack("<3f", uc.mem_read(inp, 12))
        d = [p[i] - m[12 + i] for i in range(3)]
        loc = [sum(m[4 * r + i] * d[i] for i in range(3)) for r in range(3)]
        uc.mem_write(out, struct.pack("<3f", *loc))
        uc.reg_write(UC_X86_REG_ESP, sp + 12)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def road(self, x, z):
        """Not crashed: the cell is part of the world (kind >= 1) and holds no placed static object
        (StaticObjectsPlaceMap.dat == 0: buildings, walls, trees...). Road cells (kinds 2..4) never
        hold one; wide roads have plain drivable ground (kind 1) between their driving lines."""
        c = cell_of(x, z)
        return c is not None and self.sim.kinds[c] >= 1 and self.place[c] == 0

    def w(self, a, fmt, *v):
        self.mu.mem_write(a, struct.pack(fmt, *v))

    def r(self, a, fmt):
        return struct.unpack(fmt, self.mu.mem_read(a, struct.calcsize(fmt)))

    def set_cop(self, x, y, z, ang, v):
        fx, fz = math.sin(ang), math.cos(ang)
        mat = (fz, 0, -fx, 0, 0, 1, 0, 0, fx, 0, fz, 0, x, y, z, 1)
        self.w(COP, "<16f", *mat)
        self.w(COP + 0xa18, "<3f", x, y, z)
        self.w(COP + 0x7f70, "<f", v * 3.6)

    def run(self, cop_xyz, ang, me_xyz, seconds=15.0):
        mu = self.mu
        mu.mem_write(self.sim.guard_lo, self.sim.guard)
        mu.mem_write(COP, bytes(0x9000)); mu.mem_write(ME, bytes(0x9000))
        self.w(ME + 0xa18, "<3f", *me_xyz)
        self.w(ME + 0x20, "<3f", 0.0, 0.0, 1.0)
        self.w(PLAYER, "<I", ME)
        self.w(WANTED, "<f", 0.5)
        self.w(DT_ADDR, "<f", DT)
        self.w(COP + 0x7f74, "<f", 150.0)                 # police top speed, km/h
        self.w(COP + 0x1ea4, "<f", 10.0)                  # re-route on the first frame
        self.w(COP + 0x1e74, "<I", 4)
        x, y, z = cop_xyz
        v = 50 / 3.6
        trace = []
        for f in range(int(seconds / DT)):
            self.set_cop(x, y, z, ang, v)
            self.w(COP + 0x7f94, "<f", 0.0)
            esp = STACK + 0xE0000
            self.w(esp, "<I", MAGIC)
            mu.reg_write(UC_X86_REG_ESP, esp)
            mu.reg_write(UC_X86_REG_ECX, COP)
            try:
                mu.emu_start(0x0043CDA0, MAGIC, count=50_000_000)
            except UcError as e:
                return dict(result="FAULT %08x %s" % (mu.reg_read(UC_X86_REG_EIP), e), t=f * DT, trace=trace)
            steer, = self.r(COP + 0x7fa0, "<f")
            thr, = self.r(COP + 0x7f8c, "<f")
            brk, = self.r(COP + 0x7f94, "<f")
            hb, = self.r(COP + 0x7f98, "<I")
            acc = min(max(thr, 0), 100) / 100 * 4.5 - min(max(brk, 0), 100) / 100 * 9.0 - (7.0 if hb else 0.0)
            v = min(max(v + acc * DT, 0.0), 150 / 3.6)
            s = max(-1.0, min(1.0, steer))
            yaw = v / 2.6 * math.tan(s * 0.6)
            lim = 8.0 / max(v, 1.0)
            yaw = max(-lim, min(lim, yaw))
            ang += yaw * DT
            x += math.sin(ang) * v * DT
            z += math.cos(ang) * v * DT
            trace.append((x, z, v * 3.6))
            d = math.hypot(x - me_xyz[0], z - me_xyz[2])
            if not self.road(x, z):
                return dict(result="CRASH", t=f * DT, trace=trace, vmax=max(p[2] for p in trace))
            if d < 6.0:
                return dict(result="CAUGHT", t=f * DT, trace=trace, vmax=max(p[2] for p in trace))
        return dict(result="TIMEOUT", t=seconds, trace=trace, vmax=max(p[2] for p in trace))


def cases(chase, n, seed=11):
    """(cop start, heading, player) with a clearly bent road route between them."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "re-tools"))
    import chaseprobe
    rnd = random.Random(seed)
    sim = chase.sim
    out = []
    tries = 0
    while len(out) < n and tries < n * 400 + 2000:
        tries += 1
        p = rnd.choice(sim.k3)
        pr, pc = divmod(p, SIDE)
        c = pr * SIDE + pc
        dr, dc = rnd.randint(-18, 18), rnd.randint(-18, 18)
        if not 10 <= max(abs(dr), abs(dc)) <= 18:
            continue
        c = (pr + dr) * SIDE + (pc + dc)
        if not (0 <= pr + dr < SIDE and 0 <= pc + dc < SIDE) or sim.kinds[c] != 3:
            continue
        P, C = chaseprobe.pos(sim, p), chaseprobe.pos(sim, c)
        res, pts = chaseprobe.reroute(sim, C, P)
        if not res.startswith("ROUTE") or len(pts) < 4:
            continue
        L = sum(math.dist((a[0], a[2]), (b[0], b[2])) for a, b in zip(pts, pts[1:]))
        straight = math.dist((C[0], C[2]), (P[0], P[2]))
        if L < 1.15 * straight or L > 110:
            continue
        a, b = pts[-1], pts[-3]                       # the route is stored reversed: last = police end
        ang = math.atan2(b[0] - a[0], b[2] - a[2])
        out.append((C, ang, P, L))
    return out


def main():
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 200
    stock = Chase(BASE)
    smart = Chase(BASE + ["smartpolice"])
    cs = cases(stock, n)
    print(f"{len(cs)} chases with a corner on the road route (route 1.15x+ the straight line, <= 110 m)\n")
    tally = {"stock": {}, "smart": {}}
    times = {"stock": [], "smart": []}
    for i, (C, ang, P, L) in enumerate(cs):
        row = []
        for name, ch in (("stock", stock), ("smart", smart)):
            r = ch.run(C, ang, P)
            tally[name][r["result"]] = tally[name].get(r["result"], 0) + 1
            if r["result"] == "CAUGHT":
                times[name].append(r["t"])
            row.append(f"{r['result']:<8} {r['t']:5.1f}s")
        if i < 12:
            print(f"  route {L:5.1f} m: stock {row[0]}   smart {row[1]}")
    print()
    for name in ("stock", "smart"):
        t = tally[name]
        tt = times[name]
        print(f"  {name}: " + ", ".join(f"{k} {v}" for k, v in sorted(t.items()))
              + (f"   mean time to reach you {sum(tt) / len(tt):.1f} s" if tt else ""))
    n_ok = len(cs)
    sm, st = tally["smart"], tally["stock"]
    checks = [sm.get("CAUGHT", 0) >= 0.85 * n_ok,                  # smart police reach you
              sm.get("CRASH", 0) * 3 <= max(1, st.get("CRASH", 0)),  # and crash far less than stock
              not any(k.startswith("FAULT") for k in list(sm) + list(st))]
    print(f"\n{sum(checks)}/{len(checks)} checks passed (smart reaches you in >= 85%, crashes <= 1/3 of stock, no faults)")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
