r"""texcheck.py - ddsmip.build() against EVERY DDS texture in the game's four archives.

For each original: decode level 0, rebuild it "like" the original, then check
  - the rebuild has the same format / size / mip count / byte length, and Pillow reads it;
  - uncompressed textures come back BYTE-EXACT;
  - level 0: colour as it is seen (premultiplied RGB x alpha) and alpha each >= 30 dB PSNR (DXT is
    lossy; 4-bit DXT3 alpha alone costs ~34 dB);
  - every mip level >= 4x4 is within compression error of an ideal premultiplied box downscale of
    level 0 (>= 26 dB, or no more than 1 dB worse than the developers' own 2005 mip of that level
    against the same ideal) - i.e. the chain is a faithful smaller copy, at least 2005 quality;
  - for information: how close our mips are to the ones the developers' 2005 tool made.
Usage: texcheck.py [--verbose]
"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak
import ddsmip
from PIL import Image, ImageChops, ImageStat

STOCK = crpaths.STOCK_DATA
VERBOSE = "--verbose" in sys.argv


def _db(rms):
    return 99.0 if rms == 0 else 20 * math.log10(255 / rms)


def seen_psnr(a, b):
    """(premultiplied-RGB PSNR, alpha PSNR)"""
    pa, pb = a.convert("RGBa"), b.convert("RGBa")
    rms = ImageStat.Stat(ImageChops.difference(pa, pb)).rms
    rgb = math.sqrt(sum(r * r for r in rms[:3]) / 3)
    return _db(rgb), _db(rms[3])


def ideal_chain(top, dims, fmt):
    """Uncompressed premultiplied box chain; for DXT1 each level's alpha cut to 1 bit with the same
    coverage rule the builder uses (the best a 1-bit format can hold)."""
    pm, out = top.convert("RGBa"), [top]
    for d in dims[1:]:
        pm = pm.reduce((pm.size[0] // d[0], pm.size[1] // d[1])) if pm.size[0] >= 2 * d[0] and \
            pm.size[1] >= 2 * d[1] else pm.resize(d, Image.Resampling.BOX)
        out.append(pm.convert("RGBA"))
    return [ddsmip._binary_alpha(x) for x in out] if fmt == "DXT1" else out


def coverage(img):
    h = img.getchannel("A").histogram()
    return sum(v * c for v, c in enumerate(h)) / 255 / (img.size[0] * img.size[1])


def main():
    rows, bad = [], []
    for arc in ("Objects", "SD", "Textures", "World"):
        entries, _, payloads, _ = crpak.load_archive(STOCK, arc)
        for (name, _, _), data in zip(entries, payloads):
            if not name.lower().endswith(".dds"):
                continue
            try:
                li = ddsmip.info(data)
                orig = ddsmip.levels(data)
                new = ddsmip.build(orig[0], like=data)
                ni = ddsmip.info(new)
                got = ddsmip.levels(new)
                Image.open(io.BytesIO(new)).load()
            except Exception as e:
                bad.append(f"{name}: {e}")
                continue
            shape = (ni["w"], ni["h"], ni["mips"], ni["fmt"]) == (li["w"], li["h"], li["mips"], li["fmt"]) \
                and len(new) == len(data)
            c0, a0 = seen_psnr(orig[0], got[0])
            ideal = ideal_chain(orig[0], li["dims"], li["fmt"])
            mip_ok = [min(seen_psnr(i, g)) for i, g, d in zip(ideal[1:], got[1:], li["dims"][1:]) if min(d) >= 4]
            mip_dev = [min(seen_psnr(i, o)) for i, o, d in zip(ideal[1:], orig[1:], li["dims"][1:]) if min(d) >= 4]
            mip_pass = all(m >= 26 or m >= dv - 1 for m, dv in zip(mip_ok, mip_dev))
            cov = max((abs(coverage(i) - coverage(g)) for i, g, d in zip(ideal, got, li["dims"]) if min(d) >= 4),
                      default=0.0)
            dev = [min(seen_psnr(o, g)) for o, g, d in zip(orig[1:], got[1:], li["dims"][1:]) if min(d) >= 8]
            exact = None
            if not li["fmt"].startswith("DXT"):
                exact = new[128:] == data[128:]
            ok = shape and (exact if exact is not None else min(c0, a0) >= 30) and mip_pass
            rows.append(dict(name=name, li=li, c0=c0, a0=a0, mip=min(mip_ok, default=None), cov=cov,
                             dev=sum(dev) / len(dev) if dev else None, exact=exact, ok=ok))
            if not ok:
                bad.append(f"{name}: shape {shape} L0 colour {c0:.1f} alpha {a0:.1f} dB, mips {mip_ok}")

    kinds = {}
    for r in rows:
        kinds.setdefault((r["li"]["fmt"], r["li"]["mips"] > 1), []).append(r)
    print(f"{len(rows)} DDS textures rebuilt like their originals:")
    for (fmt, mipped), v in sorted(kinds.items()):
        ex = [r["exact"] for r in v if r["exact"] is not None]
        line = f"  {fmt:<7} {'+ mips' if mipped else '1 level':<7} {len(v):>3} files  "
        if ex:
            line += f"all levels byte-exact {sum(ex)}/{len(ex)}"
        else:
            line += (f"L0 colour min {min(r['c0'] for r in v):5.1f} dB, alpha min {min(r['a0'] for r in v):5.1f} dB")
        if mipped and not ex:
            line += (f" | mips vs ideal min {min(r['mip'] for r in v if r['mip'] is not None):5.1f} dB, "
                     f"coverage off <= {100 * max(r['cov'] for r in v):.1f}%"
                     f" | vs 2005 mips avg {sum(r['dev'] for r in v if r['dev']) / len(v):4.1f} dB")
        print(line + f"   ok {sum(r['ok'] for r in v)}/{len(v)}")
    if VERBOSE:
        for r in rows:
            li = r["li"]
            print(f"    {'OK ' if r['ok'] else 'BAD'} {r['name']:<52} {li['fmt']} {li['w']}x{li['h']} mips {li['mips']}"
                  f"  L0 {r['c0']:5.1f}/{r['a0']:5.1f}" + (f"  mips {r['mip']:5.1f}" if r['mip'] else ""))
    for b in bad:
        print("  BAD", b)
    print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} textures OK, {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
