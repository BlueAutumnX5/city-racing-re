r"""Extract and render City Racing's world maps at full resolution.

No Pillow on this machine, so this includes a small pure-Python PNG writer - PNG is just
zlib-compressed scanlines with CRC'd chunks, about 15 lines of code.

Renders:
  worldmap.jpg        the game's own map image, extracted as-is
  landscapetex.jpg    the terrain texture
  altitude.png        1200x1200 heightmap, terrain-coloured
  waypoints.png        600x600  road / AI route network
  staticobjects.png    600x600  building placement
  trafficdensity.png   200x200  traffic density
  citymap.png         1200x1200 composite: terrain + roads + buildings
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
OUT = crpaths.work(r"maps")


# ----------------------------------------------------------------- PNG writer

def write_png(path, w, h, rows):
    """rows: list of h bytearrays, each w*3 bytes of RGB."""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return os.path.getsize(path)


def jpeg_size(data):
    """Read width/height from the SOF marker."""
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack_from(">HH", data, i + 5)
            return w, h
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack_from(">H", data, i + 2)[0]
        i += 2 + seg
    return None, None


def grab(arc, suffix):
    entries, _, payloads, _ = crpak.load_archive(STOCK, arc)
    for (n, _, _), p in zip(entries, payloads):
        if n.endswith(suffix):
            return n, p
    return None, None


# ------------------------------------------------------------------ colouring

def terrain_colour(v):
    """Height byte -> a plausible terrain colour ramp."""
    if v == 0:
        return (24, 52, 92)          # deep water
    if v < 8:
        return (38, 88, 140)         # shallow water
    if v < 16:
        return (198, 184, 140)       # beach
    if v < 70:
        t = (v - 16) / 54
        return (int(92 + 60 * t), int(126 + 40 * t), int(70 + 30 * t))   # grass
    if v < 150:
        t = (v - 70) / 80
        return (int(140 + 60 * t), int(132 + 50 * t), int(110 + 45 * t))  # rock
    t = min(1.0, (v - 150) / 105)
    g = int(180 + 70 * t)
    return (g, g, g)                  # peaks


def render_gray(data, w, h, path, colour=None, label=""):
    rows = []
    for y in range(h):
        row = bytearray()
        base = y * w
        for x in range(w):
            v = data[base + x]
            r, g, b = colour(v) if colour else (v, v, v)
            row += bytes((r, g, b))
        rows.append(row)
    n = write_png(path, w, h, rows)
    print(f"  {os.path.basename(path):<22} {w:>5}x{h:<5} {n:>10,} bytes   {label}")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    print("=== extracting the game's own map images ===")
    for suffix in ("Landscape/WorldMap.jpg", "Landscape/LandscapeTex.jpg",
                   "Landscape/RoadsAlpha.jpg"):
        name, payload = grab("Textures", suffix)
        if not payload:
            print(f"  {suffix}: NOT FOUND")
            continue
        w, h = jpeg_size(payload)
        dst = os.path.join(OUT, os.path.basename(suffix).lower())
        with open(dst, "wb") as f:
            f.write(payload)
        print(f"  {os.path.basename(dst):<22} {w:>5}x{h:<5} {len(payload):>10,} bytes")

    print("\n=== rendering the raw data maps ===")
    specs = [
        ("Landscape/AltitudeMap.dat", 1200, "altitude.png", terrain_colour,
         "terrain height, coloured"),
        ("Landscape/WayPointsMap.dat", 600, "waypoints.png", None,
         "road / AI route network"),
        ("Landscape/StaticObjectsPlaceMap.dat", 600, "staticobjects.png", None,
         "building placement"),
        ("Landscape/TrafficDensityMap.dat", 200, "trafficdensity.png", None,
         "traffic density"),
    ]
    loaded = {}
    for suffix, side, out, col, label in specs:
        name, payload = grab("World", suffix)
        if not payload:
            print(f"  {suffix}: NOT FOUND")
            continue
        if len(payload) != side * side:
            print(f"  {suffix}: size {len(payload)} != {side}^2, skipping")
            continue
        loaded[os.path.basename(suffix)] = (payload, side)
        render_gray(payload, side, side, os.path.join(OUT, out), col, label)

    # ---- composite city map ----
    alt = loaded.get("AltitudeMap.dat")
    way = loaded.get("WayPointsMap.dat")
    obj = loaded.get("StaticObjectsPlaceMap.dat")
    if alt and way:
        ad, aside = alt
        wd, wside = way
        od, oside = obj if obj else (None, 0)
        rows = []
        for y in range(aside):
            row = bytearray()
            for x in range(aside):
                r, g, b = terrain_colour(ad[y * aside + x])
                # roads on top
                wv = wd[(y * wside // aside) * wside + (x * wside // aside)]
                if wv:
                    t = min(1.0, wv / 96)
                    r = int(r + (245 - r) * t)
                    g = int(g + (238 - g) * t)
                    b = int(b + (210 - b) * t)
                # buildings tinted
                if od is not None:
                    ov = od[(y * oside // aside) * oside + (x * oside // aside)]
                    if ov:
                        r = min(255, int(r * 0.75 + 70))
                        g = min(255, int(g * 0.75 + 40))
                        b = min(255, int(b * 0.75 + 40))
                row += bytes((r, g, b))
            rows.append(row)
        n = write_png(os.path.join(OUT, "citymap.png"), aside, aside, rows)
        print(f"  {'citymap.png':<22} {aside:>5}x{aside:<5} {n:>10,} bytes   "
              f"composite: terrain + roads + buildings")

    print(f"\nall written to {OUT}")
