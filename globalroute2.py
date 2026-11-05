r"""GlobalRoute.dat, pass 2 - read the integer slots as integers.

Pass 1 found slots 0-3 are floats and slots 4-11 print as 0.0000 yet are "nonzero": the
signature of small integers reinterpreted as float32 (they become denormals ~1e-45).

Confirmed so far:
    slot 1 = X world coordinate  (equals -1198 + 4*column)
    slot 2 = terrain height      (0..80, mean 11.8337 vs AltitudeMap's 0..80 mean 11.82)
    slot 3 = -1198..1198, so almost certainly Z
"""

import math
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

print("slots 4..11 read as UNSIGNED 32-BIT INTEGERS")
print(f"{'slot':>4} {'min':>10} {'max':>10} {'distinct':>9}   most common values")
for k in range(NF):
    c = Counter()
    mn, mx = 1 << 62, -1
    for r in range(0, SIDE, 3):
        row = struct.unpack_from(f"<{SIDE * NF}I", gr, r * SIDE * REC)
        for col in range(SIDE):
            v = row[col * NF + k]
            mn = min(mn, v)
            mx = max(mx, v)
            if len(c) < 5000:
                c[v] += 1
    top = ", ".join(f"{v}x{n}" for v, n in c.most_common(5))
    print(f"{k:>4} {mn:>10} {mx:>10} {len(c):>9}   {top}")

print("\n--- slot 3 versus the row index ---")
for form, fn in (("-1198 + 4*row", lambda r: -1198 + 4 * r),
                 ("1198 - 4*row", lambda r: 1198 - 4 * r)):
    ok = tot = 0
    for r in range(0, SIDE, 13):
        row = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
        for col in range(0, SIDE, 13):
            tot += 1
            if abs(row[col * NF + 3] - fn(r)) < 0.01:
                ok += 1
    print(f"   {form:<16} {ok}/{tot}")

print("\n--- slot 2 versus AltitudeMap at the same cell ---")
ok = tot = 0
worst = 0.0
for r in range(0, SIDE, 7):
    row = struct.unpack_from(f"<{SIDE * NF}f", gr, r * SIDE * REC)
    arow = struct.unpack_from(f"<{SIDE}f", alt, r * SIDE * 4)
    for col in range(SIDE):
        a, b = row[col * NF + 2], arow[col]
        tot += 1
        d = abs(a - b)
        worst = max(worst, d)
        if d < 0.01:
            ok += 1
print(f"   identical: {ok}/{tot}   worst difference {worst:.4f}")

print("\n--- the integer slots versus WayPointsMap ---")
for k in (4, 5, 6, 7, 8, 9, 10, 11):
    withwp = Counter()
    without = Counter()
    for r in range(0, SIDE, 5):
        row = struct.unpack_from(f"<{SIDE * NF}I", gr, r * SIDE * REC)
        for col in range(SIDE):
            v = row[col * NF + k]
            (withwp if wp[r * SIDE + col] else without)[v] += 1
    if len(withwp) > 1 or len(without) > 1:
        print(f"   slot {k}: on-road {dict(withwp.most_common(4))}   "
              f"off-road {dict(without.most_common(4))}")
