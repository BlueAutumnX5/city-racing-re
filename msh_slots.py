r"""Decode the slot-table .msh variant, and classify which meshes use which form.

Simple form (543 files):  [u32 v][u32 t][verts x44][indices u16][40-byte footer]

Slot form (104 files): parallel u32 arrays. Observed in Data/Misc/WPCollCheckBox/Main.msh,
a collision box, with slot 0 holding 8 - exactly a box's corners. So the second array is
very likely a per-slot vertex count.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
STRIDE, FOOTER = 44, 40


def meshes():
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.lower().endswith(".msh"):
            yield n, p


def is_simple(p):
    v, t = struct.unpack_from("<II", p, 0)
    return len(p) == 8 + v * STRIDE + t * 6 + FOOTER


if __name__ == "__main__":
    simple, slot = [], []
    for n, p in meshes():
        (simple if is_simple(p) else slot).append((n, p))

    print(f"simple form : {len(simple)}")
    print(f"slot form   : {len(slot)}\n")

    def group(names):
        g = defaultdict(int)
        for n in names:
            parts = n.split("/")
            key = "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:2])
            g[key] += 1
        return sorted(g.items(), key=lambda kv: -kv[1])

    print("SIMPLE form is used by:")
    for k, c in group([n for n, _ in simple])[:12]:
        print(f"   {c:>4}  {k}")
    print("\nSLOT form is used by:")
    for k, c in group([n for n, _ in slot])[:20]:
        print(f"   {c:>4}  {k}")

    print("\n" + "=" * 78)
    print("slot-form header, first 64 dwords, for three examples")
    print("=" * 78)
    want = ("Data/Misc/WPCollCheckBox/Main.msh",
            "Data/Static/Bridges/Type-01/S055.msh",
            "Data/Vehicles/01/Main.msh")
    for name, p in slot:
        if name not in want:
            continue
        print(f"\n--- {name}   {len(p):,} bytes")
        words = struct.unpack_from("<64I", p, 0)
        for base in range(0, 64, 16):
            row = words[base:base + 16]
            nz = " ".join(f"{w:>7}" if w else "      ." for w in row)
            print(f"   [{base:>2}..{base + 15:>2}] {nz}")
        # non-zero slots paired up
        print("   non-zero pairs (A[i] at 0x00+4i, B[i] at 0x40+4i):")
        for i in range(16):
            a, b = words[i], words[16 + i]
            if a or b:
                print(f"      slot {i:>2}:  A={a:<8} B={b:<8}")
