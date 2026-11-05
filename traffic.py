"""Locate how City Racing decides how many traffic cars exist."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
EXE = crpaths.GAME_EXE

print("=" * 78)
print("1. traffic-related entries in the archives")
print("=" * 78)
for arc in ("World", "Objects", "Textures"):
    entries, _, payloads, _ = crpak.load_archive(STOCK, arc)
    for (name, size, off), payload in zip(entries, payloads):
        if re.search(r"(?i)traffic|waypoint|route|density", name):
            print(f"  {arc:<9} {size:>10,}  {name}")

print()
print("=" * 78)
print("2. TrafficDensityMap.dat contents")
print("=" * 78)
entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
for (name, size, off), payload in zip(entries, payloads):
    if "TrafficDensityMap" not in name:
        continue
    print(f"  {name}  ({size:,} bytes)")
    side = int(size ** 0.5)
    print(f"  square side if 1 byte/cell: {side} x {side} = {side * side:,}"
          f"  {'EXACT' if side * side == size else 'not exact'}")
    hist = collections.Counter(payload)
    print(f"  distinct byte values: {len(hist)}")
    print("  most common values:")
    for v, n in hist.most_common(12):
        print(f"      0x{v:02x} ({v:>3})  {n:>10,}  {100 * n / size:5.2f}%")
    print(f"  min={min(hist)}  max={max(hist)}")
    print(f"  first 48 bytes: {payload[:48].hex(' ')}")

print()
print("=" * 78)
print("3. 'Traffic' and related strings in game.exe")
print("=" * 78)
d = open(EXE, "rb").read()
SECS = [(".text", 0x400, 0x166400), (".rdata", 0x166800, 0x27800),
        (".data", 0x18e000, 0x22a00)]


def sec(o):
    for n, ra, rs in SECS:
        if ra <= o < ra + rs:
            return n
    return "?"


for pat in (rb"Traffic[\x20-\x7E]{0,30}", rb"[\x20-\x7E]{0,20}Cars?[\x20-\x7E]{0,20}",
            rb"MaxTraffic[\x20-\x7E]{0,20}", rb"[\x20-\x7E]*Density[\x20-\x7E]*"):
    seen = set()
    for m in re.finditer(pat, d):
        s = m.group(0)
        if len(s) < 5 or s in seen:
            continue
        seen.add(s)
        if re.search(rb"(?i)traffic|density", s):
            print(f"  raw 0x{m.start():06x} ({sec(m.start())})  {s[:60]!r}")

print()
print("=" * 78)
print("4. small integer constants that could be a vehicle-array cap")
print("=" * 78)
print("  looking for 'push N' / 'cmp ..., N' style immediates near plausible caps")
for n in (8, 10, 12, 16, 20, 24, 25, 32, 48, 64, 100, 128, 256):
    pat = struct.pack("<I", n)
    cnt = d.count(pat)
    print(f"    {n:>4} as dword : {cnt:>5} occurrences")
