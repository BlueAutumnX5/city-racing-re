import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
data = open(crpaths.STOCK_EXE, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)
R = lambda va: va - 0x401000 + 0x400
calls = []
for ins in md.disasm(data[R(0x425620):R(0x425a00)], 0x425620):
    if ins.mnemonic == "call" and ins.op_str in ("0x402250", "0x401070"):
        calls.append(ins.address)
    if ins.mnemonic == "ret": print(f"  ret at {ins.address:08x}"); break
print("calls:", [hex(c) for c in calls])
for c in calls[1:]:
    print(f"=== before {c:08x}")
    for ins in md.disasm(data[R(c - 0x40):R(c + 5)], c - 0x40):
        print(f"  {ins.address:08x}  {ins.mnemonic} {ins.op_str}")
