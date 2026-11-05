"""Probe (2026-10-04, smart police): run the chase handler's own re-route block (0x0043ce19..0x0043cef8)
on the real city map and print the route it gives a police car. Usage: chaseprobe.py [n_cases]"""
import os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import racesim
from racesim import ROUTE, REC, SIDE, SCR, STACK, u32
from unicorn import UcError
from unicorn.x86_const import *

NAMES = ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach",
         "view", "overlay", "racers", "shadows", "nodamage", "modsect", "astarfix"]
COP, ME = SCR + 0x100000, SCR + 0x140000
PLAYER = 0x012D0C88


def pos(sim, cell):
    return struct.unpack_from("<3f", sim.route, cell * REC + 4)


def reroute(sim, cop_xyz, me_xyz):
    mu = sim.mu
    mu.mem_write(COP, bytes(0x9000)); mu.mem_write(ME, bytes(0x9000))
    mu.mem_write(COP + 0xa18, struct.pack("<3f", *cop_xyz))
    mu.mem_write(ME + 0xa18, struct.pack("<3f", *me_xyz))
    mu.mem_write(sim.guard_lo, sim.guard)
    mu.mem_write(PLAYER, struct.pack("<I", ME))
    esp = STACK + 0xE0000
    mu.mem_write(esp, bytes(0x100))
    d = sum((a - b) ** 2 for a, b in zip(cop_xyz, me_xyz)) ** 0.5
    mu.mem_write(esp + 0x14, struct.pack("<f", d))
    for r, v in ((UC_X86_REG_ESP, esp), (UC_X86_REG_ESI, COP), (UC_X86_REG_EDI, COP + 0xa18),
                 (UC_X86_REG_EBP, 1), (UC_X86_REG_XMM1, 0)):
        mu.reg_write(r, v)
    stop = {}
    hs = [mu.hook_add(racesim.UC_HOOK_CODE, lambda uc, a, s, u: (stop.setdefault("at", a), uc.emu_stop()),
                      begin=x, end=x) for x in (0x0043CEF8, 0x0043CE7A)]
    try:
        mu.emu_start(0x0043CE19, 0x0043CEF9, count=50_000_000)
    except UcError as e:
        return "FAULT %08x %s" % (mu.reg_read(UC_X86_REG_EIP), e), []
    finally:
        for h in hs:
            mu.hook_del(h)
    n = u32(mu.mem_read(COP + 0x7f44, 4))
    pts = [struct.unpack("<3f", mu.mem_read(COP + 0x1ecc + 12 * i, 12)) for i in range(min(n, 2048))]
    return ("ROUTE" if stop.get("at") == 0x0043CEF8 else "BRAKE (road point not found)"), pts


if __name__ == "__main__":
    sim = racesim.Sim(NAMES)
    rnd = random.Random(3)
    k3 = sim.k3
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 4):
        a = rnd.choice(k3)
        ar, ac = divmod(a, SIDE)
        b = rnd.choice([i for i in k3[::7] if 6 < max(abs(i // SIDE - ar), abs(i % SIDE - ac)) < 15])
        A, B = pos(sim, a), pos(sim, b)
        res, pts = reroute(sim, A, B)
        print(f"cop {A[0]:.0f},{A[2]:.0f} -> you {B[0]:.0f},{B[2]:.0f}: {res}, {len(pts)} points")
        for i, p in enumerate(pts[:40]):
            step = (sum((x - y) ** 2 for x, y in zip(p, pts[i - 1])) ** 0.5) if i else 0
            print(f"   [{i:2}] {p[0]:8.2f} {p[1]:6.2f} {p[2]:8.2f}   step {step:5.2f}")
