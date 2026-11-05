r"""Nail down the form-B .msh layout by probing where each slot's vertices actually begin.

Established so far:
    u32 A[16] @0x00   kind flags
    u32 B[16] @0x40   vertex count per slot
    u32 C[16] @0x80   triangle count per slot
    bounds[nslots] @0xC0   40 bytes each: min(3f) max(3f) centre(3f) radius(1f)
    then slot data: vertices stride 32 (pos, normal, uv), indices u16

Sizes still come up short, so something sits between slots. Rather than guess, locate each
slot's vertex block by scanning for runs of unit-length normals at stride 32, then measure
the gaps.
"""

import math
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak

STRIDE_B = 32


def slots_of(p):
    w = struct.unpack_from("<48I", p, 0)
    A, B, C = w[0:16], w[16:32], w[32:48]
    return [(i, A[i], B[i], C[i]) for i in range(16) if A[i] or B[i]]


def unit_run(p, off, want, limit=48):
    """How many consecutive stride-32 vertices from `off` have unit normals."""
    n = 0
    for k in range(min(want, limit)):
        b = off + k * STRIDE_B + 12
        if b + 12 > len(p):
            break
        nx, ny, nz = struct.unpack_from("<3f", p, b)
        L = math.sqrt(nx * nx + ny * ny + nz * nz)
        if not (0.97 < L < 1.03):
            break
        n += 1
    return n


def find_vstart(p, want, search_from, search_to):
    best = (None, 0)
    for off in range(search_from, min(search_to, len(p) - 32), 4):
        r = unit_run(p, off, want)
        if r > best[1]:
            best = (off, r)
        if r >= min(want, 48):
            return off
    return None


if __name__ == "__main__":
    entries, _, payloads, _ = crpak.load_archive(assets.STOCK, "World")
    formb = [(n, p) for (n, _, _), p in zip(entries, payloads)
             if n.lower().endswith(".msh") and not assets.msh_is_simple(p)]
    print(f"form-B meshes: {len(formb)}\n")

    gaps = Counter()
    firsts = Counter()
    solved = 0
    shown = 0

    for name, p in formb:
        sl = slots_of(p)
        ns = len(sl)
        base = 192 + ns * 40
        # slot 0
        v0 = find_vstart(p, sl[0][2], 192, base + 400)
        if v0 is None:
            continue
        firsts[v0 - base] += 1
        off = v0
        ok = True
        chain = []
        for (i, a, b, c) in sl:
            vend = off + b * STRIDE_B
            iend = vend + c * 6
            chain.append((off, b, c, iend))
            if iend > len(p):
                ok = False
                break
            off = iend
            # where does the next slot's vertices start?
            if (i, a, b, c) != sl[-1]:
                nxt = sl[sl.index((i, a, b, c)) + 1]
                nv = find_vstart(p, nxt[2], iend, iend + 400)
                if nv is None:
                    ok = False
                    break
                gaps[nv - iend] += 1
                off = nv
        if ok:
            tail = len(p) - off
            if shown < 8:
                print(f"  {name}")
                print(f"     slots={ns} base(after bounds)=0x{base:x} "
                      f"slot0 verts at 0x{v0:x} (gap {v0 - base})  tail after last slot: {tail}")
                shown += 1
            solved += 1

    print(f"\nwalked {solved} / {len(formb)} form-B meshes")
    print("\ngap between one slot's index end and the next slot's vertex start:")
    for g, c in gaps.most_common(10):
        print(f"    {g:>6} bytes : {c:>5} times")
    print("\ngap between the bounds table end and slot 0's vertices:")
    for g, c in firsts.most_common(10):
        print(f"    {g:>6} bytes : {c:>5} files")
