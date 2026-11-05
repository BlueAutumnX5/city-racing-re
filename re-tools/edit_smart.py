"""One-off edit (2026-10-04): smartpolice extra (player: "the police behind doesn't follow the road, and
just crash into a building ... sometimes overshoot the turn too" / "can you make them smart too")."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
crlf = b"\r\n" in raw
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(old, new):
    global t
    assert t.count(old) == 1, f"not found exactly once: {old[:90]!r}"
    t = t.replace(old, new)


rep('''# ---- adaptive: the physics rate as a FLOOR''', '''# ---- smartpolice: chasing police follow the road and brake for corners (Stage 2, 2026-10-04) -------
# Player: "the Police behind doesn't follow the road, and just crash into a building to the side I turn
# into ... sometimes overshoot the turn too". The chase state (4) handler 0x0043cda0, per police car:
#  - every 0.5 s (timer +0x1ea4 vs [0x005682f8]) the route count +0x7f44 = 0 and, when you are more than
#    22 m away ([0x00569824]), the route is rebuilt by the shared path builder 0x00431350 (A* on the road
#    grid) into [car+0x1ecc] (12-byte points, 4 m apart). Within 22 m: no route, it aims at points
#    around YOU (local space) = straight across the corner block.
#  - THE BUG: the builder stores the route REVERSED - point [0] is at YOUR end, the last point at the
#    police car (re-tools/chaseprobe.py, real map). The follow code (0x0043d28a) aims at point [1]
#    anyway = 4 m from you. So with a perfect road route in hand, the police drove straight at you.
#  - target speed (0x0043d2f7..0x0043d3de, km/h) depends on your speed, the wanted level and distance,
#    never on the road ahead = no braking for corners.
# Fix (4 parts, every chasing police car; patrols and traffic untouched):
#  1. re-route every SMART_INTERVAL s (0x0043cde2 repointed), 2. use the route down to SMART_MINROUTE m
#  (0x0043ce1f repointed; < 8 m the stock ram aim still takes over), 3. cave A at 0x0043d28a: find the
#  route point nearest the car, walk toward you until one is >= L ahead (L = |speed| x SMART_LOOK_K,
#  clamped SMART_LOOK_MIN..MAX) and aim there; 4. same cave: for every route point within SMART_DMAX
#  m, corner speed = VMIN + VSPAN x max(0, cos)^2 (cos = the car's heading [car+0x20/0x28] vs the road
#  direction there, an 8 m chord), allowed now = sqrt(corner^2 + A2 x distance) (braking at SMART_DECEL
#  m/s2); the minimum goes to SMART_CAP for this car, and cave B at 0x0043d3de caps the target speed.
SMART_CAVE_A = S2_CODE + 0x300                   # 0x02704300 .. 0x02704500
SMART_CAVE_B = S2_CODE + 0x500                   # 0x02704500 .. 0x02704540
SMART_DATA = S2_CODE + 0x540                     # floats/dwords
SMART_INTERVAL = 0.25                            # s between re-routes (stock 0.5)
SMART_MINROUTE = 8.0                             # m: route used beyond this (stock 22)
SMART_LOOK_K = 0.5 / 3.6                         # look-ahead = 0.5 s of travel (speed is km/h)
SMART_LOOK_MIN, SMART_LOOK_MAX = 8.0, 30.0       # m
SMART_DMAX = 70.0                                # m of road checked for corners
SMART_VMIN, SMART_VSPAN = 45.0, 255.0            # km/h: a 90-degree corner 45, straight 300
SMART_DECEL = 6.0                                # m/s2 planned braking
_SMART_CONSTS = [  # name, value (float) - laid out from SMART_DATA in this order
    ("INTERVAL", SMART_INTERVAL), ("MINROUTE", SMART_MINROUTE), ("LOOK_K", SMART_LOOK_K),
    ("LOOK_MIN", SMART_LOOK_MIN), ("LOOK_MAX", SMART_LOOK_MAX), ("DMAX2", SMART_DMAX ** 2),
    ("VMIN", SMART_VMIN), ("VSPAN", SMART_VSPAN), ("A2", 2 * SMART_DECEL * 3.6 ** 2),
    ("BIG", 1e30), ("ONE", 1.0), ("CAP", 0.0)]
SM = {n: SMART_DATA + 4 * i for i, (n, _) in enumerate(_SMART_CONSTS)}
SM["ABS"] = SMART_DATA + 4 * len(_SMART_CONSTS)
SM["CAR"] = SM["ABS"] + 4


def _smart_dist2(dst):
    """xmm<dst> = squared 2D distance car (xmm4 x, xmm5 z) to point eax*4 in edi (eax = 3*index)."""
    return f"""
    movss xmm{dst}, dword ptr [edi+eax*4]
    subss xmm{dst}, xmm4
    mulss xmm{dst}, xmm{dst}
    movss xmm1, dword ptr [edi+eax*4+8]
    subss xmm1, xmm5
    mulss xmm1, xmm1
    addss xmm{dst}, xmm1
    """


def _smartpolice():
    a = _s2asm(f"""
        push ebx
        push edi
        push ebp
        lea edi, [esi+0x1ecc]
        mov ecx, eax
        movss xmm4, dword ptr [esi+0xa18]
        movss xmm5, dword ptr [esi+0xa20]
        xor edx, edx
        xor ebx, ebx
        movss xmm3, dword ptr [{SM['BIG']}]
    near_loop:
        cmp edx, ecx
        jae near_done
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, xmm3
        jae near_next
        movaps xmm3, xmm0
        mov ebx, edx
    near_next:
        inc edx
        jmp near_loop
    near_done:
        movss xmm2, dword ptr [esi+0x7f70]
        movss xmm1, dword ptr [{SM['ABS']}]
        andps xmm2, xmm1
        mulss xmm2, dword ptr [{SM['LOOK_K']}]
        maxss xmm2, dword ptr [{SM['LOOK_MIN']}]
        minss xmm2, dword ptr [{SM['LOOK_MAX']}]
        mulss xmm2, xmm2
        mov edx, ebx
    look_loop:
        test edx, edx
        je look_done
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, xmm2
        jae look_done
        dec edx
        jmp look_loop
    look_done:
        lea eax, [edx+edx*2]
        lea eax, [edi+eax*4]
        mov ecx, dword ptr [eax]
        mov dword ptr [esi+0x1e90], ecx
        mov ecx, dword ptr [eax+4]
        mov dword ptr [esi+0x1e94], ecx
        mov ecx, dword ptr [eax+8]
        mov dword ptr [esi+0x1e98], ecx
        movss xmm3, dword ptr [{SM['BIG']}]
        mov edx, ebx
    cap_loop:
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, dword ptr [{SM['DMAX2']}]
        ja cap_done
        mov ecx, edx
        sub ecx, 2
        jge chord
        xor ecx, ecx
    chord:
        lea ecx, [ecx+ecx*2]
        movss xmm1, dword ptr [edi+ecx*4]
        subss xmm1, dword ptr [edi+eax*4]
        movss xmm2, dword ptr [edi+ecx*4+8]
        subss xmm2, dword ptr [edi+eax*4+8]
        movaps xmm6, xmm1
        mulss xmm6, xmm6
        movaps xmm7, xmm2
        mulss xmm7, xmm7
        addss xmm6, xmm7
        comiss xmm6, dword ptr [{SM['ONE']}]
        jb cap_next
        sqrtss xmm6, xmm6
        mulss xmm1, dword ptr [esi+0x20]
        mulss xmm2, dword ptr [esi+0x28]
        addss xmm1, xmm2
        divss xmm1, xmm6
        xorps xmm2, xmm2
        maxss xmm1, xmm2
        mulss xmm1, xmm1
        mulss xmm1, dword ptr [{SM['VSPAN']}]
        addss xmm1, dword ptr [{SM['VMIN']}]
        mulss xmm1, xmm1
        sqrtss xmm0, xmm0
        mulss xmm0, dword ptr [{SM['A2']}]
        addss xmm1, xmm0
        minss xmm3, xmm1
    cap_next:
        test edx, edx
        je cap_done
        dec edx
        jmp cap_loop
    cap_done:
        sqrtss xmm3, xmm3
        movss dword ptr [{SM['CAP']}], xmm3
        mov dword ptr [{SM['CAR']}], esi
        pop ebp
        pop edi
        pop ebx
        jmp 0x0043d2c7
    """, SMART_CAVE_A, SMART_CAVE_B)
    b = _s2asm(f"""
        cmp dword ptr [{SM['CAR']}], esi
        jne keep
        minss xmm0, dword ptr [{SM['CAP']}]
        mov dword ptr [{SM['CAR']}], 0
    keep:
        movss xmm5, dword ptr [0x00568594]
        jmp 0x0043d3e6
    """, SMART_CAVE_B, SMART_DATA)
    data = b"".join(struct.pack("<f", v) for _, v in _SMART_CONSTS) + struct.pack("<II", 0x7FFFFFFF, 0)
    return [
        (0x0043CDE2, bytes.fromhex("0f2f05f8825600"), bytes.fromhex("0f2f05") + struct.pack("<I", SM["INTERVAL"]),
         f"chase: re-route every {SMART_INTERVAL:g} s (stock 0.5)"),
        (0x0043CE1F, bytes.fromhex("0f2f0524985600"), bytes.fromhex("0f2f05") + struct.pack("<I", SM["MINROUTE"]),
         f"chase: follow the road route down to {SMART_MINROUTE:g} m (stock 22, then straight at you)"),
        (0x0043D28A, bytes.fromhex("8bcd3bc572028bc8493bcd76048bc5eb073bc573028bc548"), _s2jmp(0x0043D28A, SMART_CAVE_A, 24),
         "chase: aim along the route from the police car's end (stock: 4 m from YOU - the route is stored reversed)"),
        (SMART_CAVE_A, bytes(len(a)), a, f"smartpolice cave A: look-ahead target + corner speed ({len(a)} bytes)"),
        (0x0043D3DE, bytes.fromhex("f30f102d94855600"), _s2jmp(0x0043D3DE, SMART_CAVE_B, 8),
         "chase: target speed capped for the corners ahead"),
        (SMART_CAVE_B, bytes(len(b)), b, f"smartpolice cave B ({len(b)} bytes)"),
        (SMART_DATA, bytes(len(data)), data, "smartpolice constants"),
    ]


try:
    PATCHES["smartpolice"] = _smartpolice()
except ImportError:
    pass

# ---- adaptive: the physics rate as a FLOOR''')
rep('''"wantedhits", "adaptive", "laa")''', '''"wantedhits", "smartpolice", "adaptive", "laa")''')
rep('''"evade": ["modsect"],
''', '''"evade": ["modsect"], "smartpolice": ["modsect"],
''')
out = t.replace("\n", "\r\n") if crlf else t
open(p, "wb").write(out.encode("utf-8"))
print("edited, crlf =", crlf)
