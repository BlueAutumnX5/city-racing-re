"""LIVE (2026-10-04): apply the boardkeep extra to the running game - the distance float at
BOARD_KEEP_CONST (unused .crmod space in builds since bb1fa3e0) and the despawn fld at 0x004432fe.
Usage: boardkeep_live.py [metres=400] | off"""
import ctypes, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
import racemod as r
k = cp.k32
pid = cp.find_process()
if not pid:
    sys.exit("game.exe is not running")
h = k.OpenProcess(0x0038 | 0x0400, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got)); return b.raw[:got.value]


def wr(a, data):
    old = ctypes.c_uint32()
    k.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), 0x40, ctypes.byref(old))
    got = ctypes.c_size_t()
    assert k.WriteProcessMemory(h, ctypes.c_void_p(a), data, len(data), ctypes.byref(got)) and got.value == len(data)
    k.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), old.value, ctypes.byref(old))
    k.FlushInstructionCache(h, ctypes.c_void_p(a), len(data))


SITE, STOCK = 0x004432FE, bytes.fromhex("d9053c9a5600")
NEW = bytes.fromhex("d905") + struct.pack("<I", r.BOARD_KEEP_CONST)
cur = rd(SITE, 6)
assert cur in (STOCK, NEW), f"unexpected bytes at {SITE:#x}: {cur.hex()}"
if sys.argv[1:2] == ["off"]:
    wr(SITE, STOCK); print("stock 175 m despawn back"); sys.exit()
m = float(sys.argv[1]) if len(sys.argv) > 1 else 400.0
assert r.MOD_RSIZE == 0x6000 and rd(r.BOARD_KEEP_CONST, 4) in (bytes(4), rd(r.BOARD_KEEP_CONST, 4))
wr(r.BOARD_KEEP_CONST, struct.pack("<f", m))
wr(SITE, NEW)
print(f"race billboards now deleted only beyond {m:g} m (was {'175' if cur == STOCK else 'already patched'})")
