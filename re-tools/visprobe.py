"""READ-ONLY: globals that gate drawing, plus per-car draw fields: +0xa24 distance, +0xa28
visible flag, +0x9d0 class, +0x86c fade, +0x8b4 radius, and whether a draw object exists."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, math
sys.path.insert(0, crpaths.WORK)
from livewatch import Proc, find_pid, MGR, PLAYER, CAMERA, TYPES

p = Proc(find_pid())
f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
print(f"Distance setting [0x12cc124] = {p.u32(0x012cc124)}   [0x12d0ca0] = {p.u32(0x012d0ca0)}   "
      f"[0x12d0c9c] = {p.u32(0x012d0c9c)}   [0x264832c] = {f(0x0264832c):.3f}   "
      f"vdraw {f(0x0058f654):g} vdetail {f(0x0058f658):g}")
cam = p.u32(CAMERA)
eye = p.vec(cam + 0x70)
count = p.u32(MGR + 0x128)
rows = []
for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count)):
    if not c:
        continue
    pos = p.vec(c + 0xa18)
    d = math.dist(pos, eye)
    rows.append((d, f"{TYPES.get(p.u32(c + 0xc8c), '?'):<8} d={d:6.1f} gd={f(c + 0xa24):6.1f} "
                    f"vis(+a28)={p.u32(c + 0xa28)} class(+9d0)={p.u32(c + 0x9d0):#x} "
                    f"fade={f(c + 0x86c):.2f} r={f(c + 0x8b4):.2f} active(+a34)={p.u32(c + 0xa34)}"))
for _, r in sorted(rows):
    print(r)
