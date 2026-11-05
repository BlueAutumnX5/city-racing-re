"""Capacity of the two buffers a traffic route is written to:
   1. the global path buffer 0x02641980 (12-byte points) - what is the next referenced global?
   2. the car's route array [car+0x1ecc] - who else writes it, and with what counts?
Also: what does 0x00431350 do with its 'max points' argument (the spawner passes 100)?"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

print("1) globals referenced in 0x02641900 .. 0x02648000:")
for a in sorted(k for k in m["refs"] if 0x02641900 <= k < 0x02648000):
    rs = m["refs"][a]
    print(f"   {a:#x}: {len(rs)} refs, e.g. {[hex(x) for x in rs[:4]]}  fns {sorted({hex(fn(x)) for x in rs})[:4]}")

# full resyncing sweep for struct-offset uses
t = [s for s in racemod.sections(buf) if s[0] == 0x00401000][0]
TS, TE = t[2], t[2] + t[1]
seq, off = [], TS
while off < TE:
    last = None
    for ins in md.disasm(buf[off:min(TE, off + 0x4000)], 0x00401000 + (off - TS)):
        seq.append((ins.address, f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
print("\n2) every use of +0x1ecc (car route array) and +0x7ecc / +0x7f44 (the fields after it):")
for i, (a, s) in enumerate(seq):
    if re.search(r"0x1ecc\]|0x7f44\]|0x7ecc\]", s):
        f = fn(a)
        print(f"   {a:#x} fn {f:#x}: {s}")
