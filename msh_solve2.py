r"""Brute-force the slot-form .msh layout with two unknowns.

Solved stride came out at ~32 with a small excess that grows with slot count, so each slot
almost certainly carries its own header (bounds block, material id, etc).

Model:   size == 192 + G + nslots*H + sumB*S + sumC*I
    G = global block after the 192-byte header (0 or 40)
    H = per-slot header size
    S = vertex stride
    I = bytes per triangle (3 x u16 = 6, or 3 x u32 = 12)

Search the small space and report which combination explains the most files.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA


def meshes():
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.lower().endswith(".msh"):
            yield n, p


def is_simple(p):
    v, t = struct.unpack_from("<II", p, 0)
    return len(p) == 8 + v * 44 + t * 6 + 40


if __name__ == "__main__":
    files = []
    for n, p in meshes():
        if is_simple(p):
            continue
        w = struct.unpack_from("<48I", p, 0)
        A, B, C = w[0:16], w[16:32], w[32:48]
        ns = sum(1 for a in A if a)
        if ns == 0 or sum(B) == 0:
            continue
        files.append((n, len(p), ns, sum(B), sum(C), A))
    print(f"slot-form files with usable counts: {len(files)}\n")

    best = []
    for G in (0, 40):
        for I in (6, 12):
            for S in range(24, 56, 2):
                for H in range(0, 200, 4):
                    hit = 0
                    for n, size, ns, sb, sc, A in files:
                        if size == 192 + G + ns * H + sb * S + sc * I:
                            hit += 1
                    if hit:
                        best.append((hit, G, H, S, I))
    best.sort(reverse=True)
    print("best-fitting models (hits, G, per-slot H, stride S, per-tri I):")
    for hit, G, H, S, I in best[:12]:
        print(f"   {hit:>4} files   G={G:<3} H={H:<4} S={S:<3} I={I}")

    if best:
        hit, G, H, S, I = best[0]
        print(f"\nresiduals under the best model (G={G} H={H} S={S} I={I}):")
        res = Counter()
        for n, size, ns, sb, sc, A in files:
            r = size - (192 + G + ns * H + sb * S + sc * I)
            res[r] += 1
        for r, c in res.most_common(12):
            print(f"    {r:>+10} : {c:>4} files")
