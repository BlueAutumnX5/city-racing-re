r"""skyprep.py - turn the ESO Milky Way panorama into the game's night-sky texture (2026-10-04).

Source: ESO/S. Brunier, "The Milky Way panorama" (eso0932a), CC BY 4.0 - credit "ESO/S. Brunier".
6000x3000 equirectangular in galactic coordinates (centre = galactic centre, l grows to the left).
Output: assets_src/MilkyWay.jpg, 4096x2048 (power of two, as D3D9 wants), drawn ADDITIVELY over the
night sky - so the photo's grey sky background is pulled to true black (only the Milky Way and stars
add light) and a gentle curve keeps the faint dust lanes.
Usage: skyprep.py [black_percentile=35] [gain=1.15] [gamma=1.25]
"""
import os
import sys

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "assets_src", "eso0932a.jpg")
OUT = os.path.join(HERE, "assets_src", "MilkyWay.jpg")
PREVIEW = os.path.join(HERE, "assets_src", "MilkyWay_preview.png")
OUT_DDS = os.path.join(HERE, "assets_src", "MilkyWay.dds")
DDS_W = 8192                                   # 2026-10-04 "a bit higher": ALL 6000 source pixels (the GPU
                                               # wants powers of two, so 8192x4096); Intel UHD: max 16384
DDS_FMT = "DXT1"                               # 8192 DXT1 = 16 MB (uncompressed would be 128 MB - too much
                                               # for a 32-bit game); "RGBX" = the old uncompressed X8R8G8B8


def main(black_pct=35.0, gain=1.15, gamma=1.25):
    im = Image.open(SRC).convert("RGB")                         # full 6000x3000 (was cut to 4096 first)
    # the background level: a low percentile of a heavily blurred copy (stars removed)
    bg = im.resize((256, 128), Image.BOX).filter(ImageFilter.GaussianBlur(2))
    levels = []
    for ch in bg.split():
        hist = ch.histogram()
        total, acc = sum(hist), 0
        for v, n in enumerate(hist):
            acc += n
            if acc >= total * black_pct / 100:
                levels.append(v)
                break
    luts = []
    for black in levels:
        lut = []
        for v in range(256):
            x = max(0.0, (v - black) / (255 - black))          # background -> 0
            y = min(1.0, (x ** gamma) * gain)                  # deeper darks, a little lift on the core
            lut.append(int(round(y * 255)))
        luts.append(lut)
    r, g, b = im.split()
    out = Image.merge("RGB", (r.point(luts[0]), g.point(luts[1]), b.point(luts[2])))
    out.resize((4096, 2048), Image.LANCZOS).save(OUT, quality=93, subsampling=0, optimize=True)
    out.resize((1024, 512), Image.LANCZOS).save(PREVIEW)
    # 4096x2048 X8R8G8B8 = 32 MB; it loads fine (2026-10-04 live, laa on). 2048 = an 8 MB option
    big = out.resize((DDS_W, DDS_W // 2), Image.LANCZOS)
    if DDS_FMT == "DXT1":
        big.save(OUT_DDS, "DDS", pixel_format="DXT1")          # one level: the cave asks for 1 mip
    else:
        write_dds(big, OUT_DDS)
    print(f"background levels R/G/B {levels}; wrote {OUT} ({os.path.getsize(OUT):,} bytes), "
          f"{OUT_DDS} ({os.path.getsize(OUT_DDS):,} bytes) + preview")


def write_dds(im, path):
    """Uncompressed X8R8G8B8 DDS, one level. 2026-10-04: the 4096x2048 JPEG never loaded in the game
    (STATE 2 - its 2004 D3DX did not take it; every game JPEG is <= 1024); DDS needs no decoding, and a
    name without '.bmp' keeps the file's own format (like Data/Sky/Horizon.dds)."""
    import struct
    w, h = im.size
    hdr = struct.pack("<4sIIIIIII44x", b"DDS ", 124, 0x100F, h, w, w * 4, 0, 0)
    pf = struct.pack("<IIIIIIII", 32, 0x40, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0)
    caps = struct.pack("<IIII4x", 0x1000, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(hdr + pf + caps)
        f.write(im.convert("RGB").tobytes("raw", "BGRX"))


ENTRY = "Data/Sky/MilkyWay.dds"
OLD_ENTRIES = ("Data/Sky/MilkyWay.jpg",)          # the first (JPEG) try - removed on install


def install():
    """Add/replace Data/Sky/MilkyWay.dds in the LIVE Textures.pak (game closed; backup first). The entry
    is harmless while the milkyway extra is off; assets.py build keeps it (live-only entries survive)."""
    import datetime, shutil
    sys.path.insert(0, HERE)
    import crpak, racemod
    if racemod.game_running():
        sys.exit("ABORT: game.exe is running - close City Racing first.")
    live = crpak.GAME_DATA
    entries, stored, payloads, _ = crpak.load_archive(live, "Textures")
    names = [n for n, _, _ in entries]
    keep = [i for i, n in enumerate(names) if n not in OLD_ENTRIES]
    dropped = len(names) - len(keep)
    names, payloads = [names[i] for i in keep], [payloads[i] for i in keep]
    # RAW, like every texture: only Objects.pak .obj payloads are XOR 0x80 (crpak docstring). 2026-10-04:
    # this line used crpak.xor80 - the game read C4 C4 D3 A0 for "DDS ", and D3DX said
    # D3DXERR_INVALIDDATA (0x88760b59, found live with re-tools/mwprobe.py). THAT was the whole
    # "Milky Way never loads" bug (JPEG and DDS alike) - not size or address space.
    data = open(OUT_DDS, "rb").read()
    if ENTRY in names:
        i = names.index(ENTRY)
        if payloads[i] == data and names == sorted(names, key=str.lower) and not dropped:
            print("Textures.pak already has this MilkyWay.dds, in sorted order - nothing to do")
            return
        payloads[i] = data
    else:
        names.append(ENTRY)
        payloads.append(data)
    # sorted like the stock index (the game's lookup 0x0046fb50 is a linear search, so order is cosmetic)
    order = sorted(range(len(names)), key=lambda i: names[i].lower())
    names, payloads = [names[i] for i in order], [payloads[i] for i in order]
    hdr, pak = crpak.build_archive(names, payloads)
    bdir = os.path.join(HERE, "backups", datetime.date.today().isoformat() + "_before-milkyway")
    os.makedirs(bdir, exist_ok=True)
    for ext, blob in (("hdr", hdr), ("pak", pak)):
        dst = os.path.join(live, f"Textures.{ext}")
        if not os.path.exists(os.path.join(bdir, f"Textures.{ext}")):
            shutil.copy2(dst, os.path.join(bdir, f"Textures.{ext}"))
        with open(dst + ".new", "wb") as f:
            f.write(blob)
        os.replace(dst + ".new", dst)
    e, stored, p2, blob = crpak.load_archive(live, "Textures")
    ok = stored == len(e) and e[-1][1] + e[-1][2] == len(blob) and dict(zip([n for n, _, _ in e], p2))[ENTRY] == data
    print(f"Textures.pak: {len(e)} entries ({dropped} old entry removed), MilkyWay.dds {len(data):,} bytes - {'OK' if ok else 'BROKEN'} "
          f"(backup: {bdir})")


if __name__ == "__main__":
    if sys.argv[1:2] == ["install"]:
        install()
    else:
        a = [float(x) for x in sys.argv[1:]]
        main(*a)
