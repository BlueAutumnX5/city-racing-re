"""Label game.exe functions with their C++ class, via MSVC RTTI.

x86 MSVC layout:  vtable[-1] -> CompleteObjectLocator {sig=0, off, cdOff, pTypeDesc, pCHD}
                  TypeDescriptor {pVFTable, spare, char name[] ".?AVClass@@"}
Also collects every function start we can prove (call targets + vtable entries), so any
address can be attributed to its containing function."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *

RD = [s for s in SECS if s[0] == ".rdata"][0]
RSTART, REND = RD[3], RD[3] + RD[4]
TXT_LO, TXT_HI = IMG + TEXT[1], IMG + TEXT[1] + TEXT[2]

def u32(r):
    return struct.unpack_from("<I", data, r)[0]

def in_text(v):
    return TXT_LO <= v < TXT_HI

def cstr_at(va):
    r = va2raw(va)
    if r is None:
        return None
    e = data.find(b"\0", r, r + 200)
    return data[r:e].decode("latin-1", "replace") if e > r else None

def demangle(n):
    # ".?AVCStaticObject@@" -> "CStaticObject";  nested "Inner@Outer@@" -> "Outer::Inner"
    if not n or not n.startswith(".?A"):
        return n
    body = n[4:].rstrip("@")
    parts = [p for p in body.split("@") if p]
    return "::".join(reversed(parts))

# ---- 1. vtables
func_class = {}          # function va -> "Class::vf[i]"
vtables = {}
for r in range(RSTART, REND - 8, 4):
    col = u32(r)
    cr = va2raw(col) if col else None
    if cr is None or not (RSTART <= cr < REND - 20):
        continue
    if u32(cr) != 0:                       # COL signature must be 0 on x86
        continue
    td = u32(cr + 12)
    name = cstr_at(td + 8) if va2raw(td) else None
    if not name or not name.startswith(".?AV"):
        continue
    # vtable begins right after this pointer
    vt = raw2va(r + 4)
    fns = []
    k = r + 4
    while k < REND and in_text(u32(k)):
        fns.append(u32(k))
        k += 4
    if not fns:
        continue
    cls = demangle(name)
    vtables[vt] = (cls, fns)
    for i, f in enumerate(fns):
        func_class.setdefault(f, f"{cls}::vf{i}")

# ---- 2. function starts: call targets + vtable entries
starts = set(func_class)
for rr in range(TSTART, TEND - 5):
    if data[rr] == 0xE8:
        rel = struct.unpack_from("<i", data, rr + 1)[0]
        t = raw2va(rr) + 5 + rel
        if in_text(t):
            starts.add(t)
STARTS = sorted(starts)

def containing(va):
    i = bisect.bisect_right(STARTS, va) - 1
    return STARTS[i] if i >= 0 else None

def label(va):
    f = containing(va)
    return f, func_class.get(f, "")

if __name__ == "__main__":
    print(f"{len(vtables)} vtables, {len(set(c for c,_ in vtables.values()))} classes, "
          f"{len(STARTS)} known function starts")
    for vt, (cls, fns) in sorted(vtables.items(), key=lambda x: x[1][0])[:400]:
        print(f"  0x{vt:08x}  {cls:<40} {len(fns)} virtuals")
