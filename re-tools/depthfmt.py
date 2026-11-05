"""Find the depth-buffer format the game asks D3D9 for.
D3DPRESENT_PARAMETERS: +0x24 EnableAutoDepthStencil, +0x28 AutoDepthStencilFormat.
Formats: D16=80(0x50) D24X8=77(0x4d) D24S8=75(0x4b) D32=71(0x47) D15S1=73 D24X4S4=79."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
import xmap
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
I = m["insns"]
print(type(I), len(I))
import re
FMT = {"0x50": "D16", "0x4d": "D24X8", "0x4b": "D24S8", "0x47": "D32", "0x49": "D15S1", "0x4f": "D24X4S4"}
# 1) the device-creation function: IDirect3D9::CreateDevice is vtable +0x40
fns_with_fmt = {}
for a, t in sorted(I.items()):
    mm = re.match(r"mov dword ptr \[.*\], (0x4[79bdf]|0x50)$", t)
    if mm:
        fns_with_fmt.setdefault(fn(a), []).append((a, t, FMT[mm.group(1)]))
# 2) keep only functions that also make a vtable call at +0x40 and mention "Direct3D" strings
for f, hits in fns_with_fmt.items():
    body = [(a, t) for a, t in I.items() if fn(a) == f]
    calls40 = [a for a, t in body if re.search(r"(call dword ptr|mov e.x, dword ptr) \[e.x \+ 0x40\]", t)]
    strs = "; ".join(dict.fromkeys(m["fp"].get(f, [])))[:90]
    if True:
        print(f"fn {f:#x}  vcall+0x40 at {[hex(c) for c in calls40]}  strings: {strs}")
        for a, t, n in hits:
            print(f"     {a:#x}  {t}   <- {n}?")

