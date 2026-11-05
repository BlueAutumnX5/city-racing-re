r"""Find the live D3D projection matrix inside a running game.exe.

A D3D perspective projection matrix is extremely distinctive: 11 of its 16 floats are
exactly 0.0 and one is exactly 1.0.

    row-major / row-vector (the usual D3D layout)
        [ m00   0    0    0 ]        index 11 == 1.0
        [  0   m11   0    0 ]        index 14 <  0
        [  0    0   m22   1 ]
        [  0    0   m32   0 ]

    transposed (column-vector) variant
        [ m00   0    0    0 ]        index 14 == 1.0
        [  0   m11   0    0 ]        index 11 <  0
        [  0    0   m22  m32]
        [  0    0    1    0 ]

aspect = m11 / m00, and fovY = 2 * atan(1 / m11).

So reading it tells us exactly what aspect the engine thinks it is rendering, and whether
that value tracks the real backbuffer or is frozen at 4:3.

Usage:  findproj.py            scan once
        findproj.py --watch N  rescan every N seconds (catch changes as you drive)
"""

import ctypes
import ctypes.wintypes as wt
import math
import struct
import subprocess
import sys
import time

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x20, 0x40)   # R, RW, RX, RWX

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD),
                ("Protect", wt.DWORD),
                ("Type", wt.DWORD)]


def find_pid(name="game.exe"):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout.strip()
    if name.lower() not in out.lower():
        return None
    try:
        return int(out.split(",")[1].strip('"'))
    except Exception:
        return None


def regions(h):
    addr = 0x10000
    mbi = MEMORY_BASIC_INFORMATION()
    while addr < 0x7FFF0000:
        got = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi),
                                 ctypes.sizeof(mbi))
        if not got:
            addr += 0x1000
            continue
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0x1000
        if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE
                and not (mbi.Protect & PAGE_GUARD) and size <= 64 * 1024 * 1024):
            yield base, size
        addr = base + size
        if size == 0:
            break


def read(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size,
                                 ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


ONE = struct.pack("<f", 1.0)


def classify(f):
    """Return ('row'|'col', aspect, fovY_degrees) or None."""
    def z(i):
        return abs(f[i]) < 1e-6

    common_zero = all(z(i) for i in (1, 2, 3, 4, 6, 7, 8, 9, 12, 13, 15))
    if not common_zero:
        return None
    if not (0.05 < f[0] < 200 and 0.05 < f[5] < 200):
        return None

    # row-vector layout: [11] == 1.0, [14] negative
    if abs(f[11] - 1.0) < 1e-6 and f[14] < 0 and 0.2 < f[10] < 5.0:
        return "row", f[5] / f[0], math.degrees(2 * math.atan(1.0 / f[5]))
    # column-vector layout: [14] == 1.0, [11] negative
    if abs(f[14] - 1.0) < 1e-6 and f[11] < 0 and 0.2 < f[10] < 5.0:
        return "col", f[5] / f[0], math.degrees(2 * math.atan(1.0 / f[5]))
    return None


def scan(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print(f"OpenProcess failed: {ctypes.get_last_error()}")
        return []
    hits, scanned = [], 0
    try:
        for base, size in regions(h):
            data = read(h, base, size)
            if not data:
                continue
            scanned += len(data)
            # fast pre-filter: a 1.0 float must sit at matrix offset 44 or 56
            start = 0
            while True:
                k = data.find(ONE, start)
                if k < 0:
                    break
                start = k + 4
                for moff in (44, 56):
                    m0 = k - moff
                    if m0 < 0 or m0 + 64 > len(data) or m0 % 4:
                        continue
                    f = struct.unpack_from("<16f", data, m0)
                    r = classify(f)
                    if r:
                        hits.append((base + m0, r, f))
    finally:
        k32.CloseHandle(h)
    return hits, scanned


def show(hits, scanned):
    print(f"scanned {scanned / 1024 / 1024:.0f} MB, {len(hits)} candidate matrices\n")
    seen = {}
    for addr, (layout, aspect, fov), f in hits:
        key = (round(f[0], 5), round(f[5], 5), layout)
        seen.setdefault(key, []).append(addr)
    for (m00, m11, layout), addrs in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        aspect = m11 / m00
        fov = math.degrees(2 * math.atan(1.0 / m11))
        print(f"  m00={m00:<12.6f} m11={m11:<12.6f} layout={layout}")
        print(f"      aspect = m11/m00 = {aspect:.6f}"
              f"    (4:3 = 1.333333, 16:9 = 1.777778)")
        print(f"      vertical FOV     = {fov:.2f} deg")
        print(f"      seen at {len(addrs)} address(es): "
              f"{', '.join(hex(a) for a in addrs[:6])}")
        print()


if __name__ == "__main__":
    pid = find_pid()
    if not pid:
        print("game.exe is not running - launch the game and get into the world first.")
        sys.exit(1)
    print(f"game.exe pid {pid}\n")
    if "--watch" in sys.argv:
        every = float(sys.argv[sys.argv.index("--watch") + 1])
        while True:
            hits, scanned = scan(pid)
            print(f"--- {time.strftime('%H:%M:%S')} ---")
            show(hits, scanned)
            time.sleep(every)
    else:
        hits, scanned = scan(pid)
        show(hits, scanned)
