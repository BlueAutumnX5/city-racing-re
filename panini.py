r"""panini.py - the Panini projection for City Racing: shader text + a float64 reference model.

The game renders one ordinary (rectilinear) view; `racemod` extra `panini` widens that camera to
PANINI_FOV horizontally and then, after the 3D world and before the HUD, copies the screen into a
full-resolution texture and redraws it through `techPanini` (this file) - so the HUD is never warped.

Panini (Sharpless, Ballard, German 2010): a ray with azimuth phi and cylindrical height h lands at
    S = (d + 1) / (d + cos phi),   X = S sin phi,   Y = S h
Vertical lines stay vertical (X depends on phi only); d = 1 is "standard Panini", d = 0 is
rectilinear. The inverse, used per output pixel, has a closed form (the paper's eq. 7) that
simplifies here to
    k = X^2 / (d + 1)^2,   clon = (-k d + sqrt(1 + k (1 - d^2))) / (k + 1)   ( = cos phi )
and the rectilinear source point is (X, Y) * F with F = G (1 + d / clon), G = Xe / (tanE (d+1)).
The SAME factor F scales x and y, and it depends on X only.

A neat property keeps the camera simple: a rectilinear render with the same horizontal FOV and the
same aspect covers the Panini image's corners exactly, so no overscan is needed.

Coordinates in the shader are texture-space offsets from the centre: cx = u - 0.5 in [-0.5, 0.5];
source u = 0.5 + cx * F(cx), source v = 0.5 + (v - 0.5) * F(cx).

Edges are squeezed (2:1 at 120 deg, 5.8:1 at 160 deg, d = 1): N bilinear taps (N = the edge
squeeze rounded up, 2..8) spread evenly over the pixel's source footprint stop them shimmering;
where the image is magnified (the centre) the taps fall inside one texel = a plain bilinear read.
The centre magnification (1.5x at 120, 3.4x at 160) is the real limit of one rectilinear render:
the only cure is rendering the 3D world at a higher resolution before the warp.
"""
import math

PANINI_FOV = 160.0      # degrees, HORIZONTAL, of the final image (stock game: 113 deg, squeezed)
                        # 120 (2026-09-25): "looks zoomed in" + "jagged, like 1366x768" (centre
                        # upscaled 1.5x = 1280x720 worth of pixels) -> player asked 180 (impossible
                        # with one rectilinear render: tan 90 = inf) -> chose 160 (2026-09-26)
PANINI_VFOV = 100.0     # degrees, VERTICAL at the centre of a 16:9 screen (2026-09-26, player's choice
                        # after the table: d=1 gave 86.7; 100 = sharper centre, sides ~1.5x wide).
                        # With the horizontal fixed, the Panini strength d sets the height, so d is
                        # DERIVED from this (0.544 at 160/100). None = standard Panini (d = 1).


def d_for_vertical(fov, vfov, aspect=16 / 9):
    """The Panini d whose image, `fov` wide, is `vfov` tall at the centre of an `aspect` screen:
    the centre height is 2 atan(Xe / aspect), Xe = (d+1) sin(phi) / (d + cos(phi)) falls with d."""
    phi = math.radians(fov / 2)
    target = math.tan(math.radians(vfov / 2)) * aspect
    xe = lambda d: (d + 1) * math.sin(phi) / (d + math.cos(phi))
    if not (xe(1.0) <= target <= math.tan(phi)):
        raise ValueError(f"{vfov} deg tall is not reachable at {fov} deg wide with 0 <= d <= 1 "
                         f"({2 * math.degrees(math.atan(xe(1.0) / aspect)):.1f}.."
                         f"{2 * math.degrees(math.atan(math.tan(phi) / aspect)):.1f})")
    lo, hi = 0.0, 1.0
    for _ in range(80):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if xe(m) > target else (lo, m)
    return (lo + hi) / 2


PANINI_D = 1.0 if PANINI_VFOV is None else d_for_vertical(PANINI_FOV, PANINI_VFOV)
                        # 1 = standard Panini; 0 = rectilinear; keep 0 < d <= 1

RENDER_SCALE = 2.0              # supersampling: the 3D world renders at backbuffer x this
                                 # (3840x2160 on a 1080p screen). 2026-09-26: 1440p first (4/3),
                                 # player: "still weak for this projection" + FPS unchanged
                                 # (CPU-bound) -> 2x. 1.0 = native. Linear factor, both axes.

CHASE_DISTANCE = 0.84          # chase camera distance vs stock (all views that use the chase formula).
                                 # 2026-09-26: at 100 deg tall the car looked "a bit far"; 0.84 = the
                                 # car's on-screen size in the original game (453 vs 540 px/rad).

TECH_NAME = "techPanini"

# ---- the player's settings (2026-09-27, control panel crpanel.py / `racemod.py setup`) ---------
# The four values above are the DEFAULTS. The saved settings live in racemod_state.json under
# "panini" ({"fov", "vfov", "scale", "chase"}) and are applied here at import, so racemod, the
# checkers and verify_install all build the same patch. Limits = what has been proven: the warp
# on the GPU at 120/140/160/170 deg (paninitest.py), supersampling 1.0 / 1.333 / 2.0, and the
# vertical FOV between standard Panini (d = 1) and nearly rectilinear (d = 0.05); supersampling
# 1.0 / 1.333 / 2.0 in play, 4.0 on the GPU.
DEFAULTS = dict(fov=PANINI_FOV, vfov=PANINI_VFOV, scale=RENDER_SCALE, chase=CHASE_DISTANCE)
LIMITS = dict(fov=(120.0, 170.0), scale=(1.0, 4.0), chase=(0.5, 1.2))
# scale up to 4 (player 2026-09-27): GPU-proven at 160 and 170 deg (paninitest, 7680x4320 source,
# 0.0008 px), 265 MB of VRAM at 1080p; 180 deg stays impossible (one flat render: tan 90 = inf).
D_MIN = 0.05


def vfov_range(fov, aspect=16 / 9):
    """(lowest, highest) vertical FOV at the centre reachable at `fov` wide, in whole 0.1 deg."""
    phi = math.radians(fov / 2)
    h = lambda d: 2 * math.degrees(math.atan((d + 1) * math.sin(phi) / (d + math.cos(phi)) / aspect))
    return math.ceil(h(1.0) * 10) / 10, math.floor(h(D_MIN) * 10) / 10


def configure(fov=None, vfov=None, scale=None, chase=None):
    """Set the four settings (None = default) after checking them; raises ValueError."""
    global PANINI_FOV, PANINI_VFOV, PANINI_D, RENDER_SCALE, CHASE_DISTANCE
    fov = float(DEFAULTS["fov"] if fov is None else fov)
    vfov = DEFAULTS["vfov"] if vfov is None else float(vfov)
    scale = float(DEFAULTS["scale"] if scale is None else scale)
    chase = float(DEFAULTS["chase"] if chase is None else chase)
    for name, v in (("fov", fov), ("scale", scale), ("chase", chase)):
        lo, hi = LIMITS[name]
        if not lo <= v <= hi:
            raise ValueError(f"Panini {name} {v:g} is outside {lo:g}..{hi:g}")
    lo, hi = vfov_range(fov)
    if not lo <= vfov <= hi:
        raise ValueError(f"Panini vertical FOV {vfov:g} is outside {lo:g}..{hi:g} at {fov:g} wide")
    d = d_for_vertical(fov, vfov)
    PANINI_FOV, PANINI_VFOV, PANINI_D, RENDER_SCALE, CHASE_DISTANCE = fov, vfov, d, scale, chase


def settings():
    return dict(fov=PANINI_FOV, vfov=PANINI_VFOV, scale=RENDER_SCALE, chase=CHASE_DISTANCE)


# ---- sharpness maths for the control panel's calculator (player 2026-09-27: "a calculator ... so I
# can get a high resolution middle image"). At the centre the source point is (X, Y) * F(0) with
# F(0) = Xe / tanE, so the middle of the flat render is ENLARGED by tanE / Xe on screen; with
# supersampling ss the render has ss times the pixels, so the middle is enlarged tanE / (Xe ss):
# above 1 it is soft (fewer rendered pixels than screen pixels), at or below 1 it is pin-sharp.
def centre_ratio(fov, vfov, aspect=16 / 9):
    """Supersampling needed for a 1:1 (pin-sharp) middle at this width/height: tanE / Xe."""
    d = d_for_vertical(fov, vfov, aspect)
    p = params(fov, d)
    return p["tan_e"] / p["xe"]


def vfov_for_ratio(fov, ratio, aspect=16 / 9):
    """The height (vertical FOV) whose middle is pin-sharp at supersampling `ratio`, or None when no
    height in the allowed range (d 0.05..1) does it."""
    phi = math.radians(fov / 2)
    xe = lambda d: (d + 1) * math.sin(phi) / (d + math.cos(phi))
    target = math.tan(phi) / ratio
    if not xe(1.0) <= target <= xe(D_MIN):
        return None
    return 2 * math.degrees(math.atan(target / aspect))


def _saved():
    import json, os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "racemod_state.json")) as f:
            return dict(json.load(f).get("panini") or {})
    except Exception:
        return {}


try:
    configure(**{k: v for k, v in _saved().items() if k in DEFAULTS})
except (ValueError, TypeError) as _e:
    print(f"panini: saved settings rejected ({_e}) - using the defaults")
    configure()


def params(fov=None, d=None):
    fov = PANINI_FOV if fov is None else fov
    d = PANINI_D if d is None else d
    if not (0.0 < d <= 1.0):
        raise ValueError("PANINI_D must be in (0, 1]: above 1 the closed-form inverse can hit sqrt(<0)")
    if not (60.0 <= fov <= 170.0):
        raise ValueError("PANINI_FOV must be 60..170 degrees")
    phi = math.radians(fov / 2)
    tan_e = math.tan(phi)
    xe = (d + 1) * math.sin(phi) / (d + math.cos(phi))       # Panini half-width at the edge azimuth
    return dict(fov=fov, d=d, phi=phi, tan_e=tan_e, xe=xe,
                inv2=1.0 / (d + 1) ** 2, g=xe / (tan_e * (d + 1)))


def factor(cx, p):
    """F(cx) in float64 - the reference for the shader."""
    x = 2.0 * cx * p["xe"]
    k = x * x * p["inv2"]
    d = p["d"]
    clon = (-k * d + math.sqrt(1.0 + k * (1.0 - d * d))) / (k + 1.0)
    return p["g"] * (1.0 + d / clon)


def edge_squeeze(p):
    """Source pixels per output pixel, horizontally, at the screen edge (the worst case)."""
    e = 1e-6
    return (0.5 * factor(0.5, p) - (0.5 - e) * factor(0.5 - e, p)) / e


def taps(p, ss=None):
    """Bilinear taps per pixel: enough to cover the edge footprint ~1 SOURCE texel apart (the
    source is RENDER_SCALE times denser than the screen). ps_2_0 has 32 texture slots; 8 is the cap."""
    ss = RENDER_SCALE if ss is None else ss
    return max(2, min(8, math.ceil(edge_squeeze(p) * ss - 1e-9)))


def tap_offsets(n):
    return [(i + 0.5) / n - 0.5 for i in range(n)]


def model(u, v, w_px, p, ss=None):
    """Where output texcoord (u, v) samples the source: ([u of each tap], v). The taps sit evenly
    across the pixel's source footprint [left edge, right edge]. w_px = OUTPUT width."""
    cx = u - 0.5
    f = factor(cx, p)
    su = 0.5 + cx * f
    sv = 0.5 + (v - 0.5) * f
    h = 0.5 / w_px
    left = (cx - h) * factor(cx - h, p)
    right = (cx + h) * factor(cx + h, p)
    return [su + (right - left) * o for o in tap_offsets(taps(p, ss))], sv


def _f(x):
    return f"{x:.9g}"


def technique_text(fov=None, d=None, ss=None):
    """The technique appended to RenderTechniques_20.dat in memory. Same dialect as the game's own
    techGlowScreen: vs_1_1 / ps_2_0 asm blocks, legacy state names. c0 (VS) = (-1/W, 1/H, 0, 0),
    set by the pass code: shifts the quad half a pixel (D3D9 texel/pixel centres) and reaches the
    pixel shader as t1 (the pixel width for the footprint)."""
    fov = PANINI_FOV if fov is None else fov        # resolved now: the settings can change after import
    d = PANINI_D if d is None else d
    p = params(fov, d)
    c0 = ", ".join(_f(x) for x in (0.5, 2 * p["xe"], p["inv2"], 0.0))
    c1 = ", ".join(_f(x) for x in (1.0, -d, d, p["g"]))
    n = taps(p, ss)
    c3 =", ".join(_f(x) for x in (0.0, 1 - d * d, 1.0, 1.0 / n))    # ps_2_0: ONE constant register per instruction
    offs = tap_offsets(n) + [0.0] * (8 - n)
    c4 = ", ".join(_f(x) for x in offs[:4])
    c5 = ", ".join(_f(x) for x in offs[4:])
    t = "\t"
    # ps_2_0 allows dependent reads 3 deep, and re-using a register as a texld destination counts
    # as another level (X5775). So: every tap's coordinate in its OWN register, then all the texlds
    # in one block (each 1st-order), then the sum. Free at that point: all but r2 (u), r7 (footprint
    # width) and r8 (v).
    comp = "xyzw"
    regs = ["r9", "r10", "r11", "r0", "r1", "r3", "r4", "r5"][:n]
    tap_lines = []
    for i, r in enumerate(regs):
        tap_lines.append(f"mad {r}.x, r7.x, c{4 + i // 4}.{comp[i % 4]}, r2.y")
        tap_lines.append(f"mov {r}.y, r8.y")
    tap_lines += [f"texld {r}, {r}, s0" for r in regs]
    tap_lines += [f"add r9, r9, {r}" for r in regs[1:]]
    tap_code = "".join(f"{t}{t}{t}{l}\n" for l in tap_lines)
    lines = f"""
/////////////////////////////////////////////////////////////////
// Panini projection (racemod extra `panini`): {fov:g} deg horizontal, d = {d:g}
/////////////////////////////////////////////////////////////////
technique {TECH_NAME}
{{
{t}pass P0
{t}{{
{t}{t}VertexShader=
{t}{t}asm
{t}{t}{{
{t}{t}{t}vs_1_1
{t}{t}{t}def c1, 0, 1, 0, 0
{t}{t}{t}dcl_position v0
{t}{t}{t}dcl_texcoord v1
{t}{t}{t}slt r0.xy, -v0, v0
{t}{t}{t}slt r1.xy, v0, -v0
{t}{t}{t}add r0.xy, r0, -r1
{t}{t}{t}add oPos.xy, r0, c0
{t}{t}{t}mov oPos.zw, c1.xyxy
{t}{t}{t}mov oT0.xy, v1
{t}{t}{t}mov oT1.xy, c0
{t}{t}}};
{t}{t}PixelShader=
{t}{t}asm
{t}{t}{{
{t}{t}{t}ps_2_0
{t}{t}{t}def c0, {c0}
{t}{t}{t}def c1, {c1}
{t}{t}{t}def c2, 0, -1, 1, 0
{t}{t}{t}def c3, {c3}
{t}{t}{t}def c4, {c4}
{t}{t}{t}def c5, {c5}
{t}{t}{t}dcl t0.xy
{t}{t}{t}dcl t1.xy
{t}{t}{t}dcl_2d s0
{t}{t}{t}abs r0.x, t1.x
{t}{t}{t}mul r0.y, r0.x, c0.x
{t}{t}{t}add r1.x, t0.x, -c0.x
{t}{t}{t}mad r1.xyz, r0.y, c2, r1.x
{t}{t}{t}mul r2.xyz, r1, c0.y
{t}{t}{t}mul r2.xyz, r2, r2
{t}{t}{t}mul r2.xyz, r2, c0.z
{t}{t}{t}mad r3.xyz, r2, c3.y, c3.z
{t}{t}{t}rsq r4.x, r3.x
{t}{t}{t}rsq r4.y, r3.y
{t}{t}{t}rsq r4.z, r3.z
{t}{t}{t}mul r3.xyz, r3, r4
{t}{t}{t}mad r3.xyz, r2, c1.y, r3
{t}{t}{t}add r4.xyz, r2, c1.x
{t}{t}{t}rcp r5.x, r4.x
{t}{t}{t}rcp r5.y, r4.y
{t}{t}{t}rcp r5.z, r4.z
{t}{t}{t}mul r3.xyz, r3, r5
{t}{t}{t}rcp r5.x, r3.x
{t}{t}{t}rcp r5.y, r3.y
{t}{t}{t}rcp r5.z, r3.z
{t}{t}{t}mad r5.xyz, r5, c1.z, c1.x
{t}{t}{t}mul r5.xyz, r5, c1.w
{t}{t}{t}mul r6.xyz, r1, r5
{t}{t}{t}add r7.x, r6.z, -r6.y
{t}{t}{t}add r2.x, t0.y, -c0.x
{t}{t}{t}mul r2.x, r2.x, r5.x
{t}{t}{t}add r8.y, r2.x, c0.x
{t}{t}{t}add r2.y, r6.x, c0.x
{tap_code}{t}{t}{t}mul r9, r9, c3.w
{t}{t}{t}mov oC0, r9
{t}{t}}};
{t}{t}ZEnable=False;
{t}{t}ZWriteEnable=False;
{t}{t}AlphaBlendEnable=False;
{t}{t}AlphaTestEnable=False;
{t}{t}FogEnable=False;
{t}{t}StencilEnable=False;
{t}{t}CullMode=None;
{t}{t}AddressU[0]=Clamp;
{t}{t}AddressV[0]=Clamp;
{t}{t}MinFilter[0]=Linear;
{t}{t}MagFilter[0]=Linear;
{t}{t}MipFilter[0]=None;
{t}}}
}}
"""
    return lines.replace("\n", "\r\n")


def shader_asm(which, fov=None, d=None, ss=None):
    """The bare vs/ps asm from technique_text (for assembling outside an effect)."""
    txt = technique_text(fov, d, ss).replace("\r\n", "\n")
    key = "VertexShader=" if which == "vs" else "PixelShader="
    body = txt.split(key, 1)[1].split("{", 1)[1].split("};", 1)[0]
    return "\n".join(l.strip() for l in body.strip().splitlines()) + "\n"


if __name__ == "__main__":
    p = params()
    print(f"Panini {p['fov']:g} deg horizontal, d = {p['d']:g}: Xe {p['xe']:.6f}, tanE {p['tan_e']:.6f}")
    print(f"centre factor F(0) = {factor(0.0, p):.4f} -> centre magnified {1 / factor(0.0, p):.3f}x")
    print(f"edge squeeze d(src)/d(out) at the edge = {edge_squeeze(p):.3f} x render scale "
          f"{RENDER_SCALE:.4f} -> {taps(p)} taps per pixel; centre upscale after supersampling "
          f"{1 / factor(0.0, p) / RENDER_SCALE:.2f}x")
    print(technique_text())
