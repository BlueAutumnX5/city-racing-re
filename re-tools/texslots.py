"""Read-only: CTextureManager (0x0255d7f0) slot use - names at +0x27c (0xff each), handles at +0x27c+0x3fc00."""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

pid = cp.find_process()
h = cp.k32.OpenProcess(0x0010, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


base = 0x0255D7F0 + 0x27C
ptrs = struct.unpack("<1024I", rd(base + 0x3FC00, 4096))
used = [i for i, p in enumerate(ptrs) if p]
names = rd(base, 1024 * 0xFF)
print(f"texture slots used: {len(used)} of 1024")
big = []
for i in used[:5] + used[-5:]:
    print(i, hex(ptrs[i]), names[i * 0xFF:(i + 1) * 0xFF].split(b"\0")[0])
dev = struct.unpack("<I", rd(0x025A1824, 4))[0]
print("device", hex(dev))
