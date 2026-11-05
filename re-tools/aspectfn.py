import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
data = open(crpaths.STOCK_EXE, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
R = lambda va: va - 0x401000 + 0x400
def dis(a, b, mark=()):
    for ins in md.disasm(data[R(a):R(b)], a):
        m = " <==" if ins.address in mark else ""
        print(f"  {ins.address:08x}  {ins.mnemonic} {ins.op_str}{m}")
# find start of function containing 0x4018fb: scan back for cc/c3 padding then push/sub
def fstart(va):
    p = R(va)
    while p > 0:
        if data[p-1] in (0xcc, 0x90) and data[p] not in (0xcc, 0x90): return p - 0x400 + 0x401000
        p -= 1
for hit in (0x004018fb, 0x00425700):
    s = fstart(hit)
    print(f"=== function containing {hit:08x} starts ~{s:08x}")
    dis(max(s, hit - 0x70), hit + 0x30, (hit,))
print("=== call site(s) of the projection builder 0x401070 near 0x402250")
code = data[R(0x402250):R(0x402400)]
import struct
for ins in md.disasm(code, 0x402250):
    if ins.mnemonic == "call" and ins.op_str == "0x401070":
        dis(ins.address - 0x50, ins.address + 5, (ins.address,))
