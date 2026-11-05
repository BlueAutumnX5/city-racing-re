"""End-to-end check of the texture path in assets.py (2026-10-04), WITHOUT touching the game:
extract everything to a scratch folder, edit two textures' PNGs (one recoloured at the same size, one
replaced at 2x resolution), build with the install folder pointed at another scratch folder, then
compare every archive entry with the stock one."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, shutil, sys, time
sys.path.insert(0, crpaths.WORK)
import assets, crpak, ddsmip
from PIL import Image

T = crpaths.work(r"re-tools\_assettest")
OUT, INST = os.path.join(T, "extract"), os.path.join(T, "install")
shutil.rmtree(T, ignore_errors=True)
os.makedirs(INST)
for f in os.listdir(assets.LIVE):                       # a copy of the LIVE archives (Car Tuner tune etc.)
    if f.lower().endswith((".hdr", ".pak")):
        shutil.copy2(os.path.join(assets.LIVE, f), INST)
REAL_LIVE = assets.LIVE
assets.extract(OUT)
OK = []


def check(label, cond, extra=""):
    OK.append(bool(cond))
    print(("OK  " if cond else "BAD ") + label + (("  " + str(extra)) if extra else ""))


A = "Data/Vehicles/Elements.dds"                 # DXT3 512 + 10 mips: recolour, same size
B = "Data/Landscape/Surfaces/StreetDirt.dds"     # DXT? + mips: 2x sharper
pa = os.path.join(OUT, "files", *A.split("/")) + ".png"
pb = os.path.join(OUT, "files", *B.split("/")) + ".png"
time.sleep(1.2)
im = Image.open(pa).convert("RGBA")
r, g, b, a = im.split()
Image.merge("RGBA", (b, g, r, a)).save(pa)            # swap red/blue: an unmistakable edit
im2 = Image.open(pb).convert("RGBA")
big = im2.resize((im2.size[0] * 2, im2.size[1] * 2), Image.Resampling.LANCZOS)
big.save(pb)
os.utime(pa, (time.time() + 5, time.time() + 5))
os.utime(pb, (time.time() + 5, time.time() + 5))

assets.LIVE = INST
assets.BACKUP_ROOT = os.path.join(T, "backups")
before = {f: open(os.path.join(INST, f), "rb").read() for f in os.listdir(INST)}
assets.build(OUT, install=True)
for arc in ("Objects", "SD", "World"):
    check(f"{arc}: untouched by a texture build (your Car Tuner / traffic edits survive), not rewritten",
          all(open(os.path.join(INST, f"{arc}.{x}"), "rb").read() == before[f"{arc}.{x}"] for x in ("hdr", "pak")))
bk = os.path.join(assets.BACKUP_ROOT, os.listdir(assets.BACKUP_ROOT)[0]) if os.path.isdir(assets.BACKUP_ROOT) else ""
check("the replaced Textures archive was backed up first (and only it)",
      bk and sorted(os.listdir(bk)) == ["Textures.hdr", "Textures.pak"]
      and open(os.path.join(bk, "Textures.pak"), "rb").read() == before["Textures.pak"])

for arc in ("Objects", "SD", "Textures", "World"):
    se, _, sp, _ = crpak.load_archive(REAL_LIVE, arc)
    ne, _, np_, _ = crpak.load_archive(INST, arc)
    stock = {n: p for (n, _, _), p in zip(se, sp)}
    new = {n: p for (n, _, _), p in zip(ne, np_)}
    diff = [n for n in stock if new.get(n) != stock[n]]
    want = [x for x in (A, B) if x in stock]
    check(f"{arc}: {len(new)} entries, vs the live archive changed exactly {want or 'nothing'}",
          set(new) == set(stock) and sorted(diff) == sorted(want), diff[:5])
    for n in want:
        o, x = ddsmip.info(stock[n]), ddsmip.info(new[n])
        lv = ddsmip.levels(new[n])
        if n == A:
            src = Image.open(pa).convert("RGBA")
            same = (x["fmt"], x["w"], x["h"], x["mips"]) == (o["fmt"], o["w"], o["h"], o["mips"])
            px = lv[0].getpixel((100, 100)), src.getpixel((100, 100))
            close = all(abs(p - q) <= 12 for p, q in zip(*px))
            check(f"{A}: {x['fmt']} {x['w']}x{x['h']} with {x['mips']} levels like the original, holds the edit",
                  same and close, px)
        else:
            full = max(x["w"], x["h"]).bit_length()
            check(f"{B}: 2x replacement -> {x['fmt']} {x['w']}x{x['h']} (was {o['w']}x{o['h']}), "
                  f"{x['mips']} mip levels (full chain {full})",
                  x["fmt"] == o["fmt"] and (x["w"], x["h"]) == (2 * o["w"], 2 * o["h"])
                  and x["mips"] == (full if o["mips"] == max(o["w"], o["h"]).bit_length() else o["mips"])
                  and len(lv) == x["mips"] and lv[-1].size[0] >= 1)
print(f"\n{sum(OK)}/{len(OK)} checks passed")
shutil.rmtree(T, ignore_errors=True)
