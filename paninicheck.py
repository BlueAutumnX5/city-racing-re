r"""paninicheck.py - EXECUTE every `panini` cave in Unicorn, inside the fully patched exe, against mock
COM objects (device, the big world texture and its surface, the backbuffer, the device's depth surface,
our depth surface, the game's ID3DXEffect with the 2004 D3DX layout) whose methods log their calls,
fill their out-pointers and return a chosen HRESULT. The 3D-arrow draw (0x0045ea60) is stubbed and
logged. Checks the exact call sequences and arguments, reference counts (every Get* is Released),
the renderer's technique cache, stack balance and preserved registers - for the normal frame and
every failure path, redirected (supersampled) or not.
The shader itself is proven separately on the GPU by paninitest.py.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panini
import racemod
import racesim
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                                "fadein", "spawnreach", "view", "overlay", "racers", "shadows", "nodamage",
                                "modsect", "panini"]
SIM = racesim.Sim(NAMES)
MU = SIM.mu
R = racemod.RENDERER
MOCK = 0x07000000                       # objects + vtables
STUB = 0x07100000                       # method stubs: ret N (EAX set by the hook)
RET = 0x07200000                        # sentinel return address
MU.mem_map(MOCK, 0x300000, UC_PROT_ALL)
MU.mem_write(RET, b"\xcc")
MU.mem_write(racemod.ARROW_DRAW, b"\xc3")          # the arrow draw: logged, then returns
u32 = lambda a: struct.unpack("<I", MU.mem_read(a, 4))[0]
w32 = lambda a, v: MU.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
OK = []
D24S8 = 75

# (kind, vtable offset) -> (name, argument count excluding `this`, out-pointer arg index, value)
METHODS = {
    ("dev", 0x5c): ("CreateTexture", 8, 6, "TEX"),
    ("dev", 0x74): ("CreateDepthStencilSurface", 8, 6, "BIGDS"),
    ("dev", 0x98): ("GetRenderTarget", 2, 1, "BB"),
    ("dev", 0xa0): ("GetDepthStencilSurface", 1, 0, "ZS"),
    ("dev", 0x94): ("SetRenderTarget", 2, None, None),
    ("dev", 0x9c): ("SetDepthStencilSurface", 1, None, None),
    ("dev", 0x88): ("StretchRect", 5, None, None),
    ("dev", 0x178): ("SetVertexShaderConstantF", 3, None, None),
    ("dev", 0x100): ("GetTexture", 2, 1, "OLD"),
    ("dev", 0x104): ("SetTexture", 2, None, None),
    ("dev", 0x164): ("SetFVF", 1, None, None),
    ("dev", 0x190): ("SetStreamSource", 4, None, None),
    ("dev", 0x144): ("DrawPrimitive", 3, None, None),
    ("tex", 0x08): ("Release", 0, None, None),
    ("tex", 0x48): ("GetSurfaceLevel", 2, 1, "SURF"),
    ("surf", 0x08): ("Release", 0, None, None),
    ("surf", 0x30): ("GetDesc", 1, None, None),
    ("fx", 0xec): ("SetTechnique", 1, None, None),
    ("fx", 0x100): ("Begin", 2, 0, 1),
    ("fx", 0x104): ("Pass", 1, None, None),
    ("fx", 0x108): ("End", 0, None, None),
}
OBJ = {}
for i, (name, kind) in enumerate((("DEV", "dev"), ("TEX", "tex"), ("BB", "surf"), ("SURF", "surf"),
                                  ("OLD", "surf"), ("ZS", "surf"), ("BIGDS", "surf"), ("FX", "fx"),
                                  ("QUAD", "surf"))):
    OBJ[name] = (MOCK + i * 0x1000, kind)
STUBS = {}
for oname, (addr, kind) in OBJ.items():
    vt = addr + 0x100
    w32(addr, vt)
    for off in range(0, 0x200, 4):
        s = STUB + len(STUBS) * 16
        meth = METHODS.get((kind, off), (f"UNEXPECTED+{off:#x}", 0, None, None))
        STUBS[s] = (oname, off, meth)
        w32(vt + off, s)
        MU.mem_write(s, b"\xc2" + struct.pack("<H", 4 * (meth[1] + 1)))
A = {k: v[0] for k, v in OBJ.items()}
NAME_OF = {v: k for k, v in A.items()}
LOG = []
FAILS = {}                               # method name -> HRESULT to return


def on_code(uc, addr, size, _):
    if addr == racemod.ARROW_DRAW:
        LOG.append(("HUD" if uc.reg_read(UC_X86_REG_ECX) == racemod.HUD_OBJ else "?", "Arrow", [], None))
        return
    if addr not in STUBS:
        return
    oname, off, (meth, nargs, outi, val) = STUBS[addr]
    esp = uc.reg_read(UC_X86_REG_ESP)
    this = u32(esp + 4)
    args = [u32(esp + 8 + 4 * i) for i in range(nargs)]
    hr = FAILS.get(meth, 0)
    if hr == 0 and outi is not None:
        w32(args[outi], A[val] if isinstance(val, str) else val)
    if hr == 0 and meth == "GetDesc":
        uc.mem_write(args[0], struct.pack("<8I", D24S8, 1, 2, 0, 0, 0, 1920, 1080))
    uc.reg_write(UC_X86_REG_EAX, hr & 0xFFFFFFFF)
    extra = struct.unpack("<4f", uc.mem_read(args[1], 16)) if meth == "SetVertexShaderConstantF" else None
    LOG.append((NAME_OF.get(this, hex(this)), meth, [NAME_OF.get(a, a) for a in args], extra))


MU.hook_add(UC_HOOK_CODE, on_code, begin=STUB, end=STUB + len(STUBS) * 16)
MU.hook_add(UC_HOOK_CODE, on_code, begin=racemod.ARROW_DRAW, end=racemod.ARROW_DRAW)
ESP0 = racesim.STACK + 0xF0000
REGS = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444}


def state(tex=True, ds=True, fx=True, active=False, cache=0x00568B8C, w=1920, h=1080):
    w32(racemod.PAN_TEX, A["TEX"] if tex else 0)
    w32(racemod.PAN_DS, A["BIGDS"] if ds else 0)
    w32(racemod.PAN_SAVE_RT, A["BB"] if active else 0)
    w32(racemod.PAN_SAVE_DS, A["ZS"] if active else 0)
    w32(racemod.PAN_ACTIVE, 1 if active else 0)
    w32(R + 0x44034, A["DEV"])
    w32(R + 0x4406C, A["FX"] if fx else 0)
    w32(R + 0x44070, cache)
    w32(R + 0x440A4, A["QUAD"])
    w32(R + 0x41E84, 22)
    w32(racemod.BB_W, w)
    w32(racemod.BB_H, h)
    w32(0x012D049C, 0)                   # Blur option off: 0x0040c080 returns at once


def run(start, stop, esp=ESP0, regs=None, ret=True):
    LOG.clear()
    if ret:
        w32(esp, RET)
    for r, v in {**REGS, **(regs or {})}.items():
        MU.reg_write(r, v)
    MU.reg_write(UC_X86_REG_ESP, esp)
    MU.emu_start(start, stop, count=20000)


def check(label, ok, extra=""):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}{('  ' + extra) if extra else ''}")


def calls():
    return [f"{o}.{m}" for o, m, a, x in LOG]


def args(i):
    return LOG[i][2]


def kept(esp_after, regs=REGS):
    return all(MU.reg_read(r) == v for r, v in regs.items()) and MU.reg_read(UC_X86_REG_ESP) == esp_after


def slots():
    return tuple(u32(a) for a in (racemod.PAN_TEX, racemod.PAN_DS, racemod.PAN_SAVE_RT, racemod.PAN_SAVE_DS,
                                  racemod.PAN_ACTIVE))


SW, SH = round(1920 * panini.RENDER_SCALE), round(1080 * panini.RENDER_SCALE)

# ---------------------------------------------------------------- 1. create
print(f"1. restore (end of 0x0040c7e0): the {SW}x{SH} world texture + depth")
CREATE_OK = ["DEV.CreateTexture", "DEV.GetDepthStencilSurface", "ZS.GetDesc", "ZS.Release",
             "DEV.CreateDepthStencilSurface"]


def create(**st):
    state(**st)
    esp = ESP0 - 0x70
    w32(esp, 0xEBEBEBEB)                                # the caller's ebp, popped by the epilogue
    w32(esp + 0x6C, RET)
    run(0x0040CB87, RET, esp=esp, regs={UC_X86_REG_EBP: R}, ret=False)
    return kept(esp + 0x70, {**REGS, UC_X86_REG_EBP: 0xEBEBEBEB})


FAILS.clear()
k = create(tex=False, ds=False)
check("CreateTexture, then the device's depth format, then a matching depth surface", calls() == CREATE_OK,
      str(calls()))
check(f"CreateTexture({SW}, {SH}, 1, RENDERTARGET, game format, DEFAULT, &tex, NULL)",
      args(0) == [SW, SH, 1, 1, 22, 0, racemod.PAN_TEX, 0], str(args(0)))
check(f"CreateDepthStencilSurface({SW}, {SH}, D24S8 (copied), no MSAA, 0, no discard, &ds, NULL)",
      args(4) == [SW, SH, D24S8, 0, 0, 0, racemod.PAN_DS, 0], str(args(4)))
check("pointers stored; caller's ebx/esi/edi and the epilogue intact", slots()[:2] == (A["TEX"], A["BIGDS"]) and k)
FAILS.clear()
k = create(tex=True, ds=True, active=True)
check("leftovers (texture, depth, saved targets) released first",
      calls()[:4] == ["TEX.Release", "BIGDS.Release", "BB.Release", "ZS.Release"] and calls()[4:] == CREATE_OK and k)
for fail, want, want_slots in (
        ("CreateTexture", ["DEV.CreateTexture"], (0, 0)),
        ("GetDepthStencilSurface", CREATE_OK[:2], (A["TEX"], 0)),
        ("GetDesc", CREATE_OK[:4], (A["TEX"], 0)),
        ("CreateDepthStencilSurface", CREATE_OK, (A["TEX"], 0))):
    FAILS.clear(); FAILS[fail] = -1
    k = create(tex=False, ds=False)
    check(f"{fail} fails: {'nothing' if want_slots == (0, 0) else 'texture kept, no depth (no redirect)'}",
          calls() == want and slots()[:2] == want_slots and k, str(calls()))
FAILS.clear()
create(tex=False, ds=False, w=1280, h=720)
w7, h7 = round(1280 * panini.RENDER_SCALE), round(720 * panini.RENDER_SCALE)
check(f"1280x720 screen -> {w7}x{h7} world", args(0)[:2] == [w7, h7] and args(4)[:2] == [w7, h7], str(args(0)[:2]))

# ---------------------------------------------------------------- 2. release
print("2. invalidate (0x0040c6a0, device lost / reset): everything released")
FAILS.clear(); state(active=True)
run(0x0040C7C2, 0x0040C7C8, regs={UC_X86_REG_ESI: R, UC_X86_REG_EDI: 0}, ret=False)
check("texture, depth, saved targets released and cleared; the game's own instruction still runs",
      calls() == ["TEX.Release", "BIGDS.Release", "BB.Release", "ZS.Release"] and slots() == (0, 0, 0, 0, 0)
      and MU.reg_read(UC_X86_REG_EAX) == A["QUAD"])
state(tex=False, ds=False)
run(0x0040C7C2, 0x0040C7C8, regs={UC_X86_REG_ESI: R, UC_X86_REG_EDI: 0}, ret=False)
check("nothing to release: no calls", calls() == [] and MU.reg_read(UC_X86_REG_EAX) == A["QUAD"])

# ---------------------------------------------------------------- 3. redirect
print("3. redirect (0x0042173c, before the world's clear)")
REDIR = ["DEV.GetRenderTarget", "DEV.GetDepthStencilSurface", "TEX.GetSurfaceLevel", "DEV.SetRenderTarget",
         "SURF.Release", "DEV.SetDepthStencilSurface"]


def redir(**st):
    state(**st)
    run(0x0042173C, 0x00421741, regs={UC_X86_REG_ECX: 0x9999}, ret=False)
    ok = all(MU.reg_read(r) == v for r, v in REGS.items()) and MU.reg_read(UC_X86_REG_ESP) == ESP0
    return ok and MU.reg_read(UC_X86_REG_ECX) == 0x02648150


FAILS.clear()
k = redir()
check("save backbuffer + depth, world -> big texture + our depth", calls() == REDIR, str(calls()))
check("SetRenderTarget(0, big surface); SetDepthStencilSurface(ours)",
      args(3) == [0, "SURF"] and args(5) == ["BIGDS"])
check("saved with references, ACTIVE = 1; ecx = the clear's `this`, registers kept",
      slots() == (A["TEX"], A["BIGDS"], A["BB"], A["ZS"], 1) and k)
FAILS.clear()
k = redir(active=True)
check("stale saves from an interrupted frame are released first",
      calls() == ["BB.Release", "ZS.Release"] + REDIR and k)
for label, st, fail, want, rt_after in (
        ("no world texture: nothing", dict(tex=False), None, [], 0),
        ("no depth surface: nothing", dict(ds=False), None, [], 0),
        ("GetRenderTarget fails", {}, "GetRenderTarget", REDIR[:1], 0),
        ("GetDepthStencilSurface fails: backbuffer ref dropped", {}, "GetDepthStencilSurface",
         REDIR[:2] + ["BB.Release"], 0),
        ("GetSurfaceLevel fails: both refs dropped", {}, "GetSurfaceLevel",
         REDIR[:3] + ["BB.Release", "ZS.Release"], 0),
        ("SetRenderTarget fails: target unchanged, refs dropped", {}, "SetRenderTarget",
         REDIR[:5] + ["BB.Release", "ZS.Release"], 0),
        ("SetDepthStencilSurface fails: target put BACK, refs dropped", {}, "SetDepthStencilSurface",
         REDIR + ["DEV.SetRenderTarget", "BB.Release", "ZS.Release"], 0)):
    FAILS.clear()
    if fail:
        FAILS[fail] = -1
    k = redir(**st)
    extra = True
    if fail == "SetDepthStencilSurface":
        extra = args(6) == [0, "BB"]
    check(label, calls() == want and slots()[2:] == (0, 0, rt_after) and k and extra, str(calls()))

# ---------------------------------------------------------------- 4. the pass
print("4. the pass (0x00421873: motion blur, the arrow, back to the screen, warp)")
DRAW = ["FX.SetTechnique", "DEV.SetVertexShaderConstantF", "DEV.GetTexture", "DEV.SetTexture", "DEV.SetFVF",
        "DEV.SetStreamSource", "FX.Begin", "FX.Pass", "DEV.DrawPrimitive", "FX.End", "DEV.SetTexture",
        "OLD.Release"]
BACK = ["DEV.SetRenderTarget", "DEV.SetDepthStencilSurface", "BB.Release", "ZS.Release"]
COPY = ["DEV.GetRenderTarget", "TEX.GetSurfaceLevel", "DEV.StretchRect", "SURF.Release", "BB.Release"]
FALLBACK = ["DEV.GetRenderTarget", "TEX.GetSurfaceLevel", "DEV.StretchRect", "SURF.Release", "BB.Release"]


def pas(start=racemod.PAN_PASS_CAVE, **st):
    state(**st)
    run(start, RET)
    return kept(ESP0 + 4)


FAILS.clear()
k = pas(start=0x00421873, active=True)
want = ["HUD.Arrow"] + BACK + DRAW
check("0x00421873 jumps in; redirected frame: arrow, screen back, warp", calls() == want, str(calls()))
check("arrow drawn with ecx = the HUD object, BEFORE the warp", LOG[0][0] == "HUD")
check("SetRenderTarget(0, saved backbuffer); SetDepthStencilSurface(saved)", args(1) == [0, "BB"] and args(2) == ["ZS"])
check("SetTechnique(\"techPanini\"), cache updated", args(5) == [racemod.PAN_NAME]
      and u32(R + 0x44070) == racemod.PAN_NAME and bytes(MU.mem_read(racemod.PAN_NAME, 11)) == b"techPanini\0")
c0 = LOG[6][3]
check("VS c0 = (-1/W, 1/H, 0, 0) of the SCREEN", abs(c0[0] + 1 / 1920) < 1e-9 and abs(c0[1] - 1 / 1080) < 1e-9
      and c0[2:] == (0, 0), str(c0))
check("the big world texture is sampled; quad, strip of 2", args(8) == [0, "TEX"] and args(10) == [0, "QUAD", 0, 20]
      and args(13) == [5, 0, 2])
check("stage 0 restored; saves released; ACTIVE = 0; registers kept, returned",
      args(15) == [0, "OLD"] and slots() == (A["TEX"], A["BIGDS"], 0, 0, 0) and k)
FAILS.clear()
k = pas(active=False)
check("not redirected: backbuffer copied UP into the texture (LINEAR), then the warp",
      calls() == ["HUD.Arrow"] + COPY + DRAW and args(3) == ["BB", 0, "SURF", 0, 2] and k, str(calls()))
FAILS.clear()
k = pas(active=True, cache=racemod.PAN_NAME)
check("cache already says techPanini: SetTechnique STILL called (it goes stale on a device reset)",
      calls() == ["HUD.Arrow"] + BACK + DRAW and k)
for label, st, fail, want in (
        ("no world texture: only the arrow", dict(tex=False), None, ["HUD.Arrow"]),
        ("redirected, techPanini missing: world downscaled onto the screen as is", dict(active=True),
         "SetTechnique", ["HUD.Arrow"] + BACK + ["FX.SetTechnique"] + FALLBACK),
        ("redirected, no effect: downscaled as is", dict(active=True, fx=False), None,
         ["HUD.Arrow"] + BACK + FALLBACK),
        ("redirected, Begin fails: texture restored, then downscaled as is", dict(active=True), "Begin",
         ["HUD.Arrow"] + BACK + DRAW[:7] + DRAW[10:] + FALLBACK),
        ("not redirected, techPanini missing: screen untouched", dict(active=False), "SetTechnique",
         ["HUD.Arrow"] + COPY + ["FX.SetTechnique"]),
        ("not redirected, copy fails: no warp", dict(active=False), "StretchRect", ["HUD.Arrow"] + COPY)):
    FAILS.clear()
    if fail:
        FAILS[fail] = -1
    k = pas(**st)
    fb = True
    if st.get("active") and want[-len(FALLBACK):] == FALLBACK and calls() == want:
        i = len(want) - 1 - want[::-1].index("DEV.StretchRect")
        fb = args(i) == ["SURF", 0, "BB", 0, 2]                # big world surface -> screen, LINEAR
    check(label, calls() == want and k and fb, str(calls()))
FAILS.clear(); FAILS["GetTexture"] = -1
k = pas(active=True)
check("GetTexture fails: stage 0 set back to NULL, nothing released",
      calls() == ["HUD.Arrow"] + BACK + DRAW[:-1] and args(len(BACK) + 11) == [0, 0] and k)
check("HUD no longer draws the arrow itself (0x0046b333 = 5 nops)", MU.mem_read(0x0046B333, 5) == b"\x90" * 5)

# ---------------------------------------------------------------- 5. effect text
print("5. the effect text handed to D3DXCreateEffect (0x00487a94)")
tech = panini.technique_text().encode("latin-1")
SRC = MOCK + 0x100000
text = b"technique techDirectLights { }\r\n" * 10
MU.mem_write(SRC, text)
esp = ESP0 - 0x40
for i, v in enumerate((A["DEV"], SRC, len(text), 0, 0, 0, 0, MOCK + 0x200000, MOCK + 0x200004)):
    w32(esp + 4 * i, v)
run(0x0040AB1B, 0x00487A94, esp=esp, regs={UC_X86_REG_ECX: 0x5555}, ret=False)
e2 = MU.reg_read(UC_X86_REG_ESP)
got = bytes(MU.mem_read(racemod.PAN_FXBUF, len(text) + len(tech)))
check("arrives at D3DXCreateEffect with the call's return address", e2 == esp - 4 and u32(e2) == 0x0040AB20)
check("source = buffer holding the file text + techPanini", u32(e2 + 8) == racemod.PAN_FXBUF and got == text + tech)
check("length = file + technique; other arguments untouched", u32(e2 + 12) == len(text) + len(tech)
      and u32(e2 + 4) == A["DEV"] and u32(e2 + 32) == MOCK + 0x200000)
check("esi / edi / ecx preserved (esi = the buffer the game frees)",
      MU.reg_read(UC_X86_REG_ESI) == 0x2222 and MU.reg_read(UC_X86_REG_EDI) == 0x3333
      and MU.reg_read(UC_X86_REG_ECX) == 0x5555)
for i, v in enumerate((A["DEV"], SRC, racemod.PAN_FXBUF_SIZE, 0, 0, 0, 0, 0, 0)):
    w32(esp + 4 * i, v)
run(0x0040AB1B, 0x00487A94, esp=esp, ret=False)
e2 = MU.reg_read(UC_X86_REG_ESP)
check("a text too big for the buffer passes through unchanged",
      u32(e2 + 8) == SRC and u32(e2 + 12) == racemod.PAN_FXBUF_SIZE)

# ---------------------------------------------------------------- 7. sky dome
print("7. sky dome (0x004276e0: unit sphere re-centred on the camera each frame)")
HOLDER, SKYOBJ = MOCK + 0x120000, MOCK + 0x130000
w32(HOLDER, SKYOBJ)
ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 123.0, 45.0, -678.0, 1]      # identity + camera position
MU.mem_write(SKYOBJ, struct.pack("<16f", *ident))
esp = ESP0 - 0x40
run(0x00427723, 0x0042772D, esp=esp, regs={UC_X86_REG_EBX: HOLDER}, ret=False)
mat = struct.unpack("<16f", MU.mem_read(SKYOBJ, 64))
k = racemod.SKY_SCALE
check(f"dome scaled {k:g}x on all three axes, camera position kept",
      mat == (k, 0, 0, 0, 0, k, 0, 0, 0, 0, k, 0, 123.0, 45.0, -678.0, 1), str(mat))
check("the game's own next steps intact: push 0x44, edx = object + 0x860",
      MU.reg_read(UC_X86_REG_ESP) == esp - 4 and u32(esp - 4) == 0x44 and MU.reg_read(UC_X86_REG_EDX) == SKYOBJ + 0x860)
near = 0.2
check(f"near-clip now only past {math.degrees(math.acos(near / k)):.1f} deg off-axis (view edge is "
      f"{panini.PANINI_FOV / 2:g})", math.degrees(math.acos(near / k)) > panini.PANINI_FOV / 2 + 5)

# ---------------------------------------------------------------- 8. chase distance
print(f"8. chase camera distance (0x004018c0) vs the stock code: x {panini.CHASE_DISTANCE:g}")
REF = racesim.Sim([n for n in NAMES if n not in ("panini", "modsect")])
REF.mu.mem_map(MOCK, 0x300000, UC_PROT_ALL)
REF.mu.mem_write(RET, b"\xcc")


def chase(mu, mode, speed):
    CAM, CAR, OUT = MOCK + 0x140000, MOCK + 0x150000, MOCK + 0x160000
    wr = lambda a, fmt, *v: mu.mem_write(a, struct.pack(fmt, *v))
    wr(CAM + 0x9EF0, "<I", CAR)
    wr(CAM + 0x9ED0, "<I", mode)
    wr(CAR + 0x8B4, "<f", 5.0)                      # the car's camera base distance
    wr(CAR + 0x7F70, "<f", speed)
    wr(CAR + 0x10, "<3f", 100.0, 5.0, 200.0)        # position
    wr(CAR + 0x20, "<3f", 0.6, 0.0, 0.8)            # forward (unit)
    esp = ESP0 - 0x100
    wr(esp, "<4I", RET, OUT, OUT + 0x10, OUT + 0x20)
    mu.reg_write(UC_X86_REG_ECX, CAM)
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.emu_start(0x004018C0, RET, count=5000)
    vec = lambda a: struct.unpack("<3f", mu.mem_read(a, 12))
    return vec(OUT), vec(OUT + 0x10), vec(OUT + 0x20), mu.reg_read(UC_X86_REG_ESP) == esp + 0x10


k = panini.CHASE_DISTANCE
for mode, speed in ((1, 0.0), (2, 0.0), (1, 150.0), (2, 400.0)):
    e1, t1, p1, b1 = chase(MU, mode, speed)
    e0, t0, p0, b0 = chase(REF.mu, mode, speed)
    ok = all(abs(a - k * b) < 1e-4 for a, b in zip(e1 + t1, e0 + t0)) and p1 == p0 and b1 and b0
    check(f"mode {mode}, speed {speed:g}: eye + aim offsets = {k:g} x stock, anchor unchanged "
          f"(eye {e0[0]:.2f},{e0[1]:.2f},{e0[2]:.2f} -> {e1[0]:.2f},{e1[1]:.2f},{e1[2]:.2f})", ok)

# ---------------------------------------------------------------- 6. camera
print("6. main camera (0x00425620 -> 0x00402250 -> projection builder 0x00401070)")
for w, h in ((1920, 1080), (1280, 1024), (2560, 1080), (1024, 768)):
    w32(racemod.BB_W, w); w32(racemod.BB_H, h)
    esp = ESP0 - 0x100
    run(0x0042569D, 0x00425713, esp=esp, ret=False)             # stop before the two pushes
    e = MU.reg_read(UC_X86_REG_ESP)
    fov, aspect = struct.unpack("<2f", MU.mem_read(e, 8))
    want_a = w / h
    want_f = 2 * math.atan(math.tan(math.radians(panini.PANINI_FOV / 2)) / want_a)
    hfov = 2 * math.degrees(math.atan(math.tan(fov / 2) * aspect))
    check(f"{w}x{h}: aspect {aspect:.4f} (no 0.85), vertical {math.degrees(fov):.2f} deg -> horizontal "
          f"{hfov:.2f} deg", abs(aspect - want_a) < 1e-5 and abs(fov - want_f) < 1e-5
          and abs(hfov - panini.PANINI_FOV) < 1e-3 and e == esp)

print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
