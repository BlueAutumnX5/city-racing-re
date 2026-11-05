"""READ-ONLY (2026-10-04): every static-manager object within R m of the camera (true distance, any
direction), with game distance +0xa24, alpha +0x86c, visible +0xa28, active +0xa34, GTYPE, +0xc8c
(race billboard kind?) and parts. Usage: boardprobe.py [R=250] [only_c8c]"""
import math, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from livewatch import Proc, find_pid, CAMERA
MGR = 0x026b1aa0
R = float(sys.argv[1]) if len(sys.argv) > 1 else 250.0
only = len(sys.argv) > 2
p = Proc(find_pid())
f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
eye = p.vec(p.u32(CAMERA) + 0x70)
count = p.u32(MGR + 0x5000)
rows = []
for o in struct.unpack(f"<{count}I", p.read(MGR, 4 * count)):
    try:
        pos = p.vec(o + 0xa18)
        d = math.dist((pos[0], pos[2]), (eye[0], eye[2]))
        if d > R:
            continue
        k = p.u32(o + 0xc8c)
        if only and not k:
            continue
        cls = p.u32(o + 0x9d0)
        n = p.u32(o + 0xc60)
        rows.append((d, f"{o:#010x} type {cls:#06x} c8c {k}  dist {d:6.1f}  gd {f(o + 0xa24):6.1f}  alpha {f(o + 0x86c):5.2f}  "
                        f"vis {p.u32(o + 0xa28)}  active {p.u32(o + 0xa34)}  parts {n}  pos ({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f})"))
    except OSError:
        pass
print(f"eye ({eye[0]:.0f},{eye[1]:.0f},{eye[2]:.0f}); {len(rows)} objects within {R:g} m")
for _, r in sorted(rows):
    print(" ", r)
