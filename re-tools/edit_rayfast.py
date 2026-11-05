"""One-off edit (2026-10-04): rayfast extra - the wheel-ray bottleneck found by the player's 5 CPU profiles."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(old, new):
    global t
    assert t.count(old) == 1, f"not found exactly once: {old[:90]!r}"
    t = t.replace(old, new)


rep('''# ---- adaptive: the physics rate as a FLOOR''', '''# ---- rayfast: the wheel rays stop testing every object in the world (Stage 2 #15, 2026-10-04) -----
# The player's 5 CPU profiles (city, 2026-10-04 11:25-11:31): physics = 70-84% of the main thread,
# almost all of it in btCollisionWorld::rayTest 0x0051e8f0 (~40% in its own loop) and the two shape
# getAabb's it calls (0x0051bbb0 ~13%, 0x005271e0 ~11%). Who casts the rays: btDefaultVehicleRaycaster::
# castRay 0x00538400 - one per WHEEL per physics step for every car (traffic, police, racers, you).
# This Bullet (2.6x/2.7x, btAxisSweep3) answers each ray by looping over EVERY collision object,
# recomputing its AABB through a virtual call and slab-testing the ray against it; later Bullet versions
# (2.76+) ask the broadphase instead. Cost = cars x 4 x steps/s x objects.
# Fix, exact by construction:
#  H1 updateAabbs 0x0051d930 (once per step, before the rays) already computes every awake object's
#     AABB (getAabb into [esp+0x20] min / [esp+0x10] max) - cave H1 at 0x0051d9a9 copies it, with the
#     object, its shape and its origin, into a table (VirtualAlloc'd on first use, index = the object's
#     slot in m_collisionObjects).
#  H2 rayTest's loop 0x0051ea6c (after the filter test): if the table entry is this object AND shape,
#     shift the cached box by how far the object has moved since (origin now - origin then), widen it
#     by RAYFAST_MARGIN for rotation, and skip the object when the ray's own box misses it. Anything not
#     clearly missed - and every object without a valid entry - goes through the ORIGINAL getAabb +
#     btRayAabb + rayTestSingle, so hits are found exactly as before.
RAYFAST_H1 = S2_CODE + 0x700                     # .. 0x780
RAYFAST_H2 = S2_CODE + 0x780                     # .. 0x880
RAYFAST_DATA = S2_CODE + 0x880                   # table pointer, margin
RAYFAST_TABLE = RAYFAST_DATA                     # dword: 0 until the first step allocates it
RAYFAST_MARGIN_C = RAYFAST_DATA + 4              # float
RAYFAST_MARGIN = 0.5                             # m: rotation within one step (a car spinning 2 rev/s
                                                 # at 90 Hz moves its corners ~0.35 m)
RAYFAST_CAP = 16384                              # objects (entries of 48 bytes = 768 KB)
RAYFAST_ENTRY = 48                               # obj, shape, origin xyz, min xyz, max xyz, pad


def _rayfast():
    E, CAP = RAYFAST_ENTRY, RAYFAST_CAP
    h1 = _s2asm(f"""
        push eax
        push ecx
        push edx
        mov eax, dword ptr [{RAYFAST_TABLE}]
        test eax, eax
        jne have
        push 4
        push 0x3000
        push {CAP * E}
        push 0
        call dword ptr [0x00568170]
        mov dword ptr [{RAYFAST_TABLE}], eax
        test eax, eax
        je done
    have:
        cmp ebp, {CAP}
        jae done
        imul ecx, ebp, {E}
        add eax, ecx
        mov dword ptr [eax], edi
        mov ecx, dword ptr [edi+0xa8]
        mov dword ptr [eax+4], ecx
        mov ecx, dword ptr [edi+0x34]
        mov dword ptr [eax+8], ecx
        mov ecx, dword ptr [edi+0x38]
        mov dword ptr [eax+0xc], ecx
        mov ecx, dword ptr [edi+0x3c]
        mov dword ptr [eax+0x10], ecx
        mov ecx, dword ptr [esp+0x2c]
        mov dword ptr [eax+0x14], ecx
        mov ecx, dword ptr [esp+0x30]
        mov dword ptr [eax+0x18], ecx
        mov ecx, dword ptr [esp+0x34]
        mov dword ptr [eax+0x1c], ecx
        mov ecx, dword ptr [esp+0x1c]
        mov dword ptr [eax+0x20], ecx
        mov ecx, dword ptr [esp+0x20]
        mov dword ptr [eax+0x24], ecx
        mov ecx, dword ptr [esp+0x24]
        mov dword ptr [eax+0x28], ecx
    done:
        pop edx
        pop ecx
        pop eax
        test byte ptr [edi+0xac], 1
        jmp 0x0051d9b0
    """, RAYFAST_H1, RAYFAST_H2)
    axes = ""
    for a in (0, 4, 8):
        axes += f"""
        movss xmm1, dword ptr [eax+{0x34 + a}]
        subss xmm1, dword ptr [edx+{0x8 + a}]
        movss xmm2, dword ptr [edx+{0x14 + a}]
        addss xmm2, xmm1
        subss xmm2, dword ptr [{RAYFAST_MARGIN_C}]
        movss xmm3, dword ptr [edx+{0x20 + a}]
        addss xmm3, xmm1
        addss xmm3, dword ptr [{RAYFAST_MARGIN_C}]
        movss xmm4, dword ptr [esi+{a}]
        minss xmm4, dword ptr [edi+{a}]
        comiss xmm4, xmm3
        ja skip
        movss xmm4, dword ptr [esi+{a}]
        maxss xmm4, dword ptr [edi+{a}]
        comiss xmm4, xmm2
        jb skip
        """
    h2 = _s2asm(f"""
        mov edx, dword ptr [{RAYFAST_TABLE}]
        test edx, edx
        je slow
        mov ecx, dword ptr [esp+0x10]
        cmp ecx, {CAP}
        jae slow
        imul ecx, ecx, {E}
        add edx, ecx
        cmp dword ptr [edx], eax
        jne slow
        mov ecx, dword ptr [eax+0xa8]
        cmp dword ptr [edx+4], ecx
        jne slow
        {axes}
    slow:
        mov ecx, dword ptr [eax+0xa8]
        mov edx, dword ptr [ecx]
        jmp 0x0051ea74
    skip:
        jmp 0x0051ed7a
    """, RAYFAST_H2, RAYFAST_DATA)
    return [
        (0x0051D9A9, bytes.fromhex("f687ac00000001"), _s2jmp(0x0051D9A9, RAYFAST_H1, 7),
         "updateAabbs: remember every object's AABB + position for this step's rays"),
        (RAYFAST_H1, bytes(len(h1)), h1, f"rayfast cave H1 ({len(h1)} bytes)"),
        (0x0051EA6C, bytes.fromhex("8b88a80000008b11"), _s2jmp(0x0051EA6C, RAYFAST_H2, 8),
         "rayTest: skip objects whose remembered box the ray clearly misses (the rest: exact test as before)"),
        (RAYFAST_H2, bytes(len(h2)), h2, f"rayfast cave H2 ({len(h2)} bytes)"),
        (RAYFAST_MARGIN_C, bytes(4), struct.pack("<f", RAYFAST_MARGIN), f"rotation margin {RAYFAST_MARGIN:g} m"),
    ]


try:
    PATCHES["rayfast"] = _rayfast()
except ImportError:
    pass

# ---- adaptive: the physics rate as a FLOOR''')
rep('''"wantedhits", "smartpolice", "adaptive", "laa")''', '''"wantedhits", "smartpolice", "rayfast", "adaptive", "laa")''')
rep('''"smartpolice": ["modsect"],
''', '''"smartpolice": ["modsect"], "rayfast": ["modsect"],
''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
