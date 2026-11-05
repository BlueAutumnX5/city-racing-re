"""Cross-reference the 'Traffic' ini key and TrafficDensityMap.dat string in game.exe,
to find the code that decides how much traffic exists."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re
import struct

EXE = crpaths.GAME_EXE
d = open(EXE, "rb").read()
IMAGEBASE = 0x400000
SECS = [(".text", 0x1000, 0x16622b, 0x400, 0x166400),
        (".rdata", 0x168000, 0x27642, 0x166800, 0x27800),
        (".data", 0x190000, 0x216c57c, 0x18e000, 0x22a00)]


def off2va(off):
    for n, va, vs, ra, rs in SECS:
        if ra <= off < ra + rs:
            return IMAGEBASE + va + (off - ra), n
    return None, "?"


def sec(off):
    return off2va(off)[1]


def xrefs(target_off, label):
    va, s = off2va(target_off)
    print(f"\n--- '{label}' at raw 0x{target_off:06x} ({s}), VA 0x{va:08x} ---")
    pat = struct.pack("<I", va)
    found = 0
    i = 0
    while True:
        k = d.find(pat, i)
        if k < 0:
            break
        i = k + 1
        ks = sec(k)
        if ks != ".text":
            continue
        found += 1
        lo = max(0, k - 48)
        hi = min(len(d), k + 40)
        print(f"\n  referenced from raw 0x{k:06x} (VA 0x{off2va(k)[0]:08x})")
        for a in range(lo, hi, 16):
            c = d[a:a + 16]
            mark = " <<<" if a <= k < a + 16 else ""
            print(f"      {a:08x}  {c.hex(' ')}{mark}")
        # look for small immediates nearby - candidate caps / limits
        win = d[lo:hi]
        imms = []
        for m in re.finditer(rb"\x6a([\x00-\x7f])", win):      # push imm8
            imms.append(("push", m.group(1)[0]))
        for m in re.finditer(rb"\x83[\xf8-\xff]([\x00-\x7f])", win):  # cmp r32, imm8
            imms.append(("cmp", m.group(1)[0]))
        if imms:
            print(f"      nearby immediates: {imms}")
        if found >= 6:
            print("      ... more suppressed")
            break
    if not found:
        print("  no direct .text reference found (may be loaded via a table)")


# locate the strings
for needle, label in ((b"Traffic\x00", "Traffic"),
                      (b"TrafficDensityMap.dat\x00", "TrafficDensityMap.dat"),
                      (b"Traffic :\x00", "Traffic :")):
    k = d.find(needle)
    if k < 0:
        print(f"string {label!r} not found")
        continue
    xrefs(k, label)
