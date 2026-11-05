"""Annotated disassembly with IDirect3DDevice9 / texture / surface vtable names on indirect calls.
The receiving interface is not known statically, so both device and texture names are shown
where they differ. Usage: d3dlabel.py <start> <end>"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, re
sys.path.insert(0, crpaths.RETOOLS)
from adis import annotate

DEV = ["QueryInterface", "AddRef", "Release", "TestCooperativeLevel", "GetAvailableTextureMem",
       "EvictManagedResources", "GetDirect3D", "GetDeviceCaps", "GetDisplayMode", "GetCreationParameters",
       "SetCursorProperties", "SetCursorPosition", "ShowCursor", "CreateAdditionalSwapChain", "GetSwapChain",
       "GetNumberOfSwapChains", "Reset", "Present", "GetBackBuffer", "GetRasterStatus", "SetDialogBoxMode",
       "SetGammaRamp", "GetGammaRamp", "CreateTexture", "CreateVolumeTexture", "CreateCubeTexture",
       "CreateVertexBuffer", "CreateIndexBuffer", "CreateRenderTarget", "CreateDepthStencilSurface",
       "UpdateSurface", "UpdateTexture", "GetRenderTargetData", "GetFrontBufferData", "StretchRect",
       "ColorFill", "CreateOffscreenPlainSurface", "SetRenderTarget", "GetRenderTarget",
       "SetDepthStencilSurface", "GetDepthStencilSurface", "BeginScene", "EndScene", "Clear",
       "SetTransform", "GetTransform", "MultiplyTransform", "SetViewport", "GetViewport", "SetMaterial",
       "GetMaterial", "SetLight", "GetLight", "LightEnable", "GetLightEnable", "SetClipPlane",
       "GetClipPlane", "SetRenderState", "GetRenderState", "CreateStateBlock", "BeginStateBlock",
       "EndStateBlock", "SetClipStatus", "GetClipStatus", "GetTexture", "SetTexture",
       "GetTextureStageState", "SetTextureStageState", "GetSamplerState", "SetSamplerState",
       "ValidateDevice", "SetPaletteEntries", "GetPaletteEntries", "SetCurrentTexturePalette",
       "GetCurrentTexturePalette", "SetScissorRect", "GetScissorRect", "SetSoftwareVertexProcessing",
       "GetSoftwareVertexProcessing", "SetNPatchMode", "GetNPatchMode", "DrawPrimitive",
       "DrawIndexedPrimitive", "DrawPrimitiveUP", "DrawIndexedPrimitiveUP", "ProcessVertices",
       "CreateVertexDeclaration", "SetVertexDeclaration", "GetVertexDeclaration", "SetFVF", "GetFVF",
       "CreateVertexShader", "SetVertexShader", "GetVertexShader", "SetVertexShaderConstantF"]
TEX = {0x48: "Tex.GetSurfaceLevel", 0x4c: "Tex.LockRect", 0x50: "Tex.UnlockRect", 0x44: "Tex.GetLevelDesc",
       0x08: "Release", 0x04: "AddRef"}

lines = annotate(int(sys.argv[1], 16), int(sys.argv[2], 16)).splitlines()
last_off = {}
for l in lines:
    m = re.search(r"mov\s+(e\w\w), dword ptr \[e\w\w \+ (0x[0-9a-f]+)\]", l)
    if m:
        last_off[m.group(1)] = int(m.group(2), 16)
    c = re.search(r"call\s+(e\w\w)$", l.strip())
    c2 = re.search(r"call\s+dword ptr \[e\w\w \+ (0x[0-9a-f]+)\]", l)
    off = last_off.get(c.group(1)) if c else (int(c2.group(1), 16) if c2 else None)
    if off is not None and off % 4 == 0 and off // 4 < len(DEV):
        extra = f"   <<< dev.{DEV[off // 4]}" + (f" / {TEX[off]}" if off in TEX else "")
        l += extra
    print(l)
