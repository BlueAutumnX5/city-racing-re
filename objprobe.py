r"""objprobe.py - READ-ONLY: static-manager objects (0x026b1aa0) in front of the camera.

For decorations / lamp posts (GTYPE 0x200 / 0x400, incl. race billboards, ramps, cafe sets):
game distance [+0xa24], render alpha [+0x86c], visible flag [+0xa28], parts and each part's
alpha, and the screen x (the vertical projection is unreliable, see carsnap).
USAGE  objprobe.py [max_distance] [classes_hex]      default 400, 0x600
"""
import math
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from livewatch import Proc, find_pid, CAMERA

MGR = 0x026b1aa0
CLS = {0x10: "static", 0x20: "stone", 0x40: "tree", 0x80: "bridge", 0x100: "building",
       0x200: "decor", 0x400: "lamp"}


def main():
    maxd = float(sys.argv[1]) if len(sys.argv) > 1 else 400.0
    mask = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x600
    p = Proc(find_pid())
    f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
    cam = p.u32(CAMERA)
    eye, look = p.vec(cam + 0x70), p.vec(cam + 0x7c)
    fwd = [a - b for a, b in zip(look, eye)]
    n = math.hypot(fwd[0], fwd[2]) or 1.0
    fx, fz = fwd[0] / n, fwd[2] / n
    count = p.u32(MGR + 0x5000)
    objs = struct.unpack(f"<{count}I", p.read(MGR, 4 * count))
    rows = []
    for o in objs:
        try:
            cls = p.u32(o + 0x9d0)
            if not cls & mask:
                continue
            gd = f(o + 0xa24)
            if gd > maxd:
                continue
            pos = p.vec(o + 0xa18)
            rx, rz = pos[0] - eye[0], pos[2] - eye[2]
            z = rx * fx + rz * fz                     # distance along the view direction
            if z <= 1:
                continue
            side = (rx * fz - rz * fx) / z            # tan of the horizontal angle
            if abs(side) > 1.3:
                continue
            nparts = p.u32(o + 0xc60)
            pa = []
            if 0 < nparts < 16:
                plist = p.u32(o + 0xc64)
                for i in range(nparts):
                    part = p.u32(plist + 4 * i)
                    pa.append(round(f(part + 0x86c), 2))
            rows.append((gd, f"{CLS.get(cls, hex(cls)):<6} gd {gd:6.1f}  alpha {f(o + 0x86c):5.2f}  "
                             f"vis {p.u32(o + 0xa28)}  active {p.u32(o + 0xa34)}  parts {pa}  "
                             f"screen-x {960 - side * 960 / (1920 / 1080 * 0.85):5.0f}"))
        except OSError:
            continue
    print(f"eye ({eye[0]:.0f},{eye[1]:.0f},{eye[2]:.0f}); {count} objects in the manager; "
          f"{len(rows)} decor/lamp in view within {maxd:g}")
    for _, r in sorted(rows):
        print("  " + r)


if __name__ == "__main__":
    main()
