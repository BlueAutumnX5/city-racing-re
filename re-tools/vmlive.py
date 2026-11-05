"""Read-only: is game.exe large-address-aware in memory, and how is its 32-bit address space used
(free total, largest free block, top free blocks). 2026-10-04: why the 33.5 MB Milky Way DDS fails."""
import ctypes, ctypes.wintypes as w, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

pid = cp.find_process()
h = cp.k32.OpenProcess(0x0410, False, pid)          # QUERY_INFORMATION | VM_READ


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


pe = struct.unpack("<I", rd(0x400000 + 0x3C, 4))[0]
ch = struct.unpack("<H", rd(0x400000 + pe + 22, 2))[0]
print(f"in-memory PE characteristics {ch:#06x}: LARGE_ADDRESS_AWARE = {bool(ch & 0x20)}")


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD),
                ("Type", w.DWORD)]


VQ = cp.k32.VirtualQueryEx
VQ.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
VQ.restype = ctypes.c_size_t
a, free, used, top = 0, [], 0, 0
m = MBI()
while a < 0x100000000:
    if not VQ(h, ctypes.c_void_p(a), ctypes.byref(m), ctypes.sizeof(m)):
        break
    base, size = m.BaseAddress or 0, m.RegionSize
    if m.State == 0x10000:
        free.append((size, base))
    else:
        used += size
        top = max(top, base + size)
    a = base + size
free.sort(reverse=True)
print(f"committed+reserved {used / 2**20:,.0f} MB, highest used address {top:#x}")
print(f"free total {sum(s for s, _ in free) / 2**20:,.0f} MB; largest free blocks (MB @ address):")
for s, b in free[:8]:
    print(f"   {s / 2**20:8.1f} @ {b:#010x}")
