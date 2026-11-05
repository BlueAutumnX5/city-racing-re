r"""GlobalRoute.dat, pass 3 - byte-level look at individual records.

Known:
    slot 0  u32 0..4          small enum/count
    slot 1  float             X = -1198 + 4*column
    slot 2  float 0..80       height - close to AltitudeMap but not identical
    slot 3  float             Z = 1198 - 4*row
    slots 4-9 integer-ish, 10-11 always zero

Dump real records and try every plausible reading, rather than guessing further.
"""

import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak

SIDE, REC, NF = 600, 48, 12


def load(name):
    e, _, p, _ = crpak.load_archive(assets.STOCK, "World")
    for (n, _, _), pl in zip(e, p):
        if n.endswith(name):
            return pl


gr = load("Landscape/GlobalRoute.dat")
wp = load("Landscape/WayPointsMap.dat")
alt = load("Landscape/AltitudeMap.dat")


def rec(r, c):
    return gr[(r * SIDE + c) * REC:(r * SIDE + c) * REC + REC]


def show(r, c, tag):
    d = rec(r, c)
    f = struct.unpack("<12f", d)
    u = struct.unpack("<12I", d)
    h16 = struct.unpack("<24H", d)
    a = struct.unpack_from("<f", alt, (r * SIDE + c) * 4)[0]
    print(f"\n--- cell ({r},{c})  {tag}   WayPoints={wp[r * SIDE + c]}  Altitude={a:.3f}")
    for k in range(NF):
        fv = f"{f[k]:.5g}" if (f[k] == f[k] and abs(f[k]) > 1e-30) else "~0"
        print(f"   slot{k:>2}  {d[k*4:k*4+4].hex(' ')}   u32={u[k]:<12} "
              f"f32={fv:<14} u16=({h16[k*2]},{h16[k*2+1]})")


# a handful of on-road and off-road cells
on = off = 0
for r in range(200, 400):
    for c in range(200, 400):
        v = wp[r * SIDE + c]
        if v and on < 3:
            show(r, c, "ON ROAD")
            on += 1
        elif not v and off < 2:
            show(r, c, "off road")
            off += 1
    if on >= 3 and off >= 2:
        break

print("\n" + "=" * 78)
print("slot 2 (height) vs AltitudeMap - is the difference bridges?")
print("=" * 78)
diffs = Counter()
big = []
for r in range(0, SIDE, 3):
    arow = struct.unpack_from(f"<{SIDE}f", alt, r * SIDE * 4)
    grow = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
    for c in range(SIDE):
        d = grow[c * NF + 2] - arow[c]
        diffs[round(d)] += 1
        if d > 5 and len(big) < 8:
            big.append((r, c, grow[c * NF + 2], arow[c], wp[r * SIDE + c]))
print("  rounded (route height - terrain height):")
for k, v in sorted(diffs.items())[:14]:
    print(f"     {k:>+5} : {v:>7,}")
print("  cells where the route sits well above the terrain (bridges?):")
for r, c, h, a, w in big:
    print(f"     ({r:>3},{c:>3})  route {h:>7.2f}  terrain {a:>7.2f}  "
          f"diff {h - a:>6.2f}  waypoint={w}")

print("\n" + "=" * 78)
print("slot 0 (0..4) vs WayPointsMap")
print("=" * 78)
tab = Counter()
for r in range(0, SIDE, 3):
    grow = struct.unpack_from(f"<{SIDE * NF}I", gr, r * SIDE * REC)
    for c in range(SIDE):
        tab[(grow[c * NF], wp[r * SIDE + c] != 0)] += 1
for (v, onroad), n in sorted(tab.items()):
    print(f"   slot0={v}  {'on-road ' if onroad else 'off-road'}  {n:>8,}")
