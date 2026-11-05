r"""Solve the slot-form .msh layout by algebra instead of guesswork.

Header is three parallel u32[16] arrays at 0x00, 0x40, 0x80 (192 bytes):
    A[i] = kind/LOD flag (1 or 2)
    B[i] = vertex count for slot i
    C[i] = triangle count for slot i

Then a 40-byte bounds block: min(3f) max(3f) centre(3f) radius(1f) - confirmed exactly on
Data/Misc/WPCollCheckBox/Main.msh, a 1.5x100x1.5 box with radius 50.047.

If the file is  192 + 40 + sum(B)*S + sum(C)*6, then
    S = (filesize - 232 - sum(C)*6) / sum(B)
Compute S for every slot-form file. A consistent integer means the layout is solved; a
scatter means slots differ in stride (e.g. render slots vs collision slots).
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
    slotfiles = [(n, p) for n, p in meshes() if not is_simple(p)]
    print(f"slot-form files: {len(slotfiles)}\n")

    strides = Counter()
    rows = []
    for n, p in slotfiles:
        w = struct.unpack_from("<48I", p, 0)
        A, B, C = w[0:16], w[16:32], w[32:48]
        sb, sc = sum(B), sum(C)
        if sb == 0:
            continue
        for hdr in (232,):
            num = len(p) - hdr - sc * 6
            s = num / sb
            rows.append((n, len(p), sb, sc, s, A))
            if abs(s - round(s)) < 1e-9:
                strides[round(s)] += 1

    print("solved stride S = (size - 232 - sumC*6) / sumB :")
    ok = 0
    for s, cnt in strides.most_common(10):
        print(f"    S = {s:<6} exact for {cnt:>4} files")
        ok += cnt
    print(f"  exact-integer solutions: {ok} / {len(slotfiles)}\n")

    print("sample (first 14):")
    print(f"  {'size':>9} {'sumB':>7} {'sumC':>7} {'S':>9}  A-flags        file")
    for n, size, sb, sc, s, A in rows[:14]:
        af = ",".join(str(a) for a in A if a)
        print(f"  {size:>9,} {sb:>7} {sc:>7} {s:>9.3f}  {af:<14} {n}")

    # split by whether the file uses only A==1 slots, or mixes 1 and 2
    print("\nsplit by A-flag pattern:")
    groups = Counter()
    for n, size, sb, sc, s, A in rows:
        kinds = tuple(sorted({a for a in A if a}))
        groups[kinds] += 1
    for k, v in groups.most_common():
        print(f"    A flags {k} : {v} files")
