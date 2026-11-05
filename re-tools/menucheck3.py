"""Disassemble, from exact instruction boundaries (xmap insns), every site that uses the
Distance cap or writes the Distance global."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

m = xmap.load()
I = m["insns"]
buf = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
print("insns type:", type(I), (list(I)[:3] if not isinstance(I, dict) else list(I.items())[:2]))
