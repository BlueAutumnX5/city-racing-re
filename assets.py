r"""City Racing asset pipeline - extract everything to editable formats, and build it back.

    assets.py extract <outdir>     unpack all four archives into editable files
    assets.py build   <outdir>     rebuild the archives and install them
    assets.py status  <outdir>     show what you have edited since extracting

What you get per type:

    .obj  configs   plain text, already de-obfuscated  -> edit in any text editor
    .wav  audio     untouched RIFF                     -> edit in Audacity
    .jpg  textures  untouched JPEG                     -> edit anywhere
    .dds  textures  untouched, PLUS a decoded .png     -> edit the .png
    .msh  meshes    untouched, PLUS a Wavefront .obj    -> edit in Blender (form A only)
    .dat            untouched

On build, a sidecar that is NEWER than its source wins - so editing `Foo.dds.png` and
running build re-encodes it into the archive. Everything else is copied through byte-exact,
so untouched assets round-trip perfectly.

The PNG writer and the DXT1/3/5 decoder are implemented here directly. Re-encoding an edited
texture uses ddsmip.py (Pillow, installed 2026-09-27): same format as the original, its mipmap chain
rebuilt, power-of-two sharper replacements allowed (texcheck.py proves it on all 69 game DDS files).
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import json
import math
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
LIVE = crpaths.LIVE_DATA
MSH_STRIDE_A, MSH_FOOTER = 44, 40
BACKUP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")


def _geom_equivalent(a, b):
    """Byte-compare two geometry blocks, treating any two NaNs as equal.

    Some meshes ship NaN normals with the sign bit set (0xFFC00000). A text round-trip
    turns those into Python's default quiet NaN (0x7FC00000) - the same value, different
    bits. Without this, an untouched mesh looks 'edited' and gets needlessly rebuilt.
    Index data cannot false-positive here: indices are small u16s, and forming a NaN
    bit pattern would need values above 32000, far beyond any vertex count in this game.
    """
    if len(a) != len(b):
        return False
    if a == b:
        return True
    if len(a) % 4:
        return False
    for i in range(0, len(a), 4):
        if a[i:i + 4] == b[i:i + 4]:
            continue
        x, = struct.unpack_from("<f", a, i)
        y, = struct.unpack_from("<f", b, i)
        if x != x and y != y:
            continue
        return False
    return True


# --------------------------------------------------------------------- PNG io

def png_write(path, w, h, rgba):
    """rgba: bytes, w*h*4 RGBA."""
    rows = []
    for y in range(h):
        rows.append(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4])
    raw = b"".join(rows)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6))
                + chunk(b"IEND", b""))


def png_read(path):
    """Minimal PNG reader: 8-bit RGB/RGBA, non-interlaced. -> (w, h, rgba bytes)"""
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    i, idat, w = 8, [], None
    while i < len(d):
        ln = struct.unpack_from(">I", d, i)[0]
        tag = d[i + 4:i + 8]
        body = d[i + 8:i + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack_from(">IIBB", body, 0)
            inter = body[12]
            if depth != 8 or ctype not in (2, 6) or inter:
                raise ValueError(f"unsupported PNG: depth={depth} ctype={ctype}")
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        i += 12 + ln
    raw = zlib.decompress(b"".join(idat))
    nch = 3 if ctype == 2 else 4
    stride = w * nch
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - nch] if x >= nch else 0
            b = prev[x]
            c = prev[x - nch] if x >= nch else 0
            if ft == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ft == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ft == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        prev = line
        if nch == 3:
            for x in range(0, stride, 3):
                out += line[x:x + 3] + b"\xff"
        else:
            out += line
    return w, h, bytes(out)


# ------------------------------------------------------------------ DDS decode

def _c565(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _dxt_colours(blk, off, four_colour):
    c0, c1 = struct.unpack_from("<HH", blk, off)
    r0, g0, b0 = _c565(c0)
    r1, g1, b1 = _c565(c1)
    cols = [(r0, g0, b0, 255), (r1, g1, b1, 255)]
    if four_colour or c0 > c1:
        cols.append(((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255))
        cols.append(((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255))
    else:
        cols.append(((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255))
        cols.append((0, 0, 0, 0))
    return cols


def dds_decode(data):
    """-> (w, h, rgba) for mip level 0. Supports DXT1/3/5 and uncompressed 32-bit."""
    if data[:4] != b"DDS ":
        raise ValueError("not a DDS")
    h, w = struct.unpack_from("<II", data, 12)
    pf_flags, fourcc = struct.unpack_from("<I4s", data, 80)
    bitcount, rmask, gmask, bmask, amask = struct.unpack_from("<5I", data, 88)
    base = 128
    out = bytearray(w * h * 4)

    def put(x, y, rgba):
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 4
            out[i:i + 4] = bytes(rgba)

    if fourcc in (b"DXT1", b"DXT3", b"DXT5"):
        bs = 8 if fourcc == b"DXT1" else 16
        p = base
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                blk = data[p:p + bs]
                p += bs
                if len(blk) < bs:
                    break
                if fourcc == b"DXT1":
                    cols = _dxt_colours(blk, 0, False)
                    bits, = struct.unpack_from("<I", blk, 4)
                    alpha = None
                elif fourcc == b"DXT3":
                    a64, = struct.unpack_from("<Q", blk, 0)
                    cols = _dxt_colours(blk, 8, True)
                    bits, = struct.unpack_from("<I", blk, 12)
                    alpha = [((a64 >> (4 * k)) & 0xF) * 17 for k in range(16)]
                else:
                    a0, a1 = blk[0], blk[1]
                    abits = int.from_bytes(blk[2:8], "little")
                    at = [a0, a1]
                    if a0 > a1:
                        at += [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]
                    else:
                        at += [((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)]
                        at += [0, 255]
                    cols = _dxt_colours(blk, 8, True)
                    bits, = struct.unpack_from("<I", blk, 12)
                    alpha = [at[(abits >> (3 * k)) & 7] for k in range(16)]
                for k in range(16):
                    c = list(cols[(bits >> (2 * k)) & 3])
                    if alpha is not None:
                        c[3] = alpha[k]
                    put(bx + (k & 3), by + (k >> 2), c)
        return w, h, bytes(out)

    if pf_flags & 0x40 and bitcount == 32:          # DDPF_RGB, uncompressed
        p = base
        for y in range(h):
            for x in range(w):
                v, = struct.unpack_from("<I", data, p)
                p += 4
                put(x, y, ((v & rmask) >> (rmask.bit_length() - 8) if rmask else 0,
                           (v & gmask) >> (gmask.bit_length() - 8) if gmask else 0,
                           (v & bmask) >> (bmask.bit_length() - 8) if bmask else 0,
                           ((v & amask) >> (amask.bit_length() - 8)) if amask else 255))
        return w, h, bytes(out)

    raise ValueError(f"unsupported DDS: fourcc={fourcc!r} flags={pf_flags} bits={bitcount}")


# ------------------------------------------------------------------ DDS encode

def _fit565(c):
    r, g, b = c
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def dds_encode_dxt(w, h, rgba, fourcc=b"DXT5"):
    """Simple min/max-endpoint DXT encoder. Good enough for 2005-era textures."""
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr, 4, 124)
    struct.pack_into("<I", hdr, 8, 0x1 | 0x2 | 0x4 | 0x1000)       # caps|h|w|pixelformat
    struct.pack_into("<II", hdr, 12, h, w)
    struct.pack_into("<I", hdr, 76, 32)
    struct.pack_into("<I", hdr, 80, 4)                              # DDPF_FOURCC
    hdr[84:88] = fourcc
    struct.pack_into("<I", hdr, 108, 0x1000)                        # DDSCAPS_TEXTURE
    out = bytearray(hdr)

    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            px = []
            for k in range(16):
                x, y = bx + (k & 3), by + (k >> 2)
                if x < w and y < h:
                    i = (y * w + x) * 4
                    px.append(tuple(rgba[i:i + 4]))
                else:
                    px.append((0, 0, 0, 255))
            if fourcc == b"DXT5":
                al = [p[3] for p in px]
                a0, a1 = max(al), min(al)
                out += bytes((a0, a1))
                if a0 == a1:
                    out += b"\x00" * 6
                else:
                    bits = 0
                    for k, a in enumerate(al):
                        t = (a0 - a) * 7 // (a0 - a1)
                        code = 0 if t == 0 else (1 if t == 7 else t + 1)
                        bits |= code << (3 * k)
                    out += bits.to_bytes(6, "little")
            elif fourcc == b"DXT3":
                a64 = 0
                for k, p in enumerate(px):
                    a64 |= (p[3] >> 4) << (4 * k)
                out += a64.to_bytes(8, "little")

            lum = [0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in px]
            cmin = px[lum.index(min(lum))][:3]
            cmax = px[lum.index(max(lum))][:3]
            c0, c1 = _fit565(cmax), _fit565(cmin)
            if c0 < c1:
                c0, c1 = c1, c0
                cmax, cmin = cmin, cmax
            if c0 == c1:
                out += struct.pack("<HHI", c0, c1, 0)
                continue
            pal = [cmax, cmin,
                   tuple((2 * cmax[i] + cmin[i]) // 3 for i in range(3)),
                   tuple((cmax[i] + 2 * cmin[i]) // 3 for i in range(3))]
            bits = 0
            for k, p in enumerate(px):
                best, bd = 0, 1 << 30
                for ci, c in enumerate(pal):
                    d = ((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2)
                    if d < bd:
                        best, bd = ci, d
                bits |= best << (2 * k)
            out += struct.pack("<HHI", c0, c1, bits)
    return bytes(out)


# ------------------------------------------------------------------- MSH form A

def msh_is_simple(p):
    v, t = struct.unpack_from("<II", p, 0)
    return len(p) == 8 + v * MSH_STRIDE_A + t * 6 + MSH_FOOTER


def msh_to_obj(p, name):
    v, t = struct.unpack_from("<II", p, 0)
    lines = [f"# exported from City Racing {name}",
             f"# {v} vertices, {t} triangles, .msh form A (stride 44)",
             "# vertex colour and uv1 are preserved in the .msh and restored on import"]
    for k in range(v):
        o = 8 + k * MSH_STRIDE_A
        x, y, z, nx, ny, nz = struct.unpack_from("<6f", p, o)
        u, vv = struct.unpack_from("<2f", p, o + 28)
        # 9 significant digits is the minimum that round-trips float32 exactly
        lines.append(f"v {x:.9g} {y:.9g} {z:.9g}")
        lines.append(f"vn {nx:.9g} {ny:.9g} {nz:.9g}")
        lines.append(f"vt {u:.9g} {vv:.9g}")
    ib = 8 + v * MSH_STRIDE_A
    idx = struct.unpack_from(f"<{t * 3}H", p, ib)
    for k in range(t):
        a, b, c = idx[k * 3] + 1, idx[k * 3 + 1] + 1, idx[k * 3 + 2] + 1
        lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- MSH form B
#
#   u32 A[16] @0x00   kind flags (1, 2, or 90)
#   u32 B[16] @0x40   vertex count per slot
#   u32 C[16] @0x80   triangle count per slot
#   bounds[nslots] @0xC0   40 bytes each: min(3f) max(3f) centre(3f) radius(1f)
#   per slot, contiguous:  vertex[B] stride 32 (pos3, normal3, uv2), u16 index[C*3]
#   tail                   64-196 bytes, contents not yet decoded - preserved verbatim
MSH_STRIDE_B = 32


def msh_b_slots(p):
    w = struct.unpack_from("<48I", p, 0)
    A, B, C = w[0:16], w[16:32], w[32:48]
    return [(i, A[i], B[i], C[i]) for i in range(16) if A[i] or B[i]]


def msh_b_parse(p):
    """-> (slots, offsets, tail_offset) or None if the layout does not fit."""
    sl = msh_b_slots(p)
    if not sl:
        return None
    off = 192 + len(sl) * 40
    offs = []
    for (_, _, b, c) in sl:
        vo = off
        io = vo + b * MSH_STRIDE_B
        off = io + c * 6
        if off > len(p):
            return None
        offs.append((vo, io))
    return sl, offs, off


def mshb_to_obj(p, name):
    parsed = msh_b_parse(p)
    if parsed is None:
        return None
    sl, offs, tail = parsed
    lines = [f"# exported from City Racing {name}",
             f"# .msh form B - {len(sl)} slot(s), vertex stride 32 (pos, normal, uv)",
             "# one group per slot; keep the group order and count when re-importing"]
    vbase = 0
    for (si, (i, a, b, c)) in enumerate(sl):
        vo, io = offs[si]
        lines.append(f"g slot_{i}_kind{a}")
        for k in range(b):
            o = vo + k * MSH_STRIDE_B
            x, y, z, nx, ny, nz, u, v = struct.unpack_from("<8f", p, o)
            lines.append(f"v {x:.9g} {y:.9g} {z:.9g}")
            lines.append(f"vn {nx:.9g} {ny:.9g} {nz:.9g}")
            lines.append(f"vt {u:.9g} {v:.9g}")
        idx = struct.unpack_from(f"<{c * 3}H", p, io)
        for k in range(c):
            t = [idx[k * 3] + 1 + vbase, idx[k * 3 + 1] + 1 + vbase,
                 idx[k * 3 + 2] + 1 + vbase]
            lines.append("f " + " ".join(f"{q}/{q}/{q}" for q in t))
        vbase += b
    return "\n".join(lines) + "\n"


def obj_to_mshb(text, original):
    """Rebuild a form-B .msh. A-flags and the undecoded tail are preserved from the
    original; counts and per-slot bounds are recomputed from the OBJ."""
    parsed = msh_b_parse(original)
    if parsed is None:
        return original
    osl, ooffs, otail = parsed

    groups, cur = [], None
    pos, nrm, uv = [], [], []
    for line in text.splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == "g":
            cur = {"name": w[1] if len(w) > 1 else "", "faces": [], "v0": len(pos)}
            groups.append(cur)
        elif w[0] == "v":
            pos.append(tuple(float(x) for x in w[1:4]))
        elif w[0] == "vn":
            nrm.append(tuple(float(x) for x in w[1:4]))
        elif w[0] == "vt":
            uv.append(tuple(float(x) for x in w[1:3]))
        elif w[0] == "f" and cur is not None:
            cur["faces"].append([int(t.split("/")[0]) - 1 for t in w[1:4]])
    if len(groups) != len(osl):
        raise ValueError(f"expected {len(osl)} slots, OBJ has {len(groups)} groups")

    A = [0] * 16
    B = [0] * 16
    C = [0] * 16
    bounds, blocks = [], []
    for gi, (i, a, _, _) in enumerate(osl):
        g = groups[gi]
        v0 = g["v0"]
        v1 = groups[gi + 1]["v0"] if gi + 1 < len(groups) else len(pos)
        nv = v1 - v0
        A[i], B[i], C[i] = a, nv, len(g["faces"])
        vb = bytearray()
        for k in range(v0, v1):
            px, py, pz = pos[k]
            nx, ny, nz = nrm[k] if k < len(nrm) else (0.0, 1.0, 0.0)
            u, v = uv[k] if k < len(uv) else (0.0, 0.0)
            vb += struct.pack("<8f", px, py, pz, nx, ny, nz, u, v)
        ib = bytearray()
        for f in g["faces"]:
            ib += struct.pack("<3H", *(q - v0 for q in f))
        blocks.append(bytes(vb) + bytes(ib))
        pts = pos[v0:v1] or [(0.0, 0.0, 0.0)]
        mn = tuple(min(p[j] for p in pts) for j in range(3))
        mx = tuple(max(p[j] for p in pts) for j in range(3))
        ct = tuple(sum(p[j] for p in pts) / len(pts) for j in range(3))
        rad = max(math.dist(p, ct) for p in pts)
        bounds.append(struct.pack("<10f", *mn, *mx, *ct, rad))

    out = bytearray()
    out += struct.pack("<16I", *A) + struct.pack("<16I", *B) + struct.pack("<16I", *C)
    for bl in bounds:
        out += bl
    for bl in blocks:
        out += bl
    out += original[otail:]
    result = bytes(out)
    # unchanged geometry -> hand back the original bytes, so bounds recomputed through
    # Python doubles cannot make an untouched mesh drift
    if (len(result) == len(original) and _geom_equivalent(
            result[192 + len(osl) * 40:], original[192 + len(osl) * 40:])):
        return original
    return result


def obj_to_msh(text, original):
    """Rebuild a form-A .msh, taking positions/normals/uvs from the OBJ and keeping
    colour + uv1 from the original mesh where vertex counts still line up."""
    pos, nrm, uv, faces = [], [], [], []
    for line in text.splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == "v":
            pos.append(tuple(float(x) for x in w[1:4]))
        elif w[0] == "vn":
            nrm.append(tuple(float(x) for x in w[1:4]))
        elif w[0] == "vt":
            uv.append(tuple(float(x) for x in w[1:3]))
        elif w[0] == "f":
            ix = [int(t.split("/")[0]) - 1 for t in w[1:4]]
            faces.append(ix)
    v, t = len(pos), len(faces)
    ov, ot = struct.unpack_from("<II", original, 0)
    out = bytearray(struct.pack("<II", v, t))
    for k in range(v):
        px, py, pz = pos[k]
        nx, ny, nz = nrm[k] if k < len(nrm) else (0.0, 1.0, 0.0)
        u, vv = uv[k] if k < len(uv) else (0.0, 0.0)
        if k < ov:
            o = 8 + k * MSH_STRIDE_A
            colour, = struct.unpack_from("<I", original, o + 24)
            u1, v1 = struct.unpack_from("<2f", original, o + 36)
        else:
            colour, u1, v1 = 0xFFFFFFFF, u, vv
        out += struct.pack("<6f", px, py, pz, nx, ny, nz)
        out += struct.pack("<I", colour)
        out += struct.pack("<4f", u, vv, u1, v1)
    for f in faces:
        out += struct.pack("<3H", *f)
    # footer: keep the original's if the shape is unchanged, else recompute
    cx = sum(p[0] for p in pos) / v
    cy = sum(p[1] for p in pos) / v
    cz = sum(p[2] for p in pos) / v
    rad = max(((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2) ** 0.5
              for p in pos)
    foot = bytearray(original[-MSH_FOOTER:])
    struct.pack_into("<4f", foot, 24, cx, cy, cz, rad)
    out += foot
    result = bytes(out)
    # If the geometry is byte-identical to the original, keep the original footer too.
    # Recomputing centre/radius through Python doubles lands on a slightly different
    # float32 than the game stored, which would make an untouched mesh drift.
    if (len(result) == len(original) and _geom_equivalent(
            result[:-MSH_FOOTER], original[:-MSH_FOOTER])):
        return original
    return result


# ------------------------------------------------------------------- .dat kinds
#
# Decoded 2026-09-21:
#   Interface/Fonts/*/Main.dat   XOR 0x80 text - the font's character map, in glyph order
#   Interface/Fonts/*/Mask.dat   1 byte/pixel glyph bitmap, 256^2 or 512^2, only 0 and 255
#   Landscape/PlaceColor.dat     300 x 300 x 3 RGB terrain colour map (270,000 bytes exact)
#   Landscape/*Map.dat           600 x 600 (or 200 x 200) uint8 grids
# Still opaque:
#   Landscape/<sector>/MeshShape.dat  serialised C++ structs - contains 0xCDCDCDCD (MSVC
#                                     uninitialised-heap fill) and stale pointers
#   Vehicles/*/MainExtra.dat          header is cumulative vertex/triangle totals matching
#                                     the .msh slot counts, then float data
#   Landscape/GlobalRoute.dat         600 x 600 x 48 = 12 floats per world cell

GRID8 = ("WayPointsMap.dat", "StaticObjectsPlaceMap.dat", "TrafficDensityMap.dat")


def dat_kind(name, payload):
    base = os.path.basename(name)
    if "/Fonts/" in name and base == "Main.dat":
        return "fonttext"
    if "/Fonts/" in name and base == "Mask.dat":
        return "fontmask"
    if base == "PlaceColor.dat" and len(payload) == 300 * 300 * 3:
        return "placecolor"
    if base in GRID8:
        side = int(len(payload) ** 0.5)
        if side * side == len(payload):
            return "grid8"
    return None


# ---------------------------------------------------------------------- driver

def extract(outdir):
    os.makedirs(outdir, exist_ok=True)
    manifest = {"archives": {}}
    counts = {"obj": 0, "dds": 0, "png": 0, "jpg": 0, "wav": 0,
              "msh": 0, "msh_obj": 0, "msh_readonly": 0, "dat": 0, "dat_text": 0, "dat_png": 0, "other": 0, "failed": 0}

    for arc in crpak.ARCHIVES:
        entries, stored, payloads, _ = crpak.load_archive(STOCK, arc)
        names = [n for n, _, _ in entries]
        manifest["archives"][arc] = names
        for name, payload in zip(names, payloads):
            rel = name.replace("/", os.sep)
            dst = os.path.join(outdir, "files", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            low = name.lower()
            if low.endswith(".obj"):
                with open(dst, "wb") as f:
                    f.write(crpak.xor80(payload))
                counts["obj"] += 1
                continue
            with open(dst, "wb") as f:
                f.write(payload)
            if low.endswith(".dds"):
                counts["dds"] += 1
                try:
                    w, h, rgba = dds_decode(payload)
                    png_write(dst + ".png", w, h, rgba)
                    counts["png"] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    print(f"    dds decode failed: {name}: {exc}")
            elif low.endswith(".msh"):
                counts["msh"] += 1
                # Only offer an editable sidecar when export+import is provably
                # byte-exact. If there is a .obj beside a .msh, editing it is safe.
                try:
                    if msh_is_simple(payload):
                        text = msh_to_obj(payload, name)
                        ok = obj_to_msh(text, payload) == payload
                    else:
                        text = mshb_to_obj(payload, name)
                        ok = text is not None and obj_to_mshb(text, payload) == payload
                except Exception:
                    text, ok = None, False
                if ok:
                    with open(dst + ".obj", "w", encoding="utf-8") as f:
                        f.write(text)
                    counts["msh_obj"] += 1
                else:
                    counts["msh_readonly"] += 1
            elif low.endswith(".jpg"):
                counts["jpg"] += 1
            elif low.endswith(".wav"):
                counts["wav"] += 1
            elif low.endswith(".dat"):
                counts["dat"] += 1
                kind = dat_kind(name, payload)
                if kind == "fonttext":
                    with open(dst + ".txt", "wb") as f:
                        f.write(crpak.xor80(payload))
                    counts["dat_text"] += 1
                elif kind == "fontmask":
                    side = int(len(payload) ** 0.5)
                    png_write(dst + ".png", side, side,
                              b"".join(bytes((v, v, v, 255)) for v in payload))
                    counts["dat_png"] += 1
                elif kind == "placecolor":
                    png_write(dst + ".png", 300, 300,
                              b"".join(payload[i:i + 3] + b"\xff"
                                       for i in range(0, len(payload), 3)))
                    counts["dat_png"] += 1
                elif kind == "grid8":
                    side = int(len(payload) ** 0.5)
                    png_write(dst + ".png", side, side,
                              b"".join(bytes((v, v, v, 255)) for v in payload))
                    counts["dat_png"] += 1
            else:
                counts["other"] += 1

    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"\nextracted to {outdir}")
    for k, v in counts.items():
        print(f"   {k:<9} {v:>5}")
    print("\nedit these, then run:  assets.py build <outdir>")
    print("   *.obj  (text)   car and object configs")
    print("   *.dds.png       textures - edit the PNG, the DDS is re-encoded")
    print("   *.msh.obj       meshes - edit in Blender, form A only")
    print("   *.wav *.jpg     replace directly")


def newer(a, b):
    return os.path.exists(a) and os.path.getmtime(a) > os.path.getmtime(b) + 1


def build(outdir, install=True):
    """Rebuild the archives from the extracted folder.

    2026-10-04: an entry you did NOT edit is taken from the LIVE archive, not from the stock one, and
    an archive is only written when it actually changes - so edits made by the other tools (the Car
    Tuner's car stats in Objects.pak, trafficmod's World.pak) survive a texture/mesh build. Before,
    every build rebuilt all four archives from stock and silently undid them. Each archive that is
    replaced is first copied to backups/<date>_before-assets/."""
    with open(os.path.join(outdir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    changed, conflicts = [], []
    for arc, names in manifest["archives"].items():
        entries, _, orig_payloads, _ = crpak.load_archive(STOCK, arc)
        orig = {n: p for (n, _, _), p in zip(entries, orig_payloads)}
        try:
            le, _, lp, _ = crpak.load_archive(LIVE, arc)
            live = {n: p for (n, _, _), p in zip(le, lp)}
        except OSError:
            live = {}
        payloads = []
        for name in names:
            rel = name.replace("/", os.sep)
            src = os.path.join(outdir, "files", rel)
            low = name.lower()
            if low.endswith(".obj"):
                data = crpak.xor80(open(src, "rb").read())
            elif low.endswith(".dds") and newer(src + ".png", src):
                w, h, rgba = png_read(src + ".png")
                try:
                    # 2026-10-04: ddsmip keeps the original's format AND its mipmap chain (17 of the 69
                    # textures have one), and allows power-of-two sharper replacements. texcheck.py: 69/69.
                    import ddsmip
                    data = ddsmip.build((w, h, rgba), like=orig[name])
                    li = ddsmip.info(data)
                    changed.append(f"{name}  <- PNG re-encoded as {li['fmt']} {li['w']}x{li['h']}"
                                   f"{', ' + str(li['mips']) + ' mip levels' if li['mips'] > 1 else ''}")
                except ImportError:
                    fourcc = struct.unpack_from("<4s", orig[name], 84)[0]
                    if fourcc not in (b"DXT3", b"DXT5"):
                        fourcc = b"DXT5"
                    data = dds_encode_dxt(w, h, rgba, fourcc)
                    changed.append(f"{name}  <- PNG re-encoded as {fourcc.decode()} (no Pillow: ONE level only)")
            elif low.endswith(".msh") and newer(src + ".obj", src):
                _t = open(src + ".obj", encoding="utf-8").read()
                data = (obj_to_msh(_t, orig[name]) if msh_is_simple(orig[name])
                        else obj_to_mshb(_t, orig[name]))
                changed.append(f"{name}  <- OBJ re-imported")
            elif low.endswith(".dat") and dat_kind(name, orig[name]):
                kind = dat_kind(name, orig[name])
                if kind == "fonttext" and newer(src + ".txt", src):
                    data = crpak.xor80(open(src + ".txt", "rb").read())
                elif kind in ("fontmask", "grid8") and newer(src + ".png", src):
                    w, h, rgba = png_read(src + ".png")
                    data = bytes(rgba[i] for i in range(0, len(rgba), 4))
                elif kind == "placecolor" and newer(src + ".png", src):
                    w, h, rgba = png_read(src + ".png")
                    data = b"".join(rgba[i:i + 3] for i in range(0, len(rgba), 4))
                else:
                    data = open(src, "rb").read()
            else:
                data = open(src, "rb").read()
            if data == orig[name]:
                data = live.get(name, data)              # untouched here: keep what is installed
            else:
                if not any(name in c for c in changed):
                    changed.append(f"{name}  <- file edited directly")
                if name in live and live[name] not in (orig[name], data):
                    conflicts.append(name)
            payloads.append(data)
        # entries that exist only in the LIVE archive (added by our tools, e.g. Data/Sky/MilkyWay.jpg
        # from skyprep.py / the milkyway extra) are kept at the end instead of being dropped
        names = list(names)
        for n, pl in live.items():
            if n not in orig and n not in names:
                names.append(n)
                payloads.append(pl)
        # the game BINARY-SEARCHES the alphabetically sorted index: keep it sorted
        order = sorted(range(len(names)), key=lambda i: names[i].lower())
        names, payloads = [names[i] for i in order], [payloads[i] for i in order]

        hdr, pak = crpak.build_archive(names, payloads)
        same = False
        try:
            same = (open(os.path.join(LIVE, f"{arc}.pak"), "rb").read() == pak
                    and open(os.path.join(LIVE, f"{arc}.hdr"), "rb").read() == hdr)
        except OSError:
            pass
        if install and not same:
            import datetime
            bdir = os.path.join(BACKUP_ROOT, datetime.date.today().isoformat() + "_before-assets")
            os.makedirs(bdir, exist_ok=True)
            for ext, blob in (("hdr", hdr), ("pak", pak)):
                dst = os.path.join(LIVE, f"{arc}.{ext}")
                if os.path.exists(dst) and not os.path.exists(os.path.join(bdir, f"{arc}.{ext}")):
                    import shutil
                    shutil.copy2(dst, os.path.join(bdir, f"{arc}.{ext}"))
                tmp = dst + ".new"
                with open(tmp, "wb") as f:
                    f.write(blob)
                os.replace(tmp, dst)
        print(f"  {arc:<9} {len(names):>4} entries   pak {len(pak):>12,} bytes   "
              f"{'unchanged, not written' if same else ('WRITTEN' if install else 'would change')}")

    for n in conflicts:
        print(f"   NOTE {n}: another tool (Car Tuner / trafficmod) had changed it too - your edit here wins")
    print(f"\n{len(changed)} asset(s) changed:")
    for c in changed[:40]:
        print(f"   {c}")
    if len(changed) > 40:
        print(f"   ... and {len(changed) - 40} more")
    if install:
        print("\n--- verifying installed archives ---")
        for arc in crpak.ARCHIVES:
            e, stored, _, blob = crpak.load_archive(LIVE, arc)
            ok = stored == len(e) and e[-1][1] + e[-1][2] == len(blob)
            print(f"  {arc:<9} {len(e):>4} entries  {'OK' if ok else 'BROKEN'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    out = sys.argv[2] if len(sys.argv) > 2 else crpaths.ASSETS_OUT
    if cmd == "extract":
        extract(out)
    elif cmd == "build":
        build(out, install=True)
    elif cmd == "dryrun":
        build(out, install=False)
    else:
        print(__doc__)
