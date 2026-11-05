#  3. supersampling (2026-09-26, player: "jagged lines very clear, as if I play in 1366x768" and
#     "upsample it to 1440p first"): the renderer makes its glow/blur targets at the end of
#     0x0040c7e0 (restore) and frees them in 0x0040c6a0 (invalidate, also on device reset). Ours
#     go there too: a render-target TEXTURE of backbuffer x panini.RENDER_SCALE (2560x1440 on a
#     1080p screen, the game's RT format) + a depth-stencil of that size in the format of the
#     device's own depth buffer (GetDepthStencilSurface / GetDesc), no multisampling (it must
#     match the texture). D3DPOOL_DEFAULT: they must go before a Reset.
#  4. redirect: 0x00421710 draws the reflection (0x0041fa20, 0x0041ff40) and shadow (0x00420320)
#     targets first - each saves and restores the current target through the renderer's helpers
#     (0x0040b3f0/0x0040b410 save, 0x0040b430/0x0040b470 restore) - then resets vertex pools
#     (0x0040b780) and clears (0x00428850). Right before that clear (0x0042173c) the world is
#     pointed at the big texture + depth: the backbuffer and the device's depth surface are saved
#     (with a reference). Glow (0x0040fbd0) and motion blur (0x0040c080) read and restore the
#     CURRENT target, so they follow. The backbuffer-size globals are read only by the camera
#     setup 0x00425620; viewport code scales the current viewport (0x004015f0).
#  5. the 3D arrow (HUD object 0x025d79b8, DirectArrow model at [+0xfea4], drawn by 0x0045ea60 at
#     a fixed camera-space spot 0.5 ahead / 0.375 up) was drawn in the HUD phase (0x0046b330)
#     after the warp, through the wide flat lens: tiny and near the middle (player, 160 deg). The
#     HUD's call (0x0046b333) is removed; the pass draws it INTO the world image before the warp,
#     so Panini's centre magnification puts it back at about its stock size and place.
#  6. pass: the 3D world ends with glow and a tail-jump into motion blur at 0x00421873; the HUD
#     comes after. The jump now calls blur, draws the arrow, and then:
#     - redirected: back to the saved backbuffer + depth surface (references dropped);
#     - not redirected (no depth surface, a failure): StretchRect(backbuffer -> big texture);
#     then SetTechnique - ALWAYS, not via the renderer's name cache at +0x44070, because the game
#     never clears that cache when a device reset recreates the effect (0x0040c6a0 / 0x0040fb00
#     release it, 0x0040aa40 rebuilds it) - then the cache is set to us so the game's own users
#     (0x0040af20 and friends, all inside the 3D world) switch back; VS c0 = (-1/W, 1/H) of the
#     SCREEN (half-pixel shift + the pixel width the edge filter needs); the renderer's full-screen
#     quad (+0x440a4); effect Begin / Pass(0) / Draw / End (2004 D3DX: End restores every state
#     the pass set); stage 0's texture restored. If the world went to the big texture but cannot
#     be warped (technique missing, Begin failing), it is StretchRect'ed onto the screen as is -
#     the player never gets a black frame.
PAN_CODE = MOD_VA + 0x40
PAN_FOV_CAVE = PAN_CODE                          # 0x02701040
PAN_FX_CAVE = PAN_CODE + 0x40                    # 0x02701080
PAN_CREATE_CAVE = PAN_CODE + 0xA0                # 0x027010e0
PAN_RELEASE_CAVE = PAN_CODE + 0x1C0              # 0x02701200
PAN_REL_ALL = PAN_CODE + 0x1E0                   # 0x02701220 helper: release everything
PAN_REL_SAVES = PAN_CODE + 0x200                 # 0x02701240 helper: release the saved targets
PAN_REDIR_CAVE = PAN_CODE + 0x240                # 0x02701280
PAN_PASS_CAVE = PAN_CODE + 0x340                 # 0x02701380
PAN_CODE_END = MOD_VA + 0x800
PAN_TANE = MOD_VA + 0x800                        # float tan(PANINI_FOV / 2)
PAN_M1 = MOD_VA + 0x804                          # -1.0f
PAN_P1 = MOD_VA + 0x808                          # +1.0f
PAN_SS = MOD_VA + 0x80C                          # float panini.RENDER_SCALE
PAN_NAME = MOD_VA + 0x810                        # "techPanini" (a D3DXHANDLE by name)
PAN_TECH = MOD_VA + 0x1000                       # the technique text
PAN_TECH_MAX = 0x2000
PAN_TEX = MOD_BSS                                # IDirect3DTexture9*: the big world image
PAN_DS = MOD_BSS + 0x4                           # IDirect3DSurface9*: its depth-stencil
PAN_SAVE_RT = MOD_BSS + 0x8                      # the backbuffer, while the world is redirected
PAN_SAVE_DS = MOD_BSS + 0xC                      # the device's depth surface, idem
PAN_ACTIVE = MOD_BSS + 0x10                      # 1 between the redirect and the pass
PAN_FXBUF = MOD_BSS + 0x1000                     # effect text + technique -> D3DXCreateEffect
PAN_FXBUF_SIZE = 0x8000
RENDERER = 0x0255D7F0
BB_W, BB_H = 0x025A180C, 0x025A1810              # backbuffer width / height (ints)
HUD_OBJ = 0x025D79B8                             # `this` of the HUD draw 0x0046b330
ARROW_DRAW = 0x0045EA60                          # draws the 3D direction arrow (thiscall, no args)


def _panini():
    import math
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    import panini
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    tech = panini.technique_text().encode("latin-1")
    tl = len(tech)
    assert tl <= PAN_TECH_MAX, "techPanini text too long"
    asm = lambda src, at: bytes(ks.asm(src, at)[0])
    fov = asm(f"""
        fst dword ptr [esp+4]
        fdivr dword ptr [{PAN_TANE:#x}]
        fld1
        fpatan
        fadd st(0), st(0)
        fstp dword ptr [esp]
        jmp 0x00425713
    """, PAN_FOV_CAVE)
    fx = asm(f"""
        push esi
        push edi
        push ecx
        mov ecx, dword ptr [esp+0x18]
        cmp ecx, {PAN_FXBUF_SIZE - tl:#x}
        ja done
        mov esi, dword ptr [esp+0x14]
        mov edi, {PAN_FXBUF:#x}
        cld
        rep movsb
        mov esi, {PAN_TECH:#x}
        mov ecx, {tl:#x}
        rep movsb
        mov dword ptr [esp+0x14], {PAN_FXBUF:#x}
        add dword ptr [esp+0x18], {tl:#x}
    done:
        pop ecx
        pop edi
        pop esi
        jmp 0x00487a94
    """, PAN_FX_CAVE)
    # release helpers: every register preserved. REL_ALL = texture, depth, both saves;
    # REL_SAVES = the two saved screen targets. Both clear PAN_ACTIVE.
    rel_all = asm(f"""
        pushad
        mov esi, {PAN_TEX:#x}
        mov ebx, 4
        jmp {PAN_REL_SAVES + 11:#x}
    """, PAN_REL_ALL)
    rel_saves = asm(f"""
        pushad
        mov esi, {PAN_SAVE_RT:#x}
        mov ebx, 2
    loop:
        mov eax, dword ptr [esi]
        test eax, eax
        je next
        mov dword ptr [esi], 0
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    next:
        add esi, 4
        dec ebx
        jne loop
        mov dword ptr [{PAN_ACTIVE:#x}], 0
        popad
        ret
    """, PAN_REL_SAVES)
    assert asm(f"pushad; mov esi, {PAN_SAVE_RT:#x}; mov ebx, 2", PAN_REL_SAVES).__len__() == 11
    # end of the renderer's restore 0x0040c7e0: ebp = renderer; ebx/esi/edi belong to ITS caller
    create = asm(f"""
        pushad
        call {PAN_REL_ALL:#x}
        mov edi, dword ptr [ebp+0x44034]
        test edi, edi
        je done
        cvtsi2ss xmm0, dword ptr [{BB_W:#x}]
        mulss xmm0, dword ptr [{PAN_SS:#x}]
        cvtss2si ebx, xmm0
        cvtsi2ss xmm0, dword ptr [{BB_H:#x}]
        mulss xmm0, dword ptr [{PAN_SS:#x}]
        cvtss2si esi, xmm0
        push 0
        push {PAN_TEX:#x}
        push 0
        push dword ptr [ebp+0x41e84]
        push 1
        push 1
        push esi
        push ebx
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x5c]
        test eax, eax
        jge texok
        mov dword ptr [{PAN_TEX:#x}], 0
        jmp done
    texok:
        sub esp, 0x28
        lea eax, [esp]
        push eax
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0xa0]
        test eax, eax
        jl nods
        mov eax, dword ptr [esp]
        lea ecx, [esp+4]
        push ecx
        push eax
        mov edx, dword ptr [eax]
        call dword ptr [edx+0x30]
        mov dword ptr [esp+0x24], eax
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        cmp dword ptr [esp+0x24], 0
        jl nods
        push 0
        push {PAN_DS:#x}
        push 0
        push 0
        push 0
        push dword ptr [esp+0x18]
        push esi
        push ebx
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x74]
        test eax, eax
        jge nods
        mov dword ptr [{PAN_DS:#x}], 0
    nods:
        add esp, 0x28
    done:
        popad
        pop ebp
        add esp, 0x68
        ret
    """, PAN_CREATE_CAVE)
    release = asm(f"""
        call {PAN_REL_ALL:#x}
        mov eax, dword ptr [esi+0x440a4]
        jmp 0x0040c7c8
    """, PAN_RELEASE_CAVE)
    redir = asm(f"""
        pushad
        call {PAN_REL_SAVES:#x}
        mov ebx, dword ptr [{PAN_TEX:#x}]
        test ebx, ebx
        je out
        cmp dword ptr [{PAN_DS:#x}], 0
        je out
        mov edi, dword ptr [{RENDERER + 0x44034:#x}]
        test edi, edi
        je out
        push {PAN_SAVE_RT:#x}
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl undo
        push {PAN_SAVE_DS:#x}
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0xa0]
        test eax, eax
        jl undo
        sub esp, 4
        lea eax, [esp]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl undopop
        mov eax, dword ptr [esp]
        push eax
        push 0
        push edi
        mov ecx, dword ptr [edi]
        call dword ptr [ecx+0x94]
        mov ebp, eax
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        add esp, 4
        test ebp, ebp
        jl undo
        push dword ptr [{PAN_DS:#x}]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x9c]
        test eax, eax
        jl undort
        mov dword ptr [{PAN_ACTIVE:#x}], 1
        jmp out
    undopop:
        add esp, 4
        jmp undo
    undort:
        push dword ptr [{PAN_SAVE_RT:#x}]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x94]
    undo:
        call {PAN_REL_SAVES:#x}
    out:
        popad
        mov ecx, 0x02648150
        jmp 0x00421741
    """, PAN_REDIR_CAVE)
    # locals after `sub esp, 0x28`: [0] backbuffer, [4] big surface, [8] pass count,
    # [0xc] stage-0 texture before the pass, [0x10..0x1f] VS c0, [0x20] redirected this frame,
    # [0x24] "warp failed after the texture was bound". `push dword ptr [esp+X]` reads its
    # operand before esp moves.
    pas = asm(f"""
        call 0x0040c080
        pushad
        mov ecx, {HUD_OBJ:#x}
        call {ARROW_DRAW:#x}
        mov esi, {RENDERER:#x}
        mov edi, dword ptr [esi+0x44034]
        mov ebx, dword ptr [{PAN_TEX:#x}]
        test ebx, ebx
        je out
        sub esp, 0x28
        xor eax, eax
        mov dword ptr [esp+0xc], eax
        mov dword ptr [esp+0x24], eax
        mov eax, dword ptr [{PAN_ACTIVE:#x}]
        mov dword ptr [esp+0x20], eax
        test eax, eax
        je copy
        push dword ptr [{PAN_SAVE_RT:#x}]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x94]
        push dword ptr [{PAN_SAVE_DS:#x}]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x9c]
        call {PAN_REL_SAVES:#x}
        jmp draw
    copy:
        mov ebp, -1
        lea eax, [esp]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl free
        lea eax, [esp+4]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl relbb
        push 2
        push 0
        push dword ptr [esp+0xc]
        push 0
        push dword ptr [esp+0x10]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x88]
        mov ebp, eax
        mov eax, dword ptr [esp+4]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    relbb:
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        test ebp, ebp
        jl free
    draw:
        mov ecx, dword ptr [esi+0x4406c]
        test ecx, ecx
        je fallback
        push {PAN_NAME:#x}
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0xec]
        test eax, eax
        jl fallback
        mov dword ptr [esi+0x44070], {PAN_NAME:#x}
        cvtsi2ss xmm0, dword ptr [{BB_W:#x}]
        movss xmm1, dword ptr [{PAN_M1:#x}]
        divss xmm1, xmm0
        movss dword ptr [esp+0x10], xmm1
        cvtsi2ss xmm0, dword ptr [{BB_H:#x}]
        movss xmm1, dword ptr [{PAN_P1:#x}]
        divss xmm1, xmm0
        movss dword ptr [esp+0x14], xmm1
        xor eax, eax
        mov dword ptr [esp+0x18], eax
        mov dword ptr [esp+0x1c], eax
        push 1
        lea eax, [esp+0x14]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x178]
        lea eax, [esp+0xc]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x100]
        test eax, eax
        jge gotold
        mov dword ptr [esp+0xc], 0
    gotold:
        push ebx
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x104]
        push 0x102
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x164]
        push 20
        push 0
        push dword ptr [esi+0x440a4]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x190]
        mov ecx, dword ptr [esi+0x4406c]
        push 0
        lea eax, [esp+0xc]
        push eax
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x100]
        test eax, eax
        jl beginfail
        mov ecx, dword ptr [esi+0x4406c]
        push 0
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x104]
        push 2
        push 0
        push 5
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x144]
        mov ecx, dword ptr [esi+0x4406c]
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x108]
        jmp restex
    beginfail:
        mov dword ptr [esp+0x24], 1
    restex:
        push dword ptr [esp+0xc]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x104]
        mov eax, dword ptr [esp+0xc]
        test eax, eax
        je texdone
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    texdone:
        cmp dword ptr [esp+0x24], 0
        je free
    fallback:
        cmp dword ptr [esp+0x20], 0
        je free
        lea eax, [esp]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl free
        lea eax, [esp+4]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl fbrelbb
        push 2
        push 0
        push dword ptr [esp+8]
        push 0
        push dword ptr [esp+0x14]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x88]
        mov eax, dword ptr [esp+4]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    fbrelbb:
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    free:
        add esp, 0x28
    out:
        popad
        ret
    """, PAN_PASS_CAVE)
    caves = [(PAN_FOV_CAVE, fov, PAN_FX_CAVE), (PAN_FX_CAVE, fx, PAN_CREATE_CAVE),
             (PAN_CREATE_CAVE, create, PAN_RELEASE_CAVE), (PAN_RELEASE_CAVE, release, PAN_REL_ALL),
             (PAN_REL_ALL, rel_all, PAN_REL_SAVES), (PAN_REL_SAVES, rel_saves, PAN_REDIR_CAVE),
             (PAN_REDIR_CAVE, redir, PAN_PASS_CAVE), (PAN_PASS_CAVE, pas, PAN_CODE_END)]
    for at, code, limit in caves:
        assert at + len(code) <= limit, f"panini cave at {at:#x} is {len(code)} bytes, overruns {limit:#x}"
    jmp = lambda frm, to, n: b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (n - 5)
    call = lambda frm, to: b"\xe8" + struct.pack("<i", to - (frm + 5))
    tan_e = math.tan(math.radians(panini.PANINI_FOV / 2))
    data = struct.pack("<4f", tan_e, -1.0, 1.0, panini.RENDER_SCALE) + panini.TECH_NAME.encode() + b"\0"
    out = [
        (0x00425700, bytes.fromhex("d80d00835600d95c2404d905a8855600d91c24"), jmp(0x00425700, PAN_FOV_CAVE, 19),
         f"main camera: true aspect, vertical FOV for {panini.PANINI_FOV:g} deg horizontal"),
        (0x0040AB1B, bytes.fromhex("e874cf0700"), call(0x0040AB1B, PAN_FX_CAVE),
         "D3DXCreateEffect gets RenderTechniques + techPanini"),
        (0x0040CB87, bytes.fromhex("5d83c468c3"), jmp(0x0040CB87, PAN_CREATE_CAVE, 5),
         f"renderer restore: also the {panini.RENDER_SCALE:.4g}x world texture + depth"),
        (0x0040C7C2, bytes.fromhex("8b86a4400400"), jmp(0x0040C7C2, PAN_RELEASE_CAVE, 6),
         "renderer invalidate: also release ours"),
        (0x0042173C, bytes.fromhex("b950816402"), jmp(0x0042173C, PAN_REDIR_CAVE, 5),
         "before the world's clear: render the world into the big texture"),
        (0x0046B333, call(0x0046B333, ARROW_DRAW), b"\x90" * 5,
         "HUD no longer draws the 3D arrow (the pass does, before the warp)"),
        (0x00421873, bytes.fromhex("e908a8feff"), jmp(0x00421873, PAN_PASS_CAVE, 5),
         "after the 3D world (motion blur), before the HUD: arrow + the Panini pass"),
    ]
    out += [(at, bytes(len(code)), code, f"panini cave {i}") for i, (at, code, _) in enumerate(caves, 1)]
    out += [(PAN_TANE, bytes(len(data)), data, "tan(fov/2), -1, +1, render scale, \"techPanini\""),
            (PAN_TECH, bytes(tl), tech, f"techPanini effect text ({tl} bytes)")]
    return out
