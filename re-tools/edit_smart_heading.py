"""One-off edit (2026-10-04): smartpolice corner check - near the car's end of the route, the incoming
direction is the car's HEADING, not 'car position -> route point' (which made a fake U-turn whenever the
car had driven past the nearest point: corner cap ~33-38 km/h = the play test's 'far police are slow')."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''        lea ecx, [edx+{SMART_BEND}]
        cmp ecx, ebp
        jb in_pt
        movaps xmm1, xmm4
        movaps xmm2, xmm5
        jmp in_got
    in_pt:
        lea ecx, [ecx+ecx*2]
        movss xmm1, dword ptr [edi+ecx*4]
        movss xmm2, dword ptr [edi+ecx*4+8]
    in_got:
        movss xmm6, dword ptr [edi+eax*4]
        subss xmm6, xmm1
        movss xmm7, dword ptr [edi+eax*4+8]
        subss xmm7, xmm2
        movaps xmm1, xmm6''', '''        lea ecx, [edx+{SMART_BEND}]
        cmp ecx, ebp
        jb in_pt
        movss xmm6, dword ptr [esi+0x20]
        mulss xmm6, dword ptr [{SM['CHORD']}]
        movss xmm7, dword ptr [esi+0x28]
        mulss xmm7, dword ptr [{SM['CHORD']}]
        jmp in_vec
    in_pt:
        lea ecx, [ecx+ecx*2]
        movss xmm1, dword ptr [edi+ecx*4]
        movss xmm2, dword ptr [edi+ecx*4+8]
        movss xmm6, dword ptr [edi+eax*4]
        subss xmm6, xmm1
        movss xmm7, dword ptr [edi+eax*4+8]
        subss xmm7, xmm2
    in_vec:
        movaps xmm1, xmm6''')
rep('''("L1", 0.0), ("L2", 0.0), ("D", 0.0), ("RAM_LEAD", SMART_RAM_LEAD)]''',
    '''("L1", 0.0), ("L2", 0.0), ("D", 0.0), ("RAM_LEAD", SMART_RAM_LEAD), ("CHORD", 4.0 * SMART_BEND)]''')
rep('''#  car and cave B at 0x0043d3de caps the target speed. 5.''', '''#  car and cave B at 0x0043d3de caps the target speed. Where the route has fewer than SMART_BEND points
#  behind a point (the car's end), the incoming direction is the car's HEADING x one chord - not
#  "car position -> point": the car has usually driven past the nearest point (lane snapping, routes
#  0.25 s old), which made a fake U-turn under the car and a 33-38 km/h cap (copwatch 2026-10-04: far
#  police piled up at 35-44 km/h while you drove 62). 5.''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
