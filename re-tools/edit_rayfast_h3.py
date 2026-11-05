"""One-off edit (2026-10-04): rayfast H3 - cache boxes computed the slow way (objects asleep in updateAabbs)."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''#     btRayAabb + rayTestSingle, so hits are found exactly as before.''', '''#     btRayAabb + rayTestSingle, so hits are found exactly as before.
#  H3 right after that original getAabb (0x0051ea8a: min [esp+0xe4], max [esp+0x34]) the box is stored
#     in the table too, so objects updateAabbs never refreshes (asleep: state 2/5 - statics too) get
#     cached on their first ray and stay cheap afterwards.''')
rep('''RAYFAST_DATA = S2_CODE + 0x940                   # table pointer, margin''', '''RAYFAST_H3 = S2_CODE + 0x940                     # .. 0x9C0
RAYFAST_DATA = S2_CODE + 0x9C0                   # table pointer, margin''')
rep('''    """, RAYFAST_H2, RAYFAST_DATA)
    return [''', '''    """, RAYFAST_H2, RAYFAST_H3)
    h3 = _s2asm(f"""
        push eax
        push ecx
        push edx
        mov eax, dword ptr [{RAYFAST_TABLE}]
        test eax, eax
        je done
        mov ecx, dword ptr [esp+0x1c]
        cmp ecx, {CAP}
        jae done
        imul ecx, ecx, {E}
        add eax, ecx
        mov edx, dword ptr [esp+0x20]
        mov dword ptr [eax], edx
        mov ecx, dword ptr [edx+0xa8]
        mov dword ptr [eax+4], ecx
        mov ecx, dword ptr [edx+0x34]
        mov dword ptr [eax+8], ecx
        mov ecx, dword ptr [edx+0x38]
        mov dword ptr [eax+0xc], ecx
        mov ecx, dword ptr [edx+0x3c]
        mov dword ptr [eax+0x10], ecx
        mov ecx, dword ptr [esp+0xf0]
        mov dword ptr [eax+0x14], ecx
        mov ecx, dword ptr [esp+0xf4]
        mov dword ptr [eax+0x18], ecx
        mov ecx, dword ptr [esp+0xf8]
        mov dword ptr [eax+0x1c], ecx
        mov ecx, dword ptr [esp+0x40]
        mov dword ptr [eax+0x20], ecx
        mov ecx, dword ptr [esp+0x44]
        mov dword ptr [eax+0x24], ecx
        mov ecx, dword ptr [esp+0x48]
        mov dword ptr [eax+0x28], ecx
    done:
        pop edx
        pop ecx
        pop eax
        movss xmm3, dword ptr [0x005682f8]
        jmp 0x0051ea92
    """, RAYFAST_H3, RAYFAST_DATA)
    return [''')
rep('''        (RAYFAST_MARGIN_C, bytes(4), struct.pack("<f", RAYFAST_MARGIN), f"rotation margin {RAYFAST_MARGIN:g} m"),''',
    '''        (0x0051EA8A, bytes.fromhex("f30f101df8825600"), _s2jmp(0x0051EA8A, RAYFAST_H3, 8),
         "rayTest: also remember a box computed the slow way (objects asleep in updateAabbs)"),
        (RAYFAST_H3, bytes(len(h3)), h3, f"rayfast cave H3 ({len(h3)} bytes)"),
        (RAYFAST_MARGIN_C, bytes(4), struct.pack("<f", RAYFAST_MARGIN), f"rotation margin {RAYFAST_MARGIN:g} m"),''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
