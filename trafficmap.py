"""Visualise TrafficDensityMap.dat so we know what the byte values mean before scaling them."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
SIDE = 200


def load(name):
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.endswith(name):
            return n, p
    return None, None


name, data = load("TrafficDensityMap.dat")
print(f"{name}  {len(data):,} bytes  ({SIDE}x{SIDE})\n")

# where do the 0xFF cells sit? border, scattered, or clustered?
ff_rows = collections.Counter()
ff_cols = collections.Counter()
for i, b in enumerate(data):
    if b == 0xFF:
        ff_rows[i // SIDE] += 1
        ff_cols[i % SIDE] += 1
print("0xFF distribution:")
print(f"  rows containing any 0xFF : {len(ff_rows)} of {SIDE}")
print(f"  cols containing any 0xFF : {len(ff_cols)} of {SIDE}")
edge = sum(n for r, n in ff_rows.items() if r < 3 or r > SIDE - 4)
print(f"  0xFF cells in the outer 3 rows: {edge} of {sum(ff_rows.values())}")
print()

# coarse ASCII map, 200 -> 66 columns, showing the max value in each block
STEP = 3
RAMP = " .:-=+*#%@"
print(f"density map, each char = {STEP}x{STEP} cells, showing the MAX in that block")
print("legend: ' '=0  '.'~low  '@'~high   'X' = 0xFF present\n")
for by in range(0, SIDE, STEP):
    row = []
    for bx in range(0, SIDE, STEP):
        vals = [data[(by + dy) * SIDE + (bx + dx)]
                for dy in range(STEP) if by + dy < SIDE
                for dx in range(STEP) if bx + dx < SIDE]
        if 0xFF in vals:
            row.append("X")
            continue
        mx = max(vals)
        row.append(RAMP[min(len(RAMP) - 1, mx * len(RAMP) // 32)])
    print("  " + "".join(row))

print()
nz = [b for b in data if b not in (0, 0xFF)]
print(f"cells: total {len(data):,}   zero {data.count(0):,}   "
      f"0xFF {data.count(0xFF):,}   other {len(nz):,}")
if nz:
    print(f"non-zero non-FF values: min={min(nz)} max={max(nz)} "
          f"mean={sum(nz) / len(nz):.2f}")
    h = collections.Counter(nz)
    print("  full distribution of the 'other' values:")
    for v in sorted(h):
        if h[v] > 30:
            print(f"      {v:>3} : {h[v]:>7,}")
