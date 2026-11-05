"""One-off edit (2026-10-04): milkyway extra (Stage 2 #13). Player: "use the ESO photo ... make it toggleable"."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''# ---- rayfast: the wheel rays''', '''# ---- milkyway: a real Milky Way in the night sky (Stage 2 #13, 2026-10-04) ----------------------
# Stock night sky = 100 copies of a 32x32 sparkle (built 0x004259b0, drawn 0x00425eb0 from 0x00428898):
# world = translate to the camera, FVF XYZ|TEX1, additive (ONE/ONE), lit by a material whose EMISSIVE is
# -(0.5..1 twinkle) x [0x02648270] (the sun direction's y: negative at night - drawn only then).
# Added: right after the stars' DrawIndexedPrimitive (hook 0x004260a2, 15 bytes: the star count stat
# call, re-run in the cave), a sphere of radius MW_RADIUS around the camera with the ESO/S. Brunier
# panorama (CC BY 4.0; skyprep.py -> Data/Sky/MilkyWay.jpg in Textures.pak, asked for as .bmp like
# every texture) is drawn with the SAME states (additive, the stars' world matrix) and its own steady
# material: emissive = clamp(-y x MW_RAMP, 0, 1) x brightness (the slider). First use: texture through
# the game's loader 0x0040ad00 (its cache), a 65x33 sphere built into VirtualAlloc'd memory (galactic
# -> world rotation MW_R, so the band arcs across the sky), both windings (cull state untouched). Draw:
# material via 0x0040ac90 and texture via 0x0040adc0 (the game's own state cache), then
# DrawIndexedPrimitiveUP (device vtable +0x150), then the stars' stream source + indices are set back
# (DrawPrimitiveUP clears them). If the texture or memory is missing, nothing is drawn.
MW_CAVE = S2_CODE + 0xB60                        # .. 0xEB0
MW_DATA = S2_CODE + 0xEB0                        # .. 0xFF0
MW_LON, MW_LAT = 64, 32
MW_NV = (MW_LON + 1) * (MW_LAT + 1)              # 2145 vertices, 20 bytes
MW_NT = MW_LON * MW_LAT * 4                      # both windings
MW_RADIUS = 590.0                                # just inside the stock stars (600)
MW_RAMP = 4.0                                    # full brightness once the sun is ~15 deg below the horizon
MW_BRIGHT_DEFAULT = 1.0
MW_BRIGHT_RANGE = (0.1, 3.0)
MW_BRIGHT = MW_BRIGHT_DEFAULT
MW_TEXNAME = b"Data/Sky/MilkyWay.bmp\\0"
MW_GC_ALT = 20.0                                 # galactic centre this high over the horizon (deg)
MW_TILT = 60.0                                   # galactic plane this steep (deg from horizontal)


def _mw_rotation():
    """Columns = where galactic x (to the centre), y (l = 90) and z (north pole) point in the game's
    left-handed world (y up). y = x cross z keeps the sky unmirrored when seen from inside."""
    import math
    a = math.radians(MW_GC_ALT)
    gx = (0.0, math.sin(a), math.cos(a))
    e = math.radians(90.0 - MW_TILT)
    nr = (math.cos(e), math.sin(e), 0.0)
    d = sum(p * q for p, q in zip(nr, gx))
    gz = tuple(p - d * q for p, q in zip(nr, gx))
    ln = math.sqrt(sum(p * p for p in gz))
    gz = tuple(p / ln for p in gz)
    gy = (gx[1] * gz[2] - gx[2] * gz[1], gx[2] * gz[0] - gx[0] * gz[2], gx[0] * gz[1] - gx[1] * gz[0])
    return gx, gy, gz


def set_milkyway(v):
    global MW_BRIGHT
    import math
    lo, hi = MW_BRIGHT_RANGE
    if not lo <= float(v) <= hi:
        raise ValueError(f"Milky Way brightness {v} is outside {lo:g}..{hi:g}")
    MW_BRIGHT = float(v)
    names = ["STATE", "TEX", "VTX", "IDX", "TMPI", "CB", "SB", "CL", "SL", "DB", "DL", "HALFPI", "PI",
             "INVLON", "INVLAT", "NEGK", "ZERO", "ONE", "GAIN", "EPS"] + [f"R{i}" for i in range(9)]
    d = {n: MW_DATA + 4 * i for i, n in enumerate(names)}
    d["MAT"] = MW_DATA + 4 * len(names)                    # D3DMATERIAL9, 0x44 bytes
    d["NAME"] = d["MAT"] + 0x44
    gx, gy, gz = _mw_rotation()
    R = [gx[r] * MW_RADIUS for r in range(3)], [gy[r] * MW_RADIUS for r in range(3)], [gz[r] * MW_RADIUS for r in range(3)]
    rvals = [R[c][r] for r in range(3) for c in range(3)]  # R{3r+c}: world axis r from galactic axis c
    floats = {"DB": math.pi / MW_LAT, "DL": 2 * math.pi / MW_LON, "HALFPI": math.pi / 2, "PI": math.pi,
              "INVLON": 1.0 / MW_LON, "INVLAT": 1.0 / MW_LAT, "NEGK": -MW_RAMP, "ZERO": 0.0, "ONE": 1.0,
              "GAIN": MW_BRIGHT, "EPS": 0.002}
    data = bytearray()
    for n in names:
        if n in floats:
            data += struct.pack("<f", floats[n])
        elif n.startswith("R"):
            data += struct.pack("<f", rvals[int(n[1:])])
        else:
            data += bytes(4)
    mat = bytearray(0x44)
    struct.pack_into("<f", mat, 0x0C, 1.0)                 # diffuse alpha 1; emissive rgb set per frame
    struct.pack_into("<f", mat, 0x3C, 1.0)
    data += mat + MW_TEXNAME
    assert MW_DATA + len(data) <= S2_CODE_END, "milkyway data past the .crmod area"
    rows = ""
    for r in range(3):
        rows += f"""
        movaps xmm3, xmm0
        mulss xmm3, dword ptr [{d[f'R{3 * r}']}]
        movaps xmm4, xmm1
        mulss xmm4, dword ptr [{d[f'R{3 * r + 1}']}]
        addss xmm3, xmm4
        movaps xmm4, xmm2
        mulss xmm4, dword ptr [{d[f'R{3 * r + 2}']}]
        addss xmm3, xmm4
        movss dword ptr [edi+{4 * r}], xmm3
        """
    code = _s2asm(f"""
        mov edx, dword ptr [ebx]
        add edx, edx
        push edx
        mov ecx, 0x0255d7f0
        call 0x0040abc0
        pushad
        cmp dword ptr [{d['STATE']}], 0
        jne ready
        mov dword ptr [{d['STATE']}], 2
        push 1
        push 1
        push {d['NAME']}
        mov ecx, 0x0255d7f0
        call 0x0040ad00
        cmp eax, -1
        je out
        mov dword ptr [{d['TEX']}], eax
        push 4
        push 0x3000
        push {MW_NV * 20 + MW_NT * 6}
        push 0
        call dword ptr [0x00568170]
        test eax, eax
        je out
        mov dword ptr [{d['VTX']}], eax
        lea ecx, [eax+{MW_NV * 20}]
        mov dword ptr [{d['IDX']}], ecx
        mov edi, eax
        xor ebp, ebp
    row:
        mov dword ptr [{d['TMPI']}], ebp
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['DB']}]
        fsubr dword ptr [{d['HALFPI']}]
        fsincos
        fstp dword ptr [{d['CB']}]
        fstp dword ptr [{d['SB']}]
        xor esi, esi
    col:
        mov dword ptr [{d['TMPI']}], esi
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['DL']}]
        fsubr dword ptr [{d['PI']}]
        fsincos
        fstp dword ptr [{d['CL']}]
        fstp dword ptr [{d['SL']}]
        movss xmm0, dword ptr [{d['CB']}]
        mulss xmm0, dword ptr [{d['CL']}]
        movss xmm1, dword ptr [{d['CB']}]
        mulss xmm1, dword ptr [{d['SL']}]
        movss xmm2, dword ptr [{d['SB']}]
        {rows}
        mov dword ptr [{d['TMPI']}], esi
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['INVLON']}]
        fstp dword ptr [edi+12]
        mov dword ptr [{d['TMPI']}], ebp
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['INVLAT']}]
        fstp dword ptr [edi+16]
        add edi, 20
        inc esi
        cmp esi, {MW_LON + 1}
        jb col
        inc ebp
        cmp ebp, {MW_LAT + 1}
        jb row
        mov edi, dword ptr [{d['IDX']}]
        xor ebp, ebp
    irow:
        xor esi, esi
    icol:
        mov eax, ebp
        imul eax, eax, {MW_LON + 1}
        add eax, esi
        lea ecx, [eax+{MW_LON + 1}]
        lea edx, [eax+1]
        mov word ptr [edi], ax
        mov word ptr [edi+2], cx
        mov word ptr [edi+4], dx
        mov word ptr [edi+6], ax
        mov word ptr [edi+8], dx
        mov word ptr [edi+10], cx
        mov word ptr [edi+12], dx
        mov word ptr [edi+14], cx
        lea edx, [ecx+1]
        mov word ptr [edi+16], dx
        mov word ptr [edi+18], dx
        mov word ptr [edi+20], cx
        lea edx, [eax+1]
        mov word ptr [edi+22], dx
        add edi, 24
        inc esi
        cmp esi, {MW_LON}
        jb icol
        inc ebp
        cmp ebp, {MW_LAT}
        jb irow
        mov dword ptr [{d['STATE']}], 1
    ready:
        cmp dword ptr [{d['STATE']}], 1
        jne out
        movss xmm0, dword ptr [0x02648270]
        mulss xmm0, dword ptr [{d['NEGK']}]
        maxss xmm0, dword ptr [{d['ZERO']}]
        minss xmm0, dword ptr [{d['ONE']}]
        mulss xmm0, dword ptr [{d['GAIN']}]
        comiss xmm0, dword ptr [{d['EPS']}]
        jbe out
        movss dword ptr [{d['MAT'] + 0x30}], xmm0
        movss dword ptr [{d['MAT'] + 0x34}], xmm0
        movss dword ptr [{d['MAT'] + 0x38}], xmm0
        push {d['MAT']}
        mov ecx, 0x0255d7f0
        call 0x0040ac90
        push 0
        push 0
        push 1
        push dword ptr [{d['TEX']}]
        mov ecx, 0x0255d7f0
        call 0x0040adc0
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push 20
        push dword ptr [{d['VTX']}]
        push 101
        push dword ptr [{d['IDX']}]
        push {MW_NT}
        push {MW_NV}
        push 0
        push 4
        push eax
        call dword ptr [ecx+0x150]
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push 0x14
        push 0
        push dword ptr [ebx+8]
        push 0
        push eax
        call dword ptr [ecx+0x190]
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push dword ptr [ebx+0xc]
        push eax
        call dword ptr [ecx+0x1a0]
    out:
        popad
        jmp 0x004260b1
    """, MW_CAVE, MW_DATA)
    PATCHES["milkyway"] = [
        (0x004260A2, bytes.fromhex("8b1303d252b9f0d75502e80f4bfeff"), _s2jmp(0x004260A2, MW_CAVE, 15),
         "night sky: after the stars, draw the Milky Way sphere"),
        (MW_CAVE, bytes(len(code)), code, f"milkyway cave ({len(code)} bytes)"),
        (MW_DATA, bytes(len(data)), bytes(data), f"milkyway data (brightness {MW_BRIGHT:g})"),
    ]


try:
    set_milkyway(_saved("milkyway_bright", MW_BRIGHT_DEFAULT))
except ImportError:
    pass

# ---- rayfast: the wheel rays''')
rep('''"policefix", "rayfast", "adaptive", "laa")''', '''"policefix", "rayfast", "milkyway", "adaptive", "laa")''')
rep('''"policefix": ["modsect"],
''', '''"policefix": ["modsect"], "milkyway": ["modsect"],
''')
rep('''    "morepolice": ("police_max",''', '''    "milkyway": ("milkyway_bright", lambda v: set_milkyway(v), lambda: MW_BRIGHT, "x", MW_BRIGHT_RANGE,
                 MW_BRIGHT_DEFAULT),
    "morepolice": ("police_max",''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
