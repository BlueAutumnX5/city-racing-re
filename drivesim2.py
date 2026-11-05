"""drivesim2.py [--quick] - the Rust drivetrain (racemod `drivetrain` + rust/crdrive crdrive.dll) inside the
REAL game code in Unicorn: the real drive function 0x004345e0, racemod's asm doors and DLL loader, and the
real 32-bit DLL mapped at its base (it has no imports). LoadLibraryA / GetProcAddress are stubbed in the IAT
and answered from the DLL's export table, so the loader path runs for real too.

Checks: the loader, model detection from the car path, AI cars bit-identical to stock, then every model's
gearbox (manual / F1 / automatic): top speed = stock, launch, shifting, Down = brake only, R, HUD text,
tachometer + shift light, engine sound, and the missing-DLL fallback (= stock)."""
import math
import struct
import sys

import racemod
import drivesim as ds
from drivesim import Car, CARS, DT, GEARBOXES, build, check, OK
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EBX,
                               UC_X86_REG_XMM0, UC_X86_REG_FPSW)

DLL = racemod.DT_DLL_SRC
STUBS = 0x07700000
PATHS = 0x07710000


def pe_image(path):
    b = open(path, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    base, size = struct.unpack_from("<II", b, pe + 0x34)[0], struct.unpack_from("<I", b, pe + 0x50)[0]
    nsec, opt = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 0x14)[0]
    secs = [struct.unpack_from("<8sIIII", b, pe + 0x18 + opt + 40 * i) for i in range(nsec)]
    img = bytearray(size)
    img[:0x400] = b[:0x400]
    for _, vs, va, rs, ro in secs:
        img[va:va + rs] = b[ro:ro + rs]
    exp = struct.unpack_from("<I", b, pe + 0x78)[0]
    n, fa, na = struct.unpack_from("<I", img, exp + 24)[0], *struct.unpack_from("<II", img, exp + 28)
    oa = struct.unpack_from("<I", img, exp + 36)[0]
    exports = {}
    for i in range(n):
        name = bytes(img[struct.unpack_from("<I", img, na + 4 * i)[0]:]).split(b"\0")[0].decode()
        ordi = struct.unpack_from("<H", img, oa + 2 * i)[0]
        exports[name] = base + struct.unpack_from("<I", img, fa + 4 * ordi)[0]
    return base, bytes(img), exports


class DCar(Car):
    """drivesim's Car + crdrive.dll mapped + the IAT loader stubs"""

    def __init__(self, exe, model="01", with_dll=True, mode=2):
        super().__init__(exe, model)
        mu = self.mu
        if mode is not None:
            # realistic gearing (settings +16, model.rs MODE_*): the older checks compare against the stock
            # car, so they run with it Off (2); section 9 keeps what the build says (mode=None)
            self.w32(racemod.DT_SETTINGS + 16, mode)
        self.base, img, self.exports = pe_image(DLL)
        mu.mem_map(self.base, (len(img) + 0xFFF) & ~0xFFF, UC_PROT_ALL)
        mu.mem_write(self.base, img)
        mu.mem_map(STUBS, 0x20000, UC_PROT_ALL)
        mu.mem_write(STUBS, b"\xc2\x04\x00")          # LoadLibraryA: ret 4
        mu.mem_write(STUBS + 0x10, b"\xc2\x08\x00")   # GetProcAddress: ret 8
        self.w32(racemod.IAT_LOADLIBRARYA, STUBS)
        self.w32(racemod.IAT_GETPROCADDRESS, STUBS + 0x10)
        self.with_dll = with_dll
        self.loads = []
        mu.hook_add(UC_HOOK_CODE, self._loadlib, begin=STUBS, end=STUBS)
        mu.hook_add(UC_HOOK_CODE, self._getproc, begin=STUBS + 0x10, end=STUBS + 0x10)
        self.model_id = int(model)

    def _cstr(self, a):
        return bytes(self.mu.mem_read(a, 64)).split(b"\0")[0].decode()

    def _loadlib(self, uc, addr, size, _):
        name = self._cstr(struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 4))[0])
        self.loads.append(name)
        uc.reg_write(UC_X86_REG_EAX, self.base if (self.with_dll and name == racemod.DT_DLL_NAME) else 0)

    def _getproc(self, uc, addr, size, _):
        esp = uc.reg_read(UC_X86_REG_ESP)
        h, np = struct.unpack("<II", uc.mem_read(esp + 4, 8))
        uc.reg_write(UC_X86_REG_EAX, self.exports.get(self._cstr(np), 0) if h == self.base else 0)

    def call(self, fn, *args):
        """cdecl call of a DLL export; returns eax"""
        esp = self.STACK + 0x9000 - 4 * (len(args) + 1)
        self.mu.mem_write(esp, struct.pack("<" + "I" * (len(args) + 1), self.RET, *args))
        self.mu.reg_write(UC_X86_REG_ESP, esp)
        self.mu.emu_start(self.exports[fn], self.RET, count=200000)
        return self.mu.reg_read(UC_X86_REG_EAX)

    def init_car(self, car, path):
        """run the car-loader door 0x00436620 (loader + cr_car_init) up to the original code at 0x00436627"""
        self.mu.mem_write(PATHS, path.encode() + b"\0")
        esp = self.STACK + 0x9000
        self.mu.mem_write(esp, struct.pack("<II", self.RET, PATHS))
        self.mu.reg_write(UC_X86_REG_ESP, esp)
        self.mu.reg_write(UC_X86_REG_ECX, car)
        self.mu.emu_start(0x00436620, 0x00436627, count=200000)
        ok = self.mu.reg_read(UC_X86_REG_ESP) == esp - 8 and self.mu.reg_read(UC_X86_REG_ECX) == car
        top = struct.unpack("<II", self.mu.mem_read(esp - 8, 8))
        return ok and top == (0x565CEC, 0xFFFFFFFF)

    def dbg(self, car=None):
        out = self.STACK + 0xA000
        self.call("cr_debug", car or self.CAR, out)
        return struct.unpack("<6f", self.mu.mem_read(out, 24))

    def key(self, vk):
        self.w32(0x00590448, 1)
        self.call("cr_key", vk, 0x00120001)


def setup(model, base, upgrades=0, mode=2):
    """stock car + drivetrain car of `model` ("01".."08"), both with the model's stock stats (mode: realistic
    gearing, settings +16; None = as built)"""
    s = Car(build([n for n in base if n not in GEARBOXES]), model)
    d = DCar(build(base + ["drivetrain"]), model, mode=mode)
    path = f"Data/Vehicles/{model}/Main.obj"
    assert d.init_car(d.CAR, path) and d.init_car(d.OTHER, "Data/Vehicles/01/Police.obj")
    for c in (s, d):
        for car in (c.CAR, c.OTHER):
            c.w32(car + 0x7fdc, upgrades)
            c.wf(car + 0x7f84, c.fbase + 200 * upgrades)
            c.wf(car + 0x7f78, c.accel + 0.2 * upgrades)
        c.accel += 0.2 * upgrades
        c.fbase += 200 * upgrades
        c.vd = 0.06 * c.fbase
        fr = CARS[model][4]
        c.c_drag = 2 * (fr[0] + fr[1]) * c.fbase * c.wheel_k / (c.vd / 3.6)        # linear (drivesim, measured)
        c.player = True
    return s, d


def run(c, kind, gears, seconds=40.0, drivetrain=True):
    """full throttle from 0; manual/F1: X at 95% revs; auto: lever to D first. -> (t, v, gear, rpm, force)"""
    c.v = 0.0
    c.wf(c.CAR + 0x7f80, 0.0)
    if drivetrain and kind == "auto":
        c.key(0x58)                                   # N -> D
    out, t = [], 0.0
    while t < seconds:
        f = c.step(2000.0)
        g, sel, rpm, eng, sh, _ = c.dbg() if drivetrain else (0, 0, 0, 0, 0, 0)
        if drivetrain and kind != "auto" and rpm >= 0.95 and g < gears and sh == 0:
            c.key(0x58)
        out.append((t, c.v, int(g), rpm, f))
        t += DT
    return out


def main():
    quick = "--quick" in sys.argv
    st = racemod.load_state()
    base = [n for n in st.get("extras", []) if n in racemod.EXTRAS and n not in GEARBOXES]
    print(f"crdrive.dll {DLL}\nextras: saved (minus the gearboxes) + drivetrain")

    print("1. loader + car detection")
    d = DCar(build(base + ["drivetrain"]), "08")
    ok = d.init_car(d.CAR, "Data/Vehicles/08/Main.obj")
    fn = [d.u32(racemod.DT_F[n]) for n in racemod.DT_FUNCS]
    check("car-loader door runs the DLL loader once, then the original code (stack, ecx, the 2 pushes)",
          ok and d.loads == [racemod.DT_DLL_NAME] and d.u32(racemod.DT_LOADED) == 1)
    check("every export resolved into the door table", fn == [d.exports[n] for n in racemod.DT_FUNCS])
    for path, want in (("Data/Vehicles/03/Police.obj", 3 | 256), ("Data/Vehicles/05/Main.obj", 5),
                       ("Data/Weird/xx.obj", 0)):
        d.init_car(d.OTHER, path)
        check(f"{path} -> model {want & 255}{' police' if want > 255 else ''}",
              d.call("cr_car_model", d.OTHER) == want)
    d.init_car(d.OTHER, "Data/Vehicles/08/Main.obj")
    check("loader ran only once", d.loads == [racemod.DT_DLL_NAME])

    print("2. traffic / police / racers drive exactly like the stock exe")
    s, d = setup("01", base)
    import random
    rnd = random.Random(11)
    for c in (s, d):
        c.player = False
    same = True
    for i in range(1500 if quick else 3000):
        th = rnd.choice((0.0, 2000.0, 2000.0))
        br = rnd.choice((0.0, 0.0, 0.0, 100.0))
        hb = 1 if rnd.random() < 0.03 else 0
        s.v = d.v = rnd.uniform(-30, 160)
        s.step(th, br, hb, integrate=False)
        d.step(th, br, hb, integrate=False)
        same &= s.forces == d.forces and s.brakes == d.brakes
    check("random steps (throttle/brake/handbrake, forward and reverse): identical wheel forces and brakes", same)

    print("3. every car with its own gearbox (stock stats, no upgrades)")
    kinds = {}
    import crdrive_table
    for model in ("01", "02", "03", "04", "05", "06", "07", "08"):
        name, kind, gears = crdrive_table.MODELS[int(model)]
        kinds[model] = (kind, gears)
        s, d = setup(model, base)
        rs = run(s, kind, gears, drivetrain=False)
        rd = run(d, kind, gears)
        seq = [rd[0][2]] + [rd[i][2] for i in range(1, len(rd)) if rd[i][2] != rd[i - 1][2]]
        vs, vm = rs[-1][1], rd[-1][1]
        t100 = (ds.t_to(rs, 100), ds.t_to(rd, 100))
        print(f"   {model} {name:22s} {kind:6s} {gears}sp: 0-100 stock {t100[0]:5.2f} s, gearbox {t100[1]:5.2f} s;"
              f" after 40 s {vs:5.1f} / {vm:5.1f} km/h; gears {seq}")
        check(f"{model} {name}: top speed within 3% of stock, never above it (+0.5)",   # stock = its design speed
              abs(vm - s.vd) / s.vd < 0.03 and vm <= s.vd + 0.5)
        check(f"{model} {name}: shifts up one at a time from 1st", seq == list(range(1, len(seq) + 1)) and len(seq) >= 2)
        if quick:
            break

    print("4. Down arrow, reverse, park (Galant automatic, Clio manual)")
    for model in ("01", "02"):
        s, d = setup(model, base)
        kind = kinds.get(model, ("auto" if model == "01" else "manual", 0))[0]
        rows = []
        for v in (20.0, 0.5, 0.0, -2.0):
            d.v = v
            for i in range(30):
                f = d.step(0.0, 100.0, integrate=False)
            rows.append((f, min(d.brakes.values())))
        check(f"{model}: Down = brake only at every speed (no reverse push)", all(f == 0 and b == 100.0 for f, b in rows))
        d.v = 0.0
        for k in range(1 if kind == "auto" else 2):
            d.key(0x5A)                       # auto: N -> R ; manual: 1 -> N -> R
            d.step(0.0, integrate=False)
        g = d.dbg()[0]
        for i in range(int(0.3 / DT)):        # let the shift (clutch time) finish
            f = d.step(2000.0, integrate=False)
        check(f"{model}: Z to R when stopped, gas drives backwards ({f:.0f} N)", g == -1 and f < 0)
    s, d = setup("01", base)
    for k in range(2):
        d.key(0x5A)                           # N -> R -> P
        d.step(0.0, integrate=False)
    d.step(0.0, integrate=False)
    check("Galant: P holds the car with the brake", d.dbg()[1] == 0 and d.f32(d.CAR + 0x7f90) == 100.0)

    print("5. HUD text, tachometer + shift light, sound")
    s, d = setup("01", base)
    d.key(0x58)                               # N -> D
    d.v = 60.0
    for i in range(80):
        d.step(2000.0, integrate=False)
    mu = d.mu
    HUDO, LOG = d.VOICE + 0x1000, []
    d.wf(d.VOICE + 0x800, 20.0)
    mu.mem_write(0x004702A0, bytes.fromhex("d905") + struct.pack("<I", d.VOICE + 0x800) + bytes.fromhex("c20c00"))
    mu.mem_write(0x00470260, bytes.fromhex("d905") + struct.pack("<I", d.VOICE + 0x800) + bytes.fromhex("c21800"))

    def font(uc, addr, size, _):
        e = uc.reg_read(UC_X86_REG_ESP)
        LOG.append((addr, [struct.unpack("<I", uc.mem_read(e + 4 + 4 * i, 4))[0] for i in range(6)]))
    mu.hook_add(UC_HOOK_CODE, font, begin=0x004702A0, end=0x004702A0)
    mu.hook_add(UC_HOOK_CODE, font, begin=0x00470260, end=0x00470260)
    esp = d.STACK + 0x9000
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_EBX, HUDO)
    sw0 = mu.reg_read(UC_X86_REG_FPSW)
    mu.emu_start(0x00468265, 0x0046826A, count=50000)
    draw = [a for adr, a in LOG if adr == 0x00470260]
    txt = bytes(mu.mem_read(draw[0][2], 4)).split(b"\0")[0] if draw else b""
    check(f"Galant in D at 60 km/h: the speedometer shows {txt.decode()!r} (stack, FPU kept, eax = car)",
          txt.startswith(b"D ") and mu.reg_read(UC_X86_REG_ESP) == esp and mu.reg_read(UC_X86_REG_FPSW) == sw0
          and mu.reg_read(UC_X86_REG_EAX) == d.CAR)

    def tach():
        esp = d.STACK + 0x9000
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_EAX, d.CAR)
        mu.emu_start(0x00468036, 0x0046807A, count=50000)
        ang = struct.unpack("<f", struct.pack("<I", mu.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF))[0]
        ok = mu.reg_read(UC_X86_REG_ESP) == esp - 4
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(0x00468119, 0x0046811E, count=100)
        return ang, d.u32(esp - 4), ok
    s, d = setup("02", base)                  # Clio manual: shift light
    mu = d.mu
    d.v = 0.0
    for i in range(int(3 / DT)):
        d.step(2000.0)                        # 1st gear to the limiter
    cols = set()
    for i in range(30):
        a, c, ok = tach()
        cols.add(c)
    full = 0.8 * 1.5 * math.pi
    check(f"Clio at the limiter: needle {a / full:.2f} revs, blinking ({len(cols)} colours), stack kept",
          ok and a / full > 0.9 and cols == {0xFF808000, 0xFFFF2020})

    print("6. no DLL (missing file) -> the stock game")
    d = DCar(build(base + ["drivetrain"]), "01", with_dll=False)
    s = Car(build(base), "01")
    d.init_car(d.CAR, "Data/Vehicles/01/Main.obj")
    same = True
    for v in (0.0, 30.0, 90.0):
        for c in (s, d):
            c.v = v
            c.wf(c.CAR + 0x7f80, 0.0)
        for i in range(60):
            s.step(2000.0, integrate=False)
            d.step(2000.0, integrate=False)
            same &= s.forces == d.forces
    check("loader failed -> every door runs the original code (player forces = stock)",
          same and d.u32(racemod.DT_LOADED) == 0xFFFFFFFF)

    print("7. AI gearboxes (aigears): traffic / police / racers shift themselves")
    for model in (("01", "05", "04", "08") if not quick else ("04",)):
        name, kind, gears = crdrive_table.MODELS[int(model)]
        s = Car(build(base), model)
        d = DCar(build(base + ["drivetrain", "aigears"]), model)
        d.init_car(d.CAR, "Data/Vehicles/02/Main.obj")             # the player drives something else
        d.init_car(d.OTHER, f"Data/Vehicles/{model}/Main.obj")
        for c in (s, d):
            c.player = False                                       # step() drives OTHER = an AI car
        rs, rd = [], []
        for c, out in ((s, rs), (d, rd)):
            c.v = 0.0
            c.wf(c.OTHER + 0x7f80, 0.0)
            t = 0.0
            while t < 40.0:
                f = c.step(1500.0)                                 # an AI throttle (analog)
                g = int(d.dbg(d.OTHER)[0]) if c is d else 0
                out.append((t, c.v, g, 0, f))
                t += DT
        seq = [rd[0][2]] + [rd[i][2] for i in range(1, len(rd)) if rd[i][2] != rd[i - 1][2]]
        vs, vm = rs[-1][1], rd[-1][1]
        print(f"   AI {model} {name:16s} {kind:6s}: 0-80 stock {ds.t_to(rs, 80):5.2f} s, gearbox {ds.t_to(rd, 80):5.2f} s;"
              f" after 40 s {vs:5.1f} / {vm:5.1f} km/h; gears {seq}")
        # against the stock TOP SPEED (design speed): with the measured linear drag the stock car is still
        # creeping up on it after 40 s while the gearbox (stronger mid-range) is already there
        check(f"AI {name}: shifts itself up one at a time, top speed within 3% of stock (never above)",
              seq == list(range(1, len(seq) + 1)) and len(seq) >= 2 and abs(vm - s.vd) / s.vd < 0.03
              and vm <= s.vd + 0.5)
        check(f"AI {name}: its throttle ramp (F) is untouched", d.f32(d.OTHER + 0x7f80) == s.f32(s.OTHER + 0x7f80))
        same = True
        for c in (s, d):
            c.v = 30.0
        braking = [int(d.dbg(d.OTHER)[0])]
        for i in range(int(5 / DT)):                               # brake hard: stop, then the stock auto-reverse
            fs, fd = s.step(0.0, 100.0), d.step(0.0, 100.0)
            same &= s.forces == d.forces and s.brakes == d.brakes
            d.v = s.v
            if d.v > 0.5 and int(d.dbg(d.OTHER)[0]) != braking[-1]:
                braking.append(int(d.dbg(d.OTHER)[0]))
        check(f"AI {name}: braking and reversing exactly like stock (ends at {s.v:.1f} km/h)", same and s.v < -1.0)
        # 2026-11-01 human-like AI: the driver keeps working the gears while the stock code brakes (the stock
        # auto-reverse then takes over: F < 0, the gearbox waits); driving off again = 1st
        d.v = 1.0
        d.wf(d.OTHER + 0x7F80, 0.0)
        d.step(1500.0)
        off = int(d.dbg(d.OTHER)[0])
        check(f"AI {name}: its driver downshifts while braking {braking}, drives off in {off}",
              all(b < a for a, b in zip(braking, braking[1:])) and len(braking) >= 2 and braking[-1] <= 2
              and off == 1)
    d = DCar(build(base + ["drivetrain", "aigears"]), "04")
    d.init_car(d.CAR, "Data/Vehicles/02/Main.obj")
    d.init_car(d.OTHER, "Data/Vehicles/04/Main.obj")
    s = Car(build(base), "04")
    pitch = {}
    for c in (s, d):
        c.player = False
        c.w32(0x012D041C, 1)                                       # sound on (car near the camera)
        c.v = 0.0
        c.wf(c.OTHER + 0x7f80, 0.0)
        p = []
        for i in range(int(12 / DT)):
            c.step(1500.0)
            if i % 30 == 0:
                p.append(c.f32(c.OTHER + 0x8000))
        pitch[c is d] = p
    drops = sum(1 for a, b in zip(pitch[True], pitch[True][1:]) if b < a - 500)
    check(f"AI engine sound follows its gearbox ({drops} pitch drops at upshifts; differs from stock's fake gears)",
          drops >= 2 and pitch[True] != pitch[False])

    print("8. long drives: the DLL's car table never loses your car (player 2026-10-31: Thunder became a 5-speed)")
    d = DCar(build(base + ["drivetrain", "aigears"]), "05")
    d.init_car(d.CAR, "Data/Vehicles/05/Main.obj")
    d.init_car(d.OTHER, "Data/Vehicles/03/Main.obj")
    d.w32(0x012D0C88, d.CAR)
    for k in range(600):                         # traffic spawning for a long while (table: 256 slots)
        d.init_car(0x09000000 + k * 0x10, "Data/Vehicles/02/Main.obj")
    check("600 traffic spawns later your Thunder is still the Thunder (3-speed automatic)",
          d.call("cr_car_model", d.CAR) == 5)
    check("... while an old traffic car did get pushed out of the full table",
          d.call("cr_car_model", d.OTHER) == 0)
    d.mu.mem_write(d.OTHER + 0x8C8, b"Data/Vehicles/07/Main.obj\0")
    d.w32(0x012D0C88, d.OTHER)
    d.call("cr_drive", d.OTHER, d.STACK + 0xA000)
    check("a car that was pushed out gets its model back from its own path (+0x8c8), not 'unknown'",
          d.call("cr_car_model", d.OTHER) == 7)

    print("9. realistic gearing (player 2026-11-01): 50/50 by default, `realcar` = the real cars' 0-100")
    import realcal
    from gearsim import BOXES
    real_top = {"01": 190, "02": 180, "03": 190, "04": 240, "05": 185, "06": 135, "07": 250, "08": 295}
    want100 = {"half": dict(realcal.TARGET["half"], **{"06": 15.4}),   # the Accord: 15.4 s even at full punch
               "real": realcal.TARGET["real"]}
    for extra, mode in (([], "half"), (["realcar"], "real")):
        for model in (BOXES if not quick else ("01", "04")):
            name, kind, gears = BOXES[model]
            _, d = setup(model, base + extra, 0, mode=None)
            built = d.u32(racemod.DT_SETTINGS + 16)
            out = run(d, kind, gears, 120.0)    # low punch = a long last stretch to top speed (tau 1/(0.1 k))
            top = max(v for _, v, *_ in out)
            t100 = next((t for t, v, *_ in out if v >= 100), None)
            want_top = (d.fbase * 0.06 + real_top[model]) / 2
            w = want100[mode][model]
            print(f"   {mode:4s} {model} {name:16s}: top {top:5.1f} (want {want_top:5.1f}), 0-100 "
                  f"{t100 if t100 is None else round(t100, 1)} s (want {w})")
            check(f"{mode} {name}: build mode {built}, top speed halfway to the real car's, 0-100 on target",
                  built == realcal.MODE[mode] and abs(top - want_top) < 0.025 * want_top
                  and t100 is not None and abs(t100 - w) < 0.06 * w)
    _, d = setup("01", base, 0, mode=None)
    rows = []
    for v in (60.0, 20.0, 0.5, 0.0, -2.0):
        d.v = v
        for i in range(30):
            f = d.step(0.0, 100.0, integrate=False)
        rows.append((v, f, min(d.brakes.values())))
    # no drag given back while braking: rolling back with Down held it made the stock code release the brakes
    check(f"50/50: Down = brake only at every speed, forward and rolling back {[(v, round(f), b) for v, f, b in rows]}",
          all(b == 100.0 and f == 0 for v, f, b in rows))
    d = DCar(build(base + ["drivetrain", "aigears"]), "04", mode=None)
    d.init_car(d.CAR, "Data/Vehicles/02/Main.obj")
    vds = {}
    for role in (1, 2, 3):
        d.init_car(d.OTHER, "Data/Vehicles/04/Main.obj")
        d.w32(d.OTHER + 0xC8C, role)
        d.wf(d.OTHER + 0x7F84, 2300.0)
        d.wf(d.OTHER + 0x7F88, 2300.0)
        d.wf(d.OTHER + 0x7F74, 138.0)
        d.player = False
        d.v = 50.0
        d.step(1500.0, integrate=False)
        vds[role] = d.f32(d.OTHER + 0x7F74)
    check(f"AI target speed (+0x7f74): racer {vds[1]:.0f} / police-role {vds[2]:.0f} = the Cosmo's halfway top "
          f"speed (189), traffic keeps 138 ({vds[3]:.0f})",
          abs(vds[1] - 189.0) < 0.6 and abs(vds[2] - 189.0) < 0.6 and vds[3] == 138.0)

    print(f"\n{sum(OK)}/{len(OK)} checks passed" + ("" if all(OK) else "  <-- FAILURES"))
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
