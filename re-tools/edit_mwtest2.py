"""Update s2check's milkyway proof for v2 (hook after the dome, own render states)."""
import crpaths
p = crpaths.work(r"s2check.py")
t = open(p, encoding="utf-8").read()
start = t.index("def check_milkyway():")
end = t.index("# ================================================================== rayfast")
new = r'''def check_milkyway():
    print("milkyway (v2, after the sky dome): texture, sphere, render states, draw call, brightness, moon pass")
    R = racemod
    SKY, DEV, VT, CAM = MOCK, MOCK + 0x300, MOCK + 0x400, MOCK + 0x800
    BUF = MOCK + 0x100000
    NIGHT = 0x02648270
    CAMPOS = (123.0, 45.0, -678.0)

    def setup(tex_ok=True):
        e = Emu(INSTALLED + ["milkyway"])
        mu = e.mu
        mu.mem_write(TRAP + 0x10, b"\xc3" * 0x80)
        log = {k: [] for k in ("load", "mat", "tex", "draw", "moon", "fog", "z", "zw", "light", "blend",
                               "world", "fvf")}

        def stub(nargs, ret=None, rec=None):
            def h(uc, a, s, u):
                sp = uc.reg_read(UC_X86_REG_ESP)
                args = struct.unpack(f"<{nargs + 1}I", uc.mem_read(sp, 4 * (nargs + 1)))
                if rec:
                    rec(uc, args[1:])
                if ret is not None:
                    uc.reg_write(UC_X86_REG_EAX, ret)
                uc.reg_write(UC_X86_REG_EIP, args[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 4 + 4 * nargs)
            return h
        L = lambda k: (lambda uc, a: log[k].append(a))
        hooks = [
            (0x0040AD00, stub(3, ret=0x1234 if tex_ok else 0xFFFFFFFF,
                              rec=lambda uc, a: log["load"].append(bytes(uc.mem_read(a[0], 32)).split(b"\0")[0]))),
            (0x0040AC90, stub(1, rec=lambda uc, a: log["mat"].append(struct.unpack("<17f", uc.mem_read(a[0], 0x44))))),
            (0x0040ADC0, stub(4, rec=L("tex"))),
            (0x00427880, stub(0, rec=lambda uc, a: log["moon"].append(uc.reg_read(UC_X86_REG_ECX)))),
            (0x0040B0F0, stub(1, rec=L("fog"))), (0x0040B000, stub(1, rec=L("z"))),
            (0x0040AFD0, stub(1, rec=L("zw"))), (0x0040B030, stub(1, rec=L("light"))),
            (0x0040B060, stub(2, rec=L("blend"))),
            (TRAP + 0x10, stub(4, ret=BUF)),
            (TRAP + 0x20, stub(9, rec=L("draw"))),
            (TRAP + 0x50, stub(3, rec=lambda uc, a: log["world"].append((a[1], struct.unpack("<16f", uc.mem_read(a[2], 64)))))),
            (TRAP + 0x60, stub(2, rec=L("fvf"))),
        ]
        for addr, h in hooks:
            mu.hook_add(UC_HOOK_CODE, h, begin=addr, end=addr)
        e.w32(0x00568170, TRAP + 0x10)
        e.w32(0x025A1824, DEV)
        e.w32(DEV, VT)
        e.w32(VT + 0x150, TRAP + 0x20)
        e.w32(VT + 0xB0, TRAP + 0x50)
        e.w32(VT + 0x164, TRAP + 0x60)
        e.w32(0x02610010, CAM)
        mu.mem_write(CAM + 0x70, struct.pack("<3f", *CAMPOS))
        return e, log

    def frame(e, y):
        e.wf(NIGHT, y)
        esp = STACK + 0x80000
        regs = {UC_X86_REG_ESI: SKY, UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x2222, UC_X86_REG_EBP: 0x3333,
                UC_X86_REG_ESP: esp}
        e.run(0x004288AB, 0x004288B2, regs, count=20_000_000)
        return all(e.mu.reg_read(r) == v for r, v in regs.items())

    e, log = setup()
    ok_regs = frame(e, -0.5)
    check(f"first night frame: texture asked for as {log['load'][0].decode() if log['load'] else '-'}, "
          f"registers kept, the moon pass still runs (this = the sky object)",
          log["load"] == [b"Data/Sky/MilkyWay.bmp"] and ok_regs and log["moon"] == [SKY])
    st = (log["fog"], log["z"], log["zw"], log["light"], log["blend"])
    check(f"stars' states set through the game's cached setters: fog {log['fog']}, z {log['z']}, z-write "
          f"{log['zw']}, lighting {log['light']}, blend {log['blend']}",
          st == ([(0,)], [(0,)], [(0,)], [(1,)], [(2, 2)]))
    w = log["world"][0] if log["world"] else None
    check(f"world matrix = translate to the camera {CAMPOS}, FVF XYZ|TEX1",
          w is not None and w[0] == 0x100 and w[1][:12] == (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
          and w[1][12:15] == CAMPOS and log["fvf"] and log["fvf"][0][1] == 0x102)
    d = log["draw"][0] if log["draw"] else None
    check(f"one DrawIndexedPrimitiveUP: triangle list, {d[3] if d else 0} vertices, {d[4] if d else 0} triangles, "
          f"16-bit indices, stride 20", d is not None and (d[0], d[1], d[2], d[3], d[4], d[6], d[8]) ==
          (DEV, 4, 0, R.MW_NV, R.MW_NT, 101, 20) and d[7] == BUF and d[5] == BUF + R.MW_NV * 20)
    vtx = [struct.unpack_from("<5f", bytes(e.mu.mem_read(BUF, R.MW_NV * 20)), 20 * i) for i in range(R.MW_NV)]
    rad = [math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) for v in vtx]
    check(f"sphere: {len(vtx)} vertices at radius {min(rad):.2f}..{max(rad):.2f}, u/v in 0..1",
          all(abs(r - R.MW_RADIUS) < 0.05 for r in rad) and all(0 <= v[3] <= 1.0001 and 0 <= v[4] <= 1.0001 for v in vtx))
    gx, gy, gz = R._mw_rotation()
    centre = vtx[(R.MW_LAT // 2) * (R.MW_LON + 1) + R.MW_LON // 2]
    pole = vtx[R.MW_LON // 2]
    l90 = vtx[(R.MW_LAT // 2) * (R.MW_LON + 1) + R.MW_LON // 4]
    near = lambda v, w_: all(abs(v[i] / R.MW_RADIUS - w_[i]) < 1e-3 for i in range(3))
    check(f"galactic centre {math.degrees(math.asin(centre[1] / R.MW_RADIUS)):.1f} deg up; pole and l=90 as the "
          f"rotation says (not mirrored)", near(centre, gx) and near(pole, gz) and near(l90, gy))
    idx = struct.unpack(f"<{R.MW_NT * 3}H", bytes(e.mu.mem_read(BUF + R.MW_NV * 20, R.MW_NT * 6)))
    tris = [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
    canon = lambda tr: min(tr[i:] + tr[:i] for i in range(3))
    have = {canon(tr) for tr in tris}
    check(f"indices < {R.MW_NV}; both windings", max(idx) < R.MW_NV and all(canon((a, c, b)) in have for a, b, c in tris))
    em = log["mat"][0][12:15]
    check(f"material: steady emissive {em[0]:.2f} at y = -0.5 (brightness {R.MW_BRIGHT:g}), texture via the cache",
          abs(em[0] - min(1, 0.5 * R.MW_RAMP) * R.MW_BRIGHT) < 1e-5 and em[0] == em[1] == em[2]
          and log["tex"] and log["tex"][0][0] == 0x1234)
    for y, want in ((-0.1, 0.4), (-0.001, 0.004), (-0.0001, None), (0.05, None)):
        n0, m0 = len(log["draw"]), len(log["moon"])
        frame(e, y)
        drew = len(log["draw"]) > n0
        got = log["mat"][-1][12] if drew else None
        lim = want * R.MW_BRIGHT if want is not None else None
        check(f"sun y = {y:+.4f}: " + (f"drawn at {got:.3f}" if drew else "not drawn") + ", moon pass runs",
              len(log["moon"]) == m0 + 1 and ((want is None and not drew) or
                                              (want is not None and drew and abs(got - lim) < 1e-5)))
    check("texture loaded and sphere built only once", len(log["load"]) == 1)
    e2, log2 = setup(tex_ok=False)
    ok2 = frame(e2, -0.5) and frame(e2, -0.5)
    check("texture missing: nothing drawn, no crash, not retried, the moon pass still runs",
          ok2 and not log2["draw"] and len(log2["load"]) == 1 and len(log2["moon"]) == 2)


'''
t = t[:start] + new + t[end:]
open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
