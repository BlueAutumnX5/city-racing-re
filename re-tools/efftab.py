"""Resolve the static-object loader's effect-type jump table (0x00419400) to effect slots."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, struct
sys.path.insert(0, crpaths.RETOOLS)
from crdis import data, va2raw, md

for ins in md.disasm(data[va2raw(0x00418e20):va2raw(0x00418e4e)], 0x00418e20):
    print(f"  {ins.address:08x}  {ins.mnemonic} {ins.op_str}")
H = {0x418e4e: "A ctor 0x411c80", 0x418e96: "B ctor 0x4120c0",
     0x418ee2: "C slot +0xbf4 (draw 0x412910)", 0x418f56: "D slot +0xbf8 (draw 0x412e50)",
     0x418f9d: "E slot +0xbfc (draw 0x414080)", 0x418fdf: "F slot +0xc00 (draw 0x415260)",
     0x41901e: "G slot +0xc04 (draw 0x417bf0)", 0x41905a: "H (0x41905a)"}
NAMES = {1010: "CHROME", 1011: "RGLASS", 1020: "LIGHTMAPS", 1021: "SELFILLUM", 1040: "LIGHTS",
         1041: "DIRECTLIGHTS", 1050: "SPOTS", 1060: "FLAME"}
for i in range(0x3d):
    t = struct.unpack_from("<I", data, va2raw(0x00419400) + 4 * i)[0]
    if t != 0x0041909f:
        print(f"  index {i:2d} (code {1010 + i} {NAMES.get(1010 + i, '?')}): {t:#x} {H.get(t, '?')}")
