r"""spawnreachcheck.py - EXECUTE the `spawnreach` hook (0x00442f8f -> cave) in Unicorn, inside the
fully patched exe. It replaces the spawner's `test eax,eax / jne 0x004431b2` (reject when
0x00441aa0 found a car near the route) and additionally rejects a route whose first point
[0x02641980] is more than SPAWN_REACH (horizontal) from the anchor at [esi]. Exits: 0x00442f97 =
go on and create the car, 0x004431b2 = attempt failed. Registers other than xmm0/xmm1 and
flags must come back untouched.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM2)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein",
                                "spawnreach", "view", "overlay", "racers", "shadows"]
MGR = racemod.TRAFFIC_MGR
ANCHOR = MGR + 0x9d7c
PATH = 0x02641980
R = racemod.SPAWN_REACH
OK = []
SIM = racesim.Sim(NAMES)
MU = SIM.mu


def run(eax, anchor, p0):
    mu = MU
    mu.mem_write(ANCHOR, struct.pack("<3f", *anchor))
    mu.mem_write(PATH, struct.pack("<3f", *p0))
    regs = {UC_X86_REG_EAX: eax, UC_X86_REG_ESI: ANCHOR, UC_X86_REG_EDI: MGR,
            UC_X86_REG_EBX: 0x11111111, UC_X86_REG_EBP: 0x22222222, UC_X86_REG_ECX: 0x33333333,
            UC_X86_REG_EDX: 0x44444444, UC_X86_REG_ESP: racesim.STACK + 0xF0000}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_XMM2, 0x0123456789abcdef0123456789abcdef)
    exits = {0x00442f97: "create", 0x004431b2: "fail"}
    hit = []
    h = mu.hook_add(1 << 2, lambda uc, a, s, u: (hit.append(a), uc.emu_stop()) if a in exits else None)
    mu.emu_start(0x00442f8f, 0xFFFFFFF0, count=200)
    mu.hook_del(h)
    kept = all(mu.reg_read(r) == v for r, v in regs.items())
    kept &= mu.reg_read(UC_X86_REG_XMM2) == 0x0123456789abcdef0123456789abcdef
    return exits.get(hit[0] if hit else 0, "NONE"), kept


def check(label, eax, anchor, p0, want):
    got, kept = run(eax, anchor, p0)
    ok = got == want and kept
    OK.append(ok)
    print(f"  {'OK ' if ok else 'BAD'} {label:<52} -> {got:<6} (want {want}){'' if kept else '  REGISTERS CHANGED'}")


print(f"spawn reach {R:g} (despawn {racemod.TRAFFIC_DESPAWN:g})")
A = (100.0, 20.0, -300.0)
check("original rejection (car near route) still fails", 1, A, (A[0] + 50, 20, A[2]), "fail")
check("route start 140 away (the ring)", 0, A, (A[0] + 140, 25, A[2]), "create")
check("route start 151.9 away", 0, A, (A[0], 20, A[2] - 151.9), "create")
check("route start 152.1 away", 0, A, (A[0], 20, A[2] - 152.1), "fail")
check("route start 167 away (the old instant deaths)", 0, A, (A[0] + 118, 20, A[2] + 118), "fail")
check("height difference is ignored (140 flat, 100 up)", 0, A, (A[0] + 140, 120, A[2]), "create")
check("route start right at the anchor", 0, A, A, "create")
check("far off (519 away)", 0, A, (A[0] - 519, 20, A[2]), "fail")
print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
