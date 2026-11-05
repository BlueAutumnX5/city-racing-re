"""READ-ONLY: sample the installed racemod headlights' own counters in the running game (5 x 1 s).
Shows whether each cave runs and how much it draws: land parts, buildings, car bodies, lamp posts/decor,
trees+rocks. Usage: hlcounters.py [samples]"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import ctypes
import struct
import subprocess
import sys
import time

sys.path.insert(0, crpaths.WORK)
import racemod                     # noqa: E402
import headlights as hl            # noqa: E402

L = hl.DATA_LAYOUT
FIELDS = ["STATE", "ERR", "FRAMES", "NIGHTI", "NUM", "MAXCARS", "DRAWN", "NOBJ", "ODRAWN", "BDRAWN",
          "NLOBJ", "LDRAWN", "NNAT", "NDRAWN"]
FLOATS = {"NIGHTI"}


def pid():
    out = subprocess.run(["tasklist", "/fi", "imagename eq game.exe", "/fo", "csv", "/nh"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0].lower() == "game.exe":
            return int(parts[1])


def main():
    p = pid()
    if not p:
        print("game.exe is not running")
        return 1
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0010, False, p)          # PROCESS_VM_READ only
    buf = ctypes.create_string_buffer(0x1000)
    got = ctypes.c_size_t()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print("  ".join(f"{f:>7}" for f in FIELDS))
    for _ in range(n):
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(racemod.HL_DATA), buf, 0x1000, ctypes.byref(got)):
            print("read failed")
            return 1
        row = []
        for f in FIELDS:
            raw = buf.raw[L[f]:L[f] + 4]
            row.append(f"{struct.unpack('<f', raw)[0]:7.2f}" if f in FLOATS else f"{struct.unpack('<i', raw)[0]:7d}")
        print("  ".join(row))
        time.sleep(1)
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
