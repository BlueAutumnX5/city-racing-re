"""dumpread.py <file.dmp> - READ a Windows minidump of game.exe (32-bit): the exception, its registers, and the
stack scanned for return addresses into game.exe / our code (.crmod S2, .crhl) / crdrive.dll / d3d9 - who called
what when it crashed. No external packages (the MINIDUMP format: header, stream directory; Exception 6, ModuleList 4,
MemoryList 5, Memory64List 9, ThreadList 3).
"""
import struct
import sys

f = open(sys.argv[1], "rb")
data = f.read()
sig, ver, nstreams, dir_rva = struct.unpack_from("<4sIII", data, 0)
assert sig == b"MDMP", sig
streams = {}
for i in range(nstreams):
    t, size, rva = struct.unpack_from("<III", data, dir_rva + 12 * i)
    streams.setdefault(t, (size, rva))


def mdstr(rva):
    n = struct.unpack_from("<I", data, rva)[0]
    return data[rva + 4:rva + 4 + n].decode("utf-16le")


mods = []
if 4 in streams:
    _, rva = streams[4]
    n = struct.unpack_from("<I", data, rva)[0]
    for i in range(n):
        o = rva + 4 + 108 * i
        base, size = struct.unpack_from("<QI", data, o)
        name_rva = struct.unpack_from("<I", data, o + 20)[0]
        mods.append((base, size, mdstr(name_rva).split("\\")[-1]))

ranges = []                                         # (va, size, file offset)
if 9 in streams:
    _, rva = streams[9]
    n, base_rva = struct.unpack_from("<QQ", data, rva)
    off = base_rva
    for i in range(n):
        va, size = struct.unpack_from("<QQ", data, rva + 16 + 16 * i)
        ranges.append((va, size, off))
        off += size
if 5 in streams:
    _, rva = streams[5]
    n = struct.unpack_from("<I", data, rva)[0]
    for i in range(n):
        va, size, mrva = struct.unpack_from("<QII", data, rva + 4 + 16 * i)
        ranges.append((va, size, mrva))


def mem(va, n):
    for a, s, o in ranges:
        if a <= va and va + n <= a + s:
            return data[o + va - a:o + va - a + n]
    return None


def where(a):
    for b, s, nm in mods:
        if b <= a < b + s:
            return f"{nm}+{a - b:#x}"
    if 0x02701000 <= a < 0x02711000:
        return f".crmod {a:#x}"
    if 0x02711000 <= a < 0x02832000:
        return f".crhl {a:#x}"
    return None


print("modules of interest:", [(nm, hex(b)) for b, s, nm in mods if nm.lower() in
                               ("game.exe", "d3d9.dll", "crdrive.dll", "nvd3dum.dll", "igdumdim32.dll")])
size, rva = streams[6]
tid = struct.unpack_from("<I", data, rva)[0]
code, flags, rec, addr, nparams = struct.unpack_from("<IIQQI", data, rva + 8)
params = struct.unpack_from("<15Q", data, rva + 8 + 32)
ctx_size, ctx_rva = struct.unpack_from("<II", data, rva + 8 + 152)
print(f"thread {tid:#x} exception {code:#x} at {addr:#x} ({where(addr)}); params {[hex(p) for p in params[:nparams]]}")
c = data[ctx_rva:ctx_rva + ctx_size]
# x86 CONTEXT: flags 0, Dr0-7 4..28, FloatSave 28..140, segs 140..156, edi 156 esi ebx edx ecx eax ebp eip cs eflags esp ss
regs = dict(zip(["edi", "esi", "ebx", "edx", "ecx", "eax", "ebp", "eip"], struct.unpack_from("<8I", c, 156)))
regs["esp"] = struct.unpack_from("<I", c, 196)[0]
print("registers:", " ".join(f"{k}={v:#010x}" for k, v in regs.items()))
for k in ("esi", "edi", "ebx", "ecx", "eax", "edx"):
    w = where(regs[k])
    if w:
        print(f"  {k} -> {w}")
print("stack (return addresses / interesting pointers):")
esp = regs["esp"]
stk = b""
for a_, s_, o_ in ranges:
    if a_ <= esp < a_ + s_:
        stk = data[o_ + esp - a_:o_ + min(s_, esp - a_ + 0x3000)]
print(f"  ({len(stk):#x} stack bytes saved from esp)")
for i in range(0, len(stk) - 3, 4):
    v = struct.unpack_from("<I", stk, i)[0]
    w = where(v)
    if w and not w.startswith(("ntdll", "KERNEL", "kernel")):
        print(f"  [esp+{i:#05x}] {v:#010x}  {w}")
