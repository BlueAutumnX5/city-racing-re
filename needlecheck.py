"""needlecheck.py - racemod `rpmdial` speed needle, executed in Unicorn inside the patched exe (player 2026-11-01:
"keep 0-180, but make the needle go beyond 180, and make sure it is accurate"). Runs the speedometer's own
clamp + scale 0x00468131..0x00468168 for many speeds: the needle angle (xmm0) must be exactly speed x 1.5 deg
up to the new limit (235) and stop there; below 0 it stays at 0; stock still stops at 180.
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import racemod
import racesim
from unicorn import UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_XMM0

CAR = 0x06100000
OK = []


def check(label, ok):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}")


def needle(names, kmh):
    sim = racesim.Sim(names)
    mu = sim.mu
    try:
        mu.mem_map(CAR, 0x10000, UC_PROT_ALL)
    except Exception:
        pass
    mu.mem_write(0x012D0C88, struct.pack("<I", CAR))
    out = []
    for v in kmh:
        mu.mem_write(CAR + 0x7F70, struct.pack("<f", v))
        mu.reg_write(UC_X86_REG_ESP, racesim.STACK + 0xF0000)
        mu.emu_start(0x00468131, 0x00468168, count=40)
        x = mu.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF
        out.append(math.degrees(struct.unpack("<f", struct.pack("<I", x))[0]))
    return out


def main():
    speeds = [-20.0, 0.0, 50.0, 100.0, 179.0, 180.0, 181.0, 189.0, 191.0, 222.0, 234.9, 235.0, 236.0, 300.0]
    stock = needle(["slack"], speeds)
    check(f"stock: 0..180 clamp at 1.421 deg/km/h (180 -> {stock[5]:.1f}, 222 -> {stock[9]:.1f} deg)",
          stock[1] == 0 and abs(stock[9] - stock[5]) < 1e-4 and abs(stock[5] - 180 * 1.42098) < 0.05)
    names = ["slack"] + [n for n in ("modsect", "drivetrain", "hudfix", "rpmdial")]
    got = needle(names, speeds)
    want = [min(max(v, 0.0), racemod.NEEDLE_MAX) * 1.5 for v in speeds]
    for v, g, w in zip(speeds, got, want):
        if abs(g - w) > 0.01:
            check(f"{v:g} km/h -> {g:.3f} deg (want {w:.3f})", False)
    check(f"rpmdial: exactly 1.5 deg per km/h past 180 (189 -> {got[7]:.2f}, 222 -> {got[9]:.2f} deg), "
          f"stops at {racemod.NEEDLE_MAX:g} ({got[-1]:.2f} deg), never below 0",
          all(abs(g - w) <= 0.01 for g, w in zip(got, want)))
    check("the needle never reaches the 0 mark again (235 x 1.5 < 360 deg)", max(got) < 359.0)
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
