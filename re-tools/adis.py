"""Annotated disassembly: every static memory operand shows its float/int value, every
call shows its target's string fingerprint. Usage: adis.py <start> [<end>]"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *
import xmap
from capstone.x86 import X86_OP_MEM, X86_OP_IMM
m = xmap.load()
S = m["starts"]
md.detail = True

def fpr(f):
    ss = m["fp"].get(f, [])
    return "; ".join(dict.fromkeys(ss))[:70]

def annotate(start, end):
    out = []
    for ins in md.disasm(data[va2raw(start):va2raw(end)], start):
        note = ""
        for op in ins.operands:
            if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                a = op.mem.disp & 0xFFFFFFFF
                r = va2raw(a)
                if r is not None and r + 4 <= len(data) and a < 0x0058f642:   # .rdata consts
                    fv = struct.unpack_from("<f", data, r)[0]
                    iv = struct.unpack_from("<i", data, r)[0]
                    note += f"   ; [{a:#x}] = {fv:g}f / {iv}"
                elif a >= 0x00590000:
                    note += f"   ; global {a:#x}"
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16)
            fp = fpr(t)
            note += f"   ; -> {fp}" if fp else ""
        out.append(f"  {ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}{note}")
        if ins.address >= end:
            break
    return "\n".join(out)

if __name__ == "__main__":
    a = int(sys.argv[1], 16)
    b = int(sys.argv[2], 16) if len(sys.argv) > 2 else a + 0x200
    print(annotate(a, b))
