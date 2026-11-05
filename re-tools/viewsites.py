"""For every instruction the view patch repoints, locate the 4-byte constant address inside
it in the BASELINE exe, and print the exact (va, old, new) for racemod. Also verifies each
in-place constant's reader count so nothing shared is edited in place."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import xmap
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

REPOINT = [   # (instruction va, old constant va, what)
    (0x00432fbc, 0x00568588, "chunk clamp 500"),
    (0x00411e58, 0x00568edc, "vehicle draw cap 400 #1"),
    (0x004140f6, 0x00568edc, "vehicle draw cap 400 #2"),
    (0x00417c71, 0x00568edc, "vehicle draw cap 400 #3"),
    (0x004152c2, 0x005682e8, "vehicle detail cap 100 #1"),
    (0x0041572e, 0x005682e8, "vehicle detail cap 100 #2"),
    (0x0043fc8c, 0x00568ec4, "traffic despawn 60"),
    (0x0043fce0, 0x00568ec4, "police despawn 60"),
    (0x0043fcf5, 0x00569830, "police pursuit despawn 90"),
    (0x00442ce4, 0x00568ec4, "spawn anchor base 60"),
    (0x0042f1f7, 0x00568eb4, "chunk collision 20 (add)"),
    (0x0042f236, 0x00568eb4, "chunk collision 20 (remove)"),
    (0x0044e773, 0x00568eb4, "tree physics 20 (add)"),
    (0x0044e7ad, 0x00568eb4, "tree physics 20 (remove)"),
    (0x0044ec13, 0x00568eb4, "list-2 physics 20 (add)"),
    (0x0044ec4d, 0x00568eb4, "list-2 physics 20 (remove)"),
]
print("REPOINT sites:")
for iva, old, what in REPOINT:
    r = racemod.va2raw(buf, iva)
    ins = next(md.disasm(buf[r:r + 16], iva))
    ob = struct.pack("<I", old)
    k = ins.bytes.find(ob)
    assert k >= 0, f"{what}: constant not inside {ins.mnemonic} {ins.op_str}"
    print(f"  0x{iva:08x}  {ins.mnemonic} {ins.op_str:<36} disp at 0x{iva + k:08x}   {what}")

INPLACE = [(0x00569838, 39.0, "traffic fade start"), (0x00569834, 1 / 21, "traffic fade 1/span"),
           (0x00569a58, 48.0, "spawn ring"), (0x00569a54, 54.0, "police spawn ring")]
print("\nIN-PLACE constants (must be private):")
for va, val, what in INPLACE:
    r = racemod.va2raw(buf, va)
    cur = struct.unpack_from("<f", buf, r)[0]
    readers = sorted({fn(a) for a in m["refs"].get(va, [])})
    print(f"  0x{va:08x} = {cur:g} (expect {val:g})  readers in {len(readers)} function(s): "
          f"{[hex(x) for x in readers]}   {what}")

print("\nOther single-site patches:")
for va, n, what in ((0x00442dab, 4, "traffic count disp (lea edx*4+3)"),
                    (0x004253af, 4, "broadphase maxHandles imm (push 0x400)"),
                    (0x00402655, 6, "overlay gate je"),
                    (0x004508c2, 5, "grass MessageBox call"),
                    (0x0045093b, 5, "tree MessageBox call"),
                    (0x00590414, 4, "master distance 600.0"),
                    (0x0059041c, 4, "Distance cap 600")):
    r = racemod.va2raw(buf, va)
    print(f"  0x{va:08x}  {buf[r:r + n].hex():<14} {what}")
print("\n.text slack after leap code 0x567322..0x567400:",
      "all zero" if buf[racemod.va2raw(buf, 0x567322):racemod.va2raw(buf, 0x567400)] == bytes(0x567400 - 0x567322) else "NOT ZERO")
