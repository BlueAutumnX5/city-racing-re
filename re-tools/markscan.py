"""markscan.py - READ-ONLY: where does the game keep its tyre marks? (player 2026-11-01: "it is really there -
look at the memory when I skid"). Scans every committed, writable region of game.exe for float triples
(x, y, z) within 40 m (y within 6 m) of the player's car (+0xa18), 4-byte aligned.
    markscan.py before     park on a clean spot, then run: baseline -> markscan_before.npz
    markscan.py after      skid / powerslide right there, then run: lists the NEW triples, grouped into
                           arrays (same region, regular stride) - the tyre-mark store should stand out
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import cpuprofile as cp

PLAYER = 0x012D0C88
R_XZ, R_Y = 40.0, 6.0


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def open_game():
    pid = cp.find_process()
    if not pid:
        sys.exit("game not running")
    return cp.k32.OpenProcess(0x0400 | 0x0010, False, pid)        # QUERY_INFORMATION | VM_READ


def read(h, a, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def regions(h):
    a, mbi = 0x10000, MBI()
    while a < 0x7FFF0000:
        if not cp.k32.VirtualQueryEx(h, ctypes.c_void_p(a), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        if mbi.State == 0x1000 and mbi.Protect & 0xCC and not mbi.Protect & 0x100:   # committed, RW, no guard
            yield base, size
        a = base + size


def scan(h):
    car = struct.unpack("<I", read(h, PLAYER, 4))[0]
    cx, cy, cz = struct.unpack("<3f", read(h, car + 0xA18, 12))
    hits = []
    for base, size in regions(h):
        for off in range(0, size, 1 << 22):
            n = min(1 << 22, size - off)
            raw = read(h, base + off, n)
            if len(raw) < 12:
                continue
            f = np.frombuffer(raw[:len(raw) // 4 * 4], dtype="<f4")
            x, y, z = f[:-2], f[1:-1], f[2:]
            with np.errstate(invalid="ignore"):
                m = (np.abs(x - cx) < R_XZ) & (np.abs(z - cz) < R_XZ) & (np.abs(y - cy) < R_Y)
            for i in np.nonzero(m)[0]:
                hits.append(base + off + 4 * int(i))
    return (cx, cy, cz), np.array(sorted(set(hits)), dtype=np.uint64), car


def groups(addrs):
    """runs of addresses with one repeating stride (>= 4 members)"""
    out, i = [], 0
    a = list(map(int, addrs))
    while i < len(a) - 3:
        st = a[i + 1] - a[i]
        j = i + 1
        while j + 1 < len(a) and a[j + 1] - a[j] == st:
            j += 1
        if j - i + 1 >= 4 and 8 <= st <= 0x400:
            out.append((a[i], st, j - i + 1))
            i = j + 1
        else:
            i += 1
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"
    h = open_game()
    pos, hits, car = scan(h)
    path = os.path.join(HERE, "markscan_before.npz")
    print(f"car {car:#x} at x {pos[0]:.1f} y {pos[1]:.1f} z {pos[2]:.1f}: {len(hits)} triples within {R_XZ:g} m")
    if mode == "before":
        np.savez(path, hits=hits, pos=np.array(pos))
        print(f"baseline saved ({path}). Now skid / powerslide right here, then run: markscan.py after")
        return 0
    old = np.load(path)
    new = np.setdiff1d(hits, old["hits"])
    print(f"NEW since the baseline: {len(new)} triples")
    gs = sorted(groups(new), key=lambda g: -g[2])
    for start, stride, count in gs[:25]:
        x, y, z = struct.unpack("<3f", read(h, start, 12))
        print(f"  array at {start:#010x} stride {stride:#x} x {count:4d}   first ({x:.1f}, {y:.1f}, {z:.1f})")
    loose = len(new) - sum(g[2] for g in gs)
    print(f"  + {loose} loose triples")
    return 0


if __name__ == "__main__":
    sys.exit(main())
