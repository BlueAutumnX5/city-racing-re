r"""Test the multi-part .msh hypothesis.

543/647 meshes are a single part:  [u32 v][u32 t][verts][indices][40-byte footer]

The other 104 have tiny leading numbers against huge files (v=1 t=0, v=90 t=0), so those
two dwords are almost certainly PART COUNTS, with each part carrying its own
[v][t][verts][indices][footer]. Walk the file and see whether the parts tile it exactly.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
STRIDE, FOOTER = 44, 40


def meshes():
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.lower().endswith(".msh"):
            yield n, p


def walk_parts(p, start, maxparts=4000):
    """Read consecutive [v][t][verts][indices][footer] blocks from `start`."""
    off = start
    parts = []
    while off + 8 <= len(p) and len(parts) < maxparts:
        v, t = struct.unpack_from("<II", p, off)
        if not (0 < v < 400000 and 0 <= t < 400000):
            break
        size = 8 + v * STRIDE + t * 6 + FOOTER
        if off + size > len(p):
            break
        parts.append((off, v, t, size))
        off += size
    return parts, off


if __name__ == "__main__":
    singles = multis = unknown = 0
    examples = []
    for name, p in meshes():
        v, t = struct.unpack_from("<II", p, 0)
        if len(p) == 8 + v * STRIDE + t * 6 + FOOTER:
            singles += 1
            continue
        # try: the file is a sequence of parts starting at offset 8
        parts, end = walk_parts(p, 8)
        if parts and end == len(p):
            multis += 1
            if len(examples) < 10:
                tv = sum(x[1] for x in parts)
                tt = sum(x[2] for x in parts)
                examples.append((name, len(p), v, t, len(parts), tv, tt, "EXACT"))
        else:
            unknown += 1
            if len(examples) < 10:
                examples.append((name, len(p), v, t, len(parts), 0, 0,
                                 f"stopped at {end} of {len(p)}"))

    total = singles + multis + unknown
    print(f"total .msh                  : {total}")
    print(f"  single part               : {singles}")
    print(f"  multi-part, tiles exactly : {multis}")
    print(f"  still unexplained         : {unknown}")
    print(f"  => solved {100 * (singles + multis) / total:.1f}%")
    print()
    for name, size, v, t, np_, tv, tt, note in examples:
        print(f"  {size:>10,}  hdr=({v},{t})  parts={np_:<5} "
              f"verts={tv:<8} tris={tt:<8} {note}")
        print(f"              {name}")
