r"""Dump every candidate projection matrix in full, and derive its frustum.

From a D3D perspective matrix:
    m22 = zf / (zf - zn)          ->  zn = -m32 / m22
    m32 = -zn * zf / (zf - zn)        zf = m22 * zn / (m22 - 1)

A genuine scene projection has a sane near plane (roughly 0.05 - 5) and a far plane in the
hundreds-to-tens-of-thousands. Anything else is a false positive - a UI transform, a shadow
matrix, or random floats that happen to fit the mask.

Also reports what m00 WOULD need to be for correct 16:9, so the patch target is explicit.
"""

import ctypes
import math
import struct
import sys

import findproj as fp


def frustum(f):
    m22, m32 = f[10], f[14]
    try:
        zn = -m32 / m22
        zf = m22 * zn / (m22 - 1.0)
    except ZeroDivisionError:
        return None, None
    return zn, zf


def dump(addr, f, tag=""):
    m00, m11 = f[0], f[5]
    aspect = m11 / m00 if m00 else float("nan")
    fovy = math.degrees(2 * math.atan(1.0 / m11)) if m11 else float("nan")
    fovx = math.degrees(2 * math.atan(1.0 / m00)) if m00 else float("nan")
    zn, zf = frustum(f)
    print(f"  === 0x{addr:08x} {tag}")
    for r in range(4):
        row = "  ".join(f"{f[r * 4 + c]:>14.6f}" for c in range(4))
        print(f"      {row}")
    print(f"      m00={m00:.6f}  m11={m11:.6f}  aspect=m11/m00={aspect:.6f}")
    print(f"      fovX={fovx:.2f} deg   fovY={fovy:.2f} deg")
    if zn is not None:
        print(f"      near={zn:.4f}   far={zf:.2f}")
    if m11:
        print(f"      for TRUE 16:9, m00 should be m11/1.777778 = {m11 / (16 / 9):.6f}"
              f"   (currently {m00:.6f})")
    print()


if __name__ == "__main__":
    pid = fp.find_pid()
    if not pid:
        print("game.exe not running")
        sys.exit(1)
    print(f"game.exe pid {pid}\n")

    h = fp.k32.OpenProcess(fp.PROCESS_QUERY_INFORMATION | fp.PROCESS_VM_READ, False, pid)
    if not h:
        print("OpenProcess failed")
        sys.exit(1)

    strict, loose = [], []
    try:
        for base, size in fp.regions(h):
            data = fp.read(h, base, size)
            if not data:
                continue
            start = 0
            while True:
                k = data.find(fp.ONE, start)
                if k < 0:
                    break
                start = k + 4
                for moff in (44, 56):
                    m0 = k - moff
                    if m0 < 0 or m0 + 64 > len(data) or m0 % 4:
                        continue
                    f = struct.unpack_from("<16f", data, m0)
                    if fp.classify(f):
                        strict.append((base + m0, f))
                        continue
                    # looser: the 4 corner zeros + positive scales, to catch
                    # layouts my strict mask misses
                    if (all(abs(f[i]) < 1e-6 for i in (1, 2, 4, 6, 8, 9))
                            and 0.01 < f[0] < 500 and 0.01 < f[5] < 500
                            and abs(f[0] - f[5]) > 1e-7):
                        loose.append((base + m0, f))
    finally:
        fp.k32.CloseHandle(h)

    print(f"### STRICT matches: {len(strict)}\n")
    seen = set()
    for addr, f in strict:
        key = tuple(round(x, 5) for x in f)
        tag = "(duplicate values)" if key in seen else ""
        seen.add(key)
        dump(addr, f, tag)

    print(f"### LOOSE matches (different layout candidates): {len(loose)}\n")
    seen2 = set()
    shown = 0
    for addr, f in loose:
        key = tuple(round(x, 5) for x in f)
        if key in seen2:
            continue
        seen2.add(key)
        dump(addr, f)
        shown += 1
        if shown >= 12:
            print(f"  ... {len(loose) - shown} more suppressed")
            break
