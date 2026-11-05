"""Who reads/writes the settings max table 0x00590410..0x0059043c and the Distance global
0x012cc124? Disassemble every site from an instruction boundary (xmap's refs are exact)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
print("xmap keys:", list(m.keys()))

def val(c):
    try:
        r = racemod.va2raw(buf, c)
        return f"{struct.unpack_from('<f', buf, r)[0]:g}f / {struct.unpack_from('<i', buf, r)[0]}"
    except Exception:
        return "?"

print("\nsettings table contents 0x00590400..0x00590440:")
for c in range(0x00590400, 0x00590444, 4):
    print(f"  {c:#010x} = {val(c)}   refs: {[hex(a) for a in m['refs'].get(c, [])]}")

for tgt in (0x012cc124,):
    refs = sorted(m["refs"].get(tgt, []))
    fns = sorted({fn(a) for a in refs})
    print(f"\n{tgt:#x}: {len(refs)} refs in {len(fns)} functions")
    for a in refs:
        r = racemod.va2raw(buf, a)
        ins = next(md.disasm(buf[r:r + 16], a))
        print(f"   {a:08x} (fn {fn(a):08x})  {ins.mnemonic} {ins.op_str}")
