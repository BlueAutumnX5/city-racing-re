r"""nodamagecheck.py - EXECUTE the `nodamage` hook (0x0043ab0d -> cave 0x0058f780) in Unicorn, inside
the fully patched exe. At the hook xmm1 = the final impact force, esi = the damaged car.
Player's car ([0x012d0c88]): must jump to the crash-sound tail 0x0043b444 with the force untouched
(no dents / tyres / engine). Any other car: must continue into the damage block at 0x0043ab15
with xmm1 += 0.5, exactly like the replaced `addss xmm1, [0.5]`. Other registers untouched.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM1)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                                "fadein", "spawnreach", "view", "overlay", "racers", "shadows", "nodamage"]
PLAYER, OTHER = 0x05000000, 0x05100000
SIM = racesim.Sim(NAMES)
MU = SIM.mu
MU.mem_write(racemod.PLAYER_CAR, struct.pack("<I", PLAYER))
fbits = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
OK = []


def run(car, force):
    regs = {UC_X86_REG_ESI: car, UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x2222, UC_X86_REG_EAX: 0x3333,
            UC_X86_REG_ECX: 0x4444, UC_X86_REG_EDX: 0x5555, UC_X86_REG_EBP: 0x6666,
            UC_X86_REG_ESP: racesim.STACK + 0xF0000}
    for r, v in regs.items():
        MU.reg_write(r, v)
    MU.reg_write(UC_X86_REG_XMM1, fbits(force))
    exits = {0x0043b444: "sound tail (no damage)", 0x0043ab15: "damage block"}
    hit = []
    h = MU.hook_add(1 << 2, lambda uc, a, s, u: (hit.append(a), uc.emu_stop()) if a in exits else None)
    MU.emu_start(0x0043ab0d, 0xFFFFFFF0, count=50)
    MU.hook_del(h)
    kept = all(MU.reg_read(r) == v for r, v in regs.items())
    x1 = struct.unpack("<f", struct.pack("<I", MU.reg_read(UC_X86_REG_XMM1) & 0xFFFFFFFF))[0]
    return exits.get(hit[0] if hit else 0, "NONE"), round(x1, 6), kept


def check(label, car, force, want_exit, want_x1):
    ex, x1, kept = run(car, force)
    ok = ex == want_exit and abs(x1 - want_x1) < 1e-6 and kept
    OK.append(ok)
    print(f"  {'OK ' if ok else 'BAD'} {label:<34} -> {ex:<24} force {x1:<8g} (want {want_exit}, {want_x1:g})"
          f"{'' if kept else '  REGISTERS CHANGED'}")


check("player's car, light hit", PLAYER, 0.3, "sound tail (no damage)", 0.3)
check("player's car, huge hit", PLAYER, 1.0, "sound tail (no damage)", 1.0)
check("traffic car, light hit", OTHER, 0.3, "damage block", 0.8)
check("traffic car, huge hit", OTHER, 1.0, "damage block", 1.5)
MU.mem_write(racemod.PLAYER_CAR, struct.pack("<I", 0))              # no player car (menus / on foot)
check("no player car set, traffic car", OTHER, 0.4, "damage block", 0.9)
print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
