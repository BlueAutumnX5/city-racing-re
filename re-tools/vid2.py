"""Phase 1b: who reads/writes the near/far floats, the max table, and the Distance global?
Accurate xrefs: decode every instruction in .text and inspect its operands, rather than
searching raw bytes (which matches addresses embedded in unrelated instructions)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *
from capstone import CS_OP_MEM, CS_OP_IMM
from capstone.x86 import X86_OP_MEM, X86_OP_IMM

md.detail = True
WATCH = {0x590410: "f100 (0x590410)", 0x590414: "f600 FAR? (0x590414)",
         0x590418: "f0.2 NEAR? (0x590418)", 0x59041c: "max Details", 0x590420: "max Traffic",
         0x590424: "max Shadows", 0x590428: "max Glow", 0x59042c: "max Blur",
         0x590430: "max Water", 0x590434: "max Reflect", 0x590438: "max 0x12cc3a0",
         0x12d0494: "Distance setting", 0x12cc124: "Details setting",
         0x12cc3a0: "setting 0x12cc3a0"}
hits = {k: [] for k in WATCH}

# linear sweep of .text; resync after bad bytes
off = TSTART
while off < TEND:
    ins_any = False
    for ins in md.disasm(data[off:min(TEND, off + 0x4000)], raw2va(off)):
        ins_any = True
        for op in ins.operands:
            a = None
            if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                a = op.mem.disp & 0xFFFFFFFF
            elif op.type == X86_OP_IMM:
                a = op.imm & 0xFFFFFFFF
            if a in hits:
                hits[a].append((ins.address, f"{ins.mnemonic} {ins.op_str}"))
        last = ins.address + ins.size
    if not ins_any:
        off += 1
    else:
        off = va2raw(last) if va2raw(last) > off else off + 1

for a, name in WATCH.items():
    h = hits[a]
    writes = [x for x in h if x[1].split()[0] in ("mov", "movss", "fstp", "fst")
              and x[1].split(" ", 1)[1].startswith(("dword ptr [0x", "qword ptr [0x"))]
    print(f"\n{name}: {len(h)} refs, {len(writes)} writes")
    for va, txt in h[:14]:
        print(f"   0x{va:08x}  {txt}{'   <-- WRITE' if (va, txt) in writes else ''}")
