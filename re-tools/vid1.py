"""Phase 1a: where does each [Video] setting go, and what range is it clamped to?"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *

KEYS = ["Mode", "Distance", "Details", "Traffic", "Shadows", "Glow", "Blur", "Water", "Reflect"]
# the strings sit together near "Traffic" (0x0056a658)
area = data[va2raw(0x0056a500):va2raw(0x0056a800)]
found = {}
for k in KEYS:
    i = -1
    while True:
        i = area.find(k.encode() + b"\0", i + 1)
        if i < 0:
            break
        va = 0x0056a500 + i
        if area[i - 1:i] in (b"\0",) or i == 0:
            found.setdefault(k, []).append(va)
for k in KEYS:
    print(f"{k:<9} string at {[hex(v) for v in found.get(k, [])]}")

print("\n=== every 'push <key string>' and the global the result is stored to ===")
for k in KEYS:
    for sva in found.get(k, []):
        for x in xrefs(sva):
            # disassemble a few instructions after the push to find `mov [global], eax`
            dest = None
            for ins in md.disasm(data[va2raw(x):va2raw(x) + 40], x):
                if ins.mnemonic == "mov" and ins.op_str.startswith("dword ptr [0x") and ins.op_str.endswith("eax"):
                    dest = ins.op_str.split("[")[1].split("]")[0]
                    break
            print(f"  {k:<9} push at 0x{x:08x}  -> stored to {dest}")
