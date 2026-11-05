"""Full resyncing sweep of .text: find `mov reg, [reg + 0x44030]` (the IDirect3D9 pointer)
followed within 40 instructions by a vtable load/call at +0x40 (CreateDevice)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, re
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
t = [s for s in racemod.sections(buf) if s[0] == 0x00401000][0]
TS, TE = t[2], t[2] + t[1]
seq = []
off = TS
while off < TE:
    last = None
    for ins in md.disasm(buf[off:min(TE, off + 0x4000)], 0x00401000 + (off - TS)):
        seq.append((ins.address, f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
print("instructions:", len(seq))
# ebp at 0x40f1b4 = the depth format. Print the function from its start to there.
idx = {a: i for i, (a, _) in enumerate(seq)}
i1 = idx[0x0040f1b4]
i0 = i1
while i0 > 0 and not (seq[i0 - 1][1].startswith("int3") or seq[i0 - 1][1].startswith("ret")):
    i0 -= 1
for b, w in seq[i0:i1 + 1]:
    if "ebp" in w or "call" in w or b == seq[i0][0]:
        print(f"   {b:08x}  {w}")
