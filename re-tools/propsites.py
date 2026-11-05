import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
md = Cs(CS_ARCH_X86, CS_MODE_32)
pr = open(racemod.BACKUP, "rb").read()
SITES = [0x00410f46, 0x00410f6c, 0x00410f7d, 0x004526a1, 0x004526f2, 0x0045272f, 0x00452749,
         0x0045353a, 0x00453567, 0x0046adc1]
for va in SITES:
    r = racemod.va2raw(pr, va)
    ins = next(md.disasm(pr[r:r + 16], va))
    op = ins.address + ins.size - 4
    val = int.from_bytes(pr[racemod.va2raw(pr, op):racemod.va2raw(pr, op) + 4], "little")
    print(f"({op:#010x}, {val:#010x}),   # {va:#x} {ins.mnemonic} {ins.op_str}  [{pr[r:r + ins.size].hex()}]")
