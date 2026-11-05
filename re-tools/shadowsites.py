import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
md = Cs(CS_ARCH_X86, CS_MODE_32)
bufs = {"pristine": open(racemod.BACKUP, "rb").read(),
        "installed": open(crpaths.GAME_EXE, "rb").read()}
for va in (0x0040c89a, 0x0040c8bf, 0x0040c8e4):
    for nm, b in bufs.items():
        r = racemod.va2raw(b, va)
        ins = next(md.disasm(b[r:r + 8], va))
        print(f"{nm:<9} {va:#x}: {b[r:r + ins.size].hex()}  {ins.mnemonic} {ins.op_str}")
print("EXTRAS:", racemod.EXTRAS)
