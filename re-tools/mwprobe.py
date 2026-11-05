"""LIVE probe (2026-10-04): why does Data/Sky/MilkyWay.dds not load? Puts a stub in fresh memory in the
running game that repeats the texture loader 0x0040ff20 step by step and RECORDS each result
(archive lookup, size, malloc, fread, first bytes, D3DXCreateTextureFromFileInMemoryEx HRESULT), points the
milkyway cave's `call 0x0040ad00` at it for ONE try (STATE 0 -> the cave runs it next night frame), then
puts the call back. The stub returns -1, so the cave ends in STATE 2 as before; a created texture is
released. Usage: mwprobe.py [pool=1] [mips=1] [live]
`live` (found 2026-10-04: the pak entry was XOR 0x80-scrambled by skyprep install - pak PAYLOADS are plain,
only index names are XORed): unscramble in memory, and on success register the texture in a free slot of
the texture manager (as 0x004100ec does) and return that slot, so the cave builds the sphere and draws NOW."""
import ctypes, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp
import racemod as r
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

POOL = int(sys.argv[1]) if len(sys.argv) > 1 else 1
MIPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
LIVE = "live" in sys.argv
k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
pid = cp.find_process()
h = k.OpenProcess(0x0038 | 0x0400, False, pid)        # VM_OPERATION|VM_READ|VM_WRITE|QUERY


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
    assert ok and got.value == len(data), f"write at {a:#x} failed"


# the cave's call to the loader
cave = rd(r.MW_CAVE, 0x80)
site = next(r.MW_CAVE + i for i in range(len(cave) - 5)
            if cave[i] == 0xE8 and r.MW_CAVE + i + 5 + struct.unpack("<i", cave[i + 1:i + 5])[0] == 0x0040AD00)
orig = rd(site, 5)
base = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
R, SIZE, TEXOUT, NAME, RET = base + 0x800, base + 0x880, base + 0x884, base + 0x900, base + 0x888
TM = 0x0255D7F0 + 0x27C
handles = struct.unpack("<1024I", rd(TM + 0x3FC00, 4096))
SLOT = handles.index(0)
name = r.MW_TEXNAME
DEVICE = 0x0255D7F0 + 0x44034
xorloop = f"""
    mov ecx, dword ptr [{SIZE}]
    mov edi, ebp
xl:
    xor byte ptr [edi], 0x80
    inc edi
    dec ecx
    jnz xl
""" if LIVE else ""
keep = f"""
    mov dword ptr [{TM + 0x3FC00 + 4 * SLOT}], eax
    mov dword ptr [{TM + 0x40C00 + 4 * SLOT}], 1
    mov dword ptr [{RET}], {SLOT}
""" if LIVE else """
    mov ecx, dword ptr [eax]
    push eax
    call dword ptr [ecx+8]
"""
src = f"""
    pushad
    mov dword ptr [{R}], 1
    mov eax, dword ptr [0x0059043c]
    mov dword ptr [{R + 4}], eax
    mov dword ptr [{SIZE}], 0
    push {SIZE}
    push 0x1388
    push {NAME}
    mov ecx, 0x012cc128
    call 0x0046fb50
    mov dword ptr [{R + 8}], eax
    mov ecx, dword ptr [{SIZE}]
    mov dword ptr [{R + 12}], ecx
    cmp eax, -1
    je done
    mov esi, eax
    push dword ptr [{SIZE}]
    call 0x0054a90c
    add esp, 4
    mov dword ptr [{R + 16}], eax
    test eax, eax
    je closeit
    mov ebp, eax
    push esi
    push dword ptr [{SIZE}]
    push 1
    push ebp
    mov ecx, 0x012cc128
    call 0x0046edf0
    mov dword ptr [{R + 20}], eax
closeit:
    push esi
    mov ecx, 0x012cc128
    call 0x0046eb80
    cmp dword ptr [{R + 20}], 0
    je done
    mov eax, dword ptr [ebp]
    mov dword ptr [{R + 24}], eax
    mov eax, dword ptr [ebp+0x50]
    mov dword ptr [{R + 40}], eax
    {xorloop}
    mov dword ptr [{TEXOUT}], 0
    push {TEXOUT}
    push 0
    push 0
    push 0
    push -1
    push -1
    push {POOL}
    push 0
    push 0
    push {MIPS}
    push -1
    push -1
    push dword ptr [{SIZE}]
    push ebp
    push dword ptr [{DEVICE}]
    call 0x004890f7
    mov dword ptr [{R + 28}], eax
    mov eax, dword ptr [{TEXOUT}]
    mov dword ptr [{R + 32}], eax
    test eax, eax
    je freeit
    {keep}
freeit:
    push ebp
    call 0x0054aafa
    add esp, 4
done:
    mov dword ptr [{R + 36}], 0xD0E
    popad
    mov eax, dword ptr [{RET}]
    ret 0xc
"""
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, base)[0])
wr(base, code)
wr(NAME, name)
wr(R, bytes(64))
wr(RET, struct.pack('<i', -1))
if LIVE:
    wr(TM + SLOT * 0xFF, name.ljust(0xFF, b'\0')[:0xFF])
st = struct.unpack("<I", rd(r.MW_DATA, 4))[0]
print(f"pid {pid}; stub {len(code)} bytes at {base:#x}; cave call at {site:#x} ({orig.hex()}); STATE was {st}")
wr(site, b"\xe8" + struct.pack("<i", base - (site + 5)))
wr(r.MW_DATA, struct.pack("<I", 0))                     # STATE 0: the cave tries again next night frame
t0 = time.time()
while time.time() - t0 < 30 and struct.unpack("<I", rd(R + 36, 4))[0] != 0xD0E:
    time.sleep(0.2)
wr(site, orig)                                          # the cave's own call back
res = struct.unpack("<11I", rd(R, 44))
if res[9] != 0xD0E:
    print("stub did not run in 30 s (not night / game paused?) - call restored; STATE", struct.unpack("<I", rd(r.MW_DATA, 4))[0])
    sys.exit(1)
print(f"pak mode [0x59043c] = {res[1]}")
print(f"lookup in archive 0x1388: handle {res[2] if res[2] != 0xFFFFFFFF else -1}, size {res[3]:,}")
print(f"malloc -> {res[4]:#x}; fread -> {res[5]:,}")
print(f"first dword {res[6]:#x} ({struct.pack('<I', res[6])}), pf flags @0x50 {res[10]:#x}")
hr = res[7]
print(f"D3DXCreateTextureFromFileInMemoryEx(pool {POOL}, mips {MIPS}) HRESULT {hr:#010x}, texture {res[8]:#x}")
time.sleep(1.0)
st, tex, vtx, idx = struct.unpack("<4I", rd(r.MW_DATA, 16))
print(f"STATE now {st}, TEX {tex}, VTX {vtx:#x} (free slot used: {SLOT if LIVE else None})")
