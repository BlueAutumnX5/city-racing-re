"""hudsim.py - racemod `hudfix` + `rpmdial` + crdrive.dll (cr_dpup / cr_dipup / cr_hud_begin / cr_hud_end) inside
the REAL game code in Unicorn (player 2026-11-01: the driving HUD is stretched on 16:9; per-car rpm dials).

A fake Direct3D device (DrawPrimitiveUP / DrawIndexedPrimitiveUP record their vertices, GetFVF says XYZRHW)
sits at [0x025a1824]; the screen is 1920x1080 (x scale 2.4, y scale 1.8). The speedometer body 0x00467eb0 is
replaced by a tiny routine that draws the dial rectangle (virtual 621,431 .. 801,601) through the game's own
rect helper 0x0045c7d0, so the HUD door 0x0046b3bc, the DLL loader, the patched draw site 0x0045c8e2 and the
DLL all run for real. The texture manager (lookup 0x00410140, acquire 0x0040ad00) is stubbed.
Checks: inside the HUD the dial is narrowed x0.75 and pinned to the right edge; the same rect drawn outside the
HUD (a menu) is untouched; without the DLL everything is untouched; with rpmdial the Cosmo's dial shows its own
face (loaded once, looked up after, re-found after a texture flush, stock when the file is missing) and the
speed needle turns 1.5 deg per km/h."""
import struct
import racemod
from drivesim import build, check, OK
from drivesim2 import DCar, GEARBOXES
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_ECX, UC_X86_REG_EAX, UC_X86_REG_EIP

base = [e for e in racemod.load_state().get("extras", []) if e not in GEARBOXES]
FAKE = 0x07800000          # fake device: [FAKE] = vtable at FAKE + 0x100, method stubs from FAKE + 0x1000
SPRITE = 0x07810000        # the rect helper's vertex object (ecx)
TEST = 0x07820000          # stand-in for the speedometer body
HUD = 0x07830000           # the HUD object (ecx of 0x00467eb0): Main.dds slot at +0x9d7c, dial sprite +0x9d84
STOCK_SLOT, FACE_SLOT = 5, 77
TEXMGR = 0x0255D7F0        # texture manager; its name table (what lookup 0x00410140 runs on) is at +0x27c
W, H = 1920.0, 1080.0
DIAL = (621.0, 431.0, 801.0, 601.0)


def rig(with_dll=True, extras=("drivetrain", "hudfix"), face_file=True):
    d = DCar(build(base + list(extras)), "04", with_dll=with_dll)
    mu = d.mu
    mu.mem_map(FAKE, 0x10000, UC_PROT_ALL)
    vt = FAKE + 0x100
    stubs = FAKE + 0x1000
    mu.mem_write(FAKE, struct.pack("<I", vt))
    plain = stubs + 0x200
    mu.mem_write(plain, b"\x31\xc0\xc2\x08\x00")                       # xor eax,eax; ret 8 (SetFVF)
    for k in range(119):
        mu.mem_write(vt + 4 * k, struct.pack("<I", plain))
    getfvf = stubs + 0x100                                             # *pFVF = 0x144 (XYZRHW|DIFFUSE|TEX1)
    mu.mem_write(getfvf, bytes.fromhex("8b442408c70044010000" "31c0c20800"))
    up, iup = stubs, stubs + 0x80
    mu.mem_write(up, b"\x31\xc0\xc2\x14\x00")                          # DrawPrimitiveUP: ret 0x14
    mu.mem_write(iup, b"\x31\xc0\xc2\x24\x00")                         # DrawIndexedPrimitiveUP: ret 0x24
    mu.mem_write(vt + 0x14c, struct.pack("<I", up))
    mu.mem_write(vt + 0x150, struct.pack("<I", iup))
    mu.mem_write(vt + 0x168, struct.pack("<I", getfvf))
    d.w32(0x025A1824, FAKE)
    for a, v in ((0x0259F7EC, W), (0x0259F7F4, W / 800), (0x0259F7FC, H), (0x0259F804, H / 600)):
        d.wf(a, v)
    # the render-state helpers the rect helper calls: stubbed (thiscall, ret n)
    for fn, ret_n in ((0x0040B000, 4), (0x0040AFD0, 4), (0x0040B030, 4), (0x0040ADC0, 0x10), (0x0040ABC0, 4)):
        mu.mem_write(fn, b"\xc2" + struct.pack("<H", ret_n))
    d.draws = []

    def on_up(uc, addr, size, _):
        esp = uc.reg_read(UC_X86_REG_ESP)
        dev, prim, count, data, stride = struct.unpack("<5I", uc.mem_read(esp + 4, 20))
        xs = [struct.unpack("<f", uc.mem_read(data + stride * i, 4))[0] for i in range(prim and count + 2)]
        d.draws.append((dev, prim, count, stride, xs))
    mu.hook_add(UC_HOOK_CODE, on_up, begin=up, end=up)
    # speedometer body -> draw the dial rect through 0x0045c7d0 (args x0 y0 x1 y1 + 4 colours, ret 0x20)
    x0, y0, x1, y1 = (struct.unpack("<I", struct.pack("<f", v))[0] for v in DIAL)
    body = (b"".join(b"\x68" + struct.pack("<I", 0x80FFFFFF) for _ in range(4))
            + b"".join(b"\x68" + struct.pack("<I", v) for v in (y1, x1, y0, x0))
            + b"\xb9" + struct.pack("<I", SPRITE) + b"\xe8" + struct.pack("<i", 0x0045C7D0 - (TEST + 45 + 5))
            + b"\xc3")
    assert body[40] == 0xB9 and body[45] == 0xE8
    mu.mem_map(TEST, 0x1000, UC_PROT_ALL)
    mu.mem_map(SPRITE, 0x1000, UC_PROT_ALL)
    mu.mem_write(TEST, body)
    mu.mem_write(0x00467EB0, b"\xe9" + struct.pack("<i", TEST - (0x00467EB0 + 5)))
    # the HUD object, the player's car (a Cosmo) and the texture manager
    mu.mem_map(HUD, 0x10000, UC_PROT_ALL)
    d.w32(HUD + 0x9D7C, STOCK_SLOT)
    d.w32(HUD + 0x9D84 + 0x70, STOCK_SLOT)
    if with_dll:
        assert d.init_car(d.CAR, "Data/Vehicles/04/Main.obj")
    d.w32(0x012D0C88, d.CAR)
    d.tex = {"loaded": set(), "acquires": [], "lookups": 0}

    def ret(uc, value, argbytes):
        esp = uc.reg_read(UC_X86_REG_ESP)
        back = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + argbytes)
        uc.reg_write(UC_X86_REG_EIP, back)

    def name_arg(uc):
        a = struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 4))[0]
        return bytes(uc.mem_read(a, 64)).split(b"\0")[0].decode()

    def lookup(uc, addr, size, _):
        # like the real one: it searches the name table at ITS ecx, which must be the manager + 0x27c
        d.tex["lookups"] += 1
        right = uc.reg_read(UC_X86_REG_ECX) == TEXMGR + 0x27C
        ret(uc, FACE_SLOT if right and name_arg(uc) in d.tex["loaded"] else -1, 4)

    def acquire(uc, addr, size, _):
        if uc.reg_read(UC_X86_REG_ECX) != TEXMGR:
            ret(uc, -1, 0xC)
            return
        n = name_arg(uc)
        args = struct.unpack("<II", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 8, 8))
        d.tex["acquires"].append((n, args))
        if face_file:
            d.tex["loaded"].add(n)
        ret(uc, FACE_SLOT if face_file else 0, 0xC)
    mu.hook_add(UC_HOOK_CODE, lookup, begin=0x00410140, end=0x00410140)
    mu.hook_add(UC_HOOK_CODE, acquire, begin=0x0040AD00, end=0x0040AD00)
    return d


def r32(c, a):
    return struct.unpack("<I", c.mu.mem_read(a, 4))[0]


def hud_frame(d):
    """the HUD call site 0x0046b3bc (-> door -> cr_hud_begin, 'speedometer', cr_hud_end) up to 0x0046b3c1"""
    d.mu.reg_write(UC_X86_REG_ESP, d.STACK + 0x9000)
    d.mu.reg_write(UC_X86_REG_ECX, HUD)
    d.mu.emu_start(0x0046B3BC, 0x0046B3C1, count=2000000)


def menu_rect(d):
    """the same rect drawn outside the HUD (a menu / shop)"""
    esp = d.STACK + 0x9000
    d.mu.mem_write(esp, struct.pack("<I", d.RET))
    d.mu.reg_write(UC_X86_REG_ESP, esp)
    d.mu.emu_start(TEST, d.RET, count=2000000)


def main():
    stretched = [v * W / 800 for v in (DIAL[0], DIAL[2], DIAL[0], DIAL[2])]
    k = (H / 600) / (W / 800)
    fixed = [W + (x - W) * k for x in stretched]
    xset = lambda draw: sorted(set(round(x, 2) for x in draw[4][:4]))

    d = rig()
    hud_frame(d)
    check("the HUD door loads the DLL's four HUD functions",
          [racemod.DT_DLL_NAME] == sorted(set(d.loads)) and r32(d, racemod.HF_STATE) == 1)
    check("one draw call reached the fake device from inside the HUD", len(d.draws) == 1 and d.draws[0][0] == FAKE)
    xs = xset(d.draws[0]) if d.draws else []
    want = sorted(set(round(x, 2) for x in fixed))
    check(f"dial narrowed x{k:.2f} and pinned right: x {xs} (want {want})", xs == want)
    check("dial right edge still at the screen edge (801 virtual)", xs and abs(xs[-1] - fixed[1]) < 0.01)
    d.draws.clear()
    menu_rect(d)
    xs = xset(d.draws[0]) if d.draws else []
    check(f"the same rect outside the HUD (menus, shops) is untouched: {xs}",
          xs == sorted(set(round(x, 2) for x in stretched)))

    n = rig(with_dll=False)
    hud_frame(n)
    xs = xset(n.draws[0]) if n.draws else []
    check(f"no DLL: the HUD draws through the pass-through thunk, untouched: {xs}",
          r32(n, racemod.HF_STATE) != 1 and xs == sorted(set(round(x, 2) for x in stretched)))

    # ---- rpmdial: the player's car's own face on the dial; the speed needle's factor
    face = "Data/Interface/HUD/SpeedBar/Main_04.dds"
    check("without rpmdial the dial keeps the stock Main.dds", r32(d, HUD + 0x9D84 + 0x70) == STOCK_SLOT)
    r = rig(extras=("drivetrain", "hudfix", "rpmdial"))
    hud_frame(r)
    check(f"rpmdial: the Cosmo's dial shows Main_04.dds (slot {r32(r, HUD + 0x9D84 + 0x70)})",
          r32(r, HUD + 0x9D84 + 0x70) == FACE_SLOT)
    check("... loaded once through the game's own texture manager like Main.dds (name, 1, 1)",
          r.tex["acquires"] == [(face, (1, 1))])
    hud_frame(r)
    hud_frame(r)
    check("... later frames only look it up (no reload)", len(r.tex["acquires"]) == 1 and r.tex["lookups"] >= 4)
    r.w32(HUD + 0x9D84 + 0x70, STOCK_SLOT)
    r.tex["loaded"].clear()                         # a level reload flushed the textures
    hud_frame(r)
    check("after a texture flush the face is found again (re-acquired, never a stale slot)",
          r32(r, HUD + 0x9D84 + 0x70) == FACE_SLOT and len(r.tex["acquires"]) == 2)
    m = rig(extras=("drivetrain", "hudfix", "rpmdial"), face_file=False)
    for _ in range(3):
        hud_frame(m)
    check("face file missing: the stock dial, and the disk is tried only once",
          r32(m, HUD + 0x9D84 + 0x70) == STOCK_SLOT and len(m.tex["acquires"]) == 1)
    kr = struct.unpack("<f", r.mu.mem_read(0x0056C030, 4))[0]
    k0 = struct.unpack("<f", d.mu.mem_read(0x0056C030, 4))[0]
    check(f"speed needle: {k0:.6f} -> {kr:.7f} rad per km/h: 100 km/h at {100 * kr * 57.29578:.0f} deg on the "
          f"printed 150 (was {100 * k0 * 57.29578:.1f} = reads {100 * k0 / kr:.1f})", abs(kr - 4.712389 / 180) < 1e-7)
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    raise SystemExit(main())
