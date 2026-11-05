"""Per-pixel headlights for City Racing (racemod extra `headlights`, player request 2026-10-05:
"headlights can shine lights on the 3D world ... make other cars too ... No shadows").

Why not the game's own lights: D3D9 fixed-function lights are PER VERTEX. Live preview 2026-10-05
(hlprobe.py) put the player's spot light (D3D light 7) on the terrain: the ground grid is ~4 m and
walls are a few big polygons, so the beam came out as blurry low-resolution blobs.

How it works (no shadows, no extra render targets):
- After the terrain and all its road/decal layers are drawn (0x0043124c, end of 0x00430bf0), the
  land parts near a lit car - and the static objects near one (buildings, bridges, decor, lamp
  posts) - are drawn AGAIN with techHeadlights. Its pixel shader computes the headlight light L of
  the N_CARS nearest cars per pixel.
- v5 "light cookie" (player 2026-10-09: "go cookie"): ONE light per car at the midpoint of its two
  lamps, in the car's own frame (right = matrix row 0, up = row 1, forward = row 2). The pixel is
  projected into that frame (x/z, y/z) and looks up a 256x128 beam texture (cookie_dds()): RED =
  the left lamp's (model lamp 0, -x) low beam, GREEN = the right lamp's (lamp 1, +x). Each channel
  x that lamp's health (the game's lamp vector [[car+0xc00]+0x1c + i*12], zero = broken: its glow
  loop skips it at 0x00415851), so a car with one broken lamp keeps the other half of the beam and
  nothing switches or pops. The cookie draws a real low beam: flat cut-off line, hot spot just
  below the horizon, wide soft spread, faint spill above.
- Blend SrcBlend=DestColor, DestBlend=One: result = dst * (1 + s), i.e. the light multiplies the
  REAL colour already on screen (every road/decal layer) without re-creating texture combiners;
  s <= 1 per pass, PASSES passes: pass k outputs clamp(F/2^k - 1, 0, 1), F = 1 + Lsoft*colour*GAIN
  -> total min(F, 2^PASSES). Lsoft = L/(1 + SOFT*L): overlapping cars add only a little (player:
  "if some cars headlights was colliding ... just brighten it up slightly (like real life)").
- Depth: ZFunc LessEqual, no Z write, DepthBias + SlopeScaleDepthBias towards the camera.
- Per-car intensity = car fade x night ramp (full at night 0.75) x distance fade (FADE_NEAR..MAX_DIST).

History: v1 one light/car (too dim, "1 output in the middle"); v2 2 lamps/car, 3 passes (crowds
blown out, flicker at the screen bottom, GPU 91 W); v3 soft saturation, slope bias, 2 passes,
per-lamp dynamic branch, broken lamps; v4 buildings/bridges/decor/lamp posts + NaN guard (a race
opponent being parked has a NaN matrix -> cars with NaN rows skipped, near tests R^2 > d^2 so an
unordered compare means "far"); v5 cookie. v4 is kept as re-tools/headlights_v4.py.

Constants (written by the cave every frame):
  VS c0-c3 World rows (terrain world, or each object's matrix), c4-c7 View, c8-c11 Projection.
  PS car i, b = 4i: c[b] = (light pos, intensity), c[b+1] = (-forward, left lamp health),
     c[b+2] = (-right*KS, right lamp health), c[b+3] = (up*KT, 0);
     c32 = (0, 0, -1/R^2, 1), c33 = colour*gain, c34 = (wrapA, wrapB, R^2, soft).
"""
import math
import struct

N_CARS = 8              # nearest cars with headlights (player choice 2026-10-05: "try 8 nearest")
RANGE = 90.0            # m, light reaches 0 here (v8: window (1 - d^2/R^2), not squared)
D0 = 40.0               # m, distance falloff 1/(1 + d^2/D0^2) (v6: v5 was flat out to ~20 m)
GAIN = 31.0             # E = GAIN*L (v7: v6 40 "can be increased a little")
EMAX = 15.0             # Esoft = E/(1 + E/EMAX) (v7: v6 14 compressed overlaps flat)
SOFT = GAIN / EMAX      # Lsoft = L/(1 + SOFT*L) (the shader form of the line above)
COLOUR = (0.78, 0.9, 1.0)   # v7: cool xenon white like the cars' lamp glows (player: "blue")
WRAP = (0.3, 0.5)       # lambert = saturate(N.L*A + B); (0.6, 0.4) made walls 2.5x the ground
ADD_K = 0.015           # final additive pass: + Esoft*colour*ADD_K - v8: carries the beam shape + overlaps
PASSES = 3              # multiply passes, cap 2^PASSES = x8 (v8: MMAX keeps it below)
OBJ_GAIN = 0.5          # objects get GAIN x this (additive too, it scales with E)
OBJ_MMAX = 1.5          # objects' multiply limit: F < 2.5
MMAX = 3.0             # v8 multiply limit: F = 1 + E/(1 + E/MMAX) < 7 - texture only, never a plateau
                        # plateau with a hard edge, overlaps added nothing, player 2026-10-09)
DEPTH_BIAS = -0.00002   # D3DRS_DEPTHBIAS, negative = towards the camera
SLOPE_BIAS = -2.0       # D3DRS_SLOPESCALEDEPTHBIAS: grazing ground near the camera (v2 flicker)
MAX_DIST = 120.0        # cars farther than this from the camera are never picked
FADE_NEAR = 90.0        # full intensity closer than this
NIGHT_RAMP = 4.0        # intensity x clamp((night - 0.5) * NIGHT_RAMP, 0, 1)
TECH_NAME = "techHeadlights"
OBJ_MASK = 0x780        # BRIDGE 0x80 | BUILDING 0x100 | DECORS 0x200 (loose objects) | LAMPPOST 0x400
MAX_OBJS = 64
STATICS = 0x026B1AA0    # static-object manager: +0 slots, +0x5000 count
OBJ_DRAW = 0x00408B40   # thiscall (ecx = object, part index): one model part
CS = 4 * N_CARS         # first static PS constant register (c32)
NPSC = CS + 3           # PS constant registers written by the cave

# cookie: u = 0.5 + KS * x/z (horizontal, +x = right), v = 0.5 - KT * y/z (texture top = up)
COOKIE_W, COOKIE_H = 256, 128
KS = 0.5                # x/z in [-1, 1]: +-45 deg horizontally
KT = 1.2                # y/z in [-0.417, 0.417]: +-22.6 deg vertically
LAMP_AIM = 2.0          # deg: each lamp's hot spot leans to its own side
LAMP_UP = 0.0           # m, light source raised above the model's lamp points (live: hllive set lamp)
HOT_EL = -1.2          # deg: hot spot elevation (v8: ~30 m ahead from a 0.6 m lamp; v7 -2 = 17 m)
CUTOFF_EL = -0.6        # deg: the low beam's flat top edge
CUTOFF_SOFT = 7.0       # deg: shoulder width centred on the line (v5 1.2, v6 2.5 = "hard")
SPILL = 0.3             # upward leak right above the line, fading over ~8 deg


def f(x):
    """Plain decimal: the game's 2004 effect parser rejects exponents ('-2e-05' -> X3000)."""
    t = f"{x:.10f}".rstrip("0")
    return t + "0" if t.endswith(".") else t


# ---- the beam texture
def beam(az, el, side):
    """Relative intensity 0..1 of one lamp at azimuth/elevation (degrees); side -1 left, +1 right."""
    # v7 (player 2026-10-09: "why a hard cutoff? ... 2008 cars not using projector lights. make it leak
    # a bit to the top/front"): reflector-style beam - hot spot clearly brighter than the foreground,
    # a wide soft shoulder instead of a line, and light leaking upwards that dies off slowly.
    hot = math.exp(-((az - side * LAMP_AIM) / 15.0) ** 2 - ((el - HOT_EL) / 3.0) ** 2)
    wide = 0.5 * math.exp(-(az / 28.0) ** 2) * math.exp(-((el - HOT_EL) / 8.0) ** 2)
    v = min(1.0, hot + wide)
    k = (el - CUTOFF_EL) / CUTOFF_SOFT + 0.5    # centred on the line: 0 .. 1 across the shoulder
    k = min(1.0, max(0.0, k))
    s = 3 * k * k - 2 * k * k * k
    above = SPILL * math.exp(-max(0.0, el - CUTOFF_EL) / 8.0 - (az / 35.0) ** 2)   # upward leak
    return v * (1.0 - s) + max(v, 0.6) * above * s


def cookie_pixels(w=COOKIE_W, h=COOKIE_H):
    """BGRA bytes, top row first. Border texels are 0 (clamp addressing repeats them outside)."""
    out = bytearray(w * h * 4)
    for j in range(h):
        t = (0.5 - (j + 0.5) / h) / KT
        el = math.degrees(math.atan(t))
        for i in range(w):
            s = ((i + 0.5) / w - 0.5) / KS
            az = math.degrees(math.atan(s))
            # v6: smooth fade over the outer 30 % sideways and the bottom 25 % (v5's 3-texel fade
            # showed as hard wedge sides once GAIN rose; player 2026-10-09 "sharp edged")
            eu = min(1.0, (0.5 - abs((i + 0.5) / w - 0.5)) / 0.15)
            ev = min(1.0, (1.0 - (j + 0.5) / h) / 0.25, ((j + 0.5) / h) / 0.05)
            fade = eu * eu * (3 - 2 * eu) * ev * ev * (3 - 2 * ev)
            r = round(255 * beam(az, el, -1) * fade)
            g = round(255 * beam(az, el, +1) * fade)
            o = 4 * (j * w + i)
            out[o:o + 4] = bytes((0, g, r, 255))
    return bytes(out)


def cookie_dds(w=COOKIE_W, h=COOKIE_H):
    """Uncompressed A8R8G8B8 DDS, one level."""
    hdr = struct.pack("<4sIIIIIII44x", b"DDS ", 124, 0x100F, h, w, w * 4, 0, 1)
    pf = struct.pack("<IIIIIIII", 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps = struct.pack("<IIII4x", 0x1000, 0, 0, 0)
    d = hdr + pf + caps
    assert len(d) == 128
    return d + cookie_pixels(w, h)


# ---- shaders
def vs_asm():
    return "\n".join([
        "vs_3_0",
        "dcl_position v0",
        "dcl_normal v1",
        "dcl_position o0",
        "dcl_texcoord0 o1.xyz",
        "dcl_texcoord1 o2.xyz",
        "mul r0, v0.x, c0",
        "mad r0, v0.y, c1, r0",
        "mad r0, v0.z, c2, r0",
        "add r0, r0, c3",
        "mul r1, r0.x, c4",
        "mad r1, r0.y, c5, r1",
        "mad r1, r0.z, c6, r1",
        "add r1, r1, c7",
        "mul r2, r1.x, c8",
        "mad r2, r1.y, c9, r2",
        "mad r2, r1.z, c10, r2",
        "mad o0, r1.w, c11, r2",
        "mov o1.xyz, r0",
        "mul r3.xyz, v1.x, c0",
        "mad r3.xyz, v1.y, c1, r3",
        "mad o2.xyz, v1.z, c2, r3",
    ])


def ps_asm(k, n=N_CARS):
    """Pass k (0-based) of the multiply chain; k = None: the final ADDITIVE pass (v7)."""
    s0, s1, s2 = f"c{CS}", f"c{CS + 1}", f"c{CS + 2}"
    sd, sh = f"c{CS + 3}", f"c{CS + 4}"
    L = ["ps_3_0",
         f"def {sd}, {f(2.0 ** -k) if k is not None else '1'}, -1, 0, 1",
         f"def {sh}, 0.5, 0, 0, 0",
         "dcl_texcoord0 v0.xyz",
         "dcl_texcoord1 v1.xyz",
         "dcl_2d s0",
         "nrm r3.xyz, v1",
         f"mov r8, {sd}",
         "mov r0.x, r8.z",
         "mov r0.y, r8.z"]
    for i in range(n):
        b = 4 * i
        L += [f"add r1.xyz, c{b}, -v0",            # towards the light
              "dp3 r1.w, r1, r1",
              f"if_lt r1.w, {s2}.z",
              f"dp3 r7.x, r1, c{b + 1}",           # z = depth along the beam
              f"if_gt r7.x, {sd}.z",
              "rcp r7.y, r7.x",
              f"dp3 r4.x, r1, c{b + 2}",
              f"dp3 r4.y, r1, c{b + 3}",
              f"mad r4.xy, r4, r7.y, {sh}.x",
              f"mov r4.zw, {sd}.z",
              "texldl r5, r4, s0",
              f"mul r6.x, r5.x, c{b + 1}.w",        # left lamp x its health
              f"mad r6.x, r5.y, c{b + 2}.w, r6.x",  # + right lamp x its health
              "rsq r2.w, r1.w",
              "mul r2.xyz, r1, r2.w",
              "dp3 r6.z, r2, r3",
              f"mad_sat r6.z, r6.z, {s2}.x, {s2}.y",
              f"mad_sat r6.y, r1.w, {s0}.z, {s0}.w",
              f"mad r6.w, r1.w, {s0}.x, {s0}.w",    # 1 + d^2/D0^2
              "rcp r6.w, r6.w",
              "mul r6.y, r6.y, r6.w",
              "mul r6.x, r6.x, r6.y",
              "mul r6.x, r6.x, r6.z",
              # slot 0 = the PLAYER car (cave sorts it first): its own accumulator, added after
              # the traffic soft limit (player 2026-10-09: "my headlights disappeared in crowds")
              (f"mad r0.y, r6.x, c{b}.w, r0.y" if i == 0 else f"mad r0.x, r6.x, c{b}.w, r0.x"),
              "endif",
              "endif"]
    L += [f"mad r6.x, r0.x, {s2}.w, r8.w",
          "rcp r6.x, r6.x",
          "mul r0.x, r0.x, r6.x",
          "add r0.x, r0.x, r0.y",
          f"mul r4.xyz, r0.x, {s1}"]
    if k is None:      # additive: Esoft * colour * ADD_K (c33.w) - light that shows even on dark surfaces
        L += [f"mul_sat r4.xyz, r4, {s1}.w",
              "mov r4.w, r8.w",
              "mov oC0, r4"]
        return "\n".join(L)
    # v8: the multiply chain gets its own gentle limit E/(1 + E/MMAX) (c32.y = 1/MMAX): it only carries
    # the surface texture; the additive pass carries the beam shape + overlaps (night dst ~7/255 has no
    # detail left to multiply - v6/v7 hit the x16 cap = flat plateau)
    L += [f"mad r6.y, r4.z, {s0}.y, r8.w",      # r4.z = E (colour blue = 1)
          "rcp r6.y, r6.y",
          "mul r4.xyz, r4, r6.y",
          "add r4.xyz, r4, r8.w",
          "mul r4.xyz, r4, r8.x",
          "add_sat r4.xyz, r4, r8.y",
          "mov r4.w, r8.w",
          "mov oC0, r4"]
    return "\n".join(L)


def technique_text(passes=PASSES, bias=DEPTH_BIAS):
    out = ["", "/////////////////////////////////////////////////////////////////",
           f"// Headlights (racemod extra `headlights`): {N_CARS} cars, beam cookie, {passes} passes",
           "/////////////////////////////////////////////////////////////////",
           f"technique {TECH_NAME}", "{"]
    for k in list(range(passes)) + [None]:
        add = k is None
        out += [f"\tpass P{passes if add else k}", "\t{",
                "\t\tVertexShader=", "\t\tasm", "\t\t{"]
        out += ["\t\t\t" + s for s in vs_asm().splitlines()]
        out += ["\t\t};", "\t\tPixelShader=", "\t\tasm", "\t\t{"]
        out += ["\t\t\t" + s for s in ps_asm(k).splitlines()]
        out += ["\t\t};",
                "\t\tAlphaBlendEnable=true;", f"\t\tSrcBlend={'One' if add else 'DestColor'};", "\t\tDestBlend=One;",
                "\t\tBlendOp=Add;", "\t\tAlphaTestEnable=false;", "\t\tFogEnable=false;",
                "\t\tZEnable=true;", "\t\tZWriteEnable=false;", "\t\tZFunc=LessEqual;",
                f"\t\tDepthBias={f(bias)};", f"\t\tSlopeScaleDepthBias={f(SLOPE_BIAS)};",
                "\t\tColorWriteEnable=7;",
                # v8: each pixel lit ONCE per pass - base terrain + overlapping road layers otherwise
                # stacked the light (white roads, seams at road-piece ends). StencilRef is set per
                # pass+frame by the cave; the game itself never uses the stencil.
                "\t\tStencilEnable=true;", "\t\tStencilFunc=NotEqual;", "\t\tStencilPass=Replace;",
                "\t\tStencilFail=Keep;", "\t\tStencilZFail=Keep;",
                "\t\tStencilMask=255;", "\t\tStencilWriteMask=255;",
                "\t\tAddressU[0]=Clamp;", "\t\tAddressV[0]=Clamp;",
                "\t\tMinFilter[0]=Linear;", "\t\tMagFilter[0]=Linear;", "\t\tMipFilter[0]=None;",
                "\t}"]
    out += ["}", ""]
    return "\r\n".join(out)


def obj_consts(gain=GAIN, f=OBJ_GAIN, mmax=OBJ_MMAX):
    """c32..c33 for the static OBJECTS (v8: ramps/bridge walls blew out to white - their textures are
    much brighter at night than the terrain): gain and additive x f, own multiply limit."""
    c = ps_static_consts(gain=gain * f, add_k=ADD_K)
    return [c[0], 1.0 / mmax, c[2], c[3], c[4], c[5], c[6], c[7]]


def ps_static_consts(rng=RANGE, gain=GAIN, colour=COLOUR, wrap=WRAP, soft=SOFT, d0=D0, add_k=None):
    add_k = ADD_K if add_k is None else add_k
    """c32..c34 as 12 floats."""
    return [1.0 / (d0 * d0), 1.0 / MMAX, -1.0 / (rng * rng), 1.0,
            colour[0] * gain, colour[1] * gain, colour[2] * gain, add_k,
            wrap[0], wrap[1], rng * rng, soft]


# ---- the per-frame cave (shared by the live prototype hllive.py and racemod)
# Hook: 0x0043124c `cmp dword ptr [0x12d0c9c], 0` (7 bytes, end of the terrain draw 0x00430bf0,
# esi = the map object 0x012d0ce0). Skipped in the reflection/cube passes ([0x12d0c9c],[0x12d0ca0]).
HOOK = 0x0043124C
HOOK_ORIG = bytes.fromhex("833d9c0c2d0100")
HOOK_BACK = 0x00431253
MGR = 0x02649368               # traffic manager: +0x28 car list (slot 0 = player), +0x128 count
DEVICE = 0x025A1824
NIGHT = 0x0264832C             # sky +0x1dc night factor 0..1 (the game's headlights need > 0.5)
PART_DRAW = 0x00429850         # one land part (ecx), stream 0 = map VB [map+0x128] stride 0x2c
# v8 (2026-10-09): the ROAD layers of a land part (thiscall ecx = part, own VB/IB at +0x2cc/+0x2e4/
# +0x2fc, FVF 0x252, each sets its own stream + world transform). Roads are drawn ON TOP of the base
# terrain, so redrawing only the base left roads unlit (light lost the depth test; only the depth
# bias let bits through = the player's "flicker normal bright / flat dim").
ROAD_DRAW = (0x00429A10, 0x00429AE0, 0x00429BD0)
ROAD_MASK = 0                  # bit i = light road layer i (overlapping layers multiply the light again)
D3DX_CREATE_EFFECT = 0x00487A94
D3DX_TEX_FROM_MEM = 0x004890F7  # D3DXCreateTextureFromFileInMemoryEx (15 args, stdcall)

DATA_LAYOUT = dict(            # offsets in the data block (16-aligned where SSE reads them)
    HALFV=0x00, MONEV=0x10, BIGV=0x20, DEFMID=0x30, KSV=0x40, KTV=0x50,
    HALF=0x60, ZERO=0x64, ONE=0x68, MAXD=0x6C, RANGEF=0x70, RAMP=0x74, INVFADE=0x78,
    STATE=0x80, EFF=0x84, ERR=0x88, HR=0x8C, NPASS=0x90, NUM=0x94, DRAWN=0x98, FRAMES=0x9C,
    HRGT=0xA0, NIGHTI=0xA4, HRBEGIN=0xA8, TEX=0xAC, OLDTEX=0xB0, TEXHR=0xB4, NOBJ=0xB8, ODRAWN=0xBC,
    DARR=0xC0, CARR=0xE0,
    VSC=0x100, PSC=0x200)
DATA_LAYOUT["NAME"] = DATA_LAYOUT["PSC"] + 16 * NPSC + 0x10
DATA_LAYOUT["OBJS"] = DATA_LAYOUT["NAME"] + 0x20
DATA_LAYOUT["LAMPUP"] = (DATA_LAYOUT["OBJS"] + 4 * MAX_OBJS + 15) & ~15   # (0, LAMP_UP, 0, 0) model offset
DATA_LAYOUT["RDRAWN"] = DATA_LAYOUT["LAMPUP"] + 16                       # road-layer part draws
DATA_LAYOUT["RMASK"] = DATA_LAYOUT["RDRAWN"] + 4                         # which road layers get lit
DATA_LAYOUT["DBIAS"] = DATA_LAYOUT["RDRAWN"] + 8                         # D3DRS_DEPTHBIAS (float bits)
DATA_LAYOUT["SBIAS"] = DATA_LAYOUT["RDRAWN"] + 12                        # D3DRS_SLOPESCALEDEPTHBIAS
DATA_LAYOUT["MAXCARS"] = DATA_LAYOUT["RDRAWN"] + 16                      # player slider: lit cars 1..N_CARS
DATA_LAYOUT["OPSC"] = DATA_LAYOUT["MAXCARS"] + 16                        # objects' c32..c33 (2 regs)
DATA_LAYOUT["DATA_END"] = DATA_LAYOUT["OPSC"] + 32


def data_init(rng=RANGE, maxd=MAX_DIST, fade_near=FADE_NEAR, ramp=NIGHT_RAMP):
    """Bytes of the static part of the data block (dynamic fields zero)."""
    A = DATA_LAYOUT
    b = bytearray(A["DATA_END"])

    def put(k, fmt, *v):
        struct.pack_into(fmt, b, A[k], *v)
    put("HALFV", "<4f", 0.5, 0.5, 0.5, 0.5)
    put("MONEV", "<4f", -1.0, -1.0, -1.0, 0.0)
    put("BIGV", "<4f", 1e6, 1e6, 1e6, 0.0)
    put("LAMPUP", "<4f", 0.0, LAMP_UP, 0.0, 0.0)
    put("RMASK", "<I", ROAD_MASK)
    put("MAXCARS", "<I", N_CARS)
    put("OPSC", "<8f", *obj_consts())
    put("DBIAS", "<f", DEPTH_BIAS)
    put("SBIAS", "<f", SLOPE_BIAS)
    put("DEFMID", "<4f", 0.0, 0.5, 2.0, 0.0)
    put("KSV", "<4f", -KS, -KS, -KS, 0.0)
    put("KTV", "<4f", KT, KT, KT, 0.0)
    put("HALF", "<f", 0.5)
    put("ZERO", "<f", 0.0)
    put("ONE", "<f", 1.0)
    put("MAXD", "<f", maxd)
    put("RANGEF", "<f", rng)
    put("RAMP", "<f", ramp)
    put("INVFADE", "<f", 1.0 / (maxd - fade_near))
    struct.pack_into("<12f", b, A["PSC"] + 16 * CS, *ps_static_consts(rng))
    nm = TECH_NAME.encode() + b"\0"
    b[A["NAME"]:A["NAME"] + len(nm)] = nm
    return bytes(b)


def _xform(src, out_off):
    """world point = src.x*row0 + src.y*row1 + src.z*row2 + row3 (car matrix at ecx) -> [eax+out_off]."""
    return f"""
    movaps xmm0, {src}
    shufps xmm0, xmm0, 0
    movups xmm1, xmmword ptr [ecx]
    mulps xmm0, xmm1
    movaps xmm2, {src}
    shufps xmm2, xmm2, 0x55
    movups xmm1, xmmword ptr [ecx+16]
    mulps xmm2, xmm1
    addps xmm0, xmm2
    movaps xmm2, {src}
    shufps xmm2, xmm2, 0xaa
    movups xmm1, xmmword ptr [ecx+32]
    mulps xmm2, xmm1
    addps xmm0, xmm2
    movups xmm1, xmmword ptr [ecx+48]
    addps xmm0, xmm1
    movups xmmword ptr [eax+{out_off}], xmm0
"""


def _near(label, fail):
    """Is the point/radius in xmm4 / xmm3 (= (R + r)^2) within reach of any car light? -> falls
    through when near, jumps to `fail` when not. Uses eax, edx, xmm0-2."""
    return f"""
    xor edx, edx
{label}:
    cmp edx, dword ptr [{{S('NUM')}}]
    jge {fail}
    mov eax, edx
    shl eax, 6
    movups xmm0, xmmword ptr [eax+{{S('PSC')}}]
    subps xmm0, xmm4
    mulps xmm0, xmm0
    movaps xmm1, xmm0
    shufps xmm1, xmm1, 0x55
    movaps xmm2, xmm0
    shufps xmm2, xmm2, 0xaa
    addss xmm0, xmm1
    addss xmm0, xmm2
    inc edx
    comiss xmm3, xmm0
    jbe {label}
"""


def cave_src(data_va, effect="own", text_va=0, text_len=0, tex_va=0, tex_len=0, renderer=0x0255D7F0):
    """effect='own': create a separate effect (text_va) and the cookie texture (tex_va, a DDS) on
    first use (live prototype); effect='game': use the game's effect [renderer+0x4406c]
    (techHeadlights appended to it) and set the renderer's technique cache +0x44070 to our name so
    the game's own users switch back; the cookie must then already be in [TEX]."""
    A = {k: data_va + v for k, v in DATA_LAYOUT.items()}
    S = lambda k: f"{A[k]:#x}"
    near_t = _near("nt", "prt").replace("{S('NUM')}", S("NUM")).replace("{S('PSC')}", S("PSC"))
    near_r = _near("rnt", "rl").replace("{S('NUM')}", S("NUM")).replace("{S('PSC')}", S("PSC"))
    near_o = _near("ont", "ol").replace("{S('NUM')}", S("NUM")).replace("{S('PSC')}", S("PSC"))
    if effect == "own":
        get_eff = f"""
    mov eax, dword ptr [{S('STATE')}]
    cmp eax, 2
    je done
    test eax, eax
    jne have
    mov dword ptr [{S('STATE')}], 2
    push {S('ERR')}
    push {S('EFF')}
    push 0
    push 0
    push 0
    push 0
    push {text_len:#x}
    push {text_va:#x}
    push dword ptr [{DEVICE:#x}]
    call {D3DX_CREATE_EFFECT:#x}
    mov dword ptr [{S('HR')}], eax
    test eax, eax
    jl done
    cmp dword ptr [{S('TEX')}], 0
    jne texok
    push {S('TEX')}
    push 0
    push 0
    push 0
    push -1
    push -1
    push 1
    push 0
    push 0
    push 1
    push -1
    push -1
    push {tex_len:#x}
    push {tex_va:#x}
    push dword ptr [{DEVICE:#x}]
    call {D3DX_TEX_FROM_MEM:#x}
    mov dword ptr [{S('TEXHR')}], eax
    test eax, eax
    jl done
texok:
    mov dword ptr [{S('STATE')}], 1
have:
    mov ecx, dword ptr [{S('EFF')}]
    push {S('NAME')}
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0xec]
    test eax, eax
    jl done
"""
    else:
        get_eff = f"""
    cmp dword ptr [{S('TEX')}], 0
    je done
    mov ecx, dword ptr [{renderer + 0x4406c:#x}]
    test ecx, ecx
    je done
    mov dword ptr [{S('EFF')}], ecx
    push {S('NAME')}
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0xec]
    test eax, eax
    jl done
    mov dword ptr [{renderer + 0x44070:#x}], {S('NAME')}
"""
    darr_last = A["DARR"] + 4 * (N_CARS - 1)
    return f"""
    cmp dword ptr [0x12d0c9c], 0
    jne back
    cmp dword ptr [0x12d0ca0], 0
    jne back
    pushad
    mov ebp, esi
    movss xmm0, dword ptr [{NIGHT:#x}]
    subss xmm0, dword ptr [{S('HALF')}]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe done
    mulss xmm0, dword ptr [{S('RAMP')}]
    minss xmm0, dword ptr [{S('ONE')}]
    movss dword ptr [{S('NIGHTI')}], xmm0
    xor edi, edi
    mov ebx, {MGR:#x}
    mov ecx, dword ptr [ebx+0x128]
    cmp ecx, 64
    jbe cntok
    mov ecx, 64
cntok:
    xor edx, edx
gl:
    cmp edx, ecx
    jge gdone
    mov eax, dword ptr [ebx+edx*4+0x28]
    inc edx
    test eax, eax
    je gl
    cmp dword ptr [eax+0xa34], 0
    je gl
    movss xmm1, dword ptr [eax+0xd00]
    comiss xmm1, dword ptr [{S('ZERO')}]
    jbe gl
    movss xmm2, dword ptr [eax+0x30]
    addss xmm2, dword ptr [eax+0x38]
    addss xmm2, dword ptr [eax+0x20]
    addss xmm2, dword ptr [eax+0x28]
    addss xmm2, dword ptr [eax]
    addss xmm2, dword ptr [eax+0x14]
    ucomiss xmm2, xmm2
    jp gl
    movss xmm1, dword ptr [eax+0xa24]
    cmp eax, dword ptr [ebx+0x28]
    jne notme
    movss xmm1, dword ptr [{S('MONEV')}]
notme:
    comiss xmm1, dword ptr [{S('MAXD')}]
    ja gl
    mov esi, edi
    cmp esi, {N_CARS}
    jb ins
    comiss xmm1, dword ptr [{darr_last:#x}]
    jae gl
    mov esi, {N_CARS - 1}
ins:
    test esi, esi
    je put
    comiss xmm1, dword ptr [esi*4+{A['DARR'] - 4:#x}]
    jae put
    movss xmm2, dword ptr [esi*4+{A['DARR'] - 4:#x}]
    movss dword ptr [esi*4+{S('DARR')}], xmm2
    push dword ptr [esi*4+{A['CARR'] - 4:#x}]
    pop dword ptr [esi*4+{S('CARR')}]
    dec esi
    jmp ins
put:
    movss dword ptr [esi*4+{S('DARR')}], xmm1
    mov dword ptr [esi*4+{S('CARR')}], eax
    cmp edi, {N_CARS}
    jae gl
    inc edi
    jmp gl
gdone:
    cmp edi, dword ptr [{S('MAXCARS')}]
    jbe ncap
    mov edi, dword ptr [{S('MAXCARS')}]
ncap:
    mov dword ptr [{S('NUM')}], edi
    test edi, edi
    je done
    xor edx, edx
ll:
    cmp edx, {N_CARS}
    jge lldone
    mov eax, edx
    shl eax, 6
    add eax, {S('PSC')}
    cmp edx, edi
    jl live1
    movaps xmm0, xmmword ptr [{S('BIGV')}]
    movups xmmword ptr [eax], xmm0
    xorps xmm0, xmm0
    movups xmmword ptr [eax+16], xmm0
    movups xmmword ptr [eax+32], xmm0
    movups xmmword ptr [eax+48], xmm0
    jmp lnext
live1:
    mov ecx, dword ptr [edx*4+{S('CARR')}]
    movss xmm7, dword ptr [{S('MAXD')}]
    subss xmm7, dword ptr [edx*4+{S('DARR')}]
    mulss xmm7, dword ptr [{S('INVFADE')}]
    minss xmm7, dword ptr [{S('ONE')}]
    maxss xmm7, dword ptr [{S('ZERO')}]
    mulss xmm7, dword ptr [ecx+0xd00]
    mulss xmm7, dword ptr [{S('NIGHTI')}]
    movss xmm6, dword ptr [{S('ONE')}]
    movss xmm5, dword ptr [{S('ONE')}]
    mov ebx, dword ptr [ecx+0xc00]
    test ebx, ebx
    je hdone
    mov ebx, dword ptr [ebx+0x1c]
    test ebx, ebx
    je hdone
    mov esi, dword ptr [ebx]
    or esi, dword ptr [ebx+4]
    or esi, dword ptr [ebx+8]
    jne h0ok
    xorps xmm6, xmm6
h0ok:
    mov esi, dword ptr [ebx+12]
    or esi, dword ptr [ebx+16]
    or esi, dword ptr [ebx+20]
    jne hdone
    xorps xmm5, xmm5
hdone:
    mov ebx, dword ptr [ecx+0x8a4]
    test ebx, ebx
    je dmid
    mov ebx, dword ptr [ebx+0x3d4]
    test ebx, ebx
    je dmid
    movups xmm4, xmmword ptr [ebx]
    movups xmm3, xmmword ptr [ebx+12]
    addps xmm4, xmm3
    mulps xmm4, xmmword ptr [{S('HALFV')}]
    addps xmm4, xmmword ptr [{S('LAMPUP')}]
    jmp gotmid
dmid:
    movaps xmm4, xmmword ptr [{S('DEFMID')}]
gotmid:
{_xform('xmm4', 0)}
    movss dword ptr [eax+12], xmm7
    movups xmm0, xmmword ptr [ecx+32]
    mulps xmm0, xmmword ptr [{S('MONEV')}]
    movups xmmword ptr [eax+16], xmm0
    movss dword ptr [eax+28], xmm6
    movups xmm0, xmmword ptr [ecx]
    mulps xmm0, xmmword ptr [{S('KSV')}]
    movups xmmword ptr [eax+32], xmm0
    movss dword ptr [eax+44], xmm5
    movups xmm0, xmmword ptr [ecx+16]
    mulps xmm0, xmmword ptr [{S('KTV')}]
    movups xmmword ptr [eax+48], xmm0
lnext:
    inc edx
    jmp ll
lldone:
    xor esi, esi
    xor edi, edi
ol:
    cmp esi, dword ptr [{STATICS + 0x5000:#x}]
    jge odone
    mov ecx, dword ptr [esi*4+{STATICS:#x}]
    inc esi
    test ecx, ecx
    je ol
    test dword ptr [ecx+0x9d0], {OBJ_MASK:#x}
    je ol
    cmp dword ptr [ecx+0xa34], 0
    je ol
    movss xmm0, dword ptr [ecx+0x86c]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe ol
    mov eax, dword ptr [ecx+0x8a4]
    test eax, eax
    je ol
    test byte ptr [eax+0x10c], 0x10
    je ol
    movss xmm3, dword ptr [eax+0x378]
    mulss xmm3, dword ptr [{S('HALF')}]
    maxss xmm3, dword ptr [ecx+0x8b4]
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0xa18]
{near_o}
    mov dword ptr [edi*4+{S('OBJS')}], ecx
    inc edi
    cmp edi, {MAX_OBJS}
    jb ol
odone:
    mov dword ptr [{S('NOBJ')}], edi
    mov ebx, dword ptr [{DEVICE:#x}]
    push {S('VSC')}
    push 256
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xb4]
    mov dword ptr [{S('HRGT')}], eax
    push {A['VSC'] + 64:#x}
    push 2
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xb4]
    push {A['VSC'] + 128:#x}
    push 3
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xb4]
{get_eff}
    push 0x2c
    push 0
    push dword ptr [ebp+0x128]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x190]
    push 0x252
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x164]
    mov ecx, dword ptr [{S('EFF')}]
    push 0
    push {S('NPASS')}
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x100]
    mov dword ptr [{S('HRBEGIN')}], eax
    test eax, eax
    jl done
    mov dword ptr [{S('OLDTEX')}], 0
    push {S('OLDTEX')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x100]
    push dword ptr [{S('TEX')}]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    push 12
    push {S('VSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    push {NPSC}
    push {S('PSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    xor edi, edi
pl:
    cmp edi, dword ptr [{S('NPASS')}]
    jge pend
    mov ecx, dword ptr [{S('EFF')}]
    push edi
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x104]
    mov ecx, dword ptr [{S('FRAMES')}]
    lea ecx, [ecx*4+ecx]
    add ecx, edi
    and ecx, 0x7f
    inc ecx
    push ecx
    push 0x39
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xe4]
    push 2
    push {A['PSC'] + 16 * CS:#x}
    push {CS}
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    push dword ptr [{S('DBIAS')}]
    push 195
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xe4]
    push dword ptr [{S('SBIAS')}]
    push 175
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0xe4]
    push 4
    push {S('VSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    push 0x2c
    push 0
    push dword ptr [ebp+0x128]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x190]
    push 0x252
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x164]
    xor esi, esi
prt:
    cmp esi, dword ptr [ebp+0x2158]
    jge pnext
    mov ecx, dword ptr [ebp+esi*4+0x1158]
    inc esi
    test ecx, ecx
    je prt
    cmp dword ptr [ecx+0x110], 0
    je prt
    movss xmm3, dword ptr [ecx+0x53c8]
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0x53bc]
{near_t}
    call {PART_DRAW:#x}
    inc dword ptr [{S('DRAWN')}]
    jmp prt
pnext:
    xor esi, esi
rl:
    cmp esi, dword ptr [ebp+0x2158]
    jge rdone
    mov ecx, dword ptr [ebp+esi*4+0x1158]
    inc esi
    test ecx, ecx
    je rl
    cmp dword ptr [ecx+0x110], 0
    je rl
    movss xmm3, dword ptr [ecx+0x53c8]
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0x53bc]
{near_r}
    push ecx
    test dword ptr [{S('RMASK')}], 1
    je r1
    mov ecx, dword ptr [esp]
    call {ROAD_DRAW[0]:#x}
r1:
    test dword ptr [{S('RMASK')}], 2
    je r2
    mov ecx, dword ptr [esp]
    call {ROAD_DRAW[1]:#x}
r2:
    test dword ptr [{S('RMASK')}], 4
    je r3
    mov ecx, dword ptr [esp]
    call {ROAD_DRAW[2]:#x}
r3:
    pop ecx
    inc dword ptr [{S('RDRAWN')}]
    jmp rl
rdone:
    push 2
    push {S('OPSC')}
    push {CS}
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    xor esi, esi
ob:
    cmp esi, dword ptr [{S('NOBJ')}]
    jge obdone
    mov ecx, dword ptr [esi*4+{S('OBJS')}]
    inc esi
    push ecx
    call drawobj
    pop ecx
    mov eax, dword ptr [ecx+0xc60]
    test eax, eax
    je ob
    push 0
sub1:
    mov eax, dword ptr [esp]
    cmp eax, dword ptr [ecx+0xc60]
    jae subdone
    inc dword ptr [esp]
    mov edx, dword ptr [ecx+0xc64]
    mov edx, dword ptr [edx+eax*4]
    test edx, edx
    je sub1
    movss xmm0, dword ptr [edx+0x86c]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe sub1
    push ecx
    push edx
    call drawobj
    pop edx
    pop ecx
    jmp sub1
subdone:
    add esp, 4
    jmp ob
obdone:
    inc edi
    jmp pl
drawobj:
    mov ecx, dword ptr [esp+4]
    push 4
    push ecx
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    mov ecx, dword ptr [esp+4]
    push 0
    call {OBJ_DRAW:#x}
    inc dword ptr [{S('ODRAWN')}]
    ret
pend:
    mov ecx, dword ptr [{S('EFF')}]
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x108]
    push dword ptr [{S('OLDTEX')}]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    mov eax, dword ptr [{S('OLDTEX')}]
    test eax, eax
    je texrel
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx+8]
texrel:
    inc dword ptr [{S('FRAMES')}]
done:
    popad
back:
    cmp dword ptr [0x12d0c9c], 0
    jmp {HOOK_BACK:#x}
"""


if __name__ == "__main__":
    print(technique_text())
