r"""ddsmip.py - build a DDS texture that matches a game original: same format, same size, SAME NUMBER
OF MIPMAP LEVELS (Stage 2 #3 groundwork, 2026-10-04).

Why: Pillow writes one level only, and assets.py's own encoder wrote one level as DXT5 whatever the
original was. 17 of the game's 69 DDS files carry a mip chain (the smaller copies the GPU uses for
distant / slanted surfaces); a replacement without them either shimmers in the distance or makes
D3DX build them itself at load. Uncompressed originals (32-bit) must stay uncompressed (lossless).

    ddsmip.info(data)                          -> dict(w, h, mips, fmt, size per level ...)
    ddsmip.build(image, like=original_bytes)   -> DDS bytes (image: PIL.Image or (w, h, rgba))
    ddsmip.levels(data)                        -> [PIL.Image RGBA per level] (decode, for checks)

Mip levels are made from the full-size picture by repeated 2x2 box averaging (what D3DX's default
box filter does), each level then compressed on its own with Pillow's DXT1/DXT3/DXT5 encoder.
"""
import io
import struct

from PIL import Image

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x1000, 0x20000, 0x80000
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB = 0x1, 0x4, 0x40


def info(data):
    if data[:4] != b"DDS ":
        raise ValueError("not a DDS file")
    flags, h, w, pitch, depth, mips = struct.unpack_from("<6I", data, 8)
    pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<I4s5I", data, 80)
    caps = struct.unpack_from("<I", data, 108)[0]
    if pf_flags & DDPF_FOURCC:
        fmt = fourcc.decode("latin-1")
        if fmt not in ("DXT1", "DXT3", "DXT5"):
            raise ValueError(f"unsupported DDS fourcc {fourcc!r}")
    elif pf_flags & DDPF_RGB and bits == 32:
        fmt = "RGBA32" if (pf_flags & DDPF_ALPHAPIXELS and am) else "RGBX32"
    else:
        raise ValueError(f"unsupported DDS pixel format flags={pf_flags:#x} bits={bits}")
    n = max(1, mips) if (flags & DDSD_MIPMAPCOUNT or caps & DDSCAPS_MIPMAP) else 1
    sizes, dims = [], []
    lw, lh = w, h
    for _ in range(n):
        dims.append((lw, lh))
        sizes.append(level_size(fmt, lw, lh))
        lw, lh = max(1, lw // 2), max(1, lh // 2)
    return dict(w=w, h=h, mips=n, fmt=fmt, flags=flags, caps=caps, pf=(pf_flags, fourcc, bits, rm, gm, bm, am),
                sizes=sizes, dims=dims, total=128 + sum(sizes), extra=len(data) - 128 - sum(sizes))


def level_size(fmt, w, h):
    if fmt in ("DXT1", "DXT3", "DXT5"):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == "DXT1" else 16)
    return w * h * 4


def _as_image(image):
    if isinstance(image, Image.Image):
        return image.convert("RGBA")
    w, h, rgba = image
    return Image.frombytes("RGBA", (w, h), bytes(rgba))


def _mip_chain(img, dims):
    """Level 0 = the picture itself; each smaller level is a 2x2 box average of the one above, done on
    PREMULTIPLIED colour (RGB x alpha) so transparent texels don't bleed black into cut-out edges
    (hair, branches, fonts)."""
    top = img if img.size == dims[0] else img.resize(dims[0], Image.Resampling.LANCZOS)
    out, pm = [top], top.convert("RGBa")
    for d in dims[1:]:
        if pm.size[0] >= 2 * d[0] and pm.size[1] >= 2 * d[1]:
            pm = pm.reduce((pm.size[0] // d[0], pm.size[1] // d[1]))
        else:
            pm = pm.resize(d, Image.Resampling.BOX)
        out.append(pm.convert("RGBA"))
    return out


def _dxt3_alpha(img):
    """DXT3's explicit 4-bit alpha, per 4x4 block in block order, rounded (a x 15 / 255). Written here
    because Pillow 12.3's DXT3 encoder stores the LOW four bits of alpha (3 -> 51, 15 -> 255)."""
    w, h = img.size
    a = img.getchannel("A").tobytes()
    out = []
    for by in range(0, max(h, 1), 4):
        for bx in range(0, max(w, 1), 4):
            v = 0
            for k in range(16):
                x, y = bx + (k & 3), by + (k >> 2)
                n = (a[y * w + x] * 15 + 127) // 255 if (x < w and y < h) else 0
                v |= n << (4 * k)
            out.append(v.to_bytes(8, "little"))
    return out


def _binary_alpha(img):
    """DXT1 has 1-bit alpha, and Pillow's DXT1 encoder makes every alpha >= 1 opaque - so a mip level's
    soft (averaged) edges would turn whole leaves and hair strands into solid blobs. Cut alpha to 0/255
    ourselves, at the level that keeps the same COVERAGE (share of opaque texels = mean alpha / 255):
    foliage keeps its density in the distance instead of thickening or vanishing."""
    a = img.getchannel("A")
    hist = a.histogram()
    n = img.size[0] * img.size[1]
    if hist[0] + hist[255] == n:
        return img
    want = round(sum(v * c for v, c in enumerate(hist)) / 255)         # opaque texels to keep
    keep, cut = 0, 256
    while cut > 1 and keep + hist[cut - 1] <= want:
        cut -= 1
        keep += hist[cut]
    if keep < want and cut > 1 and abs(keep + hist[cut - 1] - want) < abs(keep - want):
        cut -= 1                                                        # nearer with this bucket in
    mask = a.point(lambda v: 255 if v >= cut else 0)
    out = img.copy()
    out.putalpha(mask)
    return out


def _dxt5_alpha_block(vals):
    """Best DXT5 alpha block for up to 16 values (None = outside the picture), trying both modes."""
    real = [v for v in vals if v is not None]
    if not real:
        return bytes(8)
    best = None
    hi, lo = max(real), min(real)
    if hi == lo:
        return bytes((hi, lo)) + bytes(6)
    cands = [(hi, lo, [hi, lo] + [((7 - k) * hi + k * lo) // 7 for k in range(1, 7)])]
    mid = [v for v in real if 0 < v < 255]
    if mid:
        a0, a1 = min(mid), max(mid)
        cands.append((a0, a1, [a0, a1] + [((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)] + [0, 255]))
    for a0, a1, pal in cands:
        codes, err = [], 0
        for v in vals:
            if v is None:
                codes.append(0)
                continue
            c = min(range(8), key=lambda i: abs(pal[i] - v))
            err += (pal[c] - v) ** 2
            codes.append(c)
        if best is None or err < best[0]:
            bits = 0
            for k, c in enumerate(codes):
                bits |= c << (3 * k)
            best = (err, bytes((a0, a1)) + bits.to_bytes(6, "little"))
    return best[1]


def _dxt5_alpha(img):
    w, h = img.size
    a = img.getchannel("A").tobytes()
    out = []
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            out.append(_dxt5_alpha_block([a[(by + (k >> 2)) * w + bx + (k & 3)]
                                          if (bx + (k & 3) < w and by + (k >> 2) < h) else None
                                          for k in range(16)]))
    return out


def _e565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _q565(c):
    r, g, b = (min(31, max(0, round(c[0] * 31 / 255))), min(63, max(0, round(c[1] * 63 / 255))),
               min(31, max(0, round(c[2] * 31 / 255))))
    return (r << 11) | (g << 5) | b


_W4 = ((1.0, 0.0), (0.0, 1.0), (2 / 3, 1 / 3), (1 / 3, 2 / 3))


def _block_err(px, c0, c1):
    """(error, index bits) of 4-colour mode endpoints c0, c1 (565 ints) for weighted texels."""
    e0, e1 = _e565(c0), _e565(c1)
    pal = [e0, e1, tuple((2 * a + b) // 3 for a, b in zip(e0, e1)), tuple((a + 2 * b) // 3 for a, b in zip(e0, e1))]
    err, bits = 0.0, 0
    for k, p in enumerate(px):
        if p is None:
            continue
        r, g, b, w = p
        best, bd = 0, None
        for i, q in enumerate(pal):
            d = (r - q[0]) ** 2 + (g - q[1]) ** 2 + (b - q[2]) ** 2
            if bd is None or d < bd:
                best, bd = i, d
        err += w * bd
        bits |= best << (2 * k)
    return err, bits


def _refine_colour(blk, px, dxt1):
    """Least-squares endpoint refinement of one colour block (Pillow's endpoints as the start).
    px: 16 x (r, g, b, weight) or None outside the picture. Returns the better of the two blocks."""
    c0, c1, bits0 = struct.unpack("<HHI", blk)
    if dxt1 and c0 <= c1:                       # 3-colour / transparent block: keep Pillow's
        return blk
    best_err, _ = _block_err(px, c0, c1)
    best = blk
    cur = (c0, c1)
    for _ in range(3):
        _, bits = _block_err(px, *cur)
        s_aa = s_ab = s_bb = 0.0
        s_ax, s_bx = [0.0] * 3, [0.0] * 3
        for k, p in enumerate(px):
            if p is None:
                continue
            a, b = _W4[(bits >> (2 * k)) & 3]
            w = p[3]
            s_aa += w * a * a; s_ab += w * a * b; s_bb += w * b * b
            for ch in range(3):
                s_ax[ch] += w * a * p[ch]; s_bx[ch] += w * b * p[ch]
        det = s_aa * s_bb - s_ab * s_ab
        if abs(det) < 1e-9:
            break
        e0 = [(s_bb * s_ax[ch] - s_ab * s_bx[ch]) / det for ch in range(3)]
        e1 = [(s_aa * s_bx[ch] - s_ab * s_ax[ch]) / det for ch in range(3)]
        n0, n1 = _q565(e0), _q565(e1)
        if dxt1 and n0 < n1:
            n0, n1 = n1, n0
        if dxt1 and n0 == n1:
            break
        if (n0, n1) == cur:
            break
        cur = (n0, n1)
        err, bits = _block_err(px, n0, n1)
        if err < best_err:
            best_err, best = err, struct.pack("<HHI", n0, n1, bits)
    return best


def _refine_all(img, data, stride, off):
    """Refine every colour block of one encoded level (stride 8 for DXT1, 16 with the colour at +8)."""
    w, h = img.size
    raw = img.tobytes()
    out = bytearray(data)
    i = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            px = []
            for k in range(16):
                x, y = bx + (k & 3), by + (k >> 2)
                if x < w and y < h:
                    j = (y * w + x) * 4
                    px.append((raw[j], raw[j + 1], raw[j + 2], max(raw[j + 3], 8) / 255))
                else:
                    px.append(None)
            p = i * stride + off
            out[p:p + 8] = _refine_colour(bytes(out[p:p + 8]), px, stride == 8)
            i += 1
    return bytes(out)


def _encode_level(img, fmt, pf):
    if fmt == "DXT1":
        b = io.BytesIO()
        img = _binary_alpha(img)
        img.save(b, "DDS", pixel_format="DXT1")
        return _refine_all(img, b.getvalue()[128:128 + level_size(fmt, *img.size)], 8, 0)
    if fmt in ("DXT3", "DXT5"):         # Pillow's colour blocks (4-colour, the same in both) + our alpha
        b = io.BytesIO()
        img.save(b, "DDS", pixel_format="DXT5")
        d5 = _refine_all(img, b.getvalue()[128:128 + level_size("DXT5", *img.size)], 16, 8)
        alpha = _dxt3_alpha(img) if fmt == "DXT3" else _dxt5_alpha(img)
        return b"".join(alpha[i] + d5[16 * i + 8:16 * i + 16] for i in range(len(alpha)))
    _, _, _, rm, gm, bm, am = pf
    r, g, b_, a = img.split()
    shift = lambda m: (m & -m).bit_length() - 1 if m else None
    order = sorted(((shift(m), ch) for m, ch in ((rm, r), (gm, g), (bm, b_), (am, a)) if m),
                   key=lambda x: x[0])
    # 32-bit with 8-bit masks: assemble little-endian bytes in mask order (A8R8G8B8 -> B, G, R, A)
    lanes = {s // 8: ch for s, ch in order}
    filler = Image.new("L", img.size, 255)
    chans = [lanes.get(i, filler) for i in range(4)]
    return Image.merge("RGBA", chans).tobytes()


def build(image, like):
    """A DDS with the original's format, size and mip count, holding `image` (resized if needed)."""
    li = info(like)
    img = _as_image(image)
    if img.size != (li["w"], li["h"]):
        # A different size (e.g. a 2x sharper replacement): the game loads DDS through D3DX, which takes
        # the size from the file, and texture coordinates are 0..1, so the same layout at another size
        # works. Kept to power-of-two sides (what 2005 hardware and the game's own files use; DXT also
        # needs multiples of 4), and the mip chain is rebuilt for the new size: full if the original's
        # was full, otherwise as many levels as the original had.
        w, h = img.size
        pow2 = lambda n: n > 0 and n & (n - 1) == 0
        if not (pow2(w) and pow2(h)) or (li["fmt"].startswith("DXT") and (w < 4 or h < 4)):
            raise ValueError(f"picture is {w}x{h}: a replacement of another size than the original "
                             f"({li['w']}x{li['h']}) must have power-of-two sides (64, 128, 256, 512, 1024, 2048...)")
        full = li["mips"] == max(li["w"], li["h"]).bit_length()
        n = max(w, h).bit_length() if full else min(li["mips"], max(w, h).bit_length())
        dims, lw, lh = [], w, h
        for _ in range(n):
            dims.append((lw, lh))
            lw, lh = max(1, lw // 2), max(1, lh // 2)
        li = dict(li, w=w, h=h, mips=n, dims=dims, sizes=[level_size(li["fmt"], *d) for d in dims])
    chain = _mip_chain(img, li["dims"])
    body = b"".join(_encode_level(lv, li["fmt"], li["pf"]) for lv in chain)
    hdr = bytearray(like[:128])                     # keep every original header field...
    flags = li["flags"] | DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = li["caps"] | DDSCAPS_TEXTURE
    if li["mips"] > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    if li["fmt"].startswith("DXT"):
        flags = (flags | DDSD_LINEARSIZE) & ~DDSD_PITCH
        pitch = li["sizes"][0]
    else:
        flags = (flags | DDSD_PITCH) & ~DDSD_LINEARSIZE
        pitch = li["w"] * 4
    struct.pack_into("<I", hdr, 8, flags)           # ...but make the ones that describe the data right
    struct.pack_into("<II", hdr, 12, li["h"], li["w"])
    struct.pack_into("<I", hdr, 20, pitch)
    struct.pack_into("<I", hdr, 28, li["mips"] if li["mips"] > 1 else struct.unpack_from("<I", like, 28)[0])
    struct.pack_into("<I", hdr, 108, caps)
    orig = info(like)
    tail = like[128 + sum(orig["sizes"]):] if (li["w"], li["h"]) == (orig["w"], orig["h"]) else b""
    return bytes(hdr) + body + tail


def levels(data):
    """Every mip level decoded to RGBA (Pillow reads level 0; each level is re-wrapped on its own)."""
    li = info(data)
    out, off = [], 128
    for (w, h), size in zip(li["dims"], li["sizes"]):
        hdr = bytearray(data[:128])
        struct.pack_into("<II", hdr, 12, h, w)
        struct.pack_into("<I", hdr, 28, 0)
        struct.pack_into("<I", hdr, 8, struct.unpack_from("<I", hdr, 8)[0] & ~DDSD_MIPMAPCOUNT)
        struct.pack_into("<I", hdr, 108, DDSCAPS_TEXTURE)
        struct.pack_into("<I", hdr, 20, size if li["fmt"].startswith("DXT") else w * 4)
        out.append(Image.open(io.BytesIO(bytes(hdr) + data[off:off + size])).convert("RGBA"))
        off += size
    return out
