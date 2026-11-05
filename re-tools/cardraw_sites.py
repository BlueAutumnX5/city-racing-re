import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
md = Cs(CS_ARCH_X86, CS_MODE_32)
INST = crpaths.GAME_EXE
bufs = {"pristine": open(racemod.BACKUP, "rb").read(), "installed": open(INST, "rb").read()}
def off(buf, va):
    for s in racemod.sections(buf):
        if s[0] <= va < s[0] + s[1]:
            return s[2] + (va - s[0])
SITES = [0x004355e5, 0x004358a5, 0x00435a35, 0x00435bf5, 0x00435ee5, 0x0043bd9f, 0x0043c17d]
for va in SITES:
    for nm, b in bufs.items():
        o = off(b, va)
        ins = next(md.disasm(b[o:o + 16], va))
        print(f"{nm:<9} {va:#x}: {b[o:o + ins.size].hex()}  {ins.mnemonic} {ins.op_str}  operand@{va + 3:#x} = {b[o + 3:o + 7].hex()}")
print("VIEW_CONSTS tail in installed:", bufs['installed'][off(bufs['installed'], 0x0058f650):off(bufs['installed'], 0x0058f650) + 48].hex())
