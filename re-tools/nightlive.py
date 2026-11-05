"""LIVE preview (2026-10-05): DARKER NIGHTS. The time-of-day step 0x00426c90 ends by writing the ambient
colour (sky obj 0x02648150 +0x1b8, read ONLY by the light manager: D3D ambient, moonlight = ambient*moon
intensity, fog colour). Hook its last store 0x00427190 (movss [esi+0x1c4],xmm6; 8 bytes) and scale the RGB
by f = 1 - night*(1-K), night = the game's smooth night factor +0x1dc (0..1). Lamps, windows, glows and
headlights are emissive/separate and untouched. Memory only. Usage: nightlive.py [K=0.55] [tintR,tintG,tintB] | off"""
import ctypes, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
h = k.OpenProcess(0x0038 | 0x0400, False, cp.find_process())
SITE, ORIG = 0x00427190, bytes.fromhex("f30f11b6c4010000")
JMP, NOP3 = bytes([0xE9]), bytes([0x90, 0x90, 0x90])


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


def night_src(dark_addr, back):
    """Per-channel: c *= 1 - night*DARK_c, DARK_c = 1 - K*tint_c (v2 2026-10-10: blue moonlit nights)."""
    ch = ""
    for n, off in enumerate((0x1b8, 0x1bc, 0x1c0)):
        ch += f"""
        movss xmm0, dword ptr [esi+0x1dc]
        mulss xmm0, dword ptr [{dark_addr + 4 * n:#x}]
        movss xmm1, dword ptr [{dark_addr + 12:#x}]
        subss xmm1, xmm0
        movss xmm0, dword ptr [esi+{off:#x}]
        mulss xmm0, xmm1
        movss dword ptr [esi+{off:#x}], xmm0"""
    return f"""
        movss dword ptr [esi+0x1c4], xmm6{ch}
        jmp {back:#x}
    """


cur = rd(SITE, 8)
if sys.argv[1:2] == ["off"]:
    wr(SITE, ORIG); print("stock night"); sys.exit()
K = float(sys.argv[1]) if len(sys.argv) > 1 else 0.55
TINT = tuple(float(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else (1.0, 1.0, 1.0)
data = struct.pack("<4f", *(1.0 - K * t for t in TINT), 1.0)
if cur != ORIG:                       # unhook first, so the game never runs a half-written cave
    base = SITE + 5 + struct.unpack("<i", cur[1:5])[0]
    wr(SITE, ORIG); time.sleep(0.1)
else:
    base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(night_src(base + 0x200, SITE + 8), base)[0])
wr(base + 0x200, data)
wr(base, code)
wr(SITE, JMP + struct.pack("<i", base - (SITE + 5)) + NOP3)
print(f"cave {len(code)} bytes at {base:#x}; night ambient K = {K:g} x tint {TINT} (1 = stock)")
