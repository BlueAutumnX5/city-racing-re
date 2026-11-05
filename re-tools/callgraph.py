"""Transitive call graph of the traffic route builder 0x004315e0: every direct call,
every indirect call, every FS/absolute-global access, so the emulator can be trusted."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

def body(f):
    """Disassemble a function by following its code until the next function start."""
    nxt = S[bisect.bisect_right(S, f)]
    r = racemod.va2raw(buf, f)
    return list(md.disasm(buf[r:r + (nxt - f)], f))

seen, todo = set(), [0x004315e0]
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    calls, other = [], []
    for ins in body(f):
        t = f"{ins.mnemonic} {ins.op_str}"
        if ins.mnemonic == "call":
            if ins.op_str.startswith("0x"):
                c = int(ins.op_str, 16); calls.append(c)
                if c not in (0x0054aba3,):          # rand is hooked in racesim
                    todo.append(c)
            else:
                other.append(f"INDIRECT {ins.address:#x}: {t}")
        if "fs:" in t:
            other.append(f"FS {ins.address:#x}: {t}")
    fp = "; ".join(dict.fromkeys(m["fp"].get(f, [])))[:50]
    print(f"{f:#x}  calls {[hex(c) for c in sorted(set(calls))]}  {fp}")
    for o in other:
        print("      ", o)
