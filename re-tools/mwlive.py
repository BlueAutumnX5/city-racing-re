"""Read-only: the milkyway cave's status block + night value from the running game."""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
import racemod as r

pid = cp.find_process()
print("pid", pid)
h = cp.k32.OpenProcess(0x0010, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


names = ["STATE", "TEX", "VTX", "IDX", "TMPI", "CB", "SB", "CL", "SL", "DB", "DL", "HALFPI", "PI", "INVLON",
         "INVLAT", "NEGK", "ZERO", "ONE", "GAIN", "EPS"]
st, tex, vtx, idx = struct.unpack("<4I", rd(r.MW_DATA, 16))
print("STATE", st, "TEX", hex(tex), "VTX", hex(vtx), "IDX", hex(idx))
print("night y [0x2648270]", struct.unpack("<f", rd(0x2648270, 4))[0])
print("GAIN", struct.unpack("<f", rd(r.MW_DATA + 4 * names.index("GAIN"), 4))[0])
print("material emissive", struct.unpack("<17f", rd(r.MW_DATA + 4 * (len(names) + 9), 0x44))[12:16])
print("hook bytes at 0x4260a2:", rd(0x4260A2, 5).hex(), " name:", rd(r.MW_DATA + 4 * (len(names) + 9) + 0x44, 24))
if vtx:
    for i in (0, 1072, 2144):
        print("vertex", i, [round(x, 2) for x in struct.unpack("<5f", rd(vtx + 20 * i, 20))])
