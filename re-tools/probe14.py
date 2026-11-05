"""Post-walk pipeline, the pathfinder, the constants - and what each function calls."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *

def fconst(va):
    return struct.unpack_from("<f", data, va2raw(va))[0]

print("=== .rdata float constants used by race setup ===")
for va, what in ((0x569a44, "scale mul"), (0x5682c4, "scale clamp"), (0x569a40, "scale->dist"),
                 (0x568ba8, "dist add"), (0x56953c, "arg to 42db00"),
                 (0x569a3c, "max dist?"), (0x5682e8, "min dist?"), (0x568ec4, "radius")):
    print(f"  0x{va:08x}  {fconst(va):12.4f}   {what}")
r = va2raw(0x12d0df0)
print(f"  .data 0x012d0df0 initial = {struct.unpack_from('<f', data, r)[0] if r and r < len(data) else '(bss, set at runtime)'}")

def calls_in(start, maxn=900):
    out, n = [], 0
    for ins in md.disasm(data[va2raw(start):va2raw(start) + maxn * 8], start):
        if ins.mnemonic == "call":
            out.append((ins.address, ins.op_str))
        n += 1
        if ins.mnemonic in ("ret",) and n > 5:
            break
        if n >= maxn:
            break
    return out, ins.address

for nm, va in (("walker 0x432b40", 0x432b40), ("pathfinder 0x42d260", 0x42d260),
               ("nearest 0x42c5d0", 0x42c5d0)):
    c, end = calls_in(va)
    print(f"\n=== calls made by {nm} (scanned to 0x{end:08x}) ===")
    for a, t in c:
        print(f"   0x{a:08x}  call {t}")

print("\n=== walker post-processing tail 0x00432da5 .. return ===")
print(dis(0x00432da5, 70))
print("\n=== pathfinder head 0x0042d260 ===")
print(dis(0x0042d260, 60))
