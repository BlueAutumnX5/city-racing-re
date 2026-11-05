"""Find every indirect call at IDirect3DDevice9 vtable offsets of interest, with the function it is in
and whether the receiver was loaded from the device global [0x025a1824] within the preceding 16 insns."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
data = open(crpaths.STOCK_EXE, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32); md.detail = False
R = lambda va: va - 0x401000 + 0x400
TEXT_END = 0x401000 + 0x166400  # generous; stops at bad decode anyway
WANT = {0x40: "Reset", 0x44: "Present", 0x48: "GetBackBuffer", 0x70: "CreateRenderTarget", 0x74: "CreateDepthStencilSurface",
        0x88: "StretchRect", 0x94: "SetRenderTarget", 0x98: "GetRenderTarget", 0x9c: "SetDepthStencilSurface",
        0xa0: "GetDepthStencilSurface", 0xa4: "BeginScene", 0xa8: "EndScene", 0xac: "Clear", 0xbc: "SetViewport",
        0x10c: "SetVertexShader?", 0x1a8: "SetPixelShader"}
# function starts: after cc/90 padding
def fstart(va):
    p = R(va)
    while p > 0x400:
        if data[p-1] in (0xcc,) and data[p] != 0xcc: return p - 0x400 + 0x401000
        p -= 1
    return 0
import re
text = data[0x400:0x400 + 0x166000]
out = []
hist = []
off = 0
while off < len(text) - 16:
    got = False
    for ins in md.disasm(text[off:off+16], 0x401000 + off, 1):
        got = True
        hist.append(ins); hist = hist[-16:]
        m = re.fullmatch(r"dword ptr \[(e\w\w) \+ (0x[0-9a-f]+)\]", ins.op_str) if ins.mnemonic == "call" else None
        if m and int(m.group(2), 16) in WANT:
            o = int(m.group(2), 16)
            dev = any("0x25a1824" in h.op_str for h in hist)
            out.append((ins.address, WANT[o], dev))
        off += ins.size
    if not got: off += 1
for a, n, dev in out:
    if dev or n in ("Present", "BeginScene", "EndScene", "SetRenderTarget", "Reset", "GetBackBuffer", "SetDepthStencilSurface", "StretchRect", "CreateRenderTarget", "CreateDepthStencilSurface"):
        print(f"{a:08x}  fn {fstart(a):08x}  {n:<26} {'DEV' if dev else '?'}")
