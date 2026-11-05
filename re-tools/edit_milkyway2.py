"""One-off edit (2026-10-04): milkyway moved AFTER the sky dome (play test: "I see nothing of the galaxy").
The sky pass order is clear -> stars 0x00425eb0 -> sun? 0x00427bc0 -> DOME 0x004271a0 (effect, blends over
what is behind) -> moon? 0x00427880 -> clouds? 0x00428590. Drawn with the stars, the dome painted over it.
New hook 0x004288ab (`mov ecx,esi; call 0x427880`, 7 bytes), so: dome -> Milky Way -> moon/clouds. The
cave sets the stars' states itself through the game's cached setters (fog off 0x0040b0f0, z off
0x0040b000, z-write off 0x0040afd0, lighting on 0x0040b030, blend ONE/ONE 0x0040b060), the world matrix
(camera translation, device SetTransform +0xb0) and FVF XYZ|TEX1 (+0x164) - the moon pass sets its own."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''# Added: right after the stars' DrawIndexedPrimitive (hook 0x004260a2, 15 bytes: the star count stat
# call, re-run in the cave), a sphere''', '''# Added (2026-10-04 v2 - v1 drew with the stars and the sky DOME 0x004271a0, drawn after them, painted
# over it): between the dome and the moon (hook 0x004288ab `mov ecx,esi; call 0x427880`), a sphere''')
rep('''# panorama (CC BY 4.0; skyprep.py -> Data/Sky/MilkyWay.jpg in Textures.pak, asked for as .bmp like
# every texture) is drawn with the SAME states (additive, the stars' world matrix) and its own steady
# material:''', '''# panorama (CC BY 4.0; skyprep.py -> Data/Sky/MilkyWay.jpg in Textures.pak, asked for as .bmp like
# every texture), drawn with the stars' states set by the cave itself through the game's cached setters
# (fog off 0x0040b0f0, z off 0x0040b000, z-write off 0x0040afd0, lighting on 0x0040b030, ONE/ONE
# 0x0040b060), world = camera translation (SetTransform +0xb0), FVF XYZ|TEX1 (+0x164), and its own steady
# material:''')
rep('''# DrawIndexedPrimitiveUP (device vtable +0x150), then the stars' stream source + indices are set back
# (DrawPrimitiveUP clears them). If the texture or memory is missing, nothing is drawn.''',
    '''# DrawIndexedPrimitiveUP (device vtable +0x150). The moon/cloud passes after it set their own states and
# streams. If the texture or memory is missing, nothing is drawn.''')
rep('''    d["NAME"] = d["MAT"] + 0x44''', '''    d["NAME"] = d["MAT"] + 0x44
    d["WORLD"] = d["NAME"] + 24                            # 4x4 world matrix, translation filled per frame''')
rep('''    data += mat + MW_TEXNAME
    assert''', '''    data += mat + MW_TEXNAME.ljust(24, b"\\0")
    data += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    assert''')
rep('''    code = _s2asm(f"""
        mov edx, dword ptr [ebx]
        add edx, edx
        push edx
        mov ecx, 0x0255d7f0
        call 0x0040abc0
        pushad''', '''    code = _s2asm(f"""
        pushad''')
rep('''        movss dword ptr [{d['MAT'] + 0x30}], xmm0''', '''        push 0
        mov ecx, 0x0255d7f0
        call 0x0040b0f0
        push 0
        mov ecx, 0x0255d7f0
        call 0x0040b000
        push 0
        mov ecx, 0x0255d7f0
        call 0x0040afd0
        push 1
        mov ecx, 0x0255d7f0
        call 0x0040b030
        push 2
        push 2
        mov ecx, 0x0255d7f0
        call 0x0040b060
        mov eax, dword ptr [0x02610010]
        mov ecx, dword ptr [eax+0x70]
        mov dword ptr [{d['WORLD'] + 0x30}], ecx
        mov ecx, dword ptr [eax+0x74]
        mov dword ptr [{d['WORLD'] + 0x34}], ecx
        mov ecx, dword ptr [eax+0x78]
        mov dword ptr [{d['WORLD'] + 0x38}], ecx
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push {d['WORLD']}
        push 0x100
        push eax
        call dword ptr [ecx+0xb0]
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push 0x102
        push eax
        call dword ptr [ecx+0x164]
        movss xmm0, dword ptr [0x02648270]
        mulss xmm0, dword ptr [{d['NEGK']}]
        maxss xmm0, dword ptr [{d['ZERO']}]
        minss xmm0, dword ptr [{d['ONE']}]
        mulss xmm0, dword ptr [{d['GAIN']}]
        movss dword ptr [{d['MAT'] + 0x30}], xmm0''')
rep('''        call dword ptr [ecx+0x150]
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
        jmp 0x004260b1''', '''        call dword ptr [ecx+0x150]
    out:
        popad
        mov ecx, esi
        call 0x00427880
        jmp 0x004288b2''')
rep('''        (0x004260A2, bytes.fromhex("8b1303d252b9f0d75502e80f4bfeff"), _s2jmp(0x004260A2, MW_CAVE, 15),
         "night sky: after the stars, draw the Milky Way sphere"),''', '''        (0x004288AB, bytes.fromhex("8bcee8ceefffff"), _s2jmp(0x004288AB, MW_CAVE, 7),
         "night sky: after the sky dome (before moon/clouds), draw the Milky Way sphere"),''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
