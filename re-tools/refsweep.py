"""Full resyncing .text sweep of BOTH the pristine backup and the installed exe: every
instruction whose text matches a regex (default: the shared 60.0 at 0x568ec4), with its
function and fingerprint, marked 'same' / 'CHANGED' between the two builds.
Usage: refsweep.py [regex]"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
md = Cs(CS_ARCH_X86, CS_MODE_32)
INSTALLED = crpaths.GAME_EXE


def sweep(buf):
    t = [s for s in racemod.sections(buf) if s[0] == 0x00401000][0]
    TS, TE = t[2], t[2] + t[1]
    seq, off = {}, TS
    while off < TE:
        last = None
        for ins in md.disasm(buf[off:min(TE, off + 0x4000)], 0x00401000 + (off - TS)):
            seq[ins.address] = f"{ins.mnemonic} {ins.op_str}"
            last = ins.address + ins.size
        off = (TS + last - 0x00401000) if last and TS + last - 0x00401000 > off else off + 1
    return seq


pat = sys.argv[1] if len(sys.argv) > 1 else r"0x568ec4\]"
old = sweep(open(racemod.BACKUP, "rb").read())
new = sweep(open(INSTALLED, "rb").read())
for a in sorted(k for k, s in old.items() if re.search(pat, s)):
    f = fn(a)
    tag = "same   " if new.get(a) == old[a] else f"CHANGED -> {new.get(a)}"
    print(f"{a:#010x} fn {f:#010x}  {old[a]:<45} {tag}   "
          f"{'; '.join(dict.fromkeys(m['fp'].get(f, [])))[:50]}")
