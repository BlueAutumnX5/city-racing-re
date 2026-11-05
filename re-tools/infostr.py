import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.RETOOLS)
import xmap
m = xmap.load()
hits = {a: s for a, s in m["strings"].items() if "INFOSCREEN" in s.upper() or "SELFILLUM" in s.upper() or "InfoScreen" in s}
for a, s in sorted(hits.items()):
    users = sorted({__import__("rtti").containing(i) for i in m["refs"].get(a, [])})
    print(f"{a:#x}  {s[:60]!r:<62} used by {[hex(u) for u in users]}")
