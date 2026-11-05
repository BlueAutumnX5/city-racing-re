"""Assemble the racerfree and pedanchor code at a dummy address to measure their sizes."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re, sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
src = open(crpaths.work(r"racemod.py")).read()
ks = Ks(KS_ARCH_X86, KS_MODE_32)
for name in ("_racerfree", "_pedanchor"):
    body = src.split(f"def {name}():", 1)[1]
    asm = body.split('ks.asm(', 1)[1].split('"""', 2)[1]
    # substitute the f-string names with plausible addresses
    for k, v in {"PED_ANCHOR + 4": "0x026fc584", "PED_ANCHOR + 8": "0x026fc588",
                 "PED_ANCHOR": "0x026fc580", "tiny": "0x00568b74", "c60": "0x00568ec4",
                 "c04": "0x00568ed4", "half": "0x005682f8"}.items():
        asm = asm.replace("{" + k + "}", v)
    code, _ = ks.asm(asm, 0x00567300)
    print(f"{name}: {len(code)} bytes")
print("free .text slack after the leap walker: 0x567321 .. 0x567400 =", 0x567400 - 0x567321, "bytes")
