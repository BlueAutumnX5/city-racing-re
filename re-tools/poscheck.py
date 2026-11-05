"""Every read of a car's race position [car+0xc80], with the next 8 instructions, flagging any
that index a table with it (a position-indexed table sized for 8 racers would break at 12)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
b = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
t = [s for s in racemod.sections(b) if s[0] == 0x00401000][0]
TS, TE = t[2], t[2] + t[1]
seq, off = [], TS
while off < TE:
    last = None
    for ins in md.disasm(b[off:min(TE, off + 0x4000)], 0x00401000 + (off - TS)):
        seq.append((ins.address, f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
for i, (a, s) in enumerate(seq):
    if a < 0x480000 and "+ 0xc80]" in s and not s.startswith("mov dword ptr [e"):
        win = seq[i:i + 9]
        idx = [w for _, w in win[1:] if re.search(r"\*[248] \+ 0x[0-9a-f]{5,}\]|\[e.. \+ e..\*4\]", w)]
        fp = "; ".join(dict.fromkeys(m["fp"].get(fn(a), [])))[:40]
        print(f"{a:#x} fn {fn(a):#x} {fp}: {s}")
        for w in idx:
            print(f"      TABLE? {w}")
