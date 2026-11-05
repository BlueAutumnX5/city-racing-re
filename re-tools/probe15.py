"""Who writes this+0x100/0x108/0x110 (0x012d0de0/de8/df0)?  And is P really 2048 entries?"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *

for g in (0x012d0de0, 0x012d0de8, 0x012d0df0):
    print(f"\n=== references to 0x{g:08x} (this+0x{g-0x012d0ce0:x}) ===")
    for h in xrefs(g):
        for ins in md.disasm(data[va2raw(h):va2raw(h) + 12], h):
            print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}")
            break

# stores via [reg+0x110]/[reg+0x100]/[reg+0x108] inside the map-object code 0x429000-0x433000
print("\n=== stores to [reg+0x100/0x108/0x110] in map code ===")
for ins in md.disasm(data[va2raw(0x00429000):va2raw(0x00433000)], 0x00429000):
    if ins.mnemonic.startswith(("mov", "fst", "movss")) and any(
            f"+ 0x{o:x}]" in ins.op_str for o in (0x100, 0x108, 0x110)) and \
            ins.op_str.split(",")[0].strip().startswith(("dword ptr [", "qword ptr [")):
        print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}")
