"""Phase 1c: every distance reader, labelled by its function's string fingerprint,
plus the capacity checks behind 'Trees/Grass objects too much!'."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *
import xmap
m = xmap.load()
S = m["starts"]

def func(va):
    i = bisect.bisect_right(S, va) - 1
    return S[i]

def fpr(f, n=4):
    ss = [s for s in m["fp"].get(f, []) if len(s) > 3]
    return "; ".join(dict.fromkeys(ss))[:150] if ss else "(no strings)"

def callers(f):
    return sorted({func(a) for a in m["refs"].get(f, [])})

def report(target, name):
    sites = m["refs"].get(target, [])
    byf = {}
    for a in sites:
        byf.setdefault(func(a), []).append(a)
    print(f"\n#### {name} (0x{target:08x}): {len(sites)} refs in {len(byf)} functions")
    for f, aa in sorted(byf.items()):
        own = fpr(f)
        # if the function itself has no strings, borrow its callers' fingerprints
        if own == "(no strings)":
            cs = callers(f)[:3]
            own = "callers: " + " | ".join(f"0x{c:08x}[{fpr(c)[:60]}]" for c in cs) if cs else own
        print(f"  func 0x{f:08x}  {own}")
        for a in aa[:4]:
            print(f"      0x{a:08x}  {m['insns'].get(a, '?')}")

report(0x012cc124, "VIEW DISTANCE setting, world units")
report(0x00590414, "600.0 far-plane constant")
report(0x012d0488, "TRAFFIC setting")
report(0x012cc120, "DETAILS setting")

print("\n#### capacity guards")
for s_va, s in m["strings"].items():
    if s in ("Trees objects too much!", "Grass objects too much!", "Active objects: %d",
             "Collision objects: %d", "View distance :", "FogParam", "FogColor"):
        for a in m["refs"].get(s_va, []):
            print(f"\n  '{s}' used at 0x{a:08x} in func 0x{func(a):08x}")
            print(dis(a - 0x30, 18))
