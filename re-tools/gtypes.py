import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, re
sys.path.insert(0, crpaths.RETOOLS)
from crdis import data, va2raw, md
import xmap
m = xmap.load()
S = m["strings"]
for fn, end in ((0x004562e0, 0x00456360), (0x00456360, 0x00456460)):
    print(f"=== {fn:#x}")
    pend = None
    for ins in md.disasm(data[va2raw(fn):va2raw(end)], fn):
        mm = re.search(r"push (0x[0-9a-f]+)", ins.mnemonic + " " + ins.op_str)
        if mm and int(mm.group(1), 16) in S:
            pend = S[int(mm.group(1), 16)]
        mv = re.match(r"mov eax, (0x[0-9a-f]+|\d+)$", ins.mnemonic + " " + ins.op_str)
        if mv and pend:
            print(f"   {pend:<20} -> {int(mv.group(1), 0):#x}")
            pend = None
        if ins.mnemonic == "ret" and ins.address > fn + 0x10 and False:
            break
