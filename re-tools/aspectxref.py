import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.WORK)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
data = open(crpaths.STOCK_EXE, "rb").read()
pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
opt = struct.unpack_from("<H", data, pe + 20)[0]
secs = []
for i in range(nsec):
    o = pe + 24 + opt + 40 * i
    name = data[o:o+8].rstrip(b"\0").decode()
    vs, va, rs, ro = struct.unpack_from("<IIII", data, o + 8)
    secs.append((name, 0x400000 + va, vs, ro, rs))
def raw(v):
    for n, va, vs, ro, rs in secs:
        if va <= v < va + max(vs, rs): return ro + v - va
TARGET = 0x00568300
print("value at 0x568300:", struct.unpack_from("<f", data, raw(TARGET))[0])
text = [s for s in secs if s[0] == ".text"][0]
md = Cs(CS_ARCH_X86, CS_MODE_32)
pat = struct.pack("<I", TARGET)
code = data[text[3]:text[3] + text[4]]
i = code.find(pat)
while i >= 0:
    va = text[1] + i
    # find instruction containing the operand: try starts up to 8 bytes back
    for back in range(2, 9):
        s = va - back
        ins = list(md.disasm(code[s - text[1]: s - text[1] + 16], s, 1))
        if ins and ins[0].address + ins[0].size >= va + 4 and ins[0].address + ins[0].size <= va + 8 and pat in bytes(ins[0].bytes):
            print(f"  {ins[0].address:08x}  {ins[0].mnemonic} {ins[0].op_str}")
            break
    else:
        print(f"  {va:08x}  (raw hit, undecoded)")
    i = code.find(pat, i + 1)
