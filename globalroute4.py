r"""GlobalRoute.dat - validate the decoded record across all 360,000 cells.

Proposed 48-byte record:
    0x00  u32    kind: 0 = off-road, 1..4 = on-road
    0x04  f32    X  = -1198 + 4*column
    0x08  f32    height
    0x0c  f32    Z  =  1198 - 4*row
    0x10  u32    runtime pointer (stale on disk)
    0x14  u32    runtime pointer
    0x18  u32    runtime pointer
    0x1c  u32    runtime pointer
    0x20  u8[4]  [?] [waypoint id] [cost] [?]
    0x24  u16[2] (column, row) - the cell's own grid coordinates
    0x28  u32    reserved, always 0
    0x2c  u32    reserved, always 0
"""

import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak

SIDE, REC = 600, 48


def load(name):
    e, _, p, _ = crpak.load_archive(assets.STOCK, "World")
    for (n, _, _), pl in zip(e, p):
        if n.endswith(name):
            return pl


gr = load("Landscape/GlobalRoute.dat")
wp = load("Landscape/WayPointsMap.dat")

selfidx_ok = selfidx_bad = 0
x_ok = z_ok = 0
b1_eq_wp = b1_ne_wp = 0
kind_wp = Counter()
cost_by_kind = Counter()
b0 = Counter()
b3 = Counter()
ptr_nonzero = Counter()

for r in range(SIDE):
    base = r * SIDE * REC
    for c in range(SIDE):
        o = base + c * REC
        kind, = struct.unpack_from("<I", gr, o)
        x, hgt, z = struct.unpack_from("<3f", gr, o + 4)
        p4, p5, p6, p7 = struct.unpack_from("<4I", gr, o + 16)
        bb = gr[o + 32:o + 36]
        col, row = struct.unpack_from("<2H", gr, o + 36)
        r10, r11 = struct.unpack_from("<2I", gr, o + 40)

        if (col, row) == (c, r):
            selfidx_ok += 1
        else:
            selfidx_bad += 1
        if abs(x - (-1198 + 4 * c)) < 0.01:
            x_ok += 1
        if abs(z - (1198 - 4 * r)) < 0.01:
            z_ok += 1

        w = wp[r * SIDE + c]
        if bb[1] == w:
            b1_eq_wp += 1
        else:
            b1_ne_wp += 1
        kind_wp[(kind, w != 0)] += 1
        cost_by_kind[(kind, bb[2])] += 1
        b0[bb[0]] += 1
        b3[bb[3]] += 1
        for i, pv in enumerate((p4, p5, p6, p7)):
            if pv:
                ptr_nonzero[i] += 1

n = SIDE * SIDE
print(f"cells: {n:,}\n")
print(f"  slot9 u16 == (column, row)   : {selfidx_ok:,} ok, {selfidx_bad:,} bad")
print(f"  X == -1198 + 4*column        : {x_ok:,} / {n:,}")
print(f"  Z ==  1198 - 4*row           : {z_ok:,} / {n:,}")
print(f"  byte[1] at 0x21 == WayPoints : {b1_eq_wp:,} ok, {b1_ne_wp:,} mismatched")
print()
print("  kind (0x00) vs whether the cell is on a waypoint road:")
for (k, onroad), v in sorted(kind_wp.items()):
    print(f"     kind={k}  {'on-road ' if onroad else 'off-road'}  {v:>8,}")
print()
print("  cost byte (0x22) by kind:")
for (k, cost), v in sorted(cost_by_kind.items()):
    if v > 200:
        print(f"     kind={k}  cost={cost:<4} {v:>8,}")
print()
print(f"  byte[0] at 0x20 values: {dict(b0.most_common(6))}")
print(f"  byte[3] at 0x23 values: {dict(b3.most_common(6))}")
print(f"  pointer slots non-zero counts: "
      f"{{0x10: {ptr_nonzero[0]:,}, 0x14: {ptr_nonzero[1]:,}, "
      f"0x18: {ptr_nonzero[2]:,}, 0x1c: {ptr_nonzero[3]:,}}}")
