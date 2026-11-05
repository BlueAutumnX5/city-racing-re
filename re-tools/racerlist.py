"""EVERY instruction touching the racer list (traffic manager 0x02649368 + 0x13da0 .. +0x13dc0),
by displacement or by absolute address, plus every reader of the racer count 0x02668944 with
its surrounding code, so every per-racer array can be found."""
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
        seq.append((ins.address, f"{ins.mnemonic} {ins.op_str}", ins.size))
        last = ins.address + ins.size
    off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
MGR = 0x02649368
lo, hi = MGR + 0x13da0, MGR + 0x13dc0
print("racer-list references:")
for a, s, n in seq:
    if a >= 0x480000:
        continue
    hit = "0x13da" in s or "0x13db" in s
    for mm in re.finditer(r"0x([0-9a-f]{6,8})", s):
        v = int(mm.group(1), 16)
        if lo <= v < hi:
            hit = True
    if hit:
        print(f"  {a:#x} ({n} B) fn {fn(a):#x}: {s}")
