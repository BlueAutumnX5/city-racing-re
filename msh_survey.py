r"""Survey the .msh mesh format across all 647 files, looking for the header structure.

Strategy: a binary format's header is usually a run of counts and offsets. If a value equals
(filesize - headersize) / k for some sensible stride k, it is probably a vertex or index
count. Comparing MANY files makes the constant fields obvious - they are the ones that never
change - and makes the size-correlated fields obvious too.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA


def meshes():
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, s, o), p in zip(entries, payloads):
        if n.lower().endswith(".msh"):
            yield n, p


if __name__ == "__main__":
    all_m = list(meshes())
    print(f"{len(all_m)} .msh files\n")

    sizes = sorted((len(p), n) for n, p in all_m)
    print("smallest 10:")
    for s, n in sizes[:10]:
        print(f"   {s:>10,}  {n}")
    print("largest 5:")
    for s, n in sizes[-5:]:
        print(f"   {s:>10,}  {n}")

    # --- which of the first 32 dwords are constant across all files? ---
    print("\n" + "=" * 78)
    print("first 32 dwords: how much do they vary across all 647 files?")
    print("=" * 78)
    cols = defaultdict(Counter)
    for n, p in all_m:
        if len(p) < 160:
            continue
        for i in range(32):
            cols[i][struct.unpack_from("<I", p, i * 4)[0]] += 1
    print(f"  {'idx':>3} {'off':>5} {'distinct':>9}  most common values")
    for i in range(32):
        c = cols[i]
        top = ", ".join(f"{v}x{n}" for v, n in c.most_common(4))
        flag = "  <- CONSTANT" if len(c) == 1 else ""
        print(f"  {i:>3} {i * 4:>5} {len(c):>9}  {top}{flag}")

    # --- does any early dword correlate with file size? ---
    print("\n" + "=" * 78)
    print("dwords that look like counts: value * stride + header == filesize ?")
    print("=" * 78)
    hits = Counter()
    for n, p in all_m:
        if len(p) < 160:
            continue
        for i in range(32):
            v = struct.unpack_from("<I", p, i * 4)[0]
            if not (0 < v < 2_000_000):
                continue
            for stride in (4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64):
                for hdr in range(0, 260, 4):
                    if v * stride + hdr == len(p):
                        hits[(i, stride, hdr)] += 1
    print("  strongest (dword index, stride, header size) -> how many files fit exactly:")
    for (i, stride, hdr), n in hits.most_common(20):
        print(f"     dword[{i:>2}] @0x{i * 4:02x}  stride {stride:>3}  header {hdr:>3}"
              f"   fits {n:>4} / {len(all_m)} files")

    # --- structural look at the smallest file ---
    print("\n" + "=" * 78)
    small_name = sizes[0][1]
    small = dict(all_m)[small_name]
    print(f"smallest file: {small_name}  ({len(small):,} bytes)")
    print("=" * 78)
    print("  first 128 bytes as dwords / floats:")
    for i in range(0, 128, 16):
        ints = struct.unpack_from("<4I", small, i)
        flts = struct.unpack_from("<4f", small, i)
        hexs = small[i:i + 16].hex(' ')
        fs = "  ".join(f"{f:>12.4g}" if 1e-6 < abs(f) < 1e9 else f"{'-':>12}"
                       for f in flts)
        print(f"    {i:04x}  {hexs}")
        print(f"          u32 {ints}")
        print(f"          f32 {fs}")
