"""Every caller of A* (0x0042d260), the path builder (0x00431350) and the traffic route
builder (0x004315e0), with the containing function and its string fingerprint."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
import xmap
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
for tgt, name in ((0x42d260, "A* 0x0042d260"), (0x431350, "path builder 0x00431350"),
                  (0x4315e0, "traffic route 0x004315e0"), (0x42db00, "ring point 0x0042db00")):
    refs = sorted(m["refs"].get(tgt, []))
    print(f"{name}: {len(refs)} reference(s)")
    for a in refs:
        f = fn(a)
        fp = "; ".join(dict.fromkeys(m["fp"].get(f, [])))[:60]
        print(f"   {a:#x}  {m['insns'].get(a, ''):<22} in fn {f:#x}  {fp}")
