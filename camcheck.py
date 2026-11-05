r"""camcheck.py - racemod `camfix` (player 2026-11-02: close chase view a tiny bit farther, both views higher, same
angle) executed in Unicorn: the game's chase-camera function 0x004018c0 run in the stock build and with camfix, for
the close and far views, standing and at speed, on a level and a tilted car. Checks: close view 10 % farther back,
far view the same distance; both heights + 0.1 x distance (eye AND aim, so the look-down angle is unchanged); the up
vector (3rd output) untouched; registers / stack as the caller expects (ret 0xc).
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP

BASE = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein",
                               "spawnreach", "view", "overlay", "racers", "shadows", "modsect", "panini"]
CAM, CAR, OUT = 0x05800000, 0x05900000, 0x05A00000
OK = []


def check(label, ok):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}")


def run(names, view, speed, fwd=(0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0), size=6.0):
    s = racesim.Sim(names)
    mu = s.mu
    for a in (CAM, CAR, OUT):
        mu.mem_map(a, 0x10000 if a != CAR else 0x10000, UC_PROT_ALL)
    mu.mem_write(CAM + 0x9EF0, struct.pack("<I", CAR))
    mu.mem_write(CAM + 0x9ED0, struct.pack("<I", view))
    mu.mem_write(CAR + 0x8B4, struct.pack("<f", size))
    mu.mem_write(CAR + 0x7F70, struct.pack("<f", speed))
    mu.mem_write(CAR + 0x10, struct.pack("<3f", *up))
    mu.mem_write(CAR + 0x20, struct.pack("<3f", *fwd))
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<4I", 0x0BADF00D, OUT, OUT + 0x10, OUT + 0x20))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, CAM)
    mu.reg_write(UC_X86_REG_ESI, 0x1234)
    mu.emu_start(0x004018C0, 0x0BADF00D, count=5000)
    vec = lambda a: struct.unpack("<3f", mu.mem_read(a, 12))
    stack = mu.reg_read(UC_X86_REG_ESP) == esp + 0x10 and mu.reg_read(UC_X86_REG_ESI) == 0x1234
    return vec(OUT), vec(OUT + 0x10), vec(OUT + 0x20), stack


def main():
    stock_names, fix_names = BASE, BASE + ["hlsect", "camfix"]
    print("1. level car, standing and at 150 km/h: distance back, heights, angle")
    for view, name, k in ((1, "close", racemod.CAM_CLOSE), (2, "far", 1.0)):
        for speed in (0.0, 150.0):
            (se, sa, su, sst), (fe, fa, fu, fst) = run(stock_names, view, speed), run(fix_names, view, speed)
            back_s, back_f = -se[2], -fe[2]
            d_s = back_s / (1 + 0.5 * min(speed * 0.005, 1))      # the stock distance d (eye back = d x stretch)
            d_f = d_s * k
            lift = racemod.CAM_LIFT * d_f
            ang = lambda e, a: math.degrees(math.atan2(e[1] - a[1], a[2] - e[2]))
            check(f"{name} @ {speed:g} km/h: back {back_s:.2f} -> {back_f:.2f} m (x{back_f / back_s:.3f}), eye up "
                  f"{se[1]:.2f} -> {fe[1]:.2f}, aim up {sa[1]:.2f} -> {fa[1]:.2f}, look-down {ang(se, sa):.2f} -> "
                  f"{ang(fe, fa):.2f} deg",
                  abs(back_f / back_s - k) < 1e-4 and abs(fe[1] - (se[1] * k + lift)) < 1e-3
                  and abs(fa[1] - (sa[1] * k + lift)) < 1e-3 and abs(fa[2] - sa[2] * k) < 1e-3
                  and abs(ang(se, sa) - ang(fe, fa)) < 0.05 and su == fu and sst and fst)
    print("2. a car pitched up a hill and rolled: the same changes, the up vector untouched")
    f = (0.0, math.sin(0.3), math.cos(0.3))
    u = (math.sin(0.2), math.cos(0.2), 0.0)
    (se, sa, su, _), (fe, fa, fu, fst) = run(stock_names, 1, 60.0, f, u), run(fix_names, 1, 60.0, f, u)
    k = racemod.CAM_CLOSE
    d = 6.0 * 0.85 * racemod.panini.CHASE_DISTANCE * k if hasattr(racemod, "panini") else None
    check(f"close view on a 17 deg hill: eye {tuple(round(x, 2) for x in se)} -> {tuple(round(x, 2) for x in fe)}, "
          f"up vector {tuple(round(x, 3) for x in fu)} unchanged",
          su == fu and fst and abs(fe[0] - se[0] * k) < 1e-3 and abs(fe[2] - se[2] * k) < 1e-3
          and fe[1] > se[1] * k)
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
