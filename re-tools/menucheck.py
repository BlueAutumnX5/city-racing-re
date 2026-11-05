"""Re-read every piece of code that touches the Distance cap slot 0x0059041c and the
Distance global 0x012cc124 inside the menu code, from the PRISTINE baseline."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
secs = racemod.sections(buf)
text = [s for s in secs if s[0] == 0x00401000][0]
code = buf[text[2]:text[2] + text[1]]

def val(c):
    try:
        r = racemod.va2raw(buf, c)
        return f"{struct.unpack_from('<f', buf, r)[0]:g}f / {struct.unpack_from('<i', buf, r)[0]}"
    except Exception:
        return "?"

hits = []
for ins in md.disasm(code, 0x00401000):
    if "0x5904" in ins.op_str or "0x5903f" in ins.op_str:
        hits.append(ins.address)
        print(f"   {ins.address:08x}  {ins.mnemonic} {ins.op_str}")
print("instructions addressing 0x005903f0..0x005904ff:", len(hits))
hits = [h for h in hits if h not in ()]

for a in hits:
    print(f"\n-- around 0x{a:08x}")
    start = a - 0x40
    lines = list(md.disasm(buf[racemod.va2raw(buf, start):racemod.va2raw(buf, start) + 0xa0], start))
    # resync: only print from an instruction boundary that reaches `a`
    for back in range(0x40, 0, -1):
        seq = list(md.disasm(buf[racemod.va2raw(buf, a - back):racemod.va2raw(buf, a - back) + 0xa0], a - back))
        if any(i.address == a for i in seq):
            lines = seq
            break
    for ins in lines[:40]:
        note = ""
        for tok in ("[0x5", "[0x12", "[0x13"):
            if tok in ins.op_str:
                c = int(ins.op_str.split("[0x")[1].split("]")[0].split(" ")[0], 16)
                note = f"   ; [{c:#x}] = {val(c)}"
        mark = ">>" if ins.address == a else "  "
        print(f"{mark} {ins.address:08x}  {ins.mnemonic} {ins.op_str}{note}")
