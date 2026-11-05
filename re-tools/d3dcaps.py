"""Read-only: D3D9 limits per adapter (max texture size, DXT1 support) - no device, no window."""
import ctypes, struct
d3d9 = ctypes.WinDLL("d3d9")
d3d9.Direct3DCreate9.restype = ctypes.c_void_p
obj = d3d9.Direct3DCreate9(32)
vt = ctypes.cast(ctypes.c_void_p.from_address(obj).value, ctypes.POINTER(ctypes.c_void_p))
fn = lambda i, *a: ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *a)(vt[i])
n = ctypes.WINFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)(vt[4])(obj)
DXT1 = struct.unpack("<I", b"DXT1")[0]
for ad in range(n):
    ident = ctypes.create_string_buffer(1100)
    fn(5, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p)(obj, ad, 0, ident)
    caps = ctypes.create_string_buffer(400)
    fn(14, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p)(obj, ad, 1, caps)
    mw, mh = struct.unpack_from("<II", caps.raw, 88)
    tc = struct.unpack_from("<I", caps.raw, 60)[0]
    ok = fn(10, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)(
        obj, ad, 1, 22, 0, 3, DXT1)          # HAL, display X8R8G8B8, texture, DXT1
    print(f"adapter {ad}: {ident.raw[512:1024].split(b'\0')[0].decode(errors='replace')}: max texture {mw}x{mh}, "
          f"DXT1 {'yes' if ok == 0 else hex(ok & 0xffffffff)}, pow2-only {bool(tc & 2)}")
