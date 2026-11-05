r"""fadecheck.py - EXECUTE the `fadein` hook (0x0043fc55 -> cave) in Unicorn, inside the fully
patched exe, and check it against a Python model.

The hook replaces the per-car step's `movss [ebx+0xd00], xmm0` (store the distance fade).
For traffic (type 3) and police (type 2): alpha = min(distance alpha, previous + dt * rate).
Anything else stores the distance alpha unchanged. It must come back at 0x0043fc5d with every
register except eax/xmm1/xmm2 untouched (those three are dead there, see racemod).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_XMM0,
                               UC_X86_REG_XMM3)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                                "fadein", "spawnreach", "view", "overlay", "racers", "shadows"]
CAR = 0x05000000
DT = 0x012d04a8
RATE = 1.0 / racemod.FADEIN_SECONDS
f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]      # round to float32
OK = []

SIM = racesim.Sim(NAMES)
MU = SIM.mu
MU.mem_map(CAR, 0x10000)


def step(ty, prev, dist, dt):
    """Run the hook once; return (stored alpha, registers preserved?, xmm3 preserved?)."""
    mu = MU
    mu.mem_write(CAR + 0xc8c, struct.pack("<I", ty))
    mu.mem_write(CAR + 0xd00, struct.pack("<f", prev))
    mu.mem_write(DT, struct.pack("<f", dt))
    regs = {UC_X86_REG_EBX: CAR, UC_X86_REG_EBP: CAR + 0xa18, UC_X86_REG_ESI: 0x33333333,
            UC_X86_REG_EDI: 0x44444444, UC_X86_REG_ECX: 0x55555555, UC_X86_REG_EDX: 0x66666666,
            UC_X86_REG_ESP: racesim.STACK + 0xF0000}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", dist))[0])
    mu.reg_write(UC_X86_REG_XMM3, 0x0123456789abcdef0123456789abcdef)
    mu.emu_start(0x0043fc55, 0x0043fc5d, count=1000)
    got = struct.unpack("<f", mu.mem_read(CAR + 0xd00, 4))[0]
    kept = all(mu.reg_read(r) == v for r, v in regs.items())
    x3 = mu.reg_read(UC_X86_REG_XMM3) == 0x0123456789abcdef0123456789abcdef
    x0 = struct.unpack("<f", struct.pack("<I", mu.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF))[0]
    return got, kept and x3, x0


def model(ty, prev, dist, dt):
    if ty in (2, 3):
        return min(f32(dist), f32(f32(prev) + f32(f32(dt) * f32(RATE))))
    return f32(dist)


def check(label, ty, prev, dist, dt):
    got, kept, x0 = step(ty, prev, dist, dt)
    want = model(ty, prev, dist, dt)
    ok = got == want and kept and x0 == got
    OK.append(ok)
    print(f"  {'OK ' if ok else 'BAD'} {label:<48} type {ty} prev {prev:<6g} dist {dist:<5g} "
          f"dt {dt:<7g} -> {got:.6f} (model {want:.6f}){'' if kept else '  REGISTERS CHANGED'}")


print(f"fade-in hook: {racemod.FADEIN_SECONDS:g} s from invisible to solid (rate {RATE:g}/s)")
check("new traffic car, distance says solid", 3, 0.0, 1.0, 0.008)
check("new police car, distance says solid", 2, 0.0, 1.0, 0.008)
check("traffic mid fade-in, still rising", 3, 0.4, 1.0, 0.008)
check("traffic nearly in, capped at distance alpha", 3, 0.995, 1.0, 0.008)
check("traffic driving away: falls with distance", 3, 1.0, 0.3, 0.008)
check("traffic beyond the fade: 0 at once", 3, 0.7, 0.0, 0.008)
check("paused frame (dt 0) holds the value", 3, 0.25, 1.0, 0.0)
check("big hitch (dt 0.5)", 3, 0.2, 1.0, 0.5)
check("race opponent: never limited", 1, 0.0, 1.0, 0.008)
check("player's car type: never limited", 0, 0.0, 1.0, 0.008)
check("unknown type 7: never limited", 7, 0.0, 0.6, 0.008)

# a whole fade-in at 144 fps, compared frame by frame with the model
prev, pm, frames, same = 0.0, 0.0, 0, True
while prev < 1.0 and frames < 1000:
    prev, _, _ = step(3, prev, 1.0, 1 / 144)
    pm = model(3, pm, 1.0, 1 / 144)
    same &= prev == pm
    frames += 1
ok = same and abs(frames / 144 - racemod.FADEIN_SECONDS) < 0.02
OK.append(ok)
print(f"  {'OK ' if ok else 'BAD'} full fade-in at 144 fps: {frames} frames = {frames / 144:.3f} s, "
      f"every frame == model: {same}")

print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
