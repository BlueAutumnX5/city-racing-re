r"""Decode the .msh vertex layout.

From Data/Landscape/02_02/SideWalks.msh (186 bytes, the smallest mesh):

  0x08  -842.8, 16.47, 839.9     position
  0x14  0.0, 1.0, 0.0            normal - exactly straight up, as a pavement should be
  0x20  0x00FFFFFF               vertex colour
  0x24  0.995, 0.6284            UV set 0 (normalised - lightmap?)
  0x2c  -84.28, 83.99            UV set 1 (large values = tiled texture)
  0x34  next vertex starts       => stride 44

44 = 12 (pos) + 12 (normal) + 4 (colour) + 8 (uv0) + 8 (uv1). Confirmed by the colour dwords
appearing exactly 44 bytes apart, and by consecutive vertices sharing a Y of 16.47.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK = crpaths.STOCK_DATA
STRIDE = 44


def grab(suffix):
    entries, _, payloads, _ = crpak.load_archive(STOCK, "World")
    for (n, _, _), p in zip(entries, payloads):
        if n.endswith(suffix):
            return n, p
    return None, None


def annotate(data, name):
    print("=" * 78)
    print(f"{name}   {len(data):,} bytes")
    print("=" * 78)
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        if len(chunk) < 4:
            print(f"  {i:04x}  {chunk.hex(' ')}   <- {len(chunk)} trailing byte(s)")
            break
        u = struct.unpack("<I", chunk)[0]
        f = struct.unpack("<f", chunk)[0]
        s = struct.unpack("<h", chunk[:2])[0], struct.unpack("<h", chunk[2:])[0]
        fs = f"{f:>14.5g}" if (f == f and 1e-8 < abs(f) < 1e9) else " " * 14
        note = ""
        if i == 0:
            note = "  <- header[0]"
        elif i == 4:
            note = "  <- header[1]"
        print(f"  {i:04x}  {chunk.hex(' ')}  u32={u:<12} {fs}  i16={s}{note}")


if __name__ == "__main__":
    name, data = grab("Landscape/02_02/SideWalks.msh")
    annotate(data, name)

    h0, h1 = struct.unpack_from("<II", data, 0)
    print(f"\nheader: [0]={h0}  [1]={h1}   filesize={len(data)}")
    for hdr in (8, 12, 16):
        rest = len(data) - hdr
        print(f"  if header is {hdr} bytes: {rest} remaining"
              f"   /44 = {rest / STRIDE:.3f}   /36 = {rest / 36:.3f}")
    # try: h0 vertices of 44 bytes, then indices
    for hdr in (8, 12):
        vbytes = h0 * STRIDE
        tail = len(data) - hdr - vbytes
        print(f"  {h0} verts x {STRIDE} = {vbytes} after {hdr}-byte header"
              f" -> tail {tail} bytes"
              f"  = {tail / 2:.1f} u16  or {tail / 4:.1f} u32")
