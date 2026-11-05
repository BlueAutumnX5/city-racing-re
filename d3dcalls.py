"""Find IDirect3DDevice9 vtable calls in game.exe.

A COM interface call compiles to `call dword ptr [reg + vtable_offset]`. For IDirect3DDevice9
the method order is fixed, so the offset identifies the method:

    index * 4 = offset      Clear=43 (0xAC)  SetTransform=44 (0xB0)  GetTransform=45 (0xB4)
                            MultiplyTransform=46 (0xB8)  SetViewport=47 (0xBC)
                            BeginScene=41 (0xA4)  EndScene=42 (0xA8)  Present=17 (0x44)

Encoding for a 32-bit displacement: FF /2 with mod=10b ->
    FF 90+r  disp32       (eax=0, ecx=1, edx=2, ebx=3, esp=4, ebp=5, esi=6, edi=7)
Finding Clear/BeginScene/EndScene/Present at their expected offsets validates the whole
approach before trusting the SetTransform hits.
"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct

PATH = crpaths.GAME_EXE
d = open(PATH, "rb").read()

SECS = [('.text', 0x1000, 0x16622b, 0x400, 0x166400),
        ('.rdata', 0x168000, 0x27642, 0x166800, 0x27800),
        ('.data', 0x190000, 0x216c57c, 0x18e000, 0x22a00)]
IMAGEBASE = 0x400000

METHODS = {
    0x44: "Present(17)",
    0xA4: "BeginScene(41)",
    0xA8: "EndScene(42)",
    0xAC: "Clear(43)",
    0xB0: "SetTransform(44)   <<< projection",
    0xB4: "GetTransform(45)",
    0xB8: "MultiplyTransform(46)",
    0xBC: "SetViewport(47)",
    0xC0: "GetViewport(48)",
}
REGS = {0: "eax", 1: "ecx", 2: "edx", 3: "ebx", 5: "ebp", 6: "esi", 7: "edi"}


def sec_of(off):
    for n, va, vs, ra, rs in SECS:
        if ra <= off < ra + rs:
            return n, IMAGEBASE + va + (off - ra)
    return "?", 0


def find_calls(disp):
    """call dword ptr [reg+disp32] -> FF (90+r) disp32"""
    out = []
    for r, rn in REGS.items():
        pat = bytes([0xFF, 0x90 + r]) + struct.pack("<I", disp)
        i = 0
        while True:
            k = d.find(pat, i)
            if k < 0:
                break
            sec, va = sec_of(k)
            if sec == ".text":
                out.append((k, va, rn))
            i = k + 1
    return sorted(out)


print("=== IDirect3DDevice9 vtable call sites ===")
for disp in sorted(METHODS):
    hits = find_calls(disp)
    print(f"\n[0x{disp:02x}] {METHODS[disp]:<34} {len(hits)} call site(s)")
    for k, va, rn in hits[:12]:
        print(f"      raw 0x{k:06x}  VA 0x{va:08x}  call [{rn}+0x{disp:02x}]")

# For each SetTransform site, show preceding bytes - the first arg (D3DTRANSFORMSTATETYPE)
# is pushed just before. D3DTS_VIEW=2, D3DTS_PROJECTION=3, D3DTS_WORLD=256.
print("\n\n=== context before each SetTransform call (looking for a pushed 3 = D3DTS_PROJECTION) ===")
for k, va, rn in find_calls(0xB0):
    lo = max(0, k - 40)
    print(f"\n-- raw 0x{k:06x} (VA 0x{va:08x}) --")
    for i in range(lo, k + 6, 16):
        c = d[i:i + 16]
        mark = " <<< call" if i <= k < i + 16 else ""
        print(f"    {i:08x}  {c.hex(' '):<47}{mark}")
    win = d[lo:k]
    for val, name in ((3, "D3DTS_PROJECTION"), (2, "D3DTS_VIEW"), (256, "D3DTS_WORLD")):
        if bytes([0x6A, val]) in win:
            print(f"    -> found push {val} ({name})  [6a {val:02x}]")
        if bytes([0x68]) + struct.pack("<I", val) in win:
            print(f"    -> found push dword {val} ({name})  [68 ...]")
