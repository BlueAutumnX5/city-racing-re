"""Step 3: identify the remaining undecoded .dat formats."""
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak


def dats():
    for arc in crpak.ARCHIVES:
        e, _, p, _ = crpak.load_archive(assets.STOCK, arc)
        for (n, s, o), pl in zip(e, p):
            if n.lower().endswith(".dat"):
                yield arc, n, pl


groups = defaultdict(list)
for arc, n, pl in dats():
    base = os.path.basename(n)
    groups[base].append((n, pl))

print("=" * 78)
print("undecoded .dat files by basename")
print("=" * 78)
for base, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    sizes = Counter(len(p) for _, p in items)
    sz = ", ".join(f"{s:,}x{c}" for s, c in sizes.most_common(4))
    print(f"  {len(items):>4}x  {base:<30} sizes: {sz}")

print()
print("=" * 78)
print("structure probe")
print("=" * 78)
for base in ("Main.dat", "Mask.dat", "MainExtra.dat", "PoliceExtra.dat",
             "MeshShape.dat", "PlaceColor.dat", "GlobalRoute.dat"):
    items = groups.get(base)
    if not items:
        continue
    n, pl = items[0]
    s = len(pl)
    print(f"\n--- {n}   {s:,} bytes ---")
    for side in (64, 128, 256, 512, 600, 1024):
        for bpp in (1, 2, 4):
            if side * side * bpp == s:
                print(f"    fits {side}x{side} at {bpp} byte(s)/cell")
    print(f"    first 48 bytes: {pl[:48].hex(' ')}")
    if s >= 48:
        print(f"    as u32: {struct.unpack_from('<8I', pl, 0)}")
        print(f"    as f32: {tuple(round(x, 4) if -1e9 < x < 1e9 else 'big' for x in struct.unpack_from('<8f', pl, 0))}")
        print(f"    as u16: {struct.unpack_from('<12H', pl, 0)}")
    printable = sum(1 for b in pl[:2000] if 32 <= b < 127 or b in (9, 10, 13))
    print(f"    printable in first 2000 bytes: {100 * printable / min(2000, s):.0f}%")
    hist = Counter(pl)
    print(f"    distinct byte values: {len(hist)}   most common: "
          f"{[(v, c) for v, c in hist.most_common(5)]}")
    if len(items) > 1:
        sizes = sorted(len(p) for _, p in items)
        print(f"    across {len(items)} files: size min {sizes[0]:,} max {sizes[-1]:,}")
