import sys, struct, re
sys.path.insert(0, ".")
from crdis import *
import rtti
md.detail = False
WANT = (0x440a4, 0x440a8, 0x440ac, 0x440b0, 0x440b4, 0x440b8, 0x440bc, 0x44064)
hits = {}
off = TSTART
while off < TEND:
    last = None
    for ins in md.disasm(data[off:min(TEND, off + 0x4000)], raw2va(off)):
        mm = re.search(r"\+ (0x440[0-9a-f]{2})\]", ins.op_str)
        if mm and int(mm.group(1), 16) in WANT:
            hits.setdefault(int(mm.group(1), 16), []).append((ins.address, rtti.containing(ins.address), f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    nxt = va2raw(last) if last else None
    off = nxt if nxt and nxt > off else off + 1
for k in sorted(hits):
    print(f"+{k:#x}:")
    for a, f, t in hits[k]:
        print(f"   {a:08x} fn {f:08x}  {t}")
