import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
data = open(crpaths.STOCK_EXE, "rb").read()
base_raw = 0x400; base_va = 0x401000   # .text
md = Cs(CS_ARCH_X86, CS_MODE_32)
for hit in (0x004018fb, 0x00425700, 0x00440896, 0x004495bf, 0x00449718):
    op = data.find(struct.pack("<I", 0x568300), hit - base_va + base_raw - 2)  # operand position
    op_va = op - base_raw + base_va
    print(f"--- operand at {op_va:08x}; bytes before: {data[op-6:op].hex(' ')}")
    # voting: start sweeps at many offsets 0x40 back, keep ones that land on an instruction ending at op+4
    votes = {}
    for s in range(op_va - 0x40, op_va - 0x30):
        chain = []
        for ins in md.disasm(data[s - base_va + base_raw: op - base_raw + base_raw + 16 + 0x0], s):
            chain.append(ins)
            if ins.address + ins.size >= op_va + 4: break
        if chain and chain[-1].address + chain[-1].size == op_va + 4:
            key = tuple((i.address, i.mnemonic, i.op_str) for i in chain[-6:])
            votes[key] = votes.get(key, 0) + 1
    best = max(votes.items(), key=lambda kv: kv[1]) if votes else None
    if best:
        for a, m, o in best[0]: print(f"  {a:08x}  {m} {o}")
        print(f"  ({best[1]} of 16 sweeps agree)")
    else:
        print("  no sweep ends on the operand -> not a code reference")
