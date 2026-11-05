"""For every instruction that reads the device global [0x025a1824], follow forward (<=24 insns) to the
first `call [reg+off]` and name the IDirect3DDevice9 method. Grouped by containing function."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, re, collections
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *
import xmap, rtti
import re as _re, os as _os
DEV = eval(_re.search(r"DEV = (\[.*?\])", open(_os.path.join(_os.path.dirname(__file__), "d3dlabel.py")).read(), _re.S).group(1))
m = xmap.load()
DEVG = 0x025a1824
want = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
by_fn = collections.defaultdict(list)
for iva in sorted(m["refs"].get(DEVG, [])):
    r = va2raw(iva)
    n = 0
    last = {}
    for ins in md.disasm(data[r:r + 200], iva):
        n += 1
        lm = re.fullmatch(r"(e\w\w), dword ptr \[e\w\w \+ (0x[0-9a-f]+)\]", ins.op_str) if ins.mnemonic == "mov" else None
        if lm:
            last[lm.group(1)] = int(lm.group(2), 16)
        mm = re.fullmatch(r"dword ptr \[e\w\w \+ (0x[0-9a-f]+)\]", ins.op_str) if ins.mnemonic == "call" else None
        mr = ins.mnemonic == "call" and ins.op_str in last
        if mm or mr:
            off = int(mm.group(1), 16) if mm else last[ins.op_str]
            name = DEV[off // 4] if off // 4 < len(DEV) else f"+{off:#x}"
            if want is None or name in want:
                by_fn[rtti.containing(ins.address)].append((ins.address, name))
            break
        if ins.mnemonic in ("ret", "jmp") or n > 24:
            break
for f in sorted(by_fn):
    print(f"fn {f:08x} ({rtti.func_class.get(f, '')}):  " + ", ".join(f"{a:08x} {n}" for a, n in by_fn[f]))
