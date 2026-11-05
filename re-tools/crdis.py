"""Small disassembly toolkit for game.exe."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re, struct, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = crpaths.GAME_EXE
data = open(EXE, "rb").read()
pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
opt = struct.unpack_from("<H", data, pe + 20)[0]
IMG = struct.unpack_from("<I", data, pe + 24 + 28)[0]
SECS = []
for i in range(nsec):
    o = pe + 24 + opt + i * 40
    nm = data[o:o+8].rstrip(b"\0").decode("latin-1")
    vsz, va, rsz, raw = struct.unpack_from("<4I", data, o + 8)
    SECS.append((nm, va, vsz, raw, rsz))
TEXT = [s for s in SECS if s[0] == ".text"][0]
TSTART, TEND = TEXT[3], TEXT[3] + TEXT[4]

def raw2va(r):
    for n, va, vsz, raw, rsz in SECS:
        if raw <= r < raw + rsz:
            return IMG + va + (r - raw)
def va2raw(v):
    for n, va, vsz, raw, rsz in SECS:
        if IMG + va <= v < IMG + va + vsz:
            return raw + (v - IMG - va)

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = False

def dis(va, n=40, back=0):
    r = va2raw(va) - back
    out = []
    for ins in md.disasm(data[r:r + n*8], va - back):
        out.append(f"  {ins.address:08x}  {ins.bytes.hex():<20} {ins.mnemonic} {ins.op_str}")
        if len(out) >= n:
            break
    return "\n".join(out)

def cstr(va):
    r = va2raw(va)
    if r is None:
        return None
    e = data.index(b"\0", r)
    return data[r:e].decode("latin-1", "replace")

def xrefs(va):
    needle = struct.pack("<I", va)
    hits, i = [], TSTART
    while True:
        i = data.find(needle, i + 1, TEND)
        if i < 0:
            break
        hits.append(raw2va(i - 1))
    return hits

def find_string(lit):
    b = lit.encode("latin-1")
    out, i = [], -1
    while True:
        i = data.find(b, i + 1)
        if i < 0:
            break
        out.append(raw2va(i))
    return [v for v in out if v]

def func_start(va, limit=0x900):
    """walk back to a likely prologue"""
    r = va2raw(va)
    for back in range(4, limit):
        p = r - back
        if data[p:p+3] == b"\x55\x8b\xec" or data[p:p+1] == b"\x55" and data[p+1:p+3] == b"\x8b\xec":
            return raw2va(p)
        if data[p:p+2] in (b"\x83\xec", b"\x81\xec") and data[p-1:p] == b"\x55":
            return raw2va(p-1)
    return None

if __name__ == "__main__":
    for lit in ("You are invited to take part in timed race",
                "You are invited to take part in competition"):
        for va in find_string(lit):
            print(f"\n=== {lit!r} at 0x{va:08x} ===")
            for x in xrefs(va):
                print(f"  xref 0x{x:08x}")
                print(dis(x, 26, back=0))
