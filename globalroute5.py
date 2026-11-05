r"""GlobalRoute.dat - characterise the two fields that matter for traffic behaviour.

1. The X/Z floats match the cell centre in 96.4% of cells. Where they DIVERGE, what are
   they? If they are a snapped position on the nearest road, that is the steering target
   traffic aims at.
2. The cost byte at 0x22 is exactly 100 off-road and spreads 0..99 on-road. Is it a smooth
   spatial gradient (a distance/cost field) or scattered (a segment id)?
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


def cell(r, c):
    o = (r * SIDE + c) * REC
    kind, = struct.unpack_from("<I", gr, o)
    x, h, z = struct.unpack_from("<3f", gr, o + 4)
    bb = gr[o + 32:o + 36]
    return kind, x, h, z, bb


print("=" * 78)
print("1. where X/Z diverge from the cell centre")
print("=" * 78)
div_kind = Counter()
div_wp = Counter()
offsets = Counter()
samples = []
for r in range(SIDE):
    for c in range(SIDE):
        kind, x, h, z, bb = cell(r, c)
        dx = x - (-1198 + 4 * c)
        dz = z - (1198 - 4 * r)
        if abs(dx) > 0.01 or abs(dz) > 0.01:
            div_kind[kind] += 1
            div_wp[wp[r * SIDE + c] != 0] += 1
            offsets[(round(dx / 4), round(dz / 4))] += 1
            if len(samples) < 6:
                samples.append((r, c, dx, dz, kind, bb[1], bb[2]))
print(f"  diverging cells: {sum(div_kind.values()):,}")
print(f"  by kind      : {dict(sorted(div_kind.items()))}")
print(f"  on-road?     : {dict(div_wp)}")
print("  offset from own centre, in CELLS (dx/4, dz/4):")
for k, v in offsets.most_common(10):
    print(f"     {k} : {v:,}")
print("  samples:")
for r, c, dx, dz, kind, w, cost in samples:
    print(f"     ({r:>3},{c:>3}) dx={dx:>8.1f} dz={dz:>8.1f} "
          f"= ({dx/4:>5.1f},{dz/4:>5.1f}) cells   kind={kind} wp={w} cost={cost}")

print()
print("=" * 78)
print("2. the cost byte at 0x22 - gradient or scattered?")
print("=" * 78)
# neighbour difference: a smooth field has mostly small differences
diffs = Counter()
for r in range(1, SIDE - 1, 2):
    for c in range(1, SIDE - 1, 2):
        k0, _, _, _, b0 = cell(r, c)
        if k0 == 0:
            continue
        k1, _, _, _, b1 = cell(r, c + 1)
        if k1 == 0:
            continue
        diffs[abs(b0[2] - b1[2])] += 1
tot = sum(diffs.values())
print(f"  |cost(c) - cost(c+1)| for adjacent on-road cells ({tot:,} pairs):")
for d in sorted(diffs)[:10]:
    print(f"     diff {d:>3} : {diffs[d]:>8,}  ({100*diffs[d]/tot:5.1f}%)")
big = sum(v for d, v in diffs.items() if d > 5)
print(f"     diff > 5 : {big:>8,}  ({100*big/tot:5.1f}%)")

print()
print("  cost value range on-road:")
cc = Counter()
for r in range(0, SIDE, 2):
    for c in range(0, SIDE, 2):
        k, _, _, _, bb = cell(r, c)
        if k:
            cc[bb[2]] += 1
ks = sorted(cc)
print(f"     min {ks[0]}  max {ks[-1]}  distinct {len(ks)}")
print(f"     highest few: {[(v, cc[v]) for v in ks[-6:]]}")
