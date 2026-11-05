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

N_CARS = 16             # nearest cars with headlights (player choice 2026-10-05: "try 8 nearest")
RANGE = 90.0            # m, light reaches 0 here (v8: window (1 - d^2/R^2), not squared)
D0 = 40.0               # m, distance falloff 1/(1 + d^2/D0^2) (v6: v5 was flat out to ~20 m)
GAIN = 40.0             # E = GAIN*L (2026-10-10: 27 was tuned for the old brighter night; realistic dark moon night needs 40)
# v10 (2026-10-10, player: traffic beams "drowning" in crowds, "I just want it behave like real world"):
# light now adds up like real light - each car's beam is squeezed ON ITS OWN, L/(1 + SOFT*L) (tames only
# extreme close-ups), then the SUM goes through an eye-like log curve A*ln(1 + sum/A) that keeps ratios
# (a hot spot stays brighter than its surroundings inside a lit street). v9 squeezed the SUM with
# L/(1 + SOFT*L) instead, which flattened every traffic beam into one glow; the player car's special
# accumulator (v9 "high beam" look) is gone - every car is treated the same.
SOFT = 1.24             # per-car squeeze k (c34.w): a beam at L 1 -> 0.45, L 8 (lamp at a wall) -> 0.73
TONE_A = 0.15           # log curve knee (0.29 let traffic flood plazas; slider "tone")
COLOUR = (0.78, 0.9, 1.0)   # v7: cool xenon white like the cars' lamp glows (player: "blue")
WRAP = (0.3, 0.5)       # lambert = saturate(N.L*A + B); (0.6, 0.4) made walls 2.5x the ground
ADD_K = 0.008           # additive pass (v15c: 0.02 washed textures out - player; multiply keeps their contrast)
PASSES = 3              # multiply passes, cap 2^PASSES = x8 (v8: MMAX keeps it below)
OBJ_GAIN = 0.8          # objects get GAIN x this (0.5 left building walls at +3..13 %)
BODY_EXTRA = 2          # v14d: extra multiply passes for CAR BODIES only (cap x8 -> x32)
BODY_GAIN = 3.0         # v14c car bodies: multiply only, so they need more than objects
BODY_MMAX = 4.0         # v14e: multiply also boosts the paint's REFLECTIONS (sky/buildings) - x32 made
                        # 'shine from another source' (player); keep it low, light the paint additively
SPEC_SHIN = 40.0        # v14f car-paint highlight: Blinn-Phong exponent
SPEC_GAIN = 0.6         # v14f highlight strength (white)
BODY_ADD_K = 0.012      # v14e: additive light on car bodies tinted with the car PAINT colour (+0xe5c); 0.06 = neon
OBJ_MMAX = 2.5          # objects multiply limit
MMAX = 7.0              # v15c multiply limit on land/objects: F < 8 = the 3-pass cap (texture-preserving)
                        # plateau with a hard edge, overlaps added nothing, player 2026-10-09)
DEPTH_BIAS = -0.00002   # D3DRS_DEPTHBIAS, negative = towards the camera
SLOPE_BIAS = -2.0       # D3DRS_SLOPESCALEDEPTHBIAS: grazing ground near the camera (v2 flicker)
MAX_DIST = 120.0        # cars farther than this from the camera are never picked
FADE_NEAR = 90.0        # full intensity closer than this
NIGHT_RAMP = 4.0        # intensity x clamp((night - 0.5) * NIGHT_RAMP, 0, 1)
TECH_NAME = "techHeadlights"
OBJ_MASK = 0x180         # v15: early pass = BRIDGE | BUILDING only (drawn before the terrain)
LATE_MASK = 0x600        # v15: DECORS (loose objects) | LAMPPOST - drawn LATE (0x004217d2), late hook
OBJ_MASK_V14 = 0x780        # BRIDGE 0x80 | BUILDING 0x100 | DECORS 0x200 (loose objects) | LAMPPOST 0x400
MAX_OBJS = 64
STATICS = 0x026B1AA0    # static-object manager: +0 slots, +0x5000 count
OBJ_DRAW = 0x00408B40   # thiscall (ecx = object, part index): one model part
CS = 4 * N_CARS         # first static PS constant register (c32)
NPSC = CS + 6           # PS constant registers written by the cave (v10: + c[CS+3] = log tone curve)

# cookie: u = 0.5 + KS * x/z (horizontal, +x = right), v = 0.5 - KT * y/z (texture top = up)
# v11 (2026-10-10): REFLECTOR beam - all 8 car models have reflector headlights (player-verified, see
# memory city-racing-car-models). Coverage widened for the side streaks and the upward glare
# (v10's +22.6 deg top edge cut the spill off hard - player: "a hard cutoff at the very top").
COOKIE_W, COOKIE_H = 1024, 256          # v13: 1024 wide - +-80 deg keeps the centre sharp
KS = 0.5 / math.tan(math.radians(80.0))   # +-80 deg horizontally: the LEAKS (v12 +-60, v10 +-45)
KT = 0.5 / math.tan(math.radians(35.0))   # +-35 deg vertically (v10 +-22.6)
KERB = 1                # +1: right-hand traffic - the kerb side (right) gets the raised 15-deg cut-off
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


def _sstep(e0, e1, x):
    """Smoothstep, works on floats and numpy arrays (e0 > e1 gives the falling version)."""
    import numpy as np
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# v13 (2026-10-10, player: "all cars leaky ... like real leaky reflector (light patches instead of smooth
# light on the leak sides)", after showing a real motorcycle reflector on a wall): the hot zone is a
# WIDE FLAT BAND with wings; light LEAKS sideways almost to 90 deg as irregular PATCHES on a faint spill.
# hot band + wings (az, el, sigma az, sigma el, weight)
_FACETS = ((1.0, -1.2, 16.0, 1.1, 0.80), (-6.0, -1.4, 14.0, 1.2, 0.50), (8.0, -1.0, 14.0, 1.0, 0.50),
           (-20.0, -1.5, 12.0, 1.0, 0.25), (20.0, -1.2, 12.0, 0.9, 0.25), (-1.0, -3.0, 14.0, 2.2, 0.30))
# caustics near the lamp: thin wavy lines (base el, amplitude, frequency per deg, phase, weight, reach)
_CAUSTICS = ((-2.8, 0.6, 0.22, 0.4, 0.07, 30.0), (-4.5, 0.9, 0.15, 2.0, 0.06, 26.0),
             (-6.5, 1.2, 0.12, 4.1, 0.05, 22.0), (-9.0, 1.6, 0.09, 1.3, 0.04, 18.0),
             (-3.6, 0.5, 0.31, 5.2, 0.04, 34.0))
# side streaks reaching far (el, sigma el, reach, weight, phase)
_STREAKS = ((-1.0, 0.45, 70.0, 0.06, 0.0), (-2.3, 0.6, 64.0, 0.045, 1.7), (-3.8, 0.8, 56.0, 0.035, 3.1))
LEAK_PATCHES = 26       # irregular light patches per lamp on the leak sides
LEAK_SEED = 2008        # fixed: the same pattern every build


def _leak_patches(side):
    """Deterministic patch list for one lamp: (az, el, sigma az, sigma el, slant, weight). More and
    brighter patches towards the lamp's own side, a few on the far side too."""
    import random
    rnd = random.Random(LEAK_SEED + (0 if side < 0 else 1))
    out = []
    for n in range(LEAK_PATCHES):
        own = rnd.random() < 0.7                           # 70 % on the lamp's own side
        sgn = side if own else -side
        az = sgn * (20.0 + 58.0 * rnd.random() ** 0.8)    # 20 .. 78 deg out
        el = -6.0 + 7.5 * rnd.random() - 0.04 * abs(az)    # mostly around / below the cut-off
        sa = 1.5 + 3.5 * rnd.random()                     # small, separated patches (v13a)
        se = 0.4 + 1.2 * rnd.random()
        slant = (rnd.random() - 0.5) * 0.25                # some patches tilted (caustic arcs)
        w = (0.008 + 0.025 * rnd.random()) * (1.0 if own else 0.5)  # v13e: player asked 3x "darken the leak"
        out.append((az, el, sa, se, slant, w))
    return out


def reflector_np(AZ, EL, side):
    """Un-normalised LEAKY reflector low beam of one lamp (side -1 left, +1 right) on numpy grids of
    azimuth/elevation in degrees."""
    import numpy as np
    az = AZ - 0.8 * side
    k = az * KERB
    cut = -0.6 + np.minimum(1.6, np.maximum(0.0, k) * math.tan(math.radians(15.0)))
    cut = cut + 0.35 * np.sin(az * 0.21 + 0.7) + 0.2 * np.sin(az * 0.53 + 2.1)   # ragged
    below = 1.0 - _sstep(cut - 1.0, cut + 4.5, EL)   # v13f: long soft top (player: 'feels like a projector')
    lit = np.zeros_like(AZ)
    for a, e, sa, se, w in _FACETS:
        lit += w * np.exp(-((az - a) / sa) ** 2 - ((EL - e) / se) ** 2)
    lit += 0.45 * np.exp(-(az / 24.0) ** 2) * np.exp(-((EL + 2.5) / 5.0) ** 2)   # spread: player likes it (v13d narrowing reverted)
    for e, se, reach, w, ph in _STREAKS:
        ripple = 0.65 + 0.35 * np.cos(az * 0.35 + ph)
        lit += w * ripple * np.exp(-((EL - e) / se) ** 2) * np.exp(-(np.abs(az) / reach) ** 3)
    for e0, amp, fq, ph, w, reach in _CAUSTICS:
        line = e0 + amp * np.sin(az * fq + ph)
        lit += w * np.exp(-((EL - line) / 0.3) ** 2) * np.exp(-(az / reach) ** 2)
    lit += 0.25 * np.exp(-(az / 32.0) ** 2) * _sstep(-3.0, -8.0, EL) * (1.0 - _sstep(-18.0, -30.0, EL))
    # the LEAKS: a faint smooth lateral spill with irregular patches on it, out to ~78 deg
    spill = 0.005 * np.exp(-((EL + 2.0) / 4.0) ** 2) * _sstep(15.0, 30.0, np.abs(AZ))
    lit += spill
    for a, e, sa, se, sl, w in _leak_patches(side):
        de = EL - e - sl * (AZ - a)                          # slanted patch
        lit += w * np.exp(-((AZ - a) / sa) ** 2 - (de / se) ** 2)
    lit = lit * below
    up = np.maximum(0.0, EL - cut)
    above = (0.09 * np.exp(-up / 5.0) * np.exp(-(az / 30.0) ** 2)
             + 0.04 * np.exp(-((EL - cut - 0.6) / 0.5) ** 2) * np.exp(-(np.abs(az) / 55.0) ** 3)
             + 0.02 * np.exp(-up / 12.0) * np.exp(-(az / 60.0) ** 2)) * (1.0 - below)
    edge = (1.0 - _sstep(72.0, 80.0, np.abs(AZ))) * (1.0 - _sstep(24.0, 33.0, EL)) * (1.0 - _sstep(-24.0, -33.0, EL))
    return (1.0 - np.exp(-1.5 * (lit + above))) * edge


def cookie_pixels(w=COOKIE_W, h=COOKIE_H):
    """BGRA bytes, top row first: R = left lamp, G = right lamp. Stores SQRT(value) - the shader squares
    it back (1 mul) - so faint glare/leak levels get ~16x finer steps."""
    import numpy as np
    el = np.degrees(np.arctan((0.5 - (np.arange(h) + 0.5) / h) / KT))
    az = np.degrees(np.arctan(((np.arange(w) + 0.5) / w - 0.5) / KS))
    AZ, EL = np.meshgrid(az, el)
    r, g = reflector_np(AZ, EL, -1), reflector_np(AZ, EL, +1)
    peak = max(r.max(), g.max())
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., 2] = np.round(255 * np.sqrt(r / peak))
    out[..., 1] = np.round(255 * np.sqrt(g / peak))
    out[..., 3] = 255
    return out.tobytes()


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
        "dcl_texcoord2 o3.xyz",
        "dcl_texcoord0 v2",             # v15: the model's own UVs (leaf cut-out on trees)
        "dcl_texcoord3 o4.xy",
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
        # v14f: pixel -> camera vector for the car-paint highlight. camera = -(t . row_j) of the VIEW
        # matrix (c4-c6 rows, c7 = translation), so view vector = -(t.rows + world pos)
        "mov r6, c7",                 # one constant per instruction (X5752)
        "dp3 r5.x, r6, c4",
        "dp3 r5.y, r6, c5",
        "dp3 r5.z, r6, c6",
        "add r5.xyz, r5, r0",
        "mov o3.xyz, -r5",
        "mov o4.xy, v2",
    ])


def ps_asm(k, n=N_CARS):
    """Pass k (0-based) of the multiply chain; k = None: the final ADDITIVE pass (v7)."""
    s0, s1, s2, sg = f"c{CS}", f"c{CS + 1}", f"c{CS + 2}", f"c{CS + 3}"
    sp = f"c{CS + 4}"          # v14f (spec on > 0, shininess, spec gain, 0): car-paint highlight
    sa = f"c{CS + 5}"          # v15 (a, b, 0, 0): discard if alpha*a + b < 0 - trees (1, -0.5), else (0, 1)
    sd, sh = f"c{CS + 6}", f"c{CS + 7}"
    L = ["ps_3_0",
         f"def {sd}, {f(2.0 ** -k) if k is not None else '1'}, -1, 0, 1",
         f"def {sh}, 0.5, 0, 0, 0",
         "dcl_texcoord0 v0.xyz",
         "dcl_texcoord1 v1.xyz",
         "dcl_texcoord2 v2.xyz",
         "dcl_texcoord3 v3.xy",
         "dcl_2d s0",
         "dcl_2d s1",
         "texld r12, v3, s1",                    # v15: the object's own texture (stage 1)
         f"mad r12, r12.w, {sa}.x, {sa}.y",
         "texkill r12",                          #   leaf gaps stay unlit
         "nrm r3.xyz, v1",
         f"mov r8, {sd}",
         "mov r0.x, r8.z",
         "mov r0.y, r8.z"]
    if k is None:
        L += ["nrm r9.xyz, v2"]                  # v14f: towards the camera
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
              "mul r5.xy, r5, r5",                   # v11: the cookie stores sqrt(value)
              f"mul r6.x, r5.x, c{b + 1}.w",        # left lamp x its health
              f"mad r6.x, r5.y, c{b + 2}.w, r6.x",  # + right lamp x its health
              "rsq r2.w, r1.w",
              "mul r2.xyz, r1, r2.w",
              "dp3 r6.z, r2, r3",
              f"mad_sat r6.z, r6.z, {s2}.x, {s2}.y",
              f"mad_sat r6.y, r1.w, {s0}.z, {s0}.w",
              f"mad r6.w, r1.w, {s0}.x, {s0}.w",    # 1 + d^2/D0^2
              "rcp r6.w, r6.w",
              "mul r6.y, r6.y, r6.w"]
        if k is None:   # v14f Blinn-Phong highlight of this lamp (white), only where c36.x > 0 (car bodies)
            L += [f"if_lt r8.z, {sp}.x",
                  "add r10.xyz, r2, r9",
                  "nrm r11.xyz, r10",
                  "dp3_sat r10.w, r11, r3",
                  f"pow r10.w, r10.w, {sp}.y",
                  "dp3_sat r11.w, r2, r3",
                  "mul r10.w, r10.w, r11.w",
                  "mul r10.w, r10.w, r6.x",
                  "mul r10.w, r10.w, r6.y",
                  f"mad r0.y, r10.w, c{b}.w, r0.y",
                  "endif"]
        L += ["mul r6.x, r6.x, r6.y",
              "mul r6.x, r6.x, r6.z",
              f"mul r6.x, r6.x, c{b}.w",            # L = this car's light x its intensity
              f"mad r6.w, r6.x, {s2}.w, r8.w",      # v10 per-car squeeze: t = 1 + SOFT*L
              "rcp r6.w, r6.w",                      #   1/t
              "mad r0.x, r6.x, r6.w, r0.x",          #   sum += L/t (real light adds up)
              "endif",
              "endif"]
    L += [f"mad r6.x, r0.x, {sg}.x, r8.w",      # v10 eye-like curve: 1 + sum/A
          "log r6.x, r6.x",                       #   log2(...)
          f"mul r0.x, r6.x, {sg}.y",              #   x A*ln2 = A*ln(1 + sum/A)
          f"mul r4.xyz, r0.x, {s1}"]
    if k is None:      # additive: Esoft * colour * ADD_K (c33.w) - light that shows even on dark surfaces
        L += [f"mul_sat r4.xyz, r4, {s1}.w",
              f"mad_sat r4.xyz, r0.y, {sp}.z, r4",    # v14f + white lamp highlight (bodies only)
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
    # v14d: P0..P{passes-1} multiply, P{passes} ADDITIVE, then BODY_EXTRA more multiply passes that only
    # the car-body cave runs (raises the paint's brightening cap from 2^passes to 2^(passes+extra))
    for n, k in enumerate(list(range(passes)) + [None] + list(range(passes, passes + BODY_EXTRA))):
        add = k is None
        out += [f"\tpass P{n}", "\t{",
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
                "\t\tAddressU[1]=Wrap;", "\t\tAddressV[1]=Wrap;",
                "\t\tMinFilter[1]=Linear;", "\t\tMagFilter[1]=Linear;", "\t\tMipFilter[1]=Linear;",
                "\t}"]
    out += ["}", ""]
    return "\r\n".join(out)


def body_consts(rng=RANGE):
    """v14f car bodies' c32..c36 (5 regs): body gain/limit, TRUE facing shading (wrap 1, 0 - the
    land's wrapped light lit faces turned away = flat glow), same tone curve, highlight ON."""
    c = ps_static_consts(rng)
    o = obj_consts(f=BODY_GAIN, mmax=BODY_MMAX)
    return o + [1.0, 0.0, c[10], c[11]] + c[12:16] + [1.0, SPEC_SHIN, SPEC_GAIN, 0.0]


def obj_consts(gain=GAIN, f=OBJ_GAIN, mmax=OBJ_MMAX):
    """c32..c33 for the static OBJECTS (v8: ramps/bridge walls blew out to white - their textures are
    much brighter at night than the terrain): gain and additive x f, own multiply limit."""
    c = ps_static_consts(gain=gain * f, add_k=ADD_K)
    return [c[0], 1.0 / mmax, c[2], c[3], c[4], c[5], c[6], c[7]]


def ps_static_consts(rng=RANGE, gain=GAIN, colour=COLOUR, wrap=WRAP, soft=SOFT, d0=D0, add_k=None, tone_a=TONE_A):
    add_k = ADD_K if add_k is None else add_k
    """c32..c35 as 16 floats (c35 = v10 log tone curve)."""
    return [1.0 / (d0 * d0), 1.0 / MMAX, -1.0 / (rng * rng), 1.0,
            colour[0] * gain, colour[1] * gain, colour[2] * gain, add_k,
            wrap[0], wrap[1], rng * rng, soft,
            1.0 / tone_a, tone_a * math.log(2.0), 0.0, 0.0,
            0.0, SPEC_SHIN, SPEC_GAIN, 0.0,                  # c36: highlight OFF for land/objects
            0.0, 1.0, 0.0, 0.0]                              # c37: leaf cut-out OFF


# ---- the per-frame cave (shared by the live prototype hllive.py and racemod)
# Hook: 0x0043124c `cmp dword ptr [0x12d0c9c], 0` (7 bytes, end of the terrain draw 0x00430bf0,
# esi = the map object 0x012d0ce0). Skipped in the reflection/cube passes ([0x12d0c9c],[0x12d0ca0]).
HOOK = 0x0043124C
HOOK_ORIG = bytes.fromhex("833d9c0c2d0100")
HOOK_BACK = 0x00431253
MGR = 0x02649368               # traffic manager: +0x28 car list (slot 0 = player), +0x128 count
DEVICE = 0x025A1824
# v14 (2026-10-10, player: "light up the car bodies"): second hook BETWEEN the car body pass 0x00442080
# and the car detail pass 0x00442520 in the frame function: `mov ecx, 0x2649368` at 0x004217aa.
BODY_HOOK = 0x004217AA
BODY_ORIG = bytes.fromhex("b968936402")
BODY_BACK = 0x004217AF
# v15: LATE hook after the decor/lamp pass (0x004217d2..0x004217eb) and before the grass:
LATE_HOOK = 0x004217F0         # mov ecx, 0x263f328 (5 bytes)
LATE_ORIG = bytes.fromhex("b928f36302")
LATE_BACK = 0x004217F5
NATURE = 0x0263F328            # nature fields: trees [+0xca4+i*4] x [+0x1924] (chunk +0x14), rocks [+0x1930] x [+0x25b0] (chunk +8)
TEXTAB = 0x0259D66C            # renderer texture table: texture = [TEXTAB + number*4] (0x004101a0)
CARDRAW_MAX = 0x0058F678       # the game's own body draw distance (cardraw: 150)
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
    DARR=0x200, CARR=0x240,          # v9: room for 16 cars (were 0xC0/0xE0 = 8 max)
    VSC=0x100, PSC=0x300)
DATA_LAYOUT["NAME"] = DATA_LAYOUT["PSC"] + 16 * NPSC + 0x10
DATA_LAYOUT["OBJS"] = DATA_LAYOUT["NAME"] + 0x20
DATA_LAYOUT["LAMPUP"] = (DATA_LAYOUT["OBJS"] + 4 * MAX_OBJS + 15) & ~15   # (0, LAMP_UP, 0, 0) model offset
DATA_LAYOUT["RDRAWN"] = DATA_LAYOUT["LAMPUP"] + 16                       # road-layer part draws
DATA_LAYOUT["RMASK"] = DATA_LAYOUT["RDRAWN"] + 4                         # which road layers get lit
DATA_LAYOUT["DBIAS"] = DATA_LAYOUT["RDRAWN"] + 8                         # D3DRS_DEPTHBIAS (float bits)
DATA_LAYOUT["SBIAS"] = DATA_LAYOUT["RDRAWN"] + 12                        # D3DRS_SLOPESCALEDEPTHBIAS
DATA_LAYOUT["MAXCARS"] = DATA_LAYOUT["RDRAWN"] + 16                      # player slider: lit cars 1..N_CARS
DATA_LAYOUT["OPSC"] = DATA_LAYOUT["MAXCARS"] + 16                        # objects' c32..c33 (2 regs)
DATA_LAYOUT["ODIST"] = DATA_LAYOUT["OPSC"] + 32                          # v13: nearest-first object keys
DATA_LAYOUT["BTMP"] = (DATA_LAYOUT["ODIST"] + 4 * MAX_OBJS + 15) & ~15     # v14 body pass: self-light temp
DATA_LAYOUT["BDRAWN"] = DATA_LAYOUT["BTMP"] + 16                          # body draws (counter)
DATA_LAYOUT["BSELF"] = DATA_LAYOUT["BTMP"] + 20                           # slot of the car being drawn, -1
DATA_LAYOUT["BRAD"] = DATA_LAYOUT["BTMP"] + 24                            # car radius added to the reach
DATA_LAYOUT["BPSC"] = DATA_LAYOUT["BTMP"] + 32                           # v14c car bodies own c32..c33
DATA_LAYOUT["BADD"] = DATA_LAYOUT["BPSC"] + 80     # v14e (G, G, G, BODY_ADD_K): paint-tinted additive light
DATA_LAYOUT["BCOL"] = DATA_LAYOUT["BADD"] + 16     # per car: paint * G, BODY_ADD_K -> c33 in the additive pass
LATE_MAX, NAT_MAX = 96, 48       # v15b: 48 NEAREST trees/rocks (player chose it for FPS: 128 -> race 30 FPS)
DATA_LAYOUT["LOBJS"] = DATA_LAYOUT["BCOL"] + 16                         # v15 late: decor/lamp objects
DATA_LAYOUT["NAT"] = DATA_LAYOUT["LOBJS"] + 4 * LATE_MAX                # v15 late: trees + rocks
DATA_LAYOUT["NLOBJ"] = DATA_LAYOUT["NAT"] + 4 * NAT_MAX
DATA_LAYOUT["NNAT"] = DATA_LAYOUT["NLOBJ"] + 4
DATA_LAYOUT["LDRAWN"] = DATA_LAYOUT["NLOBJ"] + 8
DATA_LAYOUT["NDRAWN"] = DATA_LAYOUT["NLOBJ"] + 12
DATA_LAYOUT["NFIELD"] = DATA_LAYOUT["NLOBJ"] + 16
DATA_LAYOUT["NJ"] = DATA_LAYOUT["NLOBJ"] + 20
DATA_LAYOUT["OLDTEX1"] = DATA_LAYOUT["NLOBJ"] + 24
DATA_LAYOUT["ALPHAON"] = (DATA_LAYOUT["NLOBJ"] + 32 + 15) & ~15        # c37 for trees/rocks: (1, -0.5)
DATA_LAYOUT["NATD"] = DATA_LAYOUT["ALPHAON"] + 16                       # v15b nearest-first keys
DATA_LAYOUT["DATA_END"] = DATA_LAYOUT["NATD"] + 4 * NAT_MAX


def data_init(rng=RANGE, maxd=MAX_DIST, fade_near=FADE_NEAR, ramp=NIGHT_RAMP, gain=GAIN, cars=N_CARS):
    """Bytes of the static part of the data block (dynamic fields zero). gain/cars = what the live
    `hllive.py set gain|cars` sliders write (land, objects and bodies keep their shares of the gain)."""
    A = DATA_LAYOUT
    b = bytearray(A["DATA_END"])

    def put(k, fmt, *v):
        struct.pack_into(fmt, b, A[k], *v)
    put("HALFV", "<4f", 0.5, 0.5, 0.5, 0.5)
    put("MONEV", "<4f", -1.0, -1.0, -1.0, 0.0)
    put("BIGV", "<4f", 1e6, 1e6, 1e6, 0.0)
    put("LAMPUP", "<4f", 0.0, LAMP_UP, 0.0, 0.0)
    put("RMASK", "<I", ROAD_MASK)
    put("MAXCARS", "<I", cars)
    put("OPSC", "<8f", *obj_consts(gain=gain))
    put("BRAD", "<f", 3.0)
    put("BPSC", "<20f", *body_consts())
    put("BADD", "<4f", GAIN, GAIN, GAIN, BODY_ADD_K)
    put("ALPHAON", "<4f", 1.0, -0.5, 0.0, 0.0)
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
    struct.pack_into("<24f", b, A["PSC"] + 16 * CS, *ps_static_consts(rng, gain=gain))
    if gain != GAIN:             # car bodies: BODY_GAIN x gain, like `set gain` (BADD stays, as live)
        struct.pack_into("<3f", b, A["BPSC"] + 16, *(x * gain * BODY_GAIN for x in COLOUR))
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
    jbe nonight
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
    movss xmm5, xmm3
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0xa18]
{near_o}
    movups xmm1, xmmword ptr [{S('PSC')}]
    subps xmm1, xmm4
    mulps xmm1, xmm1
    movaps xmm0, xmm1
    shufps xmm0, xmm0, 0x55
    movaps xmm2, xmm1
    shufps xmm2, xmm2, 0xaa
    addss xmm1, xmm0
    addss xmm1, xmm2
    sqrtss xmm1, xmm1
    subss xmm1, xmm5
    maxss xmm1, dword ptr [{S('ZERO')}]
    mov edx, edi
    cmp edx, {MAX_OBJS}
    jb oins
    comiss xmm1, dword ptr [{A['ODIST'] + 4 * (MAX_OBJS - 1):#x}]
    jae ol
    mov edx, {MAX_OBJS - 1}
oins:
    test edx, edx
    je oput
    comiss xmm1, dword ptr [edx*4+{A['ODIST'] - 4:#x}]
    jae oput
    movss xmm2, dword ptr [edx*4+{A['ODIST'] - 4:#x}]
    movss dword ptr [edx*4+{S('ODIST')}], xmm2
    mov eax, dword ptr [edx*4+{A['OBJS'] - 4:#x}]
    mov dword ptr [edx*4+{S('OBJS')}], eax
    dec edx
    jmp oins
oput:
    movss dword ptr [edx*4+{S('ODIST')}], xmm1
    mov dword ptr [edx*4+{S('OBJS')}], ecx
    cmp edi, {MAX_OBJS}
    jae ol
    inc edi
    jmp ol
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
    cmp edi, {PASSES + 1}
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
    jmp done
nonight:
    mov dword ptr [{S('NUM')}], 0
done:
    popad
back:
    cmp dword ptr [0x12d0c9c], 0
    jmp {HOOK_BACK:#x}
"""


if __name__ == "__main__":
    print(technique_text())


LOST_HOOK = 0x0040C6A4          # inside the renderer's invalidate 0x0040c6a0 (runs before every Reset)
LOST_ORIG = bytes.fromhex("b980796402")   # mov ecx, 0x2647980
LOST_BACK = 0x0040C6A9


def lost_cave_src(data_va):
    """Release our separate effect before a device reset (a live effect during a Reset crashed the game,
    2026-10-05); STATE 0 makes the main cave recreate it on the next night frame. The cookie texture is
    D3DPOOL_MANAGED and survives resets. Same code as hllive.py's lost_src."""
    A = {k: data_va + v for k, v in DATA_LAYOUT.items()}
    return f"""
    pushad
    mov ecx, dword ptr [{A['EFF']:#x}]
    test ecx, ecx
    je skip
    mov dword ptr [{A['EFF']:#x}], 0
    mov dword ptr [{A['STATE']:#x}], 0
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+8]
skip:
    popad
    mov ecx, 0x2647980
    jmp {LOST_BACK:#x}
"""


def body_cave_src(data_va):
    """v14: redraw every nearby visible CAR BODY through techHeadlights right after the game drew the
    bodies (0x00442080). Same data as 0x004355b0: world = the car itself (+0), VB [+0xc90] stride 0x24
    (FVF 0x152), IB [+0xc94], DrawIndexedPrimitive(4, [+0xca4], 0, [+0xcb8], [+0xccc], [+0xce0]); same
    checks (active +0xa34, +0x1e80, visible +0xa28, distance +0xa24 <= cardraw, not the cockpit car).
    Objects' gentler c32..c33 (OPSC). A lit car's OWN slot gets intensity 0 while its body is drawn.
    v14b: the last (ADDITIVE) pass is skipped on car paint - its flat bluish-white greyed every car
    (player 2026-10-10 "why the car grey now?"); the multiply passes keep the paint's own colour."""
    A = {k: data_va + v for k, v in DATA_LAYOUT.items()}
    S = lambda k: f"{A[k]:#x}"
    near_b = _near("bnt", "bcl").replace("{S('NUM')}", S("NUM")).replace("{S('PSC')}", S("PSC"))
    return f"""
    pushad
    cmp dword ptr [{S('STATE')}], 1
    jne bdone
    cmp dword ptr [{S('EFF')}], 0
    je bdone
    cmp dword ptr [{S('NUM')}], 0
    je bdone
    cmp dword ptr [0x12d0c9c], 0
    jne bdone
    mov ebx, dword ptr [{DEVICE:#x}]
    mov ecx, dword ptr [{S('EFF')}]
    push 0
    push {S('NPASS')}
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x100]
    test eax, eax
    jl bdone
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
    push 8
    push {A['VSC'] + 64:#x}
    push 4
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    push 0x152
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x164]
    xor edi, edi
bpl:
    cmp edi, dword ptr [{S('NPASS')}]
    jge bpend
    mov ecx, dword ptr [{S('EFF')}]
    push edi
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x104]
    push {NPSC}
    push {S('PSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    push 5
    push {S('BPSC')}
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
    xor ebp, ebp
bcl:
    mov ecx, {MGR:#x}
    cmp ebp, dword ptr [ecx+0x128]
    jge bnext
    cmp ebp, 64
    jge bnext
    mov esi, dword ptr [ecx+ebp*4+0x28]
    inc ebp
    test esi, esi
    je bcl
    cmp dword ptr [esi+0xa34], 0
    je bcl
    cmp dword ptr [esi+0x1e80], 0
    je bcl
    cmp dword ptr [esi+0xa28], 0
    je bcl
    cmp dword ptr [esi+0xce0], 0
    je bcl
    movss xmm0, dword ptr [esi+0xa24]
    comiss xmm0, dword ptr [{CARDRAW_MAX:#x}]
    ja bcl
    movss xmm0, dword ptr [esi+0xd00]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe bcl
    mov eax, dword ptr [0x2610010]
    cmp dword ptr [eax+0x9ef0], esi
    jne bnotc
    cmp dword ptr [eax+0x9ed0], 1
    je bcl
bnotc:
    movups xmm4, xmmword ptr [esi+0x30]
    movss xmm3, dword ptr [{S('RANGEF')}]
    addss xmm3, dword ptr [{S('BRAD')}]
    mulss xmm3, xmm3
{near_b}
    cmp edi, {PASSES}
    jne bnocol
    movss xmm0, dword ptr [esi+0xe5c]
    mulss xmm0, dword ptr [{S('BADD')}]
    movss dword ptr [{S('BCOL')}], xmm0
    movss xmm0, dword ptr [esi+0xe60]
    mulss xmm0, dword ptr [{A['BADD'] + 4:#x}]
    movss dword ptr [{A['BCOL'] + 4:#x}], xmm0
    movss xmm0, dword ptr [esi+0xe64]
    mulss xmm0, dword ptr [{A['BADD'] + 8:#x}]
    movss dword ptr [{A['BCOL'] + 8:#x}], xmm0
    mov eax, dword ptr [{A['BADD'] + 12:#x}]
    mov dword ptr [{A['BCOL'] + 12:#x}], eax
    push 1
    push {S('BCOL')}
    push {CS + 1}
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
bnocol:
    mov dword ptr [{S('BSELF')}], -1
    xor edx, edx
bself:
    cmp edx, dword ptr [{S('NUM')}]
    jge bdraw
    cmp dword ptr [edx*4+{S('CARR')}], esi
    je bisself
    inc edx
    jmp bself
bisself:
    mov dword ptr [{S('BSELF')}], edx
    mov eax, edx
    shl eax, 6
    add eax, {S('PSC')}
    movups xmm0, xmmword ptr [eax]
    movups xmmword ptr [{S('BTMP')}], xmm0
    mov dword ptr [{A['BTMP'] + 12:#x}], 0
    lea eax, [edx*4]
    push 1
    push {S('BTMP')}
    push eax
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
bdraw:
    push 4
    push esi
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    push 0x24
    push 0
    push dword ptr [esi+0xc90]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x190]
    push dword ptr [esi+0xc94]
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1a0]
    push dword ptr [esi+0xce0]
    push dword ptr [esi+0xccc]
    push dword ptr [esi+0xcb8]
    push 0
    push dword ptr [esi+0xca4]
    push 4
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x148]
    inc dword ptr [{S('BDRAWN')}]
    mov edx, dword ptr [{S('BSELF')}]
    cmp edx, -1
    je bcl
    mov eax, edx
    shl eax, 6
    add eax, {S('PSC')}
    lea ecx, [edx*4]
    push 1
    push eax
    push ecx
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    jmp bcl
bnext:
    inc edi
    jmp bpl
bpend:
    mov ecx, dword ptr [{S('EFF')}]
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x108]
    push dword ptr [{S('OLDTEX')}]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    mov ecx, dword ptr [{S('OLDTEX')}]
    test ecx, ecx
    je bdone
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+8]
bdone:
    popad
    mov ecx, {MGR:#x}
    jmp {BODY_BACK:#x}
"""


def late_cave_src(data_va):
    """v15 LATE pass (after the game drew decor + lamp posts, hook 0x004217f0): relight LOOSE OBJECTS and
    LAMP POSTS (static classes 0x600 with sub-parts - drawn AFTER the early pass, so the game painted over
    the light) and TREES + ROCKS (nature fields; part 0 only - their +0xc60 is NOT a sub-part count; their
    own texture on stage 1 for the leaf cut-out, c37 = (1, -0.5)). Land passes only (P0..P3). Trees' fade
    +0x86c is 0 - not checked."""
    A = {k: data_va + v for k, v in DATA_LAYOUT.items()}
    S = lambda k: f"{A[k]:#x}"

    def near(label, fail):
        return _near(label, fail).replace("{S('NUM')}", S("NUM")).replace("{S('PSC')}", S("PSC"))

    nat = ""
    for li, (lst, cnt, chunk) in enumerate(((0xCA4, 0x1924, 0x14), (0x1930, 0x25B0, 0x8))):
        nat += f"""
    xor esi, esi
nfl{li}:
    cmp esi, dword ptr [{NATURE + cnt:#x}]
    jge nfd{li}
    mov edx, dword ptr [esi*4+{NATURE + lst:#x}]
    inc esi
    test edx, edx
    je nfl{li}
    mov eax, dword ptr [edx+{chunk:#x}]
    test eax, eax
    je nfl{li}
    cmp dword ptr [eax+0x110], 0
    je nfl{li}
    cmp dword ptr [edx+4], 0
    je nfl{li}
    mov dword ptr [{S('NFIELD')}], edx
    mov dword ptr [{S('NJ')}], 0
nol{li}:
    mov edx, dword ptr [{S('NFIELD')}]
    mov eax, dword ptr [{S('NJ')}]
    cmp eax, dword ptr [edx+4]
    jae nfl{li}
    inc dword ptr [{S('NJ')}]
    mov ecx, dword ptr [edx]
    mov ecx, dword ptr [ecx+eax*4]
    test ecx, ecx
    je nol{li}
    cmp dword ptr [ecx+0xa28], 0
    je nol{li}
    cmp dword ptr [ecx+0xa34], 0
    je nol{li}
    mov eax, dword ptr [ecx+0x8a4]
    test eax, eax
    je nol{li}
    movss xmm3, dword ptr [eax+0x378]
    mulss xmm3, dword ptr [{S('HALF')}]
    maxss xmm3, dword ptr [ecx+0x8b4]
    movss xmm5, xmm3
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0xa18]
{near(f"nnt{li}", f"nol{li}")}
    movups xmm1, xmmword ptr [{S('PSC')}]
    subps xmm1, xmm4
    mulps xmm1, xmm1
    movaps xmm0, xmm1
    shufps xmm0, xmm0, 0x55
    movaps xmm2, xmm1
    shufps xmm2, xmm2, 0xaa
    addss xmm1, xmm0
    addss xmm1, xmm2
    sqrtss xmm1, xmm1
    subss xmm1, xmm5
    maxss xmm1, dword ptr [{S('ZERO')}]
    mov edx, edi
    cmp edx, {NAT_MAX}
    jb nins{li}
    comiss xmm1, dword ptr [{A['NATD'] + 4 * (NAT_MAX - 1):#x}]
    jae nol{li}
    mov edx, {NAT_MAX - 1}
nins{li}:
    test edx, edx
    je nput{li}
    comiss xmm1, dword ptr [edx*4+{A['NATD'] - 4:#x}]
    jae nput{li}
    movss xmm2, dword ptr [edx*4+{A['NATD'] - 4:#x}]
    movss dword ptr [edx*4+{S('NATD')}], xmm2
    mov eax, dword ptr [edx*4+{A['NAT'] - 4:#x}]
    mov dword ptr [edx*4+{S('NAT')}], eax
    dec edx
    jmp nins{li}
nput{li}:
    movss dword ptr [edx*4+{S('NATD')}], xmm1
    mov dword ptr [edx*4+{S('NAT')}], ecx
    cmp edi, {NAT_MAX}
    jae nol{li}
    inc edi
    jmp nol{li}
nfd{li}:"""
    return f"""
    pushad
    cmp dword ptr [{S('STATE')}], 1
    jne ldone
    cmp dword ptr [{S('EFF')}], 0
    je ldone
    cmp dword ptr [{S('NUM')}], 0
    je ldone
    cmp dword ptr [0x12d0c9c], 0
    jne ldone
    xor esi, esi
    xor edi, edi
lol:
    cmp esi, dword ptr [{STATICS + 0x5000:#x}]
    jge lodone
    mov ecx, dword ptr [esi*4+{STATICS:#x}]
    inc esi
    test ecx, ecx
    je lol
    test dword ptr [ecx+0x9d0], {LATE_MASK:#x}
    je lol
    cmp dword ptr [ecx+0xa34], 0
    je lol
    movss xmm0, dword ptr [ecx+0x86c]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe lol
    mov eax, dword ptr [ecx+0x8a4]
    test eax, eax
    je lol
    test byte ptr [eax+0x10c], 0x10
    je lol
    movss xmm3, dword ptr [eax+0x378]
    mulss xmm3, dword ptr [{S('HALF')}]
    maxss xmm3, dword ptr [ecx+0x8b4]
    addss xmm3, dword ptr [{S('RANGEF')}]
    mulss xmm3, xmm3
    movups xmm4, xmmword ptr [ecx+0xa18]
{near("lnt", "lol")}
    mov dword ptr [edi*4+{S('LOBJS')}], ecx
    inc edi
    cmp edi, {LATE_MAX}
    jb lol
lodone:
    mov dword ptr [{S('NLOBJ')}], edi
    xor edi, edi
{nat}
nfdone:
    mov dword ptr [{S('NNAT')}], edi
    mov eax, dword ptr [{S('NLOBJ')}]
    or eax, edi
    je ldone
    mov ebx, dword ptr [{DEVICE:#x}]
    mov ecx, dword ptr [{S('EFF')}]
    push 0
    push {S('NPASS')}
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x100]
    test eax, eax
    jl ldone
    mov dword ptr [{S('OLDTEX')}], 0
    push {S('OLDTEX')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x100]
    mov dword ptr [{S('OLDTEX1')}], 0
    push {S('OLDTEX1')}
    push 1
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x100]
    push dword ptr [{S('TEX')}]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    push 8
    push {A['VSC'] + 64:#x}
    push 4
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x178]
    xor edi, edi
lpl:
    cmp edi, {PASSES + 1}
    jge lpend
    mov ecx, dword ptr [{S('EFF')}]
    push edi
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x104]
    push {NPSC}
    push {S('PSC')}
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    push 2
    push {S('OPSC')}
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
    xor esi, esi
lob:
    cmp esi, dword ptr [{S('NLOBJ')}]
    jge lobdone
    mov ecx, dword ptr [esi*4+{S('LOBJS')}]
    inc esi
    push ecx
    call ldraw
    pop ecx
    mov eax, dword ptr [ecx+0xc60]
    test eax, eax
    je lob
    push 0
lsub:
    mov eax, dword ptr [esp]
    cmp eax, dword ptr [ecx+0xc60]
    jae lsubdone
    inc dword ptr [esp]
    mov edx, dword ptr [ecx+0xc64]
    mov edx, dword ptr [edx+eax*4]
    test edx, edx
    je lsub
    movss xmm0, dword ptr [edx+0x86c]
    comiss xmm0, dword ptr [{S('ZERO')}]
    jbe lsub
    push ecx
    push edx
    call ldraw
    pop edx
    pop ecx
    jmp lsub
lsubdone:
    add esp, 4
    jmp lob
lobdone:
    push 1
    push {S('ALPHAON')}
    push {CS + 5}
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x1b4]
    xor esi, esi
lnat:
    cmp esi, dword ptr [{S('NNAT')}]
    jge lnatdone
    mov ecx, dword ptr [esi*4+{S('NAT')}]
    inc esi
    xor edx, edx
    mov eax, dword ptr [ecx+0x838]
    cmp eax, -1
    je lnotex
    cmp eax, 0x10000
    jae lnotex
    mov edx, dword ptr [eax*4+{TEXTAB:#x}]
lnotex:
    push ecx
    push edx
    push 1
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    pop ecx
    push ecx
    call ldraw
    pop ecx
    inc dword ptr [{S('NDRAWN')}]
    jmp lnat
lnatdone:
    inc edi
    jmp lpl
ldraw:
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
    inc dword ptr [{S('LDRAWN')}]
    ret
lpend:
    mov ecx, dword ptr [{S('EFF')}]
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+0x108]
    push dword ptr [{S('OLDTEX')}]
    push 0
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    push dword ptr [{S('OLDTEX1')}]
    push 1
    push ebx
    mov eax, dword ptr [ebx]
    call dword ptr [eax+0x104]
    mov ecx, dword ptr [{S('OLDTEX')}]
    test ecx, ecx
    je lrel1
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+8]
lrel1:
    mov ecx, dword ptr [{S('OLDTEX1')}]
    test ecx, ecx
    je ldone
    push ecx
    mov edx, dword ptr [ecx]
    call dword ptr [edx+8]
ldone:
    popad
    mov ecx, {NATURE:#x}
    jmp {LATE_BACK:#x}
"""
