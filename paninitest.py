r"""paninitest.py - prove `techPanini` BEFORE it goes near the game, on this PC's real GPU.

1. Assemble its vs_1_1 / ps_2_0 with D3DX (oldest d3dx9_24 and newest d3dx9_43 DLLs).
2. Compile the WHOLE effect the game will build - RenderTechniques_20.dat from World.pak plus the
   appended technique - with D3DXCreateEffect on a real device, in both DLLs.
3. Render: a float32 texture whose texels hold their own centre coordinates goes through the
   shader into a float32 target, so every output pixel reports exactly where it sampled.
   Compared against panini.model() (float64) - once with the raw shaders + the pass's states,
   once through the effect itself (d3dx9_43: SetTechnique / Begin / BeginPass).
The game's own D3DX is statically linked (2004 interface: Begin / Pass / End) - the technique uses
only constructs the game's own techGlowScreen / techWaterSurface already use.
Usage: paninitest.py [fov] [d] [render scale, e.g. 1.3333 = 1440p source on a 1080p screen]
"""
import array
import ctypes
import ctypes.wintypes as wt
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak
import panini

W, H = 1920, 1080
FOV = float(sys.argv[1]) if len(sys.argv) > 1 else panini.PANINI_FOV
DD = float(sys.argv[2]) if len(sys.argv) > 2 else panini.PANINI_D
SS = float(sys.argv[3]) if len(sys.argv) > 3 else panini.RENDER_SCALE
SW, SH = round(W * SS), round(H * SS)             # the supersampled source (the 3D world)
P = panini.params(FOV, DD)
HR = ctypes.c_long
PTR = ctypes.c_void_p
FAILS = []


def check(label, ok, extra=""):
    print(f"  {'OK ' if ok else 'BAD'} {label}{('  ' + extra) if extra else ''}")
    if not ok:
        FAILS.append(label)


def com(obj, index, *argtypes, restype=HR):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(PTR))).contents
    fn = ctypes.WINFUNCTYPE(restype, PTR, *argtypes)(vtbl[index])
    return lambda *a: fn(obj, *a)


def blob(buf):      # ID3DXBuffer -> bytes
    p = com(buf, 3, restype=PTR)()
    n = com(buf, 4, restype=ctypes.c_ulong)()
    return ctypes.string_at(p, n)


def effect_source():
    ents, _, pays, _ = crpak.load_archive(crpak.GAME_DATA, "World")
    for (n, s, o), p in zip(ents, pays):
        if n.replace("\\", "/").endswith("Misc/RenderTechniques_20.dat"):
            return p
    raise SystemExit("RenderTechniques_20.dat not found in World.pak")


class PP(ctypes.Structure):
    _fields_ = [("BackBufferWidth", wt.UINT), ("BackBufferHeight", wt.UINT), ("BackBufferFormat", wt.UINT),
                ("BackBufferCount", wt.UINT), ("MultiSampleType", wt.UINT), ("MultiSampleQuality", wt.DWORD),
                ("SwapEffect", wt.UINT), ("hDeviceWindow", wt.HWND), ("Windowed", wt.BOOL),
                ("EnableAutoDepthStencil", wt.BOOL), ("AutoDepthStencilFormat", wt.UINT), ("Flags", wt.DWORD),
                ("FullScreen_RefreshRateInHz", wt.UINT), ("PresentationInterval", wt.UINT)]


class LOCKED(ctypes.Structure):
    _fields_ = [("Pitch", ctypes.c_int), ("pBits", PTR)]


def main():
    tech = panini.technique_text(FOV, DD, SS).encode("latin-1")
    full = effect_source() + b"\r\n" + tech
    print(f"Panini {FOV:g} deg, d = {DD:g}, source {SW}x{SH} -> {W}x{H}; effect text {len(full)} bytes ({len(tech)} appended)")

    # ---- 1. assemble with both D3DX generations
    print("1. assemble")
    shaders = {}
    for dll in ("d3dx9_24", "d3dx9_43"):
        dx = ctypes.WinDLL(dll)
        for which in ("vs", "ps"):
            src = panini.shader_asm(which, FOV, DD, SS).encode()
            code, err = PTR(), PTR()
            hr = dx.D3DXAssembleShader(src, len(src), None, None, 0, ctypes.byref(code), ctypes.byref(err))
            msg = blob(err).decode(errors="replace").strip() if err else ""
            check(f"{dll} assembles the {which}", hr == 0, msg[:300])
            if hr == 0:
                shaders.setdefault(which, blob(code))
    ntok = len(shaders.get("ps", b"")) // 4
    print(f"     ps bytecode {len(shaders.get('ps', b''))} bytes, vs {len(shaders.get('vs', b''))} bytes ({ntok} ps tokens)")

    # ---- device
    user32 = ctypes.WinDLL("user32")
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, PTR]
    hwnd = user32.CreateWindowExW(0, "STATIC", "paninitest", 0, 0, 0, 64, 64, None, None, None, None)
    # D3D9Ex: a plain D3D9 device cannot be created while the game holds the screen in exclusive
    # fullscreen (D3DERR_NOTAVAILABLE); an Ex device can. Ex has no MANAGED pool - hence the
    # SYSTEMMEM -> UpdateTexture -> DEFAULT uploads below.
    d3d9 = ctypes.WinDLL("d3d9")
    d3dp = PTR()
    d3d9.Direct3DCreate9Ex(32, ctypes.byref(d3dp))
    d3d = d3dp.value
    pp = PP(64, 64, 22, 1, 0, 0, 1, hwnd, 1, 0, 0, 0, 0, 0x80000000)
    dev = PTR()
    hr = com(d3d, 20, wt.UINT, wt.UINT, wt.HWND, wt.DWORD, ctypes.POINTER(PP), PTR, ctypes.POINTER(PTR))(
        0, 1, hwnd, 0x40, ctypes.byref(pp), None, ctypes.byref(dev))    # CreateDeviceEx, HAL, HW VP
    check("D3D9Ex HAL device", hr == 0, f"hr {hr & 0xffffffff:#x}")
    if hr:
        return 1
    dev = dev.value
    D = lambda i, *t: com(dev, i, *t)
    fmt_ok = com(d3d, 10, wt.UINT, wt.UINT, wt.UINT, wt.DWORD, wt.UINT, wt.UINT)(0, 1, 22, 0x20000, 3, 116)
    check("GPU filters A32B32G32R32F textures (needed by this test only)", fmt_ok == 0)

    # ---- 2. the whole effect, as the game will compile it
    print("2. compile the game's effect + techPanini on the device")
    # Success = hr >= 0 AND the same result as the untouched game effect (d3dx9_24 answers S_FALSE
    # = 1 for the stock text too - a success code, not a failure).
    effects = {}
    stock = effect_source()
    for dll in ("d3dx9_24", "d3dx9_43"):
        dx = ctypes.WinDLL(dll)
        e0, err0 = PTR(), PTR()
        hr0 = dx.D3DXCreateEffect(PTR(dev), stock, len(stock), None, None, 0, None, ctypes.byref(e0), ctypes.byref(err0))
        eff, err = PTR(), PTR()
        hr = dx.D3DXCreateEffect(PTR(dev), full, len(full), None, None, 0, None, ctypes.byref(eff), ctypes.byref(err))
        msg = blob(err).decode(errors="replace").strip() if err else ""
        check(f"{dll} D3DXCreateEffect(RenderTechniques_20 + techPanini)", hr >= 0 and hr == hr0,
              f"hr {hr & 0xffffffff:#x} (stock text {hr0 & 0xffffffff:#x}) {msg[:300]}")
        effects[dll] = eff.value if hr >= 0 else None
    eff = effects.get("d3dx9_43")
    if eff:
        th = com(eff, 13, ctypes.c_char_p, restype=PTR)(panini.TECH_NAME.encode())    # GetTechniqueByName
        check("techPanini found in the compiled effect", bool(th))
        check("techPanini validates on this GPU (ValidateTechnique)", com(eff, 60, PTR)(th) == 0)

    # ---- 3. render
    src, stage = PTR(), PTR()
    mk = D(23, wt.UINT, wt.UINT, wt.UINT, wt.DWORD, wt.UINT, wt.UINT, ctypes.POINTER(PTR), PTR)
    mk(SW, SH, 1, 0, 116, 2, ctypes.byref(stage), None)                   # SYSTEMMEM float4
    mk(SW, SH, 1, 0, 116, 0, ctypes.byref(src), None)                     # DEFAULT float4
    lk = LOCKED()
    com(stage.value, 19, wt.UINT, ctypes.POINTER(LOCKED), PTR, wt.DWORD)(0, ctypes.byref(lk), None, 0)
    ucol = array.array("f", [0.0] * (SW * 4))
    for x in range(SW):
        ucol[4 * x] = (x + 0.5) / SW
        ucol[4 * x + 3] = 1.0
    for y in range(SH):
        row = array.array("f", ucol)
        v = (y + 0.5) / SH
        row[1::4] = array.array("f", [v] * SW)
        ctypes.memmove(lk.pBits + y * lk.Pitch, row.tobytes(), SW * 16)
    com(stage.value, 20, wt.UINT)(0)
    check("upload the coordinate texture", D(31, PTR, PTR)(stage, src) == 0)     # UpdateTexture

    rt, rts, sysm = PTR(), PTR(), PTR()
    D(23, wt.UINT, wt.UINT, wt.UINT, wt.DWORD, wt.UINT, wt.UINT, ctypes.POINTER(PTR), PTR)(
        W, H, 1, 1, 116, 0, ctypes.byref(rt), None)                      # RENDERTARGET, DEFAULT
    com(rt.value, 18, wt.UINT, ctypes.POINTER(PTR))(0, ctypes.byref(rts))
    D(36, wt.UINT, wt.UINT, wt.UINT, wt.UINT, ctypes.POINTER(PTR), PTR)(W, H, 116, 2, ctypes.byref(sysm), None)

    vb = PTR()
    D(26, wt.UINT, wt.DWORD, wt.DWORD, wt.UINT, ctypes.POINTER(PTR), PTR)(80, 8, 0x102, 0, ctypes.byref(vb), None)
    quad = array.array("f", [-1, 1, 0, 0, 0,  -1, -1, 0, 0, 1,  1, 1, 0, 1, 0,  1, -1, 0, 1, 1])   # the game's VB
    pv = PTR()
    com(vb.value, 11, wt.UINT, wt.UINT, ctypes.POINTER(PTR), wt.DWORD)(0, 0, ctypes.byref(pv), 0)
    ctypes.memmove(pv.value, quad.tobytes(), 80)
    com(vb.value, 12)()

    c0 = (ctypes.c_float * 4)(-1.0 / W, 1.0 / H, 0, 0)

    def draw(use_effect):
        D(37, wt.DWORD, PTR)(0, rts)
        D(43, wt.DWORD, PTR, wt.DWORD, wt.DWORD, ctypes.c_float, wt.DWORD)(0, None, 1, 0xFF00FF00, 1.0, 0)
        D(94, wt.UINT, PTR, wt.UINT)(0, c0, 1)
        D(65, wt.DWORD, PTR)(0, src)
        D(89, wt.DWORD)(0x102)
        D(100, wt.UINT, PTR, wt.UINT, wt.UINT)(0, vb, 0, 20)
        D(41)()
        if use_effect:
            com(eff, 58, ctypes.c_char_p)(panini.TECH_NAME.encode())                # SetTechnique
            n = wt.UINT()
            com(eff, 63, ctypes.POINTER(wt.UINT), wt.DWORD)(ctypes.byref(n), 0)      # Begin
            com(eff, 64, wt.UINT)(0)                                                 # BeginPass
            D(81, wt.UINT, wt.UINT, wt.UINT)(5, 0, 2)
            com(eff, 66)()                                                           # EndPass
            com(eff, 67)()                                                           # End
        else:
            vs, ps = PTR(), PTR()
            vsb, psb = shaders["vs"], shaders["ps"]
            D(91, ctypes.c_char_p, ctypes.POINTER(PTR))(vsb, ctypes.byref(vs))
            D(106, ctypes.c_char_p, ctypes.POINTER(PTR))(psb, ctypes.byref(ps))
            D(92, PTR)(vs)
            D(107, PTR)(ps)
            for st, val in ((7, 0), (14, 0), (27, 0), (15, 0), (28, 0), (52, 0), (22, 1)):
                D(57, wt.UINT, wt.DWORD)(st, val)
            for st, val in ((1, 3), (2, 3), (6, 2), (5, 2), (7, 0)):
                D(69, wt.DWORD, wt.UINT, wt.DWORD)(0, st, val)
            D(81, wt.UINT, wt.UINT, wt.UINT)(5, 0, 2)
        D(42)()
        hr = D(32, PTR, PTR)(rts, sysm)
        lk2 = LOCKED()
        com(sysm.value, 13, ctypes.POINTER(LOCKED), PTR, wt.DWORD)(ctypes.byref(lk2), None, 0x10)
        out = array.array("f")
        out.frombytes(ctypes.string_at(lk2.pBits, lk2.Pitch * H))
        com(sysm.value, 14)()
        return out, lk2.Pitch // 4, hr

    lo_u, hi_u = 0.5 / SW, 1 - 0.5 / SW
    lo_v, hi_v = 0.5 / SH, 1 - 0.5 / SH
    clampu = lambda a: min(max(a, lo_u), hi_u)
    clampv = lambda a: min(max(a, lo_v), hi_v)
    xs = sorted(set(list(range(0, W, 7)) + [0, 1, W // 2 - 1, W // 2, W - 2, W - 1]))
    ys = sorted(set(list(range(0, H, 9)) + [0, H // 2, H - 1]))
    for label, use_effect in (("raw shaders + pass states", False), ("the effect (d3dx9_43)", True)):
        if use_effect and not eff:
            continue
        print(f"3. render through {label}")
        out, stride, hr = draw(use_effect)
        check("readback", hr == 0)
        worst_u = worst_v = 0.0
        wpos = None
        for y in ys:
            v = (y + 0.5) / H
            for x in xs:
                u = (x + 0.5) / W
                tu, sv = panini.model(u, v, W, P, SS)
                eu = sum(clampu(t) for t in tu) / len(tu)
                ev = clampv(sv)
                gu, gv = out[y * stride + 4 * x], out[y * stride + 4 * x + 1]
                du, dv = abs(gu - eu) * W, abs(gv - ev) * H
                if du > worst_u:
                    worst_u, wpos = du, (x, y, gu * W, eu * W)
                worst_v = max(worst_v, dv)
        check(f"horizontal: every sampled position within 0.05 px of the model", worst_u < 0.05,
              f"worst {worst_u:.4f} px at {wpos}")
        check(f"vertical: within 0.05 px", worst_v < 0.05, f"worst {worst_v:.4f} px")
        cy = H // 2
        edge = out[cy * stride + 4 * (W - 1)] * W
        mid = out[cy * stride + 4 * (W // 2 + W // 4)] * W
        print(f"     centre row: output x {W // 2 + W // 4} samples source x {mid * SW / W:.1f} of {SW}; "
              f"output x {W - 1} samples {edge * SW / W:.1f}")
    print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
