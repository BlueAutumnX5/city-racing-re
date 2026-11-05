"""Methods called on the light manager 0x02647980 (ecx = 0x2647980; call X), and inside each
method every compare against its count field +0x40c, to find the light-list capacity."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
nxt = lambda a: S[bisect.bisect_right(S, a)] if bisect.bisect_right(S, a) < len(S) else a + 0x400
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

def dis(a, b):
    r = racemod.va2raw(buf, a)
    return list(md.disasm(buf[r:r + (b - a)], a))

methods = {}
for site in sorted(m["refs"].get(0x2647980, [])):
    f = fn(site)
    seq = dis(site, min(site + 0x40, nxt(site)))
    for ins in seq[1:12]:
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            methods.setdefault(int(ins.op_str, 16), set()).add(f)
            break
for meth, callers in sorted(methods.items()):
    fp = "; ".join(dict.fromkeys(m["fp"].get(meth, [])))[:50]
    print(f"method {meth:#x}  called from {len(callers)} fn(s): {[hex(c) for c in sorted(callers)][:6]}  {fp}")
    for ins in dis(meth, nxt(meth)):
        t = f"{ins.mnemonic} {ins.op_str}"
        if re.search(r"0x40c\]|0x410\]", t) or (ins.mnemonic == "cmp" and re.search(r", 0x[0-9a-f]+$", t)):
            print(f"      {ins.address:#x}  {t}")
