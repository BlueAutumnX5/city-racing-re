r"""Live-patch the projection matrix's m00 in the running game, to identify it visually.

Writing m00 while you watch the screen is the fastest way to confirm which matrix is the
main camera - and what the correct value actually is - without disassembling anything.

    m00 controls HORIZONTAL field of view.
    SMALLER m00  =  WIDER view (more world visible left and right)
    aspect = m11 / m00

  livepatch.py find                 locate candidate matrices, print addresses
  livepatch.py set <value>          write m00 once, then verify it stuck
  livepatch.py hold <value> <secs>  keep rewriting m00 (for matrices rebuilt per frame)
  livepatch.py restore <value>      same as set - put the original value back
"""

import ctypes
import struct
import sys
import time

import findproj as fp

PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
ALL_ACCESS = (fp.PROCESS_QUERY_INFORMATION | fp.PROCESS_VM_READ
              | PROCESS_VM_WRITE | PROCESS_VM_OPERATION)


def open_game():
    pid = fp.find_pid()
    if not pid:
        print("game.exe is not running")
        sys.exit(1)
    h = fp.k32.OpenProcess(ALL_ACCESS, False, pid)
    if not h:
        print(f"OpenProcess failed: {ctypes.get_last_error()}")
        sys.exit(1)
    return pid, h


def find_matrices(h, want_aspect_not=1.0):
    """Return [(addr, m00, m11)] for strict perspective matches, skipping square ones."""
    out = []
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
                if not fp.classify(f):
                    continue
                if abs(f[5] / f[0] - want_aspect_not) < 1e-4:
                    continue          # skip the square cube-map projection
                out.append((base + m0, f[0], f[5]))
    return out


def write_f32(h, addr, value):
    buf = struct.pack("<f", value)
    written = ctypes.c_size_t(0)
    ok = fp.k32.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, 4,
                                   ctypes.byref(written))
    return bool(ok) and written.value == 4


def read_f32(h, addr):
    d = fp.read(h, addr, 4)
    return struct.unpack("<f", d)[0] if d and len(d) == 4 else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    pid, h = open_game()
    print(f"game.exe pid {pid}")
    try:
        mats = find_matrices(h)
        if not mats:
            print("no non-square perspective matrices found - is the game in the 3D world?")
            sys.exit(1)
        print(f"{len(mats)} candidate matrix/matrices (cube-map projection excluded):")
        for addr, m00, m11 in mats:
            print(f"   0x{addr:08x}   m00={m00:.6f}  m11={m11:.6f}  "
                  f"aspect={m11 / m00:.6f}")
        print()

        if cmd == "find":
            sys.exit(0)

        if cmd in ("set", "restore"):
            val = float(sys.argv[2])
            n = sum(write_f32(h, a, val) for a, _, _ in mats)
            print(f"wrote m00={val} to {n}/{len(mats)} addresses")
            time.sleep(1.0)
            print("re-reading after 1s (did it stick, or does the game rebuild it?):")
            stuck = 0
            for addr, _, _ in mats:
                now = read_f32(h, addr)
                held = now is not None and abs(now - val) < 1e-6
                stuck += held
                print(f"   0x{addr:08x} -> {now:.6f}  {'HELD' if held else 'overwritten'}")
            print(f"\n{stuck}/{len(mats)} held. "
                  + ("The matrix persists - a one-shot patch is enough."
                     if stuck else
                     "The game rebuilds it each frame - use 'hold' instead."))

        elif cmd == "hold":
            val = float(sys.argv[2])
            secs = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
            print(f"holding m00={val} for {secs}s - WATCH THE GAME WINDOW now")
            end = time.time() + secs
            n = 0
            while time.time() < end:
                for a, _, _ in mats:
                    write_f32(h, a, val)
                n += 1
                time.sleep(0.004)
            print(f"done - {n} write passes. Matrices left at their natural values.")
        else:
            print(__doc__)
    finally:
        fp.k32.CloseHandle(h)
