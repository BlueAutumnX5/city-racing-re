"""Examine the 1024/768 proximity hits in .rdata and .data that were never inspected,
plus hunt for a hardcoded virtual resolution as ints or floats."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct

PATH = crpaths.GAME_EXE
d = open(PATH, "rb").read()

SECS = [('.text', 0x1000, 0x16622b, 0x400, 0x166400),
        ('.rdata', 0x168000, 0x27642, 0x166800, 0x27800),
        ('.data', 0x190000, 0x216c57c, 0x18e000, 0x22a00)]
IMAGEBASE = 0x400000


def sec_of(off):
    for n, va, vs, ra, rs in SECS:
        if ra <= off < ra + rs:
            return n, IMAGEBASE + va + (off - ra)
    return "?", 0


def dump(off, before=32, after=48):
    lo = max(0, off - before)
    hi = min(len(d), off + after)
    for i in range(lo, hi, 16):
        c = d[i:i + 16]
        mark = " <<<" if i <= off < i + 16 else ""
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in c)
        print(f"    {i:08x}  {c.hex(' '):<47}  {asc}{mark}")


HITS = [0x17add0, 0x17aef0, 0x17b1d0, 0x17b2b0, 0x17b3b0, 0x17b470, 0x17b570,
        0x1a0a90, 0x1a1e0c, 0x1a8a0c]

print("=== previously unexamined 1024/768 proximity hits ===")
for off in HITS:
    sec, va = sec_of(off)
    print(f"\n-- raw 0x{off:06x}  ({sec}, VA 0x{va:08x}) --")
    dump(off)
    ints = struct.unpack_from("<8I", d, off)
    flts = struct.unpack_from("<8f", d, off)
    print(f"    as u32  : {ints}")
    print(f"    as float: {tuple(round(f, 4) for f in flts)}")

print("\n\n=== floats 1024.0 / 768.0 / 640.0 / 480.0 / 800.0 / 600.0 anywhere ===")
for v in (1024.0, 768.0, 640.0, 480.0, 800.0, 600.0):
    pat = struct.pack("<f", v)
    offs = []
    i = 0
    while True:
        k = d.find(pat, i)
        if k < 0:
            break
        offs.append(k)
        i = k + 1
    print(f"  {v:>7}  {pat.hex(' '):<12} count={len(offs):>3}  "
          f"{[f'{o:06x}({sec_of(o)[0]})' for o in offs[:10]]}")

print("\n=== reciprocals / half-dims that a virtual-res projection would use ===")
for label, v in (("1/1024", 1 / 1024), ("1/768", 1 / 768), ("512.0", 512.0),
                 ("384.0", 384.0), ("0.75 (768/1024)", 0.75),
                 ("1.3333334 (1024/768)", 4 / 3)):
    pat = struct.pack("<f", v)
    offs = []
    i = 0
    while True:
        k = d.find(pat, i)
        if k < 0:
            break
        offs.append(k)
        i = k + 1
    print(f"  {label:<22} {pat.hex(' '):<12} count={len(offs):>3}  "
          f"{[f'{o:06x}({sec_of(o)[0]})' for o in offs[:10]]}")
