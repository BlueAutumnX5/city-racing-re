r"""City Racing traffic modding - route behaviour and density.

Edits two files inside World.pak:

  Data/Landscape/GlobalRoute.dat        600x600 x 48-byte records, the AI navigation field
      0x00 u32    kind   0 = no route, 1 = road, 2/3/4 = refined
      0x04 f32    X      normally -1198 + 4*col; a SNAPPED road point for kind 3/4
      0x08 f32    height
      0x0C f32    Z      normally 1198 - 4*row; same exception
      0x10-0x1C   runtime pointers, stale on disk
      0x21 u8     waypoint id  (identical to WayPointsMap.dat on all 360,000 cells)
      0x22 u8     progress along route, 0..100; exactly 100 off-road
      0x24 u16x2  (column, row) - the cell's own coordinates

  Data/Landscape/TrafficDensityMap.dat  200x200 u8, 12 world units per cell
      A plain 0..255 scale: 0 = no traffic, 255 = maximum (the city centre).
      NO sentinel values. Verified by measuring road coverage under each density band:
          0        -> 0.09 road cells out of 9
          1-99     -> 3.04
          100-199  -> 7.40
          200-254  -> 8.18
          255      -> 9.00   (completely road-covered - the busiest streets)
      Monotonic, so 255 is simply the top of the scale. p25=12 p50=52 p75=129 p90=227.

Commands
    show                       current state of both files
    render <dir>               PNG visualisations of route kind, lane deviation, density
    density --scale 2.0        multiply road-cell density (clamped 1..254)
    density --min 150          raise every road cell to at least this
    density --set 200          set every road cell to exactly this
    lane --scale -1            scale the driving-line deviation. -1 MIRRORS it (drive on
                               the other side), 0 centres it, 2 exaggerates it
    close --rect x0,z0,x1,z1   set kind=0 in a world-space rectangle - traffic stops routing
    open  --rect x0,z0,x1,z1   set kind=1 wherever a waypoint exists - re-enable routing
    restore                    put both files back to pristine

Edits always rebuild the two .dat files FROM PRISTINE, so they never stack, but everything
else in World.pak is taken from the live archive, so mesh/texture edits survive.

World space: X = -1198 + 4*col, Z = 1198 - 4*row, so the map spans -1198..1198 on both axes.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak

SIDE, REC = 600, 48
DSIDE = 200
ROUTE = "Data/Landscape/GlobalRoute.dat"
DENS = "Data/Landscape/TrafficDensityMap.dat"


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe"],
                             capture_output=True, text=True).stdout
        return "game.exe" in out
    except Exception:
        return False


def load(data_dir, name):
    e, _, p, _ = crpak.load_archive(data_dir, "World")
    for (n, _, _), pl in zip(e, p):
        if n == name:
            return pl
    return None


def world_to_cell(x, z):
    return int(round((x + 1198) / 4)), int(round((1198 - z) / 4))


def in_rect(col, row, rect):
    if rect is None:
        return True
    x = -1198 + 4 * col
    z = 1198 - 4 * row
    x0, z0, x1, z1 = rect
    return min(x0, x1) <= x <= max(x0, x1) and min(z0, z1) <= z <= max(z0, z1)


# ------------------------------------------------------------------- reporting

def cmd_show():
    for label, d in (("pristine", assets.STOCK), ("live", assets.LIVE)):
        gr = load(d, ROUTE)
        dn = load(d, DENS)
        kinds = {}
        dev = 0
        for i in range(0, len(gr), REC):
            k, = struct.unpack_from("<I", gr, i)
            kinds[k] = kinds.get(k, 0) + 1
            if k in (3, 4):
                col, row = struct.unpack_from("<2H", gr, i + 36)
                x, _, z = struct.unpack_from("<3f", gr, i + 4)
                if abs(x - (-1198 + 4 * col)) > 0.01 or abs(z - (1198 - 4 * row)) > 0.01:
                    dev += 1
        road = [v for v in dn if v not in (0, 255)]
        road.sort()
        print(f"\n=== {label} ===")
        print(f"  route kinds : " + "  ".join(f"{k}={v:,}" for k, v in sorted(kinds.items())))
        print(f"  cells with a snapped driving line (kind 3/4): {dev:,}")
        print(f"  density     : road cells {len(road):,}  "
              f"p25={road[len(road)//4]} p50={road[len(road)//2]} "
              f"p75={road[3*len(road)//4]} max={road[-1]}")
        print(f"                blocked(0xFF) {dn.count(255):,}  outside(0) {dn.count(0):,}")


# ---------------------------------------------------------------------- render

def cmd_render(outdir):
    os.makedirs(outdir, exist_ok=True)
    gr = load(assets.LIVE, ROUTE)
    dn = load(assets.LIVE, DENS)

    KCOL = {0: (26, 32, 44), 1: (90, 140, 200), 2: (120, 200, 140),
            3: (250, 200, 90), 4: (250, 120, 90)}
    rows = []
    for r in range(SIDE):
        row = bytearray()
        for c in range(SIDE):
            k, = struct.unpack_from("<I", gr, (r * SIDE + c) * REC)
            row += bytes(KCOL.get(k, (255, 0, 255))) + b"\xff"
        rows.append(row)
    assets.png_write(os.path.join(outdir, "route_kind.png"), SIDE, SIDE,
                     b"".join(bytes(x) for x in rows))

    # lane deviation magnitude, amplified so it is visible
    rows = []
    for r in range(SIDE):
        row = bytearray()
        for c in range(SIDE):
            o = (r * SIDE + c) * REC
            k, = struct.unpack_from("<I", gr, o)
            x, _, z = struct.unpack_from("<3f", gr, o + 4)
            dx = x - (-1198 + 4 * c)
            dz = z - (1198 - 4 * r)
            m = min(1.0, (dx * dx + dz * dz) ** 0.5 / 4.0)
            if k == 0:
                row += bytes((20, 24, 34, 255))
            else:
                g = int(60 + 195 * m)
                row += bytes((g, int(60 + 80 * m), 255 - g, 255))
        rows.append(row)
    assets.png_write(os.path.join(outdir, "lane_deviation.png"), SIDE, SIDE,
                     b"".join(bytes(x) for x in rows))

    rows = []
    for r in range(DSIDE):
        row = bytearray()
        for c in range(DSIDE):
            v = dn[r * DSIDE + c]
            if v == 0:
                row += bytes((18, 22, 32, 255))
            elif v == 255:
                row += bytes((200, 60, 60, 255))
            else:
                row += bytes((v, int(v * 0.85), 255 - v, 255))
        rows.append(row)
    assets.png_write(os.path.join(outdir, "traffic_density.png"), DSIDE, DSIDE,
                     b"".join(bytes(x) for x in rows))
    print(f"wrote route_kind.png, lane_deviation.png, traffic_density.png to {outdir}")
    print("  route_kind     dark=no route, blue=1, green=2, yellow=3, orange=4")
    print("  lane_deviation brighter = driving line further from the cell centre")
    print("  traffic_density blue->yellow = low->high, red = 0xFF blocked")


# ----------------------------------------------------------------------- edits

def build_route(fn, rect=None):
    src = bytearray(load(assets.STOCK, ROUTE))
    n = 0
    for r in range(SIDE):
        for c in range(SIDE):
            if not in_rect(c, r, rect):
                continue
            n += fn(src, (r * SIDE + c) * REC, c, r)
    return bytes(src), n


def build_density(fn):
    """0 is skipped (no road there, so density is meaningless), but 255 is NOT special -
    it is just the top of the scale, so scaling and clamping include it."""
    src = bytearray(load(assets.STOCK, DENS))
    n = 0
    for i, v in enumerate(src):
        if v == 0:
            continue
        nv = max(1, min(255, int(round(fn(v)))))
        if nv != v:
            src[i] = nv
            n += 1
    return bytes(src), n


def install(new_route=None, new_dens=None):
    if game_running():
        print("ABORT: game.exe is running - exit it first.")
        return 1
    entries, _, payloads, _ = crpak.load_archive(assets.LIVE, "World")
    names = [n for n, _, _ in entries]
    out = []
    for name, pl in zip(names, payloads):
        if name == ROUTE and new_route is not None:
            out.append(new_route)
        elif name == DENS and new_dens is not None:
            out.append(new_dens)
        else:
            out.append(pl)
    hdr, pak = crpak.build_archive(names, out)
    for ext, blob in (("hdr", hdr), ("pak", pak)):
        dst = os.path.join(assets.LIVE, f"World.{ext}")
        tmp = dst + ".new"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, dst)
    e2, stored, _, blob = crpak.load_archive(assets.LIVE, "World")
    ok = stored == len(e2) and e2[-1][1] + e2[-1][2] == len(blob)
    print(f"installed World.pak {len(pak):,} bytes, {len(e2)} entries, "
          f"index {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""

    def opt(flag, cast=str, default=None):
        return cast(a[a.index(flag) + 1]) if flag in a else default

    rect = None
    if "--rect" in a:
        rect = tuple(float(v) for v in a[a.index("--rect") + 1].split(","))

    if cmd == "show":
        cmd_show()
    elif cmd == "render":
        cmd_render(a[1] if len(a) > 1 else crpaths.work(r"maps"))
    elif cmd == "restore":
        sys.exit(install(load(assets.STOCK, ROUTE), load(assets.STOCK, DENS)))
    elif cmd == "density":
        if "--scale" in a:
            s = opt("--scale", float)
            dn, n = build_density(lambda v: v * s)
            print(f"density scaled by {s}: {n:,} cells changed")
        elif "--min" in a:
            m = opt("--min", int)
            dn, n = build_density(lambda v: max(v, m))
            print(f"density raised to at least {m}: {n:,} cells changed")
        elif "--set" in a:
            m = opt("--set", int)
            dn, n = build_density(lambda v: m)
            print(f"density set to {m}: {n:,} cells changed")
        else:
            print("need --scale N, --min N or --set N")
            sys.exit(2)
        sys.exit(install(None, dn))
    elif cmd == "lane":
        s = opt("--scale", float, 1.0)

        def f(buf, o, c, r):
            k, = struct.unpack_from("<I", buf, o)
            if k not in (3, 4):
                return 0
            x, h, z = struct.unpack_from("<3f", buf, o + 4)
            cx, cz = -1198 + 4 * c, 1198 - 4 * r
            dx, dz = x - cx, z - cz
            if abs(dx) < 1e-4 and abs(dz) < 1e-4:
                return 0
            struct.pack_into("<3f", buf, o + 4, cx + dx * s, h, cz + dz * s)
            return 1

        gr, n = build_route(f, rect)
        print(f"driving-line deviation scaled by {s}: {n:,} cells changed"
              + ("  (mirrored - traffic drives the other side)" if s < 0 else ""))
        sys.exit(install(gr, None))
    elif cmd in ("close", "open"):
        if rect is None:
            print("need --rect x0,z0,x1,z1  (world coordinates, -1198..1198)")
            sys.exit(2)
        want = 0 if cmd == "close" else 1

        def f(buf, o, c, r):
            k, = struct.unpack_from("<I", buf, o)
            wp = buf[o + 33]
            if cmd == "close" and k != 0:
                struct.pack_into("<I", buf, o, 0)
                return 1
            if cmd == "open" and k == 0 and wp:
                struct.pack_into("<I", buf, o, 1)
                return 1
            return 0

        gr, n = build_route(f, rect)
        print(f"{cmd} in rect {rect}: {n:,} cells changed")
        sys.exit(install(gr, None))
    else:
        print(__doc__)
