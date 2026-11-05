"""LIVE preview (2026-10-04): the cloud shadow + a Milky Way brightness in the RUNNING game, without a
restart. Puts racemod's cloud-shadow cave (the same assembly as the build, _mw_shade_src) in fresh
memory, points the clouds' 0x004287b1 at it, and writes the brightness float into the milkyway data.
Nothing on disk changes; quitting the game undoes it all.
Usage: mwlive_shade.py [brightness=0.6] [shade=1.0]      mwlive_shade.py off  (stock clouds back)"""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
import racemod as r
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
pid = cp.find_process()
h = k.OpenProcess(0x0038 | 0x0400, False, pid)
HOOK, ORIG = 0x004287B1, bytes.fromhex("8b8bf0010000")


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


d = r.MW_D
name = rd(d["NAME"], len(r.MW_TEXNAME))
assert name == r.MW_TEXNAME, f"the running game's milkyway data is not where this racemod expects it ({name!r})"
cur = rd(HOOK, 6)
if sys.argv[1:2] == ["off"]:
    wr(HOOK, ORIG)
    print(f"clouds hook {cur.hex()} -> {ORIG.hex()} (stock clouds)")
    sys.exit()
bright = float(sys.argv[1]) if len(sys.argv) > 1 else 0.6
shade = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
if cur == ORIG:
    base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
    kaddr = base + 0x200
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(r._mw_shade_src(kaddr), base)[0])
    wr(kaddr, struct.pack("<f", shade))
    wr(base, code)
    wr(HOOK, b"\xe9" + struct.pack("<i", base - (HOOK + 5)) + b"\x90")
    print(f"cloud shadow cave {len(code)} bytes at {base:#x} (strength {shade:g}); clouds hook -> it")
else:
    base = HOOK + 5 + struct.unpack("<i", cur[1:5])[0]
    wr(base + 0x200, struct.pack("<f", shade))
    print(f"cloud shadow already live at {base:#x}; strength now {shade:g}")
was = struct.unpack("<f", rd(d["GAIN"], 4))[0]
wr(d["GAIN"], struct.pack("<f", bright))
print(f"Milky Way brightness {was:g} -> {bright:g}; night y {struct.unpack('<f', rd(0x02648270, 4))[0]:+.3f}")
