"""READ-ONLY: chunk manager state. Map object 0x012d0ce0: +0x108/+0x10c grid, +0x124 chunk
radius, +0x150 R (generate radius), +0x158 N*N part pointers, active list +0x1158 (1024),
count +0x2158. Part: +0x10c distance, +0x53bc centre, +0x53c8 radius, +0x5330 collision body."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, math
sys.path.insert(0, crpaths.WORK)
from livewatch import Proc, find_pid, CAMERA

MAP = 0x012d0ce0
p = Proc(find_pid())
f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
u = p.u32
gx, gz = u(MAP + 0x108), u(MAP + 0x10c)
print(f"grid +0x108={gx} +0x10c={gz}  chunk radius +0x124={f(MAP + 0x124):g}  R +0x150={f(MAP + 0x150):g}")
for off in range(0x100, 0x160, 4):
    v = u(MAP + off)
    print(f"  +{off:#05x} = {v:#010x}  ({struct.unpack('<f', struct.pack('<I', v))[0]:g})")
parts_ptr = u(MAP + 0x158)
print(f"parts array ptr {parts_ptr:#x}")
eye = p.vec(u(CAMERA) + 0x70)
n_active = u(MAP + 0x2158)
act = struct.unpack(f"<{n_active}I", p.read(MAP + 0x1158, 4 * n_active)) if n_active < 1025 else ()
print(f"active parts: {n_active}; camera {tuple(round(v) for v in eye)}")
ds = []
for a in act:
    if not a:
        continue
    c = p.vec(a + 0x53bc); r = f(a + 0x53c8)
    ds.append((math.dist((c[0], c[2]), (eye[0], eye[2])), r, u(a + 0x5330) != 0))
N = gx
allp = struct.unpack(f"<{N * N}I", p.read(parts_ptr, 4 * N * N))
land = []
for a in allp:
    if not a:
        continue
    try:
        c = p.vec(a + 0x53bc)
        land.append((math.dist((c[0], c[2]), (eye[0], eye[2])), u(a + 0x5330) != 0, a in act))
    except OSError:
        pass
print(f"grid parts: {sum(1 for a in allp if a)} non-null of {N * N}; with collision body: "
      f"{sum(1 for _, b, _ in land if b)}")
for R in (1000, 1300, 1600, 2000, 2600):
    inside = [(d, b) for d, b, _ in land if d - 94 < R]
    print(f"  R {R:5d}: parts within {len(inside):4d}, with objects/collision {sum(1 for _, b in inside if b):3d}")
if ds:
    print(f"  distance to active part centres: min {min(d for d, _, _ in ds):.0f}, max {max(d for d, _, _ in ds):.0f}; "
          f"radius {min(r for _, r, _ in ds):.0f}..{max(r for _, r, _ in ds):.0f}; with collision body (land w/ objects): "
          f"{sum(1 for *_, b in ds if b)}")
