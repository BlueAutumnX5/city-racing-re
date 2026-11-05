"""For each function that touches the racer list, list every call site and the `this` (ecx)
it is called with - to prove the base register is always the traffic manager 0x02649368."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
b = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
ctor = fn(0x0043fecc)
for f in (ctor, 0x00441020, 0x00441150, 0x00443490):
    sites = sorted(m["refs"].get(f, []))
    print(f"fn {f:#x}: {len(sites)} caller(s)")
    for s in sites:
        # walk back up to 12 instructions from the call to find the last write to ecx
        r = racemod.va2raw(b, s)
        best = "?"
        for back in range(4, 60):
            seq = list(md.disasm(b[r - back:r + 5], s - back))
            if seq and seq[-1].address == s:
                for ins in reversed(seq[:-1]):
                    if ins.op_str.startswith("ecx,"):
                        best = f"{ins.address:#x} {ins.mnemonic} {ins.op_str}"
                        break
                break
        print(f"   call at {s:#x} in fn {fn(s):#x}: ecx <- {best}")
