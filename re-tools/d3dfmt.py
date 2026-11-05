"""Ask Direct3D 9 whether each adapter supports a texture format as a RENDER TARGET
(IDirect3D9::CheckDeviceFormat, vtable slot 10). Read-only, creates no device."""
import ctypes
from ctypes import wintypes

d3d9 = ctypes.WinDLL("d3d9")
d3d9.Direct3DCreate9.restype = ctypes.c_void_p
d3d = d3d9.Direct3DCreate9(32)
vt = ctypes.cast(ctypes.cast(d3d, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
GetAdapterCount = ctypes.WINFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)(vt[4])
class ID(ctypes.Structure):
    _fields_ = [("Driver", ctypes.c_char * 512), ("Description", ctypes.c_char * 512),
                ("DeviceName", ctypes.c_char * 32), ("DriverVersion", ctypes.c_longlong),
                ("VendorId", wintypes.DWORD), ("DeviceId", wintypes.DWORD), ("SubSysId", wintypes.DWORD),
                ("Revision", wintypes.DWORD), ("Guid", ctypes.c_byte * 16), ("WHQL", wintypes.DWORD)]
GetAdapterIdentifier = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, wintypes.DWORD, ctypes.POINTER(ID))(vt[5])
CheckDeviceFormat = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int)(vt[10])
FMT = {"A8 (0x1c, what the game asks for)": 28, "A8R8G8B8 (0x15)": 21, "R5G6B5 (0x17)": 23, "L8 (0x32)": 50}
for a in range(GetAdapterCount(d3d)):
    ident = ID(); GetAdapterIdentifier(d3d, a, 0, ctypes.byref(ident))
    print(f"adapter {a}: {ident.Description.decode(errors='replace')}")
    for name, f in FMT.items():
        hr = CheckDeviceFormat(d3d, a, 1, 22, 0x1, 3, f)     # HAL, display X8R8G8B8, RENDERTARGET, TEXTURE
        tx = CheckDeviceFormat(d3d, a, 1, 22, 0x0, 3, f)     # plain texture
        print(f"   {name:<36} render target: {'YES' if hr == 0 else 'NO '}   texture: {'YES' if tx == 0 else 'NO'}")
