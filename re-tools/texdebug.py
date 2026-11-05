"""Per-level comparison of a game DDS against ddsmip.build() of its level 0."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import math, sys
sys.path.insert(0, crpaths.WORK)
import crpak, ddsmip
from PIL import ImageChops, ImageStat

D = crpaths.STOCK_DATA


def psnr_ch(a, b):
    diff = ImageChops.difference(a, b)
    out = []
    for rms in ImageStat.Stat(diff).rms:
        out.append(99.0 if rms == 0 else 20 * math.log10(255 / rms))
    return out


d = {}
for arc in ("Objects", "SD", "Textures", "World"):
    e, _, p, _ = crpak.load_archive(D, arc)
    d.update({n: x for (n, _, _), x in zip(e, p)})
for nm in sys.argv[1:]:
    x = d[nm]
    a = ddsmip.levels(x)
    b = ddsmip.levels(ddsmip.build(a[0], like=x))
    print(nm, ddsmip.info(x)["fmt"])
    for i, (u, v) in enumerate(zip(a, b)):
        print(f"   L{i} {str(u.size):<11} PSNR R,G,B,A: " + " ".join(f"{t:5.1f}" for t in psnr_ch(u, v))
              + f"   mean orig {[round(t) for t in ImageStat.Stat(u).mean]} new {[round(t) for t in ImageStat.Stat(v).mean]}")
