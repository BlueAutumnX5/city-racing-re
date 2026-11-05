"""headlights validation step 1: assemble techHeadlights' shaders and compile the effect text
(standalone, and the game's RenderTechniques_20 + techPanini + techHeadlights) on a real D3D9Ex
device with the oldest (d3dx9_24) and newest (d3dx9_43) D3DX."""
import ctypes, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paninitest as pt
import headlights as hl
import panini

def main():
    for dll in ("d3dx9_24", "d3dx9_43"):
        dx = ctypes.WinDLL(dll)
        for which, src in [("vs", hl.vs_asm())] + [(f"ps pass {k}", hl.ps_asm(k)) for k in range(hl.PASSES)]:
            s = src.encode(); code, err = pt.PTR(), pt.PTR()
            hr = dx.D3DXAssembleShader(s, len(s), None, None, 0, ctypes.byref(code), ctypes.byref(err))
            msg = pt.blob(err).decode(errors="replace").strip() if err else ""
            n = len(pt.blob(code)) // 4 if hr == 0 else 0
            pt.check(f"{dll} assembles the {which} ({n} tokens)", hr == 0, msg[:400])
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32")
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, pt.PTR]
    hwnd = user32.CreateWindowExW(0, "STATIC", "hltest", 0, 0, 0, 64, 64, None, None, None, None)
    d3d9 = ctypes.WinDLL("d3d9"); d3dp = pt.PTR(); d3d9.Direct3DCreate9Ex(32, ctypes.byref(d3dp))
    pp = pt.PP(64, 64, 22, 1, 0, 0, 1, hwnd, 1, 1, 80, 0, 0, 0x80000000)
    dev = pt.PTR()
    hr = pt.com(d3dp.value, 20, wt.UINT, wt.UINT, wt.HWND, wt.DWORD, ctypes.POINTER(pt.PP), pt.PTR, ctypes.POINTER(pt.PTR))(
        0, 1, hwnd, 0x40, ctypes.byref(pp), None, ctypes.byref(dev))
    pt.check("D3D9Ex HAL device", hr == 0, f"{hr & 0xffffffff:#x}")
    tech = hl.technique_text().encode("latin-1")
    stock = pt.effect_source()
    full = stock + b"\r\n" + panini.technique_text().encode("latin-1") + b"\r\n" + tech
    for dll in ("d3dx9_24", "d3dx9_43"):
        dx = ctypes.WinDLL(dll)
        for label, txt in (("techHeadlights alone", tech), ("game effect + techPanini + techHeadlights", full)):
            eff, err = pt.PTR(), pt.PTR()
            hr = dx.D3DXCreateEffect(dev, txt, len(txt), None, None, 0, None, ctypes.byref(eff), ctypes.byref(err))
            msg = pt.blob(err).decode(errors="replace").strip() if err else ""
            pt.check(f"{dll} D3DXCreateEffect({label}) {len(txt)} bytes", hr >= 0, f"hr {hr & 0xffffffff:#x} {msg[:600]}")
    print("ALL GOOD" if not pt.FAILS else f"FAILED: {pt.FAILS}")
    return 1 if pt.FAILS else 0

if __name__ == "__main__":
    sys.exit(main())
