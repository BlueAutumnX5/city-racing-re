r"""Render City Racing's world as a proper high-resolution map.

Corrected format understanding - the engine's world grid is 600x600:
    AltitudeMap.dat            600x600 float32   terrain height, 0.00 - 80.00
    WayPointsMap.dat           600x600 uint8     road / AI route network
    StaticObjectsPlaceMap.dat  600x600 uint8     building placement
    TrafficDensityMap.dat      200x200 uint8     traffic density (1/3 resolution)

Output is upscaled 3x to 1800x1800 with bilinear terrain and hillshading, roads kept crisp
with nearest-neighbour so they stay sharp.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import math
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
OUT = crpaths.work(r"maps")
SIDE = 600
SCALE = 3
BIG = SIDE * SCALE


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return os.path.getsize(path)


def grab(arc, suffix):
    entries, _, payloads, _ = crpak.load_archive(STOCK, arc)
    for (n, _, _), p in zip(entries, payloads):
        if n.endswith(suffix):
            return p
    return None


def terrain(h, shade):
    """Height in world units -> RGB, with a hillshade multiplier applied."""
    if h <= 0.05:
        r, g, b = 20, 46, 84
    elif h < 1.2:
        t = h / 1.2
        r, g, b = int(24 + 30 * t), int(60 + 45 * t), int(104 + 30 * t)
    elif h < 2.2:
        r, g, b = 206, 192, 148
    elif h < 22:
        t = (h - 2.2) / 19.8
        r = int(104 + 46 * t)
        g = int(132 + 30 * t)
        b = int(78 + 22 * t)
    elif h < 50:
        t = (h - 22) / 28
        r = int(150 + 48 * t)
        g = int(162 + 30 * t)
        b = int(100 + 30 * t)
    else:
        t = min(1.0, (h - 50) / 30)
        v = int(198 + 52 * t)
        r = g = b = v
    s = shade
    return (max(0, min(255, int(r * s))),
            max(0, min(255, int(g * s))),
            max(0, min(255, int(b * s))))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)

    alt_raw = grab("World", "AltitudeMap.dat")
    way = grab("World", "WayPointsMap.dat")
    obj = grab("World", "StaticObjectsPlaceMap.dat")
    dens = grab("World", "TrafficDensityMap.dat")

    H = list(struct.unpack(f"<{SIDE * SIDE}f", alt_raw))
    hmin, hmax = min(H), max(H)
    print(f"altitude: {SIDE}x{SIDE} float32, {hmin:.2f} .. {hmax:.2f}")

    # hillshade from the height gradient, light from the north-west
    print("computing hillshade ...")
    lx, ly, lz = -0.55, -0.55, 0.63
    shade = [1.0] * (SIDE * SIDE)
    for y in range(SIDE):
        ym, yp = max(0, y - 1), min(SIDE - 1, y + 1)
        for x in range(SIDE):
            xm, xp = max(0, x - 1), min(SIDE - 1, x + 1)
            dzdx = (H[y * SIDE + xp] - H[y * SIDE + xm]) * 0.5
            dzdy = (H[yp * SIDE + x] - H[ym * SIDE + x]) * 0.5
            nl = math.sqrt(dzdx * dzdx + dzdy * dzdy + 1.0)
            d = (-dzdx * lx - dzdy * ly + lz) / nl
            shade[y * SIDE + x] = 0.62 + 0.55 * max(0.0, min(1.0, d))

    def render(with_roads, with_buildings, path, label):
        rows = []
        for by in range(BIG):
            sy = by / SCALE
            y0 = int(sy)
            y1 = min(SIDE - 1, y0 + 1)
            fy = sy - y0
            row = bytearray()
            for bx in range(BIG):
                sx = bx / SCALE
                x0 = int(sx)
                x1 = min(SIDE - 1, x0 + 1)
                fx = sx - x0
                # bilinear height and shade
                h = (H[y0 * SIDE + x0] * (1 - fx) * (1 - fy)
                     + H[y0 * SIDE + x1] * fx * (1 - fy)
                     + H[y1 * SIDE + x0] * (1 - fx) * fy
                     + H[y1 * SIDE + x1] * fx * fy)
                s = (shade[y0 * SIDE + x0] * (1 - fx) * (1 - fy)
                     + shade[y0 * SIDE + x1] * fx * (1 - fy)
                     + shade[y1 * SIDE + x0] * (1 - fx) * fy
                     + shade[y1 * SIDE + x1] * fx * fy)
                r, g, b = terrain(h, s)
                idx = y0 * SIDE + x0
                if with_buildings and obj[idx]:
                    t = min(1.0, obj[idx] / 160)
                    r = int(r + (196 - r) * t * 0.75)
                    g = int(g + (108 - g) * t * 0.75)
                    b = int(b + (96 - b) * t * 0.75)
                if with_roads and way[idx]:
                    t = min(1.0, way[idx] / 64)
                    r = int(r + (252 - r) * t)
                    g = int(g + (248 - g) * t)
                    b = int(b + (232 - b) * t)
                row += bytes((r, g, b))
            rows.append(row)
        n = write_png(os.path.join(OUT, path), BIG, BIG, rows)
        print(f"  {path:<22} {BIG}x{BIG}  {n:>10,} bytes   {label}")

    print("rendering ...")
    render(True, True, "citymap_hires.png", "terrain + hillshade + roads + buildings")
    render(False, False, "terrain_hires.png", "terrain + hillshade only")

    # road network on its own, black on white, full 600 -> 1800
    rows = []
    for by in range(BIG):
        row = bytearray()
        sy = by // SCALE
        for bx in range(BIG):
            v = way[sy * SIDE + (bx // SCALE)]
            g = 255 - min(255, v * 4)
            row += bytes((g, g, g))
        rows.append(row)
    n = write_png(os.path.join(OUT, "roads_hires.png"), BIG, BIG, rows)
    print(f"  {'roads_hires.png':<22} {BIG}x{BIG}  {n:>10,} bytes   road network only")
    print(f"\nwritten to {OUT}")
