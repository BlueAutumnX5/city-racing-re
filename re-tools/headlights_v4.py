"""Per-pixel headlights for City Racing (racemod extra `headlights`, player request 2026-10-05:
"headlights can shine lights on the 3D world ... make other cars too ... No shadows").

Why not the game's own lights: D3D9 fixed-function lights are PER VERTEX. Live preview 2026-10-05
(hlprobe.py) put the player's spot light (D3D light 7) on the terrain: the ground grid is ~4 m and
walls are a few big polygons, so the beam came out as blurry low-resolution blobs.

How this works instead (no shadows, no extra render targets):
- After the terrain and all its road/decal layers are drawn (0x0043124c, end of 0x00430bf0), the
  land parts near a lit car are drawn AGAIN with techHeadlights. Its pixel shader computes, per
  pixel, the light L of the N_CARS nearest cars' headlights - TWO lamps per car (the model's own
  headlight points [model+0x3d4]) - spot cone, distance fall-off, a wrapped N.L so the low beam
  still reaches the road at a grazing angle.
- The blend is SrcBlend=DestColor, DestBlend=One: result = dst * (1 + s). The pixel already on
  screen is the surface's own colour x the night ambient, so the light is multiplied by the REAL
  surface colour of every layer (terrain, roads, markings) without re-creating their texture
  combiners. s <= 1 per pass, so the technique has PASSES passes: pass k outputs
  clamp(F/2^k - 1, 0, 1) with F = 1 + L*colour*gain -> total factor min(F, 2^passes).
- Depth: ZFunc LessEqual + no Z write + a tiny DepthBias towards the camera (our VS transforms the
  same vertices in three steps; the fixed-function pipe may round differently).
- Per-car intensity = car fade x night ramp (full at night factor 0.75) x distance fade (cars
  between FADE_NEAR and MAX_DIST from the camera fade in, so lights do not pop on).

v3 (2026-10-05, after the v2 test: "too bright" where many cars meet, flicker at the bottom/edges
of the screen, GPU 91 W / 98 %, broken lamps still lit): soft saturation L/(1 + SOFT*L) so a crowd
is no brighter than one car; SlopeScaleDepthBias against the grazing-angle z-fighting; 2 passes;
each lamp is skipped per pixel (ps_3_0 dynamic branch) beyond RANGE; a lamp whose health vector
[[car+0xc00]+0x1c + i*12] is zero (the game's own glow skips it, 0x00415851) gives no light.
v4 (player: "why the cars and buildings not shine? We are all black voids in light up terrain",
"THE BRIDGES TOO!!"): static objects of class OBJ_MASK (BRIDGE 0x80 | BUILDING 0x100; all 2739
statics use FVF 0x112 = position+normal+uv) within reach of a lamp are collected once per frame
(max MAX_OBJS, manager 0x026b1aa0) and redrawn in every pass through the game's own part draw
0x00408b40(obj, 0) (sets WORLD = the object's matrix at +0, FVF, buffers, DIP), main object + its
loaded sub-parts [obj+0xc64] x [obj+0xc60]; VS c0-c3 = that object's matrix before each draw.
v4 fix: a race opponent being parked had a NaN matrix -> NaN lamps made every "near" test true
(300 land parts per pass, 32 FPS). Cars with a NaN position/forward are skipped, and the near
tests are written R^2 > d^2 so that an unordered compare means "far".
Live test history: v1 2026-10-05 (8 cars, ONE light per car, gain 3, 2 passes, night ramp to 1.0):
compiled in game, "No FPS losing", but "1 output, in the middle. Cars have 2", "low brightness",
"many cars have it suddenly". v2 = this file: 2 lamps per car, 3 passes, faster ramp, distance fade.

Constants (written by the cave every frame):
  VS c0-c3 World rows, c4-c7 View rows, c8-c11 Projection rows (device GetTransform).
  PS c[2i] = lamp i position (xyz), c[2i+1] = (-beam direction xyz, intensity), i < N_LIGHTS,
     cS = c[2N] (spotA, spotB, -1/R^2, 1), cS+1 = colour*gain (rgb), cS+2 = (wrapA, wrapB, 0, 0).
"""
import math

N_CARS = 8              # nearest cars with headlights (player choice 2026-10-05: "try 8 nearest")
N_LIGHTS = 2 * N_CARS   # two lamps per car
RANGE = 45.0            # m, light reaches 0 here ((1 - d^2/R^2)^2)
CONE_INNER = 12.0       # deg half-angle: full brightness inside
CONE_OUTER = 34.0       # deg half-angle: 0 outside
TILT = 0.035            # beam direction = forward - (0, TILT, 0), normalised (about 2 deg down)
GAIN = 4.5              # player 2026-10-05 "brighter" (was 3); F = 1 + Lsoft*colour*GAIN, Lsoft = L / (1 + SOFT*L) < 1/SOFT
SOFT = 0.5              # one car's hot spot (L ~ 2) -> Lsoft 1; a crowd -> at most 2
COLOUR = (1.0, 0.95, 0.85)
WRAP = (0.3, 0.5)       # lambert = saturate(N.L*A + B); was (0.6, 0.4): walls facing a lamp 2.5x the ground (player: bridge too bright)
PASSES = 2              # max brightening = 2^PASSES
DEPTH_BIAS = -0.00002   # D3DRS_DEPTHBIAS, negative = towards the camera
SLOPE_BIAS = -2.0       # D3DRS_SLOPESCALEDEPTHBIAS: grazing ground near the camera (v2 flicker)
MAX_DIST = 120.0        # cars farther than this from the camera are never picked
FADE_NEAR = 90.0        # full intensity closer than this
NIGHT_RAMP = 4.0        # intensity x clamp((night - 0.5) * NIGHT_RAMP, 0, 1)
TECH_NAME = "techHeadlights"
OBJ_MASK = 0x780        # BRIDGE 0x80 | BUILDING 0x100 | DECORS 0x200 (loose objects) | LAMPPOST 0x400 (player: "loose objects, streetlights")
MAX_OBJS = 64
STATICS = 0x026B1AA0    # static-object manager: +0 slots, +0x5000 count
OBJ_DRAW = 0x00408B40   # thiscall (ecx = object, part index): one model part
CS = 2 * N_LIGHTS       # first static PS constant register (c32)
NPSC = CS + 3           # PS constant registers written by the cave


def spot_ab(inner=CONE_INNER, outer=CONE_OUTER):
    ci, co = math.cos(math.radians(inner)), math.cos(math.radians(outer))
    a = 1.0 / (ci - co)
    return a, -co * a


def ps_static_consts(rng=RANGE, gain=GAIN, colour=COLOUR, wrap=WRAP, soft=SOFT):
    """cS..cS+2 as 12 floats: (spotA, spotB, -1/R^2, 1), colour*gain, (wrapA, wrapB, R^2, soft)."""
    a, b = spot_ab()
    return [a, b, -1.0 / (rng * rng), 1.0,
            colour[0] * gain, colour[1] * gain, colour[2] * gain, 0.0,
            wrap[0], wrap[1], rng * rng, soft]


def f(x):
    """Plain decimal: the game's 2004 effect parser rejects exponents ('-2e-05' -> X3000)."""
    t = f"{x:.10f}".rstrip("0")
    return t + "0" if t.endswith(".") else t


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


def ps_asm(k, n=N_LIGHTS):
    """Pass k (0-based) of the multiply chain."""
    s0, s1, s2, sd = f"c{CS}", f"c{CS + 1}", f"c{CS + 2}", f"c{CS + 3}"
    L = ["ps_3_0",
         f"def {sd}, {f(2.0 ** -k)}, -1, 0, 1",
         "dcl_texcoord0 v0.xyz",
         "dcl_texcoord1 v1.xyz",
         "nrm r3.xyz, v1",
         f"mov r5, {sd}",
         "mov r0.x, r5.z"]
    for i in range(n):
        p, d = f"c{2 * i}", f"c{2 * i + 1}"
        L += [f"add r1.xyz, {p}, -v0",
              "dp3 r1.w, r1, r1",
              f"if_lt r1.w, {s2}.z",
              "rsq r2.w, r1.w",
              "mul r1.xyz, r1, r2.w",
              f"dp3 r2.x, r1, {d}",
              f"mad_sat r2.x, r2.x, {s0}.x, {s0}.y",
              f"mad_sat r2.y, r1.w, {s0}.z, {s0}.w",
              "mul r2.y, r2.y, r2.y",
              "dp3 r2.z, r1, r3",
              f"mad_sat r2.z, r2.z, {s2}.x, {s2}.y",
              "mul r2.x, r2.x, r2.y",
              "mul r2.x, r2.x, r2.z",
              f"mad r0.x, r2.x, {d}.w, r0.x",
              "endif"]
    L += [f"mad r6.x, r0.x, {s2}.w, r5.w",
          "rcp r6.x, r6.x",
          "mul r0.x, r0.x, r6.x",
          f"mul r4.xyz, r0.x, {s1}",
          "add r4.xyz, r4, r5.w",
          "mul r4.xyz, r4, r5.x",
          "add_sat r4.xyz, r4, r5.y",
          "mov r4.w, r5.w",
          "mov oC0, r4"]
    return "\n".join(L)


def technique_text(passes=PASSES, bias=DEPTH_BIAS):
    out = ["", "/////////////////////////////////////////////////////////////////",
           f"// Headlights (racemod extra `headlights`): {N_CARS} cars x 2 lamps, {passes} passes",
           "/////////////////////////////////////////////////////////////////",
           f"technique {TECH_NAME}", "{"]
    for k in range(passes):
        out += [f"\tpass P{k}", "\t{",
                "\t\tVertexShader=", "\t\tasm", "\t\t{"]
        out += ["\t\t\t" + s for s in vs_asm().splitlines()]
        out += ["\t\t};", "\t\tPixelShader=", "\t\tasm", "\t\t{"]
        out += ["\t\t\t" + s for s in ps_asm(k).splitlines()]
        out += ["\t\t};",
                "\t\tAlphaBlendEnable=true;", "\t\tSrcBlend=DestColor;", "\t\tDestBlend=One;",
                "\t\tBlendOp=Add;", "\t\tAlphaTestEnable=false;", "\t\tFogEnable=false;",
                "\t\tZEnable=true;", "\t\tZWriteEnable=false;", "\t\tZFunc=LessEqual;",
                f"\t\tDepthBias={f(bias)};", f"\t\tSlopeScaleDepthBias={f(SLOPE_BIAS)};",
                "\t\tColorWriteEnable=7;", "\t}"]
    out += ["}", ""]
    return "\r\n".join(out)


# ---- float model of one pixel (for the GPU test)
def light_L(P, N, lights, rng=RANGE, wrap=WRAP):
    a, b = spot_ab()
    nn = math.sqrt(sum(x * x for x in N)) or 1.0
    N = [x / nn for x in N]
    tot = 0.0
    for pos, ndir, inten in lights:
        v = [pos[j] - P[j] for j in range(3)]
        d2 = sum(x * x for x in v)
        r = 1.0 / math.sqrt(d2)
        ln = [x * r for x in v]
        spot = min(max(sum(ln[j] * ndir[j] for j in range(3)) * a + b, 0.0), 1.0)
        att = min(max(1.0 - d2 / (rng * rng), 0.0), 1.0) ** 2
        lam = min(max(sum(ln[j] * N[j] for j in range(3)) * wrap[0] + wrap[1], 0.0), 1.0)
        tot += spot * att * lam * inten
    return tot


def model_factor(P, N, lights, passes=PASSES, gain=GAIN, colour=COLOUR):
    L = light_L(P, N, lights)
    F = [1.0 + L * c * gain for c in colour]
    out = [1.0, 1.0, 1.0]
    for k in range(passes):
        s = [min(max(x * 2.0 ** -k - 1.0, 0.0), 1.0) for x in F]
        out = [o * (1.0 + t) for o, t in zip(out, s)]
    return out


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
D3DX_CREATE_EFFECT = 0x00487A94

DATA_LAYOUT = dict(            # offsets in the data block (16-aligned where SSE reads them)
    HALFV=0x00, TILTV=0x10, BIGV=0x20, DEFL0=0x30, DEFL1=0x40,
    HALF=0x50, ZERO=0x54, ONE=0x58, MAXD=0x5C, MONE=0x60, RANGEF=0x64, RAMP=0x68, INVFADE=0x6C,
    STATE=0x70, EFF=0x74, ERR=0x78, HR=0x7C, NPASS=0x80, NUM=0x84, DRAWN=0x88, FRAMES=0x8C,
    HRGT=0x90, NIGHTI=0x94, HRBEGIN=0x98, NUML=0x9C,
    DARR=0xA0, CARR=0xC0, NOBJ=0xE0, ODRAWN=0xE4,
    VSC=0x100, PSC=0x200, NAME=0x200 + 16 * NPSC + 0x10)
DATA_LAYOUT["OBJS"] = DATA_LAYOUT["NAME"] + 0x20
DATA_LAYOUT["DATA_END"] = DATA_LAYOUT["OBJS"] + 4 * MAX_OBJS


def data_init(rng=RANGE, tilt=TILT, maxd=MAX_DIST, fade_near=FADE_NEAR, ramp=NIGHT_RAMP):
    """Bytes of the static part of the data block (dynamic fields zero)."""
    import struct
    A = DATA_LAYOUT
    b = bytearray(A["DATA_END"])

    def put(k, fmt, *v):
        struct.pack_into(fmt, b, A[k], *v)
    put("HALFV", "<4f", 0.5, 0.5, 0.5, 0.5)
    put("TILTV", "<4f", 0.0, tilt, 0.0, 0.0)
    put("BIGV", "<4f", 1e6, 1e6, 1e6, 0.0)
    put("DEFL0", "<4f", -0.7, 0.5, 2.0, 0.0)
    put("DEFL1", "<4f", 0.7, 0.5, 2.0, 0.0)
    put("HALF", "<f", 0.5)
    put("ZERO", "<f", 0.0)
    put("ONE", "<f", 1.0)
    put("MAXD", "<f", maxd)
    put("MONE", "<f", -1.0)
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


def cave_src(data_va, effect="own", text_va=0, text_len=0, renderer=0x0255D7F0):
    """effect='own': create a separate effect from text_va on first use (live prototype);
    effect='game': use the game's effect [renderer+0x4406c] (techHeadlights appended to it) and set
    the renderer's technique cache +0x44070 to our name so the game's own users switch back."""
    A = {k: data_va + v for k, v in DATA_LAYOUT.items()}
    S = lambda k: f"{A[k]:#x}"
    if effect == "own":
        get_eff = f"""
    mov eax, dword ptr [{S('STATE')}]
    cmp eax, 2
    je done
    test eax, eax
    jne have
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
    mov dword ptr [{S('STATE')}], 2
    test eax, eax
    jl done
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
    ucomiss xmm2, xmm2
    jp gl
    movss xmm1, dword ptr [eax+0xa24]
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
    mov dword ptr [{S('NUM')}], edi
    lea eax, [edi+edi]
    mov dword ptr [{S('NUML')}], eax
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
    movups xmmword ptr [eax+32], xmm0
    xorps xmm0, xmm0
    movups xmmword ptr [eax+16], xmm0
    movups xmmword ptr [eax+48], xmm0
    jmp lnext
live1:
    mov ecx, dword ptr [edx*4+{S('CARR')}]
    movups xmm6, xmmword ptr [ecx+32]
    subps xmm6, xmmword ptr [{S('TILTV')}]
    movaps xmm1, xmm6
    mulps xmm1, xmm1
    movaps xmm2, xmm1
    shufps xmm2, xmm2, 0x55
    movaps xmm3, xmm1
    shufps xmm3, xmm3, 0xaa
    addss xmm1, xmm2
    addss xmm1, xmm3
    rsqrtss xmm1, xmm1
    mulss xmm1, dword ptr [{S('MONE')}]
    shufps xmm1, xmm1, 0
    mulps xmm6, xmm1
    movss xmm7, dword ptr [{S('MAXD')}]
    subss xmm7, dword ptr [edx*4+{S('DARR')}]
    mulss xmm7, dword ptr [{S('INVFADE')}]
    minss xmm7, dword ptr [{S('ONE')}]
    maxss xmm7, dword ptr [{S('ZERO')}]
    mulss xmm7, dword ptr [ecx+0xd00]
    mulss xmm7, dword ptr [{S('NIGHTI')}]
    movaps xmm3, xmm7
    mov ebx, dword ptr [ecx+0xc00]
    test ebx, ebx
    je alive_done
    mov ebx, dword ptr [ebx+0x1c]
    test ebx, ebx
    je alive_done
    mov esi, dword ptr [ebx]
    or esi, dword ptr [ebx+4]
    or esi, dword ptr [ebx+8]
    jne a0ok
    xorps xmm7, xmm7
a0ok:
    mov esi, dword ptr [ebx+12]
    or esi, dword ptr [ebx+16]
    or esi, dword ptr [ebx+20]
    jne alive_done
    xorps xmm3, xmm3
alive_done:
    mov ebx, dword ptr [ecx+0x8a4]
    test ebx, ebx
    je deflt
    mov ebx, dword ptr [ebx+0x3d4]
    test ebx, ebx
    je deflt
    movups xmm4, xmmword ptr [ebx]
    movups xmm5, xmmword ptr [ebx+12]
    jmp gotl
deflt:
    movaps xmm4, xmmword ptr [{S('DEFL0')}]
    movaps xmm5, xmmword ptr [{S('DEFL1')}]
gotl:
{_xform('xmm4', 0)}
{_xform('xmm5', 32)}
    movups xmmword ptr [eax+16], xmm6
    movups xmmword ptr [eax+48], xmm6
    movss dword ptr [eax+28], xmm7
    movss dword ptr [eax+60], xmm3
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
    xor edx, edx
ont:
    cmp edx, dword ptr [{S('NUML')}]
    jge ol
    mov eax, edx
    shl eax, 5
    movups xmm0, xmmword ptr [eax+{S('PSC')}]
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
    jbe ont
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
    push 4
    push {S('VSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
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
    xor edx, edx
nt:
    cmp edx, dword ptr [{S('NUML')}]
    jge prt
    mov eax, edx
    shl eax, 5
    movups xmm0, xmmword ptr [eax+{S('PSC')}]
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
    jbe nt
    call {PART_DRAW:#x}
    inc dword ptr [{S('DRAWN')}]
    jmp prt
pnext:
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
    inc dword ptr [{S('FRAMES')}]
done:
    popad
back:
    cmp dword ptr [0x12d0c9c], 0
    jmp {HOOK_BACK:#x}
"""


if __name__ == "__main__":
    print(technique_text())
