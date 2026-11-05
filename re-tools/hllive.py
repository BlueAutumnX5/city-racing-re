"""LIVE prototype (2026-10-05/09): per-pixel headlights for the 8 nearest cars, in the RUNNING game.
Memory only - quitting the game undoes it. Compiles techHeadlights (headlights.py) as a SEPARATE
effect inside the game on the first night frame (plus the v5 beam-cookie texture, D3DPOOL_MANAGED),
hooks the end of the terrain draw (0x0043124c) and redraws the land parts / static objects near
lit cars with it (see headlights.py for the design).
Device reset (Alt-Tab, a hidden window): 2026-10-05 a reset with the separate effect alive CRASHED the
game. A second hook at 0x0040c6a4 (inside the renderer's invalidate 0x0040c6a0, which runs before
every Reset) releases our effect too; the cave recreates it on the next night frame. The managed
cookie texture survives resets. `rebuild` releases the old effect (and cookie) IN the game's thread
first, finding the running block's data layout by its technique name (v4 and v5 layouts differ).
Usage: hllive.py on | off | rebuild | status | set <name> <value>
       names: range, gain, maxd, soft, wrap A,B"""
import ctypes, math, os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import cpuprofile as cp
import headlights as hl
import headlights_v4 as hl4
import headlights_v8 as hl8
import headlights_v9 as hl9
import headlights_v14e as hl14e
import headlights_v14f as hl14f
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

k = cp.k32
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
h = k.OpenProcess(0x0038 | 0x0400, False, cp.find_process())
A = hl.DATA_LAYOUT
DOFF = 0x2000                 # data block offset in our allocation
TVA, XVA, LVA, STUB = 0x4000, 0x20000, 0x1000, 0x1100
LATEVA = 0x3000                 # v15 late cave (decor/lamps + trees/rocks), up to TVA
BVA = 0x1800                    # v14 car-body cave (up to the data block at DOFF)  # effect text, cookie DDS, reset hook, release stub
ALLOC = 0x130000               # v14d: 77 KB effect text (6 passes) + 1 MB cookie at +0x20000
LOST, LOST_ORIG = 0x0040C6A4, bytes.fromhex("b980796402")   # mov ecx, 0x2647980
ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, at):
    return bytes(ks.asm(src, at)[0])


def lost_src(d, lay):
    return f"""
    pushad
    mov ecx, dword ptr [{d + lay['EFF']:#x}]
    test ecx, ecx
    je skip
    mov dword ptr [{d + lay['EFF']:#x}], 0
    mov dword ptr [{d + lay['STATE']:#x}], 0
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+8]
skip:
    popad
    mov ecx, 0x2647980
    jmp 0x40c6a9
"""


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


def jmp5(at, to):
    return b"\xe9" + struct.pack("<i", to - (at + 5))


u32 = lambda a: struct.unpack("<I", rd(a, 4))[0]
i32 = lambda a: struct.unpack("<i", rd(a, 4))[0]
f32 = lambda a: struct.unpack("<f", rd(a, 4))[0]
cur = rd(hl.HOOK, 7)
base = None if cur == hl.HOOK_ORIG else hl.HOOK + 5 + struct.unpack("<i", cur[1:5])[0]
if base is not None and base & 0xFFFF == STUB:     # a rebuild's release stub still waiting (no 3D frame yet)
    base -= STUB


def layout_of(b):
    """(data layout, version name, generator module) of a running block, found by the technique name at
    each known layout's NAME offset (current = headlights.py; older snapshots in re-tools)."""
    for mod, name in ((hl, "current"), (hl14f, "v14f"), (hl14e, "v14e"), (hl9, "v9"), (hl8, "v8"), (hl4, "v4")):
        if rd(b + DOFF + mod.DATA_LAYOUT["NAME"], 15) == b"techHeadlights\0":
            return mod.DATA_LAYOUT, name, mod
    raise SystemExit(f"block at {b:#x}: unknown data layout - not touching it")


cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

if cmd == "rebuild":
    if base is not None:
        lay, ver, _ = layout_of(base)
        d = base + DOFF
        tex = d + lay["TEX"] if "TEX" in lay else 0
        if u32(d + lay["EFF"]) or (tex and u32(tex)):
            rel_tex = f"""
                mov ecx, dword ptr [{tex:#x}]
                test ecx, ecx
                je t
                mov dword ptr [{tex:#x}], 0
                push ecx
                mov edx, dword ptr [ecx]
                call dword ptr [edx+8]
            t:""" if tex else ""
            src = f"""
                pushad
                mov dword ptr [{d + lay['STATE']:#x}], 3
                mov ecx, dword ptr [{d + lay['EFF']:#x}]
                test ecx, ecx
                je s
                mov dword ptr [{d + lay['EFF']:#x}], 0
                push ecx
                mov edx, dword ptr [ecx]
                call dword ptr [edx+8]
            s:{rel_tex}
                popad
                cmp dword ptr [0x12d0c9c], 0
                jmp {hl.HOOK_BACK:#x}
            """
            wr(base + STUB, asm(src, base + STUB))
            wr(hl.HOOK, jmp5(hl.HOOK, base + STUB) + b"\x90\x90")
            t0 = time.time()
            while (u32(d + lay["EFF"]) or (tex and u32(tex))) and time.time() - t0 < 10:
                time.sleep(0.1)
            assert not u32(d + lay["EFF"]), "old effect not released (no 3D frame in 10 s?) - stub left in place"
            print(f"old {ver} effect{' + cookie' if tex else ''} released")
        wr(hl.HOOK, hl.HOOK_ORIG)
        if rd(hl.BODY_HOOK, 1) == bytes([0xE9]):      # v14 body hook back to stock first
            wr(hl.BODY_HOOK, hl.BODY_ORIG)
        if rd(hl.LATE_HOOK, 1) == bytes([0xE9]):      # v15 late hook too
            wr(hl.LATE_HOOK, hl.LATE_ORIG)
        wr(LOST, LOST_ORIG)
        base = None
    cmd = "on"

if cmd == "on":
    if base is None:
        text = hl.technique_text().encode("latin-1")
        dds = hl.cookie_dds()
        assert len(text) < XVA - TVA and XVA + len(dds) < ALLOC
        base = k.VirtualAllocEx(h, None, ALLOC, 0x3000, 0x40)
        d = base + DOFF
        code = asm(hl.cave_src(d, "own", base + TVA, len(text), base + XVA, len(dds)), base)
        lcode = asm(lost_src(d, A), base + LVA)
        bcode = asm(hl.body_cave_src(d), base + BVA)   # v14 car bodies
        lcode2 = asm(hl.late_cave_src(d), base + LATEVA)   # v15 decor/lamps + trees/rocks
        assert len(lcode2) < TVA - LATEVA and rd(hl.LATE_HOOK, 5) == hl.LATE_ORIG, "late hook site changed"
        assert hl.DATA_LAYOUT["DATA_END"] < LATEVA - DOFF, "data block runs into the late cave"
        assert len(bcode) < DOFF - BVA and rd(hl.BODY_HOOK, 5) == hl.BODY_ORIG, "body hook site changed"
        assert len(code) < LVA and len(lcode) < STUB - LVA
        assert rd(LOST, 5) == LOST_ORIG, "invalidate hook site changed"
        wr(base + TVA, text + b"\x00")
        wr(base + XVA, dds)
        wr(d, hl.data_init())
        wr(base, code)
        wr(base + LVA, lcode)
        wr(LOST, jmp5(LOST, base + LVA))
        wr(base + BVA, bcode)
        wr(hl.BODY_HOOK, jmp5(hl.BODY_HOOK, base + BVA))
        wr(base + LATEVA, lcode2)
        wr(hl.LATE_HOOK, jmp5(hl.LATE_HOOK, base + LATEVA))
        wr(hl.HOOK, jmp5(hl.HOOK, base) + b"\x90\x90")
        print(f"cave {len(code)} bytes at {base:#x}, effect text {len(text)} bytes, cookie {len(dds)} bytes; "
              f"hooked (+ reset hook)")
    else:
        print(f"already on (cave {base:#x})")
    time.sleep(1.5)
    cmd = "status"
elif cmd == "off":
    if rd(hl.BODY_HOOK, 1) == bytes([0xE9]):
        wr(hl.BODY_HOOK, hl.BODY_ORIG)
    if rd(hl.LATE_HOOK, 1) == bytes([0xE9]):
        wr(hl.LATE_HOOK, hl.LATE_ORIG)
    wr(hl.HOOK, hl.HOOK_ORIG)       # the invalidate hook stays: it still frees our effect on a reset
    print("hook removed (stock terrain draw); the separate effect stays allocated until the game quits")
    sys.exit()
elif cmd == "set":
    assert base is not None, "not on"
    A, ver, M = layout_of(base)          # the RUNNING block's layout + its generator's constants
    assert ver != "v4", "set does not support the v4 layout - rebuild first"
    name, arg = sys.argv[2], sys.argv[3]
    d = base + DOFF
    c = d + A["PSC"] + 16 * M.CS
    if name == "range":
        v = float(arg)
        wr(d + A["RANGEF"], struct.pack("<f", v))
        wr(c + 8, struct.pack("<f", -1.0 / (v * v)))
        wr(c + 32 + 8, struct.pack("<f", v * v))
    elif name == "gain":
        old = struct.unpack("<f", rd(c + 24, 4))[0]            # land gain before (colour blue = 1)
        share = struct.unpack("<f", rd(d + A["OPSC"] + 24, 4))[0] / old if old > 1e-6 else getattr(M, 'OBJ_GAIN', 0.5)
        wr(c + 16, struct.pack("<3f", *(x * float(arg) for x in M.COLOUR)))
        wr(d + A["OPSC"] + 16, struct.pack("<3f", *(x * float(arg) * share for x in M.COLOUR)))
        if "BPSC" in A:             # car bodies keep their share too
            bs = struct.unpack("<f", rd(d + A["BPSC"] + 24, 4))[0] / old if old > 1e-6 else getattr(M, 'BODY_GAIN', 1.5)
            wr(d + A["BPSC"] + 16, struct.pack("<3f", *(x * float(arg) * bs for x in M.COLOUR)))
    elif name == "ogain":      # objects' share of the gain (0..1)
        g = struct.unpack("<f", rd(c + 24, 4))[0]          # current land gain (colour blue = 1)
        wr(d + A["OPSC"] + 16, struct.pack("<3f", *(x * g * float(arg) for x in M.COLOUR)))
    elif name == "bgain":      # car bodies' share of the gain
        g = struct.unpack("<f", rd(c + 24, 4))[0]
        wr(d + A["BPSC"] + 16, struct.pack("<3f", *(x * g * float(arg) for x in M.COLOUR)))
    elif name == "spec":       # car-paint highlight strength
        wr(d + A["BPSC"] + 64 + 8, struct.pack("<f", float(arg)))
    elif name == "shin":       # car-paint highlight sharpness (exponent)
        wr(d + A["BPSC"] + 64 + 4, struct.pack("<f", float(arg)))
    elif name == "bpaint":     # car bodies: strength of the paint-tinted additive light
        wr(d + A["BADD"] + 12, struct.pack("<f", float(arg)))
    elif name == "bmmax":      # car bodies' multiply limit
        wr(d + A["BPSC"] + 4, struct.pack("<f", 1.0 / float(arg)))
    elif name == "ommax":      # objects' multiply limit
        wr(d + A["OPSC"] + 4, struct.pack("<f", 1.0 / float(arg)))
    elif name == "blue":       # final additive pass strength (ADD_K)
        wr(c + 16 + 12, struct.pack("<f", float(arg)))
    elif name == "lamp":       # light source height above the model lamp points (m)
        wr(d + A["LAMPUP"], struct.pack("<4f", 0.0, float(arg), 0.0, 0.0))
    elif name == "bias":       # "D,S": depth bias, slope-scale bias (negative = towards the camera)
        db, sb = (float(x) for x in arg.split(","))
        wr(d + A["DBIAS"], struct.pack("<ff", db, sb))
    elif name == "cars":       # how many nearest cars get headlight light (1..N_CARS)
        n = int(arg)
        assert 1 <= n <= M.N_CARS, f"cars must be 1..{M.N_CARS}"
        wr(d + A["MAXCARS"], struct.pack("<I", n))
    elif name == "roads":      # bit mask of lit road layers (1, 2, 4)
        wr(d + A["RMASK"], struct.pack("<I", int(arg)))
    elif name == "mmax":       # multiply limit: F = 1 + E/(1 + E/MMAX)
        wr(c + 4, struct.pack("<f", 1.0 / float(arg)))
    elif name == "d0":         # distance falloff 1/(1 + d^2/D0^2)
        wr(c, struct.pack("<f", 1.0 / float(arg) ** 2))
    elif name == "tone":       # v10 log curve knee A (sum -> A*ln(1 + sum/A))
        assert M.NPSC > M.CS + 3, "this block has no tone constant"
        a = float(arg)
        wr(c + 48, struct.pack("<2f", 1.0 / a, a * math.log(2.0)))
        if "BPSC" in A and M.NPSC > M.CS + 4:
            wr(d + A["BPSC"] + 48, struct.pack("<2f", 1.0 / a, a * math.log(2.0)))
    elif name == "soft":
        wr(c + 32 + 12, struct.pack("<f", float(arg)))
    elif name == "wrap":       # "A,B": lambert = saturate(N.L*A + B)
        wr(c + 32, struct.pack("<2f", *(float(x) for x in arg.split(","))))
    elif name == "maxd":
        wr(d + A["MAXD"], struct.pack("<f", float(arg)))
    else:
        raise SystemExit(f"unknown {name}")
    print(f"{name} = {arg}")
    cmd = "status"

if cmd == "status":
    if base is None:
        print("off"); sys.exit()
    lay, ver, M = layout_of(base)
    d = base + DOFF
    st, eff, err, hr = u32(d + lay["STATE"]), u32(d + lay["EFF"]), u32(d + lay["ERR"]), i32(d + lay["HR"])
    print(f"{ver} cave {base:#x}: state {st} (1 ok, 2 create failed), effect {eff:#x}, create hr "
          f"{hr & 0xffffffff:#x}, passes {u32(d + lay['NPASS'])}"
          + (f", cookie {u32(d + lay['TEX']):#x} (hr {i32(d + lay['TEXHR']) & 0xffffffff:#x})" if ver != "v4" else ""))
    if err:      # ID3DXBuffer: look for the compiler's text in the object's own allocation
        blk = rd(err, 0x40)
        for o in range(4, 0x20, 4):
            ptr = struct.unpack_from("<I", blk, o)[0]
            txt = rd(ptr, 600) if ptr > 0x10000 else b""
            if txt[:1].isascii() and b"(" in txt[:200]:
                print("  compiler says:", txt.split(b"\0")[0].decode(errors="replace")[:600])
                break
    print(f"night {f32(hl.NIGHT):.2f}, cars lit {u32(d + lay['NUM'])}, frames {u32(d + lay['FRAMES'])}, "
          f"land part draws {u32(d + lay['DRAWN'])}, objects near lamps {u32(d + lay['NOBJ'])}, "
          f"object draws {u32(d + lay['ODRAWN'])}, road draws {u32(d + lay['RDRAWN']) if 'RDRAWN' in lay else '-'}, body draws {u32(d + lay['BDRAWN']) if 'BDRAWN' in lay else '-'}, late: decor/lamps {u32(d + lay['NLOBJ']) if 'NLOBJ' in lay else '-'} trees/rocks {u32(d + lay['NNAT']) if 'NNAT' in lay else '-'} (nature draws {u32(d + lay['NDRAWN']) if 'NDRAWN' in lay else '-'}), Begin hr {i32(d + lay['HRBEGIN']) & 0xffffffff:#x}")
    if ver != "v4":
        for i in range(min(u32(d + lay["NUM"]), M.N_CARS)):
            p = struct.unpack("<16f", rd(d + lay["PSC"] + 64 * i, 64))
            print(f"  car {i}: light ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) intensity {p[3]:.2f}  forward "
                  f"({-p[4]:.2f}, {-p[5]:.2f}, {-p[6]:.2f})  lamps left {p[7]:.0f} right {p[11]:.0f}  "
                  f"dist {struct.unpack('<f', rd(d + lay['DARR'] + 4 * i, 4))[0]:.1f}")
