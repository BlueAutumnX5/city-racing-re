r"""Decode Data/Landscape/GlobalRoute.dat.

17,280,000 bytes = 600 x 600 x 48, i.e. 12 floats per world cell on the same 600x600 grid
as AltitudeMap / WayPointsMap / StaticObjectsPlaceMap.

First two records:
    (0.0, -1198.0, 0.6275, 1198.0, 0,0,0,0,0,0,0,0)
    (0.0, -1194.0, 0.4706, 1198.0, 0,0,0,0,0,0,0,0)
field[1] steps by 4 per cell, matching a ~2396-unit world over 600 cells.

Work out what each of the 12 slots is by measuring, not guessing:
  - does it correlate with the cell's x or z index?
  - is it an integer in disguise?
  - do any triples form unit vectors (a direction)?
  - which cells are empty, and does that match WayPointsMap?
"""

import math
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak

SIDE = 600
REC = 48
NF = 12


def load(name):
    e, _, p, _ = crpak.load_archive(assets.STOCK, "World")
    for (n, _, _), pl in zip(e, p):
        if n.endswith(name):
            return pl
    return None


if __name__ == "__main__":
    gr = load("Landscape/GlobalRoute.dat")
    wp = load("Landscape/WayPointsMap.dat")
    alt = load("Landscape/AltitudeMap.dat")
    print(f"GlobalRoute.dat {len(gr):,} bytes = {SIDE}x{SIDE} x {REC}"
          f"  ({'exact' if len(gr) == SIDE * SIDE * REC else 'MISMATCH'})\n")

    # per-slot statistics
    mins = [float("inf")] * NF
    maxs = [float("-inf")] * NF
    sums = [0.0] * NF
    nonzero = [0] * NF
    intlike = [0] * NF
    nan = [0] * NF
    distinct = [Counter() for _ in range(NF)]
    empty_cells = 0
    n = SIDE * SIDE

    for r in range(SIDE):
        base = r * SIDE * REC
        row = struct.unpack_from(f"<{SIDE * NF}f", gr, base)
        for c in range(SIDE):
            v = row[c * NF:(c + 1) * NF]
            if not any(v):
                empty_cells += 1
            for k in range(NF):
                x = v[k]
                if x != x:
                    nan[k] += 1
                    continue
                mins[k] = min(mins[k], x)
                maxs[k] = max(maxs[k], x)
                sums[k] += x
                if x:
                    nonzero[k] += 1
                if abs(x - round(x)) < 1e-6:
                    intlike[k] += 1
                if len(distinct[k]) < 3000:
                    distinct[k][round(x, 3)] += 1

    print(f"{'slot':>4} {'min':>12} {'max':>12} {'mean':>12} "
          f"{'nonzero%':>9} {'int-like%':>10} {'distinct':>9}")
    for k in range(NF):
        print(f"{k:>4} {mins[k]:>12.4f} {maxs[k]:>12.4f} {sums[k] / n:>12.4f} "
              f"{100 * nonzero[k] / n:>8.1f}% {100 * intlike[k] / n:>9.1f}% "
              f"{len(distinct[k]):>9}")
    print(f"\nall-zero cells: {empty_cells:,} of {n:,} ({100 * empty_cells / n:.1f}%)")

    # does any slot track the cell's grid position?
    print("\n--- does a slot equal -1198 + 4*index ? ---")
    for k in range(NF):
        okc = okr = 0
        for r in range(0, SIDE, 37):
            row = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
            for c in range(0, SIDE, 37):
                v = row[c * NF + k]
                if abs(v - (-1198 + 4 * c)) < 0.01:
                    okc += 1
                if abs(v - (-1198 + 4 * r)) < 0.01:
                    okr += 1
        tot = len(range(0, SIDE, 37)) ** 2
        if okc or okr:
            print(f"  slot {k}: matches column index {okc}/{tot}, row index {okr}/{tot}")

    # unit-vector hunt across float triples
    print("\n--- do any consecutive triples form unit vectors? ---")
    for k in range(NF - 2):
        unit = tested = 0
        for r in range(0, SIDE, 17):
            row = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
            for c in range(0, SIDE, 17):
                v = row[c * NF:(c + 1) * NF]
                if not any(v):
                    continue
                L = math.sqrt(v[k] ** 2 + v[k + 1] ** 2 + v[k + 2] ** 2)
                tested += 1
                if 0.98 < L < 1.02:
                    unit += 1
        if tested and unit / tested > 0.2:
            print(f"  slots {k},{k+1},{k+2}: unit length in {100 * unit / tested:.0f}%"
                  f" of {tested} non-empty cells")

    # correlate emptiness with WayPointsMap
    print("\n--- non-empty GlobalRoute cells vs WayPointsMap ---")
    both = only_gr = only_wp = neither = 0
    for r in range(SIDE):
        row = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
        for c in range(SIDE):
            g = any(row[c * NF:(c + 1) * NF])
            w = wp[r * SIDE + c] != 0
            if g and w:
                both += 1
            elif g:
                only_gr += 1
            elif w:
                only_wp += 1
            else:
                neither += 1
    print(f"  route+waypoint {both:>8,}   route only {only_gr:>8,}")
    print(f"  waypoint only  {only_wp:>8,}   neither    {neither:>8,}")
