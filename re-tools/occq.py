"""Full resyncing sweep: device vtable +0x1d8 (IDirect3DDevice9::CreateQuery) loads, and the
functions around them, to see whether coronas use occlusion queries."""
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
t = [s for s in racemod.sections(buf) if s[0] == 0x00401000][0]
TS, TE = t[2], t[2] + t[1]
seq, off = [], TS
while off < TE:
    last = None
    for ins in md.disasm(buf[off:min(TE, off + 0x4000)], 0x00401000 + (off - TS)):
        seq.append((ins.address, f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
pat = sys.argv[1] if len(sys.argv) > 1 else r"\[e.x \+ 0x1d8\]"
seen = set()
for i, (a, s) in enumerate(seq):
    if re.search(pat, s) and a < 0x480000:          # game code only, not the D3DX library
        f = fn(a)
        if f in seen:
            continue
        seen.add(f)
        print(f"{a:#x} in fn {f:#x}: {s}   {'; '.join(dict.fromkeys(m['fp'].get(f, [])))[:60]}")
