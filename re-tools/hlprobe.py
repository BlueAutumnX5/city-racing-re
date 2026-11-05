"""LIVE preview (2026-10-05): the PLAYER's headlight (D3D light 7, light manager 0x02647980) also lights
the terrain + buildings. Stock enables it (0x00405090) only around cars/humans and decor/lamps (0x004217c3);
this puts an extra enable right after the sky draw in the frame list 0x00421710 (site 0x00421746
`push 0x180`, before buildings 0x453e90(0x180) and terrain 0x430bf0). Memory only.
Usage: hlprobe.py [on|off|status]"""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
pid = cp.find_process()
h = k.OpenProcess(0x0038 | 0x0400, False, pid)
SITE, ORIG = 0x00421746, bytes.fromhex("6880010000")


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


def wr(a, data):
    old = ctypes.c_uint32()
    k.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), 0x40, ctypes.byref(old))
    got = ctypes.c_size_t()
    ok = k.WriteProcessMemory(h, ctypes.c_void_p(a), data, len(data), ctypes.byref(got))
    k.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), old.value, ctypes.byref(old))
    k.FlushInstructionCache(h, ctypes.c_void_p(a), len(data))
    assert ok and got.value == len(data), f"write at {a:#x} failed"


def status():
    pl = struct.unpack("<I", rd(0x012D0C88, 4))[0]
    be4 = struct.unpack("<i", rd(pl + 0xBE4, 4))[0] if pl else None
    night = struct.unpack("<f", rd(0x0264832C, 4))[0]
    print(f"night factor [0x264832c] = {night:.3f} (light needs > 0.5); player car {pl:#x} headlight slot {be4}")


cur = rd(SITE, 5)
mode = sys.argv[1] if len(sys.argv) > 1 else "on"
if mode == "off":
    wr(SITE, ORIG); print(f"site {cur.hex()} -> {ORIG.hex()} (stock)")
elif mode == "on":
    if cur != ORIG:
        print("already on")
    else:
        base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
        src = """
            mov ecx, 0x2647980
            call 0x405090
            push 0x180
            jmp 0x42174b
        """
        code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, base)[0])
        wr(base, code)
        wr(SITE, b"\xe9" + struct.pack("<i", base - (SITE + 5)))
        print(f"stub {len(code)} bytes at {base:#x}; headlight now also lights terrain + buildings")
status()
