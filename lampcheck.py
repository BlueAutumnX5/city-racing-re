r"""lampcheck.py - EXECUTE the three `view` caves in the executable .rdata tail, in Unicorn,
inside the fully patched exe, against a Python model.

1. Lamp/decor class fade (hook 0x00410f3e -> cave): run the whole fade block to 0x00410f94 and
   read the alpha written to [obj+0x86c]. Classes in racemod.LAMP_CLASS_MASK (lamps 0x400, and
   decorations 0x200 when LOOSE_LIKE_LAMPS) fade 800 -> LAMP_FAR; the rest DECOR_NEAR -> DECOR_FAR.
2. Lamp head / object parts (hook 0x004526a1 -> cave, x87): a stub loads the part distance, the
   game code decides "skip this part" (0x004527b7) or "draw" (0x004526b3); [esp+0x14] must hold
   the (scaled) distance the fade uses later.
3. Corona size (hook 0x00414224 -> cave): lamps' growth is capped, vehicles' is NOT (player).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                               UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
                               UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_XMM3)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                                "fadein", "spawnreach", "view", "overlay", "racers", "shadows"]
OBJ, SCR = 0x06000000, 0x06010000
SIM = racesim.Sim(NAMES)
MU = SIM.mu
MU.mem_map(OBJ, 0x20000, UC_PROT_ALL)
C = {k: v for k, v in zip(("near", "far", "rate"), (200.0, 250.0, 0.02))}
LAMP_FAR, DECOR_FAR = 1000.0, 250.0
S = DECOR_FAR / LAMP_FAR
f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]
fx = lambda reg: struct.unpack("<f", struct.pack("<I", MU.reg_read(reg) & 0xFFFFFFFF))[0]
OK = []
ESP0 = racesim.STACK + 0xF0000


def model_alpha(cls, d):
    x = f32(f32(d) * f32(S)) if cls & racemod.LAMP_CLASS_MASK else f32(d)
    if x > C["far"]:
        return 0.0
    if x <= C["near"]:
        return 1.0
    return f32(1.0 - f32(f32(x - C["near"]) * f32(C["rate"])))


def fade(cls, d):
    MU.mem_write(OBJ + 0x9d0, struct.pack("<I", cls))
    MU.mem_write(OBJ + 0xa24, struct.pack("<f", d))
    MU.reg_write(UC_X86_REG_ESI, OBJ)
    MU.reg_write(UC_X86_REG_ESP, ESP0)
    MU.emu_start(0x00410f3e, 0x00410f94, count=100)
    return struct.unpack("<f", MU.mem_read(OBJ + 0x86c, 4))[0]


def parts(cls, d):
    """Stub: fld d; fst [esp+0x14]; jmp 0x004526a1. Returns (exit, stored distance)."""
    MU.mem_write(OBJ + 0x9d0, struct.pack("<I", cls))
    MU.mem_write(SCR + 0x100, struct.pack("<f", d))
    stub = (b"\xd9\x05" + struct.pack("<I", SCR + 0x100) + b"\xd9\x54\x24\x14" + b"\xe9" +
            struct.pack("<i", 0x004526a1 - (SCR + 15)))   # stub = 6 + 4 + 5 bytes
    MU.mem_write(SCR, stub)
    MU.reg_write(UC_X86_REG_EBX, OBJ)
    MU.reg_write(UC_X86_REG_ESP, ESP0)
    exits = {0x004527b7: "skip", 0x004526b3: "draw"}
    hit = []
    h = MU.hook_add(1 << 2, lambda uc, a, s, u: (hit.append(a), uc.emu_stop()) if a in exits else None)
    MU.emu_start(SCR, 0xFFFFFFF0, count=100)
    MU.hook_del(h)
    stored = struct.unpack("<f", MU.mem_read(ESP0 + 0x14, 4))[0]
    return exits.get(hit[0] if hit else 0, "NONE"), stored


def corona(cls, d):
    v = f32(f32(d - 8.0) * f32(1 / 14.4))
    regs = {UC_X86_REG_EAX: cls, UC_X86_REG_EBX: 0x1111, UC_X86_REG_ECX: 0x2222, UC_X86_REG_EDX: 0x3333,
            UC_X86_REG_ESI: 0x4444, UC_X86_REG_EDI: 0x5555, UC_X86_REG_EBP: 0x6666, UC_X86_REG_ESP: ESP0}
    for r, val in regs.items():
        MU.reg_write(r, val)
    MU.reg_write(UC_X86_REG_XMM1, struct.unpack("<I", struct.pack("<f", v))[0])
    MU.reg_write(UC_X86_REG_XMM3, struct.unpack("<I", struct.pack("<f", 1.0))[0])
    MU.emu_start(0x00414224, 0x0041422b, count=20)
    kept = all(MU.reg_read(r) == val for r, val in regs.items())
    return fx(UC_X86_REG_XMM0), kept


def check(label, got, want, extra=True):
    ok = (abs(got - want) < 1e-6 if isinstance(want, float) else got == want) and extra
    OK.append(ok)
    print(f"  {'OK ' if ok else 'BAD'} {label:<58} got {got!s:<10} want {want}")


print("1. class fade (alpha)")
for cls, name in ((0x400, "lamp"), (0x200, "decor"), (0x100, "building")):
    for d in (50.0, 199.0, 225.0, 260.0, 799.0, 900.0, 999.0, 1001.0):
        check(f"{name} at {d:g}", round(fade(cls, d), 6), round(model_alpha(cls, d), 6))
print("2. lamp head / parts (skip decision + distance the fade reads)")
for cls, name in ((0x400, "lamp head"), (0x200, "cafe chair")):
    for d in (100.0, 240.0, 260.0, 990.0, 1010.0):
        x = d * S if cls & racemod.LAMP_CLASS_MASK else d
        e, st = parts(cls, d)
        check(f"{name} at {d:g}: {'skip' if x > DECOR_FAR else 'draw'}", e, "skip" if x > DECOR_FAR else "draw",
              abs(st - f32(x)) < 1e-3)
print("3. corona size")
cap = (80.0 - 8.0) / 14.4
for d in (50.0, 80.0, 250.0, 1000.0):
    g, kept = corona(0x400, d)
    check(f"lamp corona at {d:g} (capped at 80 m size)", round(g, 5),
          round(1.0 + min(f32((d - 8) * f32(1 / 14.4)), f32(cap)), 5), kept)
    g, kept = corona(0x800, d)
    check(f"car corona at {d:g} (unchanged)", round(g, 5), round(1.0 + f32((d - 8) * f32(1 / 14.4)), 5), kept)
print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
