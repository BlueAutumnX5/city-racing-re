"""LIVE (2026-10-09): ETERNAL NIGHT - freeze the time of day (player: "make the game night only ... so we
can work with this faster", later a Control Panel option = racemod extra `nightlock`).
The time-of-day step 0x00426c90 computes phase = (int)(timer [0x012d04b0] ms + 500000) mod 2000000
(one day = 2,000,000 ms = 33.3 min), `div ecx` leaves it in edx, then 0x00426d00 `mov [esp+8],edx;
fild dword [esp+8]` (8 bytes) loads it. The hook replaces edx with a fixed phase. Everything else
(sun/moon/sky colours, night factor +0x1dc, stars) is derived from that phase in the same function.
(The [0x012d0ca8] fixed-time branch right after is EDITOR MODE - not usable.)
Memory only. Usage: nightlock.py scan | <phase> | off"""
import ctypes, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
h = k.OpenProcess(0x0038 | 0x0400, False, cp.find_process())
SITE, ORIG, BACK = 0x00426D00, bytes.fromhex("89542408db442408"), 0x00426D08
TIMER, NIGHT, DAY = 0x012D04B0, 0x0264832C, 2000000


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


f32 = lambda a: struct.unpack("<f", rd(a, 4))[0]
cur = rd(SITE, 8)
arg = sys.argv[1] if len(sys.argv) > 1 else "status"
if arg == "off":
    wr(SITE, ORIG); print("time of day runs again"); sys.exit()
if arg == "status":
    ph = (int(f32(TIMER)) + 500000) % DAY
    print(f"{'LOCKED' if cur != ORIG else 'running'}; clock phase {ph}, night {f32(NIGHT):.2f}"); sys.exit()
if cur == ORIG:
    base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
    src = f"""
        mov edx, dword ptr [{base + 0x200:#x}]
        mov dword ptr [esp+8], edx
        fild dword ptr [esp+8]
        jmp {BACK:#x}
    """
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, base)[0])
    wr(base + 0x200, struct.pack("<i", (int(f32(TIMER)) + 500000) % DAY))   # start = the current time
    wr(base, code)
    wr(SITE, b"\xe9" + struct.pack("<i", base - (SITE + 5)) + b"\x90\x90\x90")
else:
    base = SITE + 5 + struct.unpack("<i", cur[1:5])[0]
PH = base + 0x200
if arg == "scan":
    res = []
    for ph in range(0, DAY, 50000):
        wr(PH, struct.pack("<i", ph)); time.sleep(0.12)
        res.append((ph, f32(NIGHT)))
    print(" ".join(f"{p // 1000}k:{n:.2f}" for p, n in res))
    full = [p for p, n in res if n > 0.999]
    ph = full[len(full) // 2] if full else max(res, key=lambda r: r[1])[0]
else:
    ph = int(arg)
wr(PH, struct.pack("<i", ph)); time.sleep(0.3)
print(f"time of day LOCKED at phase {ph}; night {f32(NIGHT):.2f}")
