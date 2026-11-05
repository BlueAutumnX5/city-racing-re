"""Read-only: the game's archive file system (0x012cc128): per archive the entry count and whether a name
is in its table (entries 0x110 bytes: name[256], size, offset). Usage: vfslive.py [name]"""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

want = (sys.argv[1] if len(sys.argv) > 1 else "Data/Sky/MilkyWay.jpg").lower()
pid = cp.find_process()
h = cp.k32.OpenProcess(0x0010, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


VFS = 0x012CC128
hdr = struct.unpack("<10I", rd(VFS, 40))
print("vfs header dwords:", [hex(x) for x in hdr])
for label, cnt_off, tab_off in (("0x3e8", 4, 0x14), ("0x1388", 8, 0x18), ("0x1770", 0xc, 0x1c), ("0xfa0", 4, 0x14)):
    n = struct.unpack("<I", rd(VFS + cnt_off, 4))[0]
    tab = struct.unpack("<I", rd(VFS + tab_off, 4))[0]
    if not tab or n > 100000:
        print(label, "count", n, "table", hex(tab)); continue
    raw = rd(tab, n * 0x110)
    names = [raw[i * 0x110:i * 0x110 + 256].split(b"\0")[0].decode("latin-1") for i in range(n)]
    hit = [i for i, s in enumerate(names) if s.lower() == want]
    sky = [s for s in names if "sky" in s.lower()]
    print(f"archive {label}: count {n}, table {tab:#x}; first {names[:1]}, last {names[-1:]}; {want!r} at {hit}; sky: {sky}")
    if hit:
        i = hit[0]
        print("   entry size/offset:", struct.unpack("<II", raw[i * 0x110 + 256:i * 0x110 + 264]))
