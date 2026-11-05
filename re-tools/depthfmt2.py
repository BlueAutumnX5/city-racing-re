"""Locate Direct3DCreate9's IAT slot, the function that calls it, and every
D3DPRESENT_PARAMETERS-like store in that function and its neighbours."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
m = xmap.load(); S = m["starts"]; I = m["insns"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
buf = open(racemod.BACKUP, "rb").read()

pe = struct.unpack_from("<I", buf, 0x3C)[0]
img = struct.unpack_from("<I", buf, pe + 0x34)[0]
imp_rva = struct.unpack_from("<I", buf, pe + 0x80)[0]
def rva2raw(rva):
    return racemod.va2raw(buf, img + rva)
def cstr(rva):
    r = rva2raw(rva); e = buf.index(b"\0", r); return buf[r:e].decode()
d = rva2raw(imp_rva)
iat = {}
while True:
    oft, _, _, name, ft = struct.unpack_from("<5I", buf, d)
    if not name:
        break
    dll = cstr(name)
    t = oft or ft; i = 0
    while True:
        e = struct.unpack_from("<I", buf, rva2raw(t) + 4 * i)[0]
        if not e:
            break
        if not e & 0x80000000:
            iat[img + ft + 4 * i] = (dll, cstr(e + 2))
        i += 1
    d += 20
for slot, (dll, f) in iat.items():
    if "d3d9" in dll.lower() or "Direct3D" in f:
        print(f"IAT {slot:#x}: {dll}!{f}")
        users = [a for a, t in I.items() if f"{slot:#x}" in t]
        for u in users:
            print(f"   used at {u:#x} in fn {fn(u):#x}: {I[u]}")
