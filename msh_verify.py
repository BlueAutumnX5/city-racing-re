r"""Validate the .msh format hypothesis against every mesh in the game.

Hypothesis:
    u32   vertexCount
    u32   triangleCount
    vertex[vertexCount]        stride 44:
        float3 position
        float3 normal
        u32    colour (BGRA/ARGB)
        float2 uv0
        float2 uv1
    u16   index[triangleCount * 3]
    byte  footer[40]           10 floats, last four = centre(3) + radius(1)

If filesize == 8 + v*44 + t*6 + 40 for all 647 files, the format is solved.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import math
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
STRIDE = 44
HDR = 8
FOOTER = 40


def meshes():
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.lower().endswith(".msh"):
            yield n, p


if __name__ == "__main__":
    all_m = list(meshes())
    exact = 0
    residuals = Counter()
    bad = []
    idx_ok = idx_bad = 0
    norm_ok = norm_bad = 0
    centre_ok = centre_bad = 0

    for name, p in all_m:
        if len(p) < HDR + FOOTER:
            bad.append((name, len(p), "too small"))
            continue
        v, t = struct.unpack_from("<II", p, 0)
        predicted = HDR + v * STRIDE + t * 6 + FOOTER
        r = len(p) - predicted
        residuals[r] += 1
        if r == 0:
            exact += 1
        else:
            if len(bad) < 8:
                bad.append((name, len(p), f"v={v} t={t} predicted={predicted} off by {r}"))
            continue

        # indices must all be < vertex count
        ibase = HDR + v * STRIDE
        idxs = struct.unpack_from(f"<{t * 3}H", p, ibase)
        if idxs and max(idxs) < v:
            idx_ok += 1
        else:
            idx_bad += 1

        # normals should be unit length
        nl_bad = 0
        for k in range(min(v, 40)):
            off = HDR + k * STRIDE + 12
            nx, ny, nz = struct.unpack_from("<3f", p, off)
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if not (0.9 < ln < 1.1):
                nl_bad += 1
        if nl_bad == 0:
            norm_ok += 1
        else:
            norm_bad += 1

        # footer: last 4 floats should be centre + radius of the vertex cloud
        fc = struct.unpack_from("<4f", p, len(p) - 16)
        xs = [struct.unpack_from("<3f", p, HDR + k * STRIDE)[0] for k in range(v)]
        ys = [struct.unpack_from("<3f", p, HDR + k * STRIDE)[1] for k in range(v)]
        zs = [struct.unpack_from("<3f", p, HDR + k * STRIDE)[2] for k in range(v)]
        cx, cy, cz = sum(xs) / v, sum(ys) / v, sum(zs) / v
        if (abs(fc[0] - cx) < max(1.0, abs(cx) * 0.02)
                and abs(fc[1] - cy) < max(1.0, abs(cy) * 0.02)
                and abs(fc[2] - cz) < max(1.0, abs(cz) * 0.02)):
            centre_ok += 1
        else:
            centre_bad += 1

    print(f"meshes tested                     : {len(all_m)}")
    print(f"size formula EXACT (8+v*44+t*6+40): {exact}  "
          f"({100 * exact / len(all_m):.1f}%)")
    print()
    print("residual (actual - predicted) distribution:")
    for r, n in residuals.most_common(8):
        print(f"    {r:>+8} bytes : {n:>4} files")
    print()
    print(f"all indices < vertexCount         : {idx_ok} ok, {idx_bad} bad")
    print(f"all normals unit length           : {norm_ok} ok, {norm_bad} bad")
    print(f"footer tail == centroid of verts  : {centre_ok} ok, {centre_bad} bad")
    if bad:
        print("\nfailures:")
        for n, s, why in bad[:8]:
            print(f"    {s:>10,}  {why}   {n}")
