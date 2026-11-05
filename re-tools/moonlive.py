"""LIVE preview (2026-10-09): DIMMER MOONLIGHT only (player: "make the Moonlight a bit dim. Not the whole
brightness ... I can see the brightness of a building shadow at night. Unrealistic").
The light manager 0x00405db0 builds the moon's directional light as ambient (sky +0x1b8) x moon intensity
(sky +0x1c8 = 0x02648318), loaded at 0x00405f9d `movss xmm0,[0x2648318]` (8 bytes). The other read of
+0x1c8 (0x00406122) only decides whether the moon light is enabled, so it is left alone. The hook scales the
loaded intensity by 1 - night*(1-M), night = sky +0x1dc (0x0264832c), so day is untouched. The ambient
(shadow side) stays as nightlive.py set it -> less contrast between lit and shadowed areas.
Memory only. Usage: moonlive.py [M=0.6] | off"""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
h = k.OpenProcess(0x0038 | 0x0400, False, cp.find_process())
SITE, ORIG = 0x00405F9D, bytes.fromhex("f30f100518836402")
MOON, NIGHT = 0x02648318, 0x0264832C


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


def moon_src(dim_addr, one_addr, back):
    # xmm1 is free here: the game loads it right after (0x00405fa7)
    return f"""
        movss xmm1, dword ptr [{NIGHT:#x}]
        mulss xmm1, dword ptr [{dim_addr}]
        movss xmm0, dword ptr [{one_addr}]
        subss xmm0, xmm1
        mulss xmm0, dword ptr [{MOON:#x}]
        jmp {back:#x}
    """


cur = rd(SITE, 8)
if sys.argv[1:2] == ["off"]:
    wr(SITE, ORIG); print("stock moonlight"); sys.exit()
M = float(sys.argv[1]) if len(sys.argv) > 1 else 0.6
if cur == ORIG:
    base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(moon_src(base + 0x200, base + 0x204, SITE + 8), base)[0])
    wr(base + 0x200, struct.pack("<ff", 1.0 - M, 1.0))
    wr(base, code)
    wr(SITE, b"\xe9" + struct.pack("<i", base - (SITE + 5)) + b"\x90\x90\x90")
    print(f"cave {len(code)} bytes at {base:#x}")
else:
    assert cur[0] == 0xE9, "hook site changed"
    base = SITE + 5 + struct.unpack("<i", cur[1:5])[0]
    wr(base + 0x200, struct.pack("<f", 1.0 - M))
print(f"moonlight x {M} at full night (1 = stock); night now {struct.unpack('<f', rd(NIGHT, 4))[0]:.2f}, "
      f"moon intensity {struct.unpack('<f', rd(MOON, 4))[0]:.2f}")
