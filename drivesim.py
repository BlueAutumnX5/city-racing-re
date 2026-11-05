r"""drivesim.py - run the game's REAL drive function 0x004345e0 (stock, and with the `manual` extra) in Unicorn
on a test car, with a 1-D vehicle model in Python closing the loop (mass, aero drag calibrated so the STOCK
car tops out at its design speed Vd = 0.06 x max force, tyre grip cap). Bullet is not emulated: the stubbed
applyEngineForce (0x00539d20) records the force per wheel, setBrake (0x00538dd0) the brake per wheel.
Checks the manual gearbox (Stage 2 #11): AI cars bit-identical to the stock exe, 1st-gear launch = stock,
top speed = stock, clutch cut, rev limiter, neutral, engine braking, bogging, reverse via the stock path,
engine-sound pitch from RPM, the X/Z key hook, the Shift clutch. Prints acceleration tables for stock vs manual.
Usage: drivesim.py [car 01..08] [--plot out.png]"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EBP, \
    UC_X86_REG_EDI

CARS = {"01": ("Galant S500", 1000, 2000, 2.0, (0, 1)), "02": ("Clio NSX", 800, 1300, 1.0, (0, 1)),
        "03": ("Rover H1200", 1200, 1700, 1.5, (0, 1)), "04": ("Cosmo R200", 1000, 2300, 2.0, (0, 1)),
        "05": ("Thunder-1960", 1200, 1800, 1.25, (0, 1)), "06": ("Accord Z8", 800, 1300, 1.0, (0, 1)),
        "07": ("Alpha GRX8", 1000, 2200, 2.25, (0, 1)), "08": ("Uber Atom-2000", 1000, 2500, 2.5, (0, 1))}
# = the STOCK Main.obj values (carmod.py stock-list; player reverted their tuning 2026-10-31): all RWD
DT = 1.0 / 60
AWDFIX = "awdfix" in racemod.load_state().get("extras", [])
# every gearbox extra: the tests add the one they test on top of the saved extras without these
GEARBOXES = ("manual", "manpower", "drivetrain", "aigears", "hudfix", "rpmdial", "realcar")
OK = []


def check(label, ok, extra=""):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}{('  ' + extra) if extra else ''}")


def build(names):
    names = list(names)
    for _ in range(2):
        for need, deps in racemod.REQUIRES.items():
            for dep in deps:
                if need in names and dep not in names:
                    names.append(dep)
    names = [n for n in racemod.ORDER_FIRST if n in names] + [n for n in names if n not in racemod.ORDER_FIRST]
    return racesim.build_exe(names)


class Car:
    CAR, OTHER, VEH, VOICE, STACK, RET = 0x07400000, 0x07410000, 0x07420000, 0x07430000, 0x07500000, 0x07600000

    def __init__(self, exe, model="01"):
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_32)
        secs = racemod.sections(exe)
        end = max(b + v for b, v, _, _ in secs)
        mu.mem_map(0x00400000, (end - 0x00400000 + 0xFFF) & ~0xFFF)
        mu.mem_write(0x00400000, exe[:0x1000])
        for b, v, raw, rsz in secs:
            mu.mem_write(b, exe[raw:raw + rsz])
        mu.mem_map(0x07400000, 0x300000, UC_PROT_ALL)
        mu.mem_write(self.RET, b"\xcc")
        for stub in (0x00539D20, 0x00538DD0):
            mu.mem_write(stub, b"\xc2\x08\x00")
        self.forces = {}
        mu.hook_add(UC_HOOK_CODE, self._force, begin=0x00539D20, end=0x00539D20)
        self.brakes = {}
        mu.hook_add(UC_HOOK_CODE, self._brake, begin=0x00538DD0, end=0x00538DD0)
        self.name, self.mass, self.fbase, self.accel, (front, rear) = CARS[model]
        self.vd = 0.06 * self.fbase
        for car in (self.CAR, self.OTHER):
            self.wf(car + 0x7f84, self.fbase)
            self.wf(car + 0x7f88, self.fbase)
            self.wf(car + 0x7f78, self.accel)
            self.w32(car + 0x7fb0, front)
            self.w32(car + 0x7fb4, rear)
            self.w32(car + 0x8024, self.VEH)
            self.w32(car + 0x7ff0, self.VOICE)
            self.wf(car + 0xa24, 10.0)
        self.w32(self.VOICE + 0x114, 22050)
        self.WHEELS = self.VEH + 0x1000              # btRaycastVehicle m_wheelInfo: 4 x 0x118, all on the ground
        self.w32(self.VEH + racemod.BT_WHEELS, self.WHEELS)
        self.ground()
        self.wf(0x012D04A8, DT)
        self.w32(0x012D041C, 0)                  # sound off unless a test turns it on
        self.w32(0x00590448, 1)                  # game running (not paused)
        self.player = True
        self.v = 0.0
        self.wheel_k = 0.5 if (front and rear and AWDFIX) else 1.0    # awdfix: AWD wheels get F/2
        # drag LINEAR in speed (Bullet linear damping), measured 2026-11-01 (re-tools/coastdown.py: speed decays
        # ~12-13 %/s from 50 to 130 km/h, same for an 800 kg Clio and the police car): stock force = drag at Vd
        self.c_drag = 2 * (front + rear) * self.fbase * self.wheel_k / (self.vd / 3.6)

    def ground(self, touching=(1, 1, 1, 1)):
        for i, c in enumerate(touching):
            self.mu.mem_write(self.WHEELS + i * racemod.BT_WHEEL_SIZE + racemod.BT_IN_CONTACT, bytes([c]))

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def wf(self, a, v):
        self.mu.mem_write(a, struct.pack("<f", v))

    def u32(self, a):
        return struct.unpack("<I", self.mu.mem_read(a, 4))[0]

    def f32(self, a):
        return struct.unpack("<f", self.mu.mem_read(a, 4))[0]

    def _force(self, uc, addr, size, _):
        esp = uc.reg_read(UC_X86_REG_ESP)
        f = struct.unpack("<f", uc.mem_read(esp + 4, 4))[0]
        wheel = struct.unpack("<I", uc.mem_read(esp + 8, 4))[0]
        self.forces[wheel] = f

    def _brake(self, uc, addr, size, _):
        esp = uc.reg_read(UC_X86_REG_ESP)
        self.brakes[struct.unpack("<I", uc.mem_read(esp + 8, 4))[0]] = struct.unpack("<f", uc.mem_read(esp + 4, 4))[0]

    def step(self, throttle=0.0, brake=0.0, hb=0, integrate=True):
        car = self.CAR if self.player else self.OTHER
        self.w32(0x012D0C88, self.CAR)
        self.wf(car + 0x7f70, self.v)
        self.wf(car + 0x7f8c, throttle)
        self.wf(car + 0x7f94, brake)
        self.w32(car + 0x7f98, hb)
        self.forces = {}
        self.brakes = {}
        esp = self.STACK + 0x8000
        self.w32(esp, self.RET)
        for r, v in ((UC_X86_REG_EBX, 0x1111), (UC_X86_REG_EDI, 0x3333), (UC_X86_REG_EBP, 0x4444)):
            self.mu.reg_write(r, v)
        self.mu.reg_write(UC_X86_REG_ESP, esp)
        self.mu.reg_write(UC_X86_REG_ECX, car)
        self.mu.emu_start(0x004345E0, self.RET, count=100000)
        assert self.mu.reg_read(UC_X86_REG_ESP) == esp + 4, "stack"
        assert (self.mu.reg_read(UC_X86_REG_EBX), self.mu.reg_read(UC_X86_REG_EDI), self.mu.reg_read(UC_X86_REG_EBP)) \
            == (0x1111, 0x3333, 0x4444), "callee-saved registers"
        ftot = sum(self.forces.values())
        if integrate:
            fd = self.c_drag * (self.v / 3.6)
            ftot_c = max(-1.1 * self.mass * 9.81, min(1.1 * self.mass * 9.81, ftot))   # tyre grip
            a = (ftot_c - fd) / self.mass
            if brake > 0 and self.v > 0:
                a -= 8.0
            self.v += a * DT * 3.6
        return ftot


def manual_state(c):
    M = racemod.MD
    return c.u32(M["GEAR"]), c.f32(M["RPM"]), c.f32(M["SHIFT_T"])


def accel_run(c, manual, shift_at=0.95, seconds=40.0):
    """Full throttle from 0; manual: shift up at RPM >= shift_at. -> list of (t, v, gear, rpm, force)."""
    c.v = 0.0
    for car in (c.CAR, c.OTHER):
        c.wf(car + 0x7f80, 0.0)
    if manual:
        c.w32(racemod.MD["GEAR"], 1)
        c.w32(racemod.MD["UP"], 0)
        c.w32(racemod.MD["DN"], 0)
        c.wf(racemod.MD["SHIFT_T"], 0.0)
    out = []
    t = 0.0
    while t < seconds:
        f = c.step(throttle=2000.0)
        g, r, _ = manual_state(c) if manual else (0, 0, 0)
        if manual and r >= shift_at and g < racemod.MAN_GEARS and c.u32(racemod.MD["UP"]) == 0 \
                and c.f32(racemod.MD["SHIFT_T"]) == 0:
            c.w32(racemod.MD["UP"], 1)
        out.append((t, c.v, g, r, f))
        t += DT
    return out


def t_to(run, kmh):
    for t, v, *_ in run:
        if v >= kmh:
            return t
    return float("inf")


def main():
    model = next((a for a in sys.argv[1:] if a in CARS), "01")
    st = racemod.load_state()
    base = [n for n in st.get("extras", []) if n in racemod.EXTRAS and n not in GEARBOXES]
    print(f"car {model} {CARS[model][0]}; extras: saved + manual ({racemod.MAN_GEARS} gears {racemod.MAN_TABLES[racemod.MAN_GEARS]})")
    exe_stock = build(base)
    exe_man = build(base + ["manual"])
    s = Car(exe_stock, model)
    m = Car(exe_man, model)

    print("1. traffic/police/racers (not the player's car) drive exactly like the stock exe")
    import random
    rnd = random.Random(7)
    same = True
    for c in (s, m):
        c.player = False
        c.v = 0.0
        c.wf(c.OTHER + 0x7f80, 0.0)
    for i in range(3000):
        th = rnd.choice((0.0, 2000.0, 2000.0))
        br = rnd.choice((0.0, 0.0, 0.0, 100.0))
        hb = 1 if rnd.random() < 0.03 else 0
        fs = s.step(th, br, hb)
        fm = m.step(th, br, hb, integrate=False)
        m.v = s.v
        same &= (s.forces == m.forces)
    check("3000 random steps (throttle/brake/handbrake, forward and reverse): identical wheel forces", same)
    for c in (s, m):
        c.player = True

    print("2. acceleration, full throttle from 0 (stock vs manual shifting at 95% revs)")
    rs = accel_run(s, False)
    rm = accel_run(m, True)
    for k in (30, 50, 80, 100):
        print(f"     0-{k:3d} km/h: stock {t_to(rs, k):6.2f} s   manual {t_to(rm, k):6.2f} s")
    vs, vm = rs[-1][1], rm[-1][1]
    print(f"     after 40 s: stock {vs:.1f} km/h, manual {vm:.1f} km/h in gear {rm[-1][2]} at {rm[-1][3]:.2f} revs "
          f"(design speed {s.vd:.0f})")
    check("top speed within 3% of stock", abs(vm - vs) / vs < 0.03, f"{vm:.1f} vs {vs:.1f}")
    # instant throttle: the manual pulls at full force from the first step, the stock F still creeps up -
    # compare with the stock launch boost at FULL force (1 + 50 accel/40) x max force on every driven wheel
    stock_full = m.fbase * m.wheel_k * (1 + 50 * m.accel / 40) * len(m.forces)
    ratio = rm[0][4] / stock_full
    check(f"1st-gear launch force at a standstill within 10% of the stock launch boost at full force (x{ratio:.3f})",
          abs(ratio - 1) < 0.10)
    shifts = [rm[i][0] for i in range(1, len(rm)) if rm[i][2] != rm[i - 1][2]]
    seq = [rm[0][2]] + [rm[i][2] for i in range(1, len(rm)) if rm[i][2] != rm[i - 1][2]]
    check(f"shifts go up one gear at a time from 1st ({seq}; top speed comes in gear {rm[-1][2]})",
          seq == list(range(1, len(seq) + 1)), f"shift times {[round(x, 2) for x in shifts]}")
    cut = [f for t, v, g, r, f in rm if shifts and shifts[0] <= t < shifts[0] + racemod.MAN_SHIFT_TIME - 2 * DT]
    check("no drive force while the clutch is in (0.25 s after each shift)", cut and all(f == 0 for f in cut),
          f"{len(cut)} steps")

    print("3. rev limiter: stay in 1st")
    m.v = 0.0
    m.wf(m.CAR + 0x7f80, 0.0)
    m.w32(racemod.MD["GEAR"], 1)
    lim = []
    for i in range(int(8 / DT)):
        f = m.step(2000.0)
        lim.append((m.v, manual_state(m)[1], f))
    top1 = max(v for v, r, f in lim)
    s1 = racemod.MAN_TABLES[racemod.MAN_GEARS][0] * m.vd
    check(f"1st tops out at its redline speed ({top1:.1f} km/h, redline {s1:.1f})", abs(top1 - s1) < 2.0)
    check("no force at or above the redline", all(f == 0 for v, r, f in lim if r >= 1.0))

    print("4. neutral, engine braking, bogging, brake/reverse")
    m.w32(racemod.MD["GEAR"], 0)
    m.wf(m.CAR + 0x7f80, m.fbase)
    m.v = 40.0
    f = m.step(2000.0, integrate=False)
    check("neutral: no drive force with full throttle", f == 0)
    m.w32(racemod.MD["GEAR"], 2)
    m.v = 50.0
    m.wf(m.CAR + 0x7f80, 0.0)
    f = m.step(0.0, integrate=False)
    r = manual_state(m)[1]
    gt = racemod.MAN_TABLES[racemod.MAN_GEARS]
    want = -racemod.MAN_EB * m.fbase * m.wheel_k * (1 + m.accel * 1.25 * (gt[-1] / gt[1] - 1) / (gt[-1] / gt[0] - 1)) \
        * (min(r, 1.15) - racemod.MAN_IDLE)
    nw = sum(1 for v in m.forces.values())
    check(f"off throttle in 2nd at 50 km/h: engine braking {f:.0f} N total (rpm {r:.2f})", f < 0 and abs(f - want * nw) < 1.0,
          f"want {want * nw:.0f}")
    m.v = 0.0
    m.wf(m.CAR + 0x7f80, m.fbase)
    m.w32(racemod.MD["GEAR"], 1)
    m.wf(racemod.MD["ENG"], 0.0)                # gears written directly: no left-over revs (a key shift resets them)
    f1 = m.step(2000.0, integrate=False)
    m.w32(racemod.MD["GEAR"], 3)
    m.wf(racemod.MD["ENG"], 0.0)
    f3 = m.step(2000.0, integrate=False)
    check(f"standstill: 3rd bogs ({f3:.0f} N) far below 1st ({f1:.0f} N)", 0 < f3 < 0.15 * f1)
    rows = []
    for c in (s, m):
        c.wf(c.CAR + 0x7f80, 0.0)
        c.wf(c.CAR + 0x7f90, 0.0)
    for v in (20.0, 5.0, 0.5, 0.0, 0.0, -0.5, -3.0):   # hold Down while the car slows, stops, rolls back
        for c in (s, m):
            c.v = v
            for i in range(30):
                f = c.step(0.0, 100.0, integrate=False)
            rows.append((c is m, v, f, min(c.brakes.values() or [0.0])))
    for c in (s, m):
        c.wf(c.CAR + 0x7f80, 0.0)
    st_rev = [r for r in rows if not r[0] and r[2] < 0]
    mrows = [r for r in rows if r[0]]
    print("     hold Down:  " + "  ".join(f"{v:+.1f} km/h: stock {fs:+.0f} N brake {bs:.0f} / manual {fm:+.0f} N "
                                          f"brake {bm:.0f}" for (_, v, fs, bs), (_, _, fm, bm) in zip(rows[0::2], rows[1::2])))
    check(f"Down arrow = brake only: never a reverse push, the brake stays full at every speed "
          f"(the stock game reverses at {len(st_rev)} of 7 speeds)",
          all(f == 0 and b == 100.0 for _, v, f, b in mrows) and st_rev)

    print("5. engine sound pitch follows the RPM")
    for c in (s, m):
        c.w32(0x012D041C, 1)
    pitches = []
    for g, v in ((1, 10.0), (1, 30.0), (2, 30.0), (3, 30.0)):
        m.w32(racemod.MD["GEAR"], g)
        m.v = v
        m.wf(m.CAR + 0x8000, 22050.0)
        for i in range(120):
            m.step(2000.0, integrate=False)
        pitches.append(m.f32(m.CAR + 0x8000))
        print(f"     gear {g} at {v:.0f} km/h: rpm {manual_state(m)[1]:.2f}  pitch {pitches[-1]:.0f} Hz (base 22050)")
    check("pitch rises with revs in a gear, drops on each upshift", pitches[1] > pitches[0] and pitches[1] > pitches[2] > pitches[3])
    m.w32(0x012D041C, 0)

    print("6. keys: X / Z through the window-procedure hook")
    KU, KD = racemod.MAN_KEY_UP, racemod.MAN_KEY_DOWN
    mu = m.mu
    for vk, field, rep in ((KU, "UP", 0), (KD, "DN", 0), (KU, "UP", 1), (0x45, None, 0), (0x52, None, 0)):
        m.w32(racemod.MD["UP"], 0)
        m.w32(racemod.MD["DN"], 0)
        esp = m.STACK + 0x9000
        m.w32(esp, vk)                       # the pushed argument of 0x00454a80
        m.w32(esp + 0x28, 0x00120001 | (rep << 30))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_EBX, vk)
        mu.emu_start(0x0045677E, 0x00456783, count=1000)
        up, dn = m.u32(racemod.MD["UP"]), m.u32(racemod.MD["DN"])
        want = {"UP": (1, 0), "DN": (0, 1), None: (0, 0)}[field] if not rep else (0, 0)
        check(f"key {vk:#x}{' (auto-repeat)' if rep else ''}: up {up} down {dn}, back at 0x00456783, stack kept",
              (up, dn) == want and mu.reg_read(UC_X86_REG_EIP) == 0x00456783 and mu.reg_read(UC_X86_REG_ESP) == esp)
    m.w32(0x00590448, 0)
    m.w32(racemod.MD["UP"], 0)
    esp = m.STACK + 0x9000
    m.w32(esp, KU)
    m.w32(esp + 0x28, 0x00120001)
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_EBX, KU)
    mu.emu_start(0x0045677E, 0x00456783, count=1000)
    check("paused (menu): X is ignored", m.u32(racemod.MD["UP"]) == 0)
    m.w32(0x00590448, 1)

    print("7. HUD: the gear under the speedometer's speed number")
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_FPSW
    HUDO, FONTLOG = m.VOICE + 0x1000, []
    m.wf(m.VOICE + 0x800, 20.0)                     # the stubbed text width
    mu.mem_write(0x004702A0, bytes.fromhex("d905") + struct.pack("<I", m.VOICE + 0x800) + bytes.fromhex("c20c00"))
    mu.mem_write(0x00470260, bytes.fromhex("d905") + struct.pack("<I", m.VOICE + 0x800) + bytes.fromhex("c21800"))

    def font(uc, addr, size, _):
        e = uc.reg_read(UC_X86_REG_ESP)
        a = [struct.unpack("<I", uc.mem_read(e + 4 + 4 * i, 4))[0] for i in range(6)]
        FONTLOG.append((addr, uc.reg_read(UC_X86_REG_ECX), a))
    mu.hook_add(UC_HOOK_CODE, font, begin=0x004702A0, end=0x004702A0)
    mu.hook_add(UC_HOOK_CODE, font, begin=0x00470260, end=0x00470260)
    fl = lambda u: struct.unpack("<f", struct.pack("<I", u))[0]
    for gear, v, want in ((1, 30.0, b"1"), (0, 0.0, b"N"), (4, 80.0, b"4"), (2, -5.0, b"2"), (-1, -5.0, b"R")):
        m.w32(racemod.MD["GEAR"], gear)
        m.wf(m.CAR + 0x7f70, v)
        FONTLOG.clear()
        esp = m.STACK + 0x9000
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_EBX, HUDO)
        sw0 = mu.reg_read(UC_X86_REG_FPSW)
        mu.emu_start(0x00468265, 0x0046826A, count=2000)
        txt = bytes(mu.mem_read(racemod.MD["GEARTXT"], 2))
        draw = [a for adr, c, a in FONTLOG if adr == 0x00470260]
        ok = (len(FONTLOG) == 2 and all(c == HUDO for _, c, _ in FONTLOG) and txt == want + bytes(1) and draw
              and abs(fl(draw[0][0]) - (racemod.MAN_HUD_X - 10.0)) < 1e-4 and fl(draw[0][1]) == racemod.MAN_HUD_Y
              and draw[0][2] == racemod.MD["GEARTXT"] and draw[0][3] == racemod.MAN_HUD_COLOR
              and fl(draw[0][4]) == racemod.MAN_HUD_SCALE and draw[0][5] == 1)
        check(f"gear {gear} at {v:+.0f} km/h shows {want.decode()!r}, centred at x {racemod.MAN_HUD_X:g}, y {racemod.MAN_HUD_Y:g}; "
              "stack, FPU stack, eax = player car, back at 0x0046826a",
              ok and mu.reg_read(UC_X86_REG_ESP) == esp and mu.reg_read(UC_X86_REG_FPSW) == sw0
              and mu.reg_read(UC_X86_REG_EAX) == m.CAR and mu.reg_read(UC_X86_REG_EIP) == 0x0046826A,
              f"text {txt!r}, calls {len(FONTLOG)}")

    print("8. instant throttle, tachometer needle, shift light")
    from unicorn.x86_const import UC_X86_REG_XMM0
    m.v = 30.0
    m.w32(racemod.MD["GEAR"], 2)
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.wf(m.CAR + 0x7f80, 0.0)
    m.step(2000.0, integrate=False)
    check("throttle down in gear: engine force jumps straight to the max force (no creeping)",
          m.f32(m.CAR + 0x7f80) == m.f32(m.CAR + 0x7f84), f"F {m.f32(m.CAR + 0x7f80):.0f} of {m.f32(m.CAR + 0x7f84):.0f}")
    s.v = 30.0
    s.wf(s.CAR + 0x7f80, 0.0)
    s.step(2000.0, integrate=False)
    check("stock game (no manual): the force still creeps", 0 < s.f32(s.CAR + 0x7f80) < 0.1 * s.f32(s.CAR + 0x7f84))
    TD = racemod.TD
    m.wf(0x012D04A8, 1 / 60)

    def tach(rpm):
        m.wf(racemod.MD["RPM"], rpm)
        m.wf(racemod.MD["ENG"], 0.0)            # engine RPM = the wheels (no clutch slip)
        esp = m.STACK + 0x9000
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_EAX, m.CAR)
        sw0 = mu.reg_read(UC_X86_REG_FPSW)
        mu.emu_start(0x00468036, 0x0046807A, count=2000)
        ang = struct.unpack("<f", struct.pack("<I", mu.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF))[0]
        ok = (mu.reg_read(UC_X86_REG_ESP) == esp - 4 and mu.reg_read(UC_X86_REG_EIP) == 0x0046807A
              and mu.reg_read(UC_X86_REG_FPSW) == sw0)
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(0x00468119, 0x0046811E, count=100)
        col = m.u32(esp - 4)
        ok &= mu.reg_read(UC_X86_REG_ESP) == esp - 4 and mu.reg_read(UC_X86_REG_EIP) == 0x0046811E
        return ang, col, ok
    full = 0.8 * 1.5 * math.pi
    m.wf(TD["TACH"], 0.5)
    a, c, ok = tach(0.5)
    check(f"RPM 0.50: needle at {math.degrees(a):.0f} deg (redline = {math.degrees(full):.0f} deg, where the old "
          "needle stopped), stock olive; stack + FPU kept, back at 0x0046807a / 0x0046811e",
          ok and abs(a - 0.5 * full) < 1e-4 and c == racemod.TACH_COLOR)
    a, c, ok = tach(0.0)
    check(f"one frame later, RPM 0: the needle swings smoothly ({a / full:.3f} revs), not a jump",
          ok and abs(a / full - (0.5 - (0.5 - 0.15) * 0.25)) < 1e-4)
    for i in range(60):
        a, c, ok = tach(0.0)
    check(f"standing still in gear: the needle settles on idle ({a / full:.3f})", ok and abs(a / full - 0.15) < 1e-3)
    m.wf(TD["TACH"], 0.95)
    m.wf(TD["BLINKT"], 0.0)
    cols = [tach(0.95)[1] for i in range(60)]
    flips = sum(1 for i in range(1, 60) if cols[i] != cols[i - 1])
    red = sum(1 for x in cols if x == racemod.TACH_COLOR_SHIFT)
    check(f"RPM 0.95 (shift light from {racemod.TACH_SHIFT}): blinks red {(flips + 1) // 2} times a second, red {red}/60 frames",
          14 <= flips <= 17 and 26 <= red <= 34 and set(cols) == {racemod.TACH_COLOR, racemod.TACH_COLOR_SHIFT})
    m.wf(TD["TACH"], 1.3)
    a, c, ok = tach(1.3)
    check(f"past the redline: the needle stops at {a / full:.2f} revs", ok and abs(a - 1.1 * full) < 1e-4)
    m.wf(TD["TACH"], 0.6)
    a, c, ok = tach(0.6)
    check("back below the shift light: olive again", ok and c == racemod.TACH_COLOR)

    print("9. clutch (hold Shift)")
    CF = racemod.MAN_CLUTCH_FLAG
    m.w32(racemod.MD["GEAR"], 2)
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.v = 40.0
    f0 = m.step(2000.0, integrate=False)
    r_wheel = manual_state(m)[1]
    m.w32(CF, 1)
    revs = []
    for i in range(int(1.5 / DT)):
        revs.append((m.step(2000.0, integrate=False), manual_state(m)[1]))
    check(f"clutch in + gas at 40 km/h in 2nd: no drive force (was {f0:.0f} N)", all(f == 0 for f, r in revs))
    check(f"... and the engine free-revs from {r_wheel:.2f} to {revs[-1][1]:.2f} in 1.5 s, smoothly",
          revs[-1][1] > 0.95 and all(b[1] >= a[1] - 1e-6 for a, b in zip(revs, revs[1:])) and revs[1][1] - revs[0][1] < 0.1)
    off = []
    for i in range(int(2.0 / DT)):
        off.append((m.step(0.0, integrate=False), manual_state(m)[1]))
    check(f"clutch in, off the gas: no engine braking, revs fall to idle ({off[-1][1]:.2f})",
          all(f == 0 for f, r in off) and abs(off[-1][1] - racemod.MAN_IDLE) < 0.02)
    m.w32(CF, 0)
    f1 = m.step(2000.0, integrate=False)
    check(f"let go of the clutch: drive is back ({f1:.0f} N), revs from the wheels again ({manual_state(m)[1]:.2f})",
          f1 > 0 and abs(manual_state(m)[1] - r_wheel) < 1e-4)
    m.w32(CF, 1)
    for c in (s, m):
        c.v = 20.0
        c.wf(c.CAR + 0x7f80, 0.0)
    ok = True
    for v in (20.0, 0.0, -2.0):
        m.v = v
        for i in range(30):
            f = m.step(0.0, 100.0, integrate=False)
        ok &= f == 0 and min(m.brakes.values()) == 100.0
    check("clutch held + Down: brake only, no reverse", ok)
    m.w32(CF, 0)

    print("10. clutch dump (flywheel kick)")
    ENG, RPM = racemod.MD["ENG"], racemod.MD["RPM"]
    m.w32(racemod.MD["GEAR"], 1)
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    s.v = m.v = 0.0
    m.wf(ENG, 0.0)
    m.wf(m.CAR + 0x7f80, 0.0)                   # out of the reverse left by test 9
    m.wf(m.CAR + 0x7f90, 0.0)
    m.step(0.0, integrate=False)
    f_plain = m.step(2000.0, integrate=False)
    m.w32(CF, 1)
    for i in range(int(1.5 / DT)):
        m.step(2000.0, integrate=False)
    e0 = m.f32(ENG)
    m.w32(CF, 0)
    dump = []
    for i in range(int(1.0 / DT)):
        f = m.step(2000.0)
        dump.append((f, m.f32(ENG), m.f32(RPM), m.v))
    k0 = dump[0][0] / f_plain
    print(f"     revved to {e0:.2f} with the clutch in, dumped at 0 km/h in 1st:")
    for i in (0, 3, 7, 15, 30, 59):
        f, e, r, v = dump[i]
        print(f"       t {i * DT:4.2f} s  force x{f / f_plain:.2f}  engine {e:.2f}  wheels/slip {r:.2f}  {v:5.1f} km/h")
    check(f"dump from the limiter at a standstill: x{k0:.2f} the normal 1st-gear launch force", 1.8 < k0 < 2.2)
    t_end = next((i * DT for i, d in enumerate(dump) if d[1] <= d[2] + 0.01), None)
    check(f"the kick fades as the revs fall to the wheels ({t_end} s), then normal drive",
          t_end is not None and t_end < 0.8
          and all(b[1] <= a[1] + 1e-6 for a, b in zip(dump, dump[1:round(t_end / DT)])))
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.w32(racemod.MD["GEAR"], 2)
    m.v = 40.0
    m.wf(ENG, 0.0)
    m.step(2000.0, integrate=False)
    m.w32(racemod.MD["UP"], 1)
    m.w32(racemod.MD["GEAR"], 2)
    m.v = 60.0
    m.step(2000.0, integrate=False)
    check("plain upshift (no clutch): the engine RPM resets to the wheels - no kick",
          m.f32(ENG) == 0.0 or abs(m.f32(ENG) - manual_state(m)[1]) < 1e-4)
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.v = 60.0
    m.wf(ENG, 0.0)
    fa = m.step(2000.0, integrate=False)
    fb = m.step(2000.0, integrate=False)
    check(f"clutch never touched: force steady ({fa:.0f} / {fb:.0f} N), ENG = wheel RPM",
          abs(fa - fb) < 1e-3 and abs(m.f32(ENG) - m.f32(RPM)) < 1e-6)

    print("11. reverse gear")
    G = racemod.MD["GEAR"]

    def press(field, v):
        m.v = v
        m.wf(racemod.MD["SHIFT_T"], 0.0)
        m.w32(racemod.MD[field], 1)
        m.step(0.0, integrate=False)
        return m.u32(G) if m.u32(G) < 0x80000000 else m.u32(G) - 0x100000000
    m.w32(G, 0)
    check("Z at 30 km/h in N: R refused (too fast), stays N", press("DN", 30.0) == 0)
    check("Z at 2 km/h in N: R", press("DN", 2.0) == -1)
    check("Z in R: nothing lower", press("DN", 0.0) == -1)
    check("X: R -> N -> 1", press("UP", 0.0) == 0 and press("UP", 0.0) == 1)
    m.w32(G, 0xFFFFFFFF)
    m.v = 0.0
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.wf(racemod.MD["ENG"], 0.0)
    m.wf(m.CAR + 0x7f80, 0.0)
    rv = []
    for i in range(int(6 / DT)):
        f = m.step(2000.0)
        rv.append((f, m.v, manual_state(m)[1]))
    m.w32(G, 1)
    m.v = 0.0
    m.wf(m.CAR + 0x7f80, 0.0)
    m.wf(racemod.MD["ENG"], 0.0)                # no left-over revs = no clutch-dump kick
    f1 = m.step(2000.0, integrate=False)
    gt1 = racemod.MAN_TABLES[racemod.MAN_GEARS][0] * m.vd
    print(f"     R + gas from 0: {rv[int(1 / DT)][1]:.1f} km/h after 1 s, {rv[-1][1]:.1f} km/h after 6 s")
    check(f"R + gas: same launch push as 1st, backwards ({rv[0][0]:.0f} vs {f1:.0f} N)", abs(rv[0][0] + f1) < 1e-3)
    check(f"R tops out at 1st gear's redline speed backwards ({rv[-1][1]:.1f}, redline -{gt1:.1f})",
          abs(rv[-1][1] + gt1) < 2.0 and all(f <= 0 for f, v, r in rv))
    m.w32(G, 0xFFFFFFFF)
    m.v = -20.0
    f = m.step(0.0, integrate=False)
    check(f"R off the gas at -20 km/h: engine braking pushes forward ({f:.0f} N)", f > 0)
    m.v = -20.0
    f = m.step(0.0, 100.0, integrate=False)
    check("R + Down: brake, no push", f == 0 and min(m.brakes.values()) > 0)
    m.w32(G, 1)

    print("12. wheels off the ground (airborne, two wheels)")
    m.w32(racemod.MD["GEAR"], 3)
    m.wf(racemod.MD["SHIFT_T"], 0.0)
    m.v = 60.0
    m.wf(racemod.MD["ENG"], 0.0)
    m.step(2000.0, integrate=False)
    r_road = manual_state(m)[1]
    fr = m.u32(m.CAR + 0x7fb0), m.u32(m.CAR + 0x7fb4)
    m.ground((0, 0, 0, 0))
    air = [m.step(2000.0, integrate=False) for i in range(int(1.0 / DT))]
    e_air = m.f32(racemod.MD["ENG"])
    check(f"airborne + gas in 3rd at 60 km/h: the engine revs up from {r_road:.2f} to {e_air:.2f} in 1 s (no load)",
          e_air > 0.9 and abs(m.f32(racemod.MD["KC"])) < 1e-6)
    for i in range(int(2.0 / DT)):
        m.step(0.0, integrate=False)
    check(f"airborne, off the gas: revs fall to idle ({m.f32(racemod.MD['ENG']):.2f})",
          abs(m.f32(racemod.MD["ENG"]) - racemod.MAN_IDLE) < 0.03)
    for i in range(int(1.0 / DT)):
        m.step(2000.0, integrate=False)
    m.ground()
    f_land = m.step(2000.0, integrate=False)
    m.wf(racemod.MD["ENG"], 0.0)
    m.step(2000.0, integrate=False)
    f_norm = m.step(2000.0, integrate=False)
    check(f"touch down at full revs: the landing kicks (x{f_land / f_norm:.2f}), then normal drive",
          f_land > 1.2 * f_norm and m.f32(racemod.MD["KC"]) == 1.0)
    driven = [i for i, d in ((0, fr[0]), (1, fr[0]), (2, fr[1]), (3, fr[1])) if d]
    two = [1, 1, 1, 1]
    two[driven[0]] = 0                                   # left side up: one driven wheel off the ground
    m.ground(tuple(two))
    m.wf(racemod.MD["ENG"], 0.0)
    for i in range(int(2.0 / DT)):
        f2 = m.step(2000.0, integrate=False)
    kc = m.f32(racemod.MD["KC"])
    want = kc * r_road + (1 - kc) * 1.0
    check(f"two wheels (driven wheels touching {kc:.2f}): revs flare part-way to {m.f32(racemod.MD['ENG']):.2f} "
          f"(road {r_road:.2f}, target {want:.2f}), no kick", 0 < kc < 1 and abs(m.f32(racemod.MD["ENG"]) - want) < 0.02
          and abs(f2 - f_norm) < 1e-3)
    m.ground()
    m.wf(racemod.MD["ENG"], 0.0)

    print("13. power slider (manpower)")
    mp = Car(build(base + ["manual", "manpower"]), model)
    for p, want in ((100.0, "same as without the slider"), (0.0, "never above stock")):
        racemod.set_manpower(p)
        mp = Car(build(base + ["manual", "manpower"]), model)
        worst = 0.0
        same = True
        for v in (5.0, 20.0, 40.0, 60.0, 90.0, 110.0):
            s.v = v
            s.wf(s.CAR + 0x7f80, s.fbase)
            fs = s.step(2000.0, integrate=False)
            for g in range(1, racemod.MAN_GEARS + 1):
                for c in (m, mp):
                    c.v = v
                    c.w32(racemod.MD["GEAR"], g)
                    c.wf(racemod.MD["SHIFT_T"], 0.0)
                    c.wf(racemod.MD["ENG"], 0.0)
                    c.wf(c.CAR + 0x7f80, c.fbase)
                f_m, f_p = m.step(2000.0, integrate=False), mp.step(2000.0, integrate=False)
                same &= abs(f_m - f_p) < 1e-3
                worst = max(worst, f_p / fs)
        if p == 100.0:
            check(f"power 100 %: every gear at every speed {want}", same)
        else:
            check(f"power 0 %: the strongest gear at any speed is x{worst:.3f} stock ({want})", worst <= 1.0005)
    racemod.set_manpower(racemod.MAN_POWER_DEFAULT)

    if "--plot" in sys.argv:
        out = sys.argv[sys.argv.index("--plot") + 1]
        from PIL import Image, ImageDraw          # (matplotlib is not installed)
        W, H, L, B = 900, 560, 50, 40
        img = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(img)
        tmax, vmax = rs[-1][0], max(max(r[1] for r in rs), max(r[1] for r in rm)) * 1.1
        X = lambda t: L + (W - L - 10) * t / tmax
        Y = lambda v, top, h: top + h - h * v / vmax if vmax else top
        for k in range(0, int(vmax) + 1, 20):
            d.line([(L, Y(k, 10, 330)), (W - 10, Y(k, 10, 330))], fill=(225, 225, 225))
            d.text((5, Y(k, 10, 330) - 6), f"{k}", fill="gray")
        for run, col in ((rs, (40, 90, 200)), (rm, (220, 110, 20))):
            d.line([(X(r[0]), Y(r[1], 10, 330)) for r in run], fill=col, width=2)
        vmax_r = vmax
        vmax = 1.1
        d.line([(X(r[0]), Y(r[3], 360, 160)) for r in rm], fill=(220, 110, 20), width=2)
        d.line([(X(r[0]), Y(r[2] / 10, 360, 160)) for r in rm], fill=(40, 160, 60), width=2)
        d.text((L + 10, 14), f"{CARS[model][0]}: km/h, full throttle from 0 - blue stock, orange manual "
               f"{racemod.MAN_GEARS}-speed (real drive code)", fill="black")
        d.text((L + 10, 364), "orange: revs (1 = redline)   green: gear / 10", fill="black")
        d.text((W - 60, H - 20), f"{tmax:.0f} s", fill="gray")
        img.save(out)
        print("plot ->", out)
    print(f"\n{sum(OK)}/{len(OK)} checks passed" + ("" if all(OK) else "  <-- FAILURES"))
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
