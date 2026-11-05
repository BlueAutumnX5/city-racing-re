"""Disassembler on the PRISTINE baseline (no racemod hooks). Usage: pdis.py <va> [n]"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
EXE = crpaths.RACEMOD_BACKUP
data = open(EXE, "rb").read()
pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
opt = struct.unpack_from("<H", data, pe + 20)[0]
IMG = struct.unpack_from("<I", data, pe + 24 + 28)[0]
SECS = []
for i in range(nsec):
    o = pe + 24 + opt + i * 40
    vsz, va, rsz, raw = struct.unpack_from("<4I", data, o + 8)
    SECS.append((data[o:o+8].rstrip(b"\0").decode(), IMG + va, max(vsz, rsz), raw, rsz))


def va2raw(v):
    for n, va, sz, raw, rsz in SECS:
        if va <= v < va + sz:
            return raw + v - va


def rd(v, n):
    r = va2raw(v)
    return data[r:r + n]


def f32(v): return struct.unpack("<f", rd(v, 4))[0]
def u32(v): return struct.unpack("<I", rd(v, 4))[0]


md = Cs(CS_ARCH_X86, CS_MODE_32)


def dis(va, n=60):
    out = []
    for ins in md.disasm(rd(va, n * 10), va):
        out.append(f"  {ins.address:08x}  {ins.bytes.hex():<22} {ins.mnemonic} {ins.op_str}")
        if len(out) >= n:
            break
    return "\n".join(out)


def text_insns():
    """Every instruction of .text (linear sweep, resyncing on bad bytes)."""
    n, va, sz, raw, rsz = SECS[0]
    off = 0
    code = data[raw:raw + rsz]
    while off < len(code):
        last = None
        for ins in md.disasm(code[off:off + 0x4000], va + off):
            yield ins
            last = ins.address + ins.size - va
        off = last if last and last > off else off + 1


if __name__ == "__main__":
    print(dis(int(sys.argv[1], 16), int(sys.argv[2]) if len(sys.argv) > 2 else 60))
