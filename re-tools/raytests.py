"""Every function that constructs a Bullet ray-test callback (writes its vtable), plus every
D3D9 occlusion-query creation (device vtable +0x1d8 = CreateQuery). Either is how a game
decides whether a corona is visible."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect, re
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap, rtti
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
print("vtables type:", type(rtti.vtables), list(rtti.vtables.items())[:2])
want = {}
for k, v in rtti.vtables.items():
    name = v if isinstance(v, str) else str(v)
    kk = k if isinstance(k, int) else None
    if re.search(r"RayResultCallback|Raycast", name + str(k)):
        want[k] = v
print("ray-related vtables:", {(hex(k) if isinstance(k, int) else k): v for k, v in want.items()})
for k, v in want.items():
    va = k if isinstance(k, int) else v
    if not isinstance(va, int):
        continue
    users = sorted(m["refs"].get(va, []))
    print(f"\n{v if isinstance(v, str) else k}: vtable {va:#x} written/used at:")
    for u in users:
        f = fn(u)
        print(f"   {u:#x} in fn {f:#x} {rtti.func_class.get(f, '')}  "
              f"{'; '.join(dict.fromkeys(m['fp'].get(f, [])))[:50]}")
