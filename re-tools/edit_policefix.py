"""One-off edit (2026-10-04): policefix extra - the ORIGINAL chase AI with only the backwards-route bug fixed
(player: "temporarily revert the police code so it is using the original dumb one ... just switch the logic
so it isn't backward"). Also: CONFLICTS (policefix vs smartpolice hook the same bytes)."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''# ---- rayfast: the wheel rays''', '''# ---- policefix: the ORIGINAL chase AI, only the backwards route fixed (2026-10-04) ------------------
# Player, after smartpolice: "revert the police code so it is using the original dumb one ... just switch
# the logic so it isn't backward". Everything stock (0.5 s re-route, straight at you within 22 m, stock
# target speed, stock 20 m ram lead) EXCEPT the aim in route mode (0x0043d28a): stock aims at route point
# [1] = 4 m from YOU (the route is stored reversed). Simply taking the point 2nd from the police end is
# not enough: the route is up to 0.5 s old, so a fast car passes that point at once and the stock "aim
# behind" branch crawls at 33.75 km/h. So: nearest route point to the car, then toward you until one is
# >= L ahead (L = |speed| x 0.5 s, 8..30 m) - the same aim as smartpolice, nothing else of it.
PFIX_CAVE = S2_CODE + 0xA40                      # .. 0xAE0
PFIX_DATA = S2_CODE + 0xAE0                      # BIG, LOOK_K, LOOK_MIN, LOOK_MAX, ABS mask


def _policefix():
    d = {n: PFIX_DATA + 4 * i for i, n in enumerate(("BIG", "LOOK_K", "LOOK_MIN", "LOOK_MAX", "ABS"))}
    dist2 = """
        movss xmm0, dword ptr [edi+eax*4]
        subss xmm0, xmm4
        mulss xmm0, xmm0
        movss xmm1, dword ptr [edi+eax*4+8]
        subss xmm1, xmm5
        mulss xmm1, xmm1
        addss xmm0, xmm1
    """
    code = _s2asm(f"""
        push ebx
        push edi
        lea edi, [esi+0x1ecc]
        mov ecx, eax
        movss xmm4, dword ptr [esi+0xa18]
        movss xmm5, dword ptr [esi+0xa20]
        xor edx, edx
        xor ebx, ebx
        movss xmm3, dword ptr [{d['BIG']}]
    near_loop:
        cmp edx, ecx
        jae near_done
        lea eax, [edx+edx*2]
        {dist2}
        comiss xmm0, xmm3
        jae near_next
        movaps xmm3, xmm0
        mov ebx, edx
    near_next:
        inc edx
        jmp near_loop
    near_done:
        movss xmm2, dword ptr [esi+0x7f70]
        movss xmm1, dword ptr [{d['ABS']}]
        andps xmm2, xmm1
        mulss xmm2, dword ptr [{d['LOOK_K']}]
        maxss xmm2, dword ptr [{d['LOOK_MIN']}]
        minss xmm2, dword ptr [{d['LOOK_MAX']}]
        mulss xmm2, xmm2
        mov edx, ebx
    look_loop:
        test edx, edx
        je look_done
        lea eax, [edx+edx*2]
        {dist2}
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
        pop edi
        pop ebx
        jmp 0x0043d2c7
    """, PFIX_CAVE, PFIX_DATA)
    data = struct.pack("<4fI", 1e30, SMART_LOOK_K, SMART_LOOK_MIN, SMART_LOOK_MAX, 0x7FFFFFFF)
    return [
        (0x0043D28A, bytes.fromhex("8bcd3bc572028bc8493bcd76048bc5eb073bc573028bc548"), _s2jmp(0x0043D28A, PFIX_CAVE, 24),
         "chase: aim along the route from the police car's end (stock aims 4 m from YOU); nothing else changed"),
        (PFIX_CAVE, bytes(len(code)), code, f"policefix cave ({len(code)} bytes)"),
        (PFIX_DATA, bytes(len(data)), data, "policefix constants"),
    ]


try:
    PATCHES["policefix"] = _policefix()
except ImportError:
    pass

# ---- rayfast: the wheel rays''')
rep('''"wantedhits", "smartpolice", "rayfast", "adaptive", "laa")''',
    '''"wantedhits", "smartpolice", "policefix", "rayfast", "adaptive", "laa")''')
rep('''"smartpolice": ["modsect"], "rayfast": ["modsect"],
''', '''"smartpolice": ["modsect"], "rayfast": ["modsect"], "policefix": ["modsect"],
''')
rep('''REQUIRES_WHY = {''', '''# Extras that patch the same bytes: never together (apply refuses and says which to untick).
CONFLICTS = {"policefix": ["smartpolice"]}
REQUIRES_WHY = {''')
rep('''    for need, deps in REQUIRES.items():
        for dep in deps:
            if need in names and dep not in names:''', '''    for a, others in CONFLICTS.items():
        clash = [b for b in others if a in names and b in names]
        if clash:
            print(f"REFUSED: '{a}' and '{clash[0]}' change the same police code - tick only one of them. "
                  f"Nothing was written.")
            return 2
    for need, deps in REQUIRES.items():
        for dep in deps:
            if need in names and dep not in names:''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
