r"""s2check.py - Unicorn proofs for the Stage 2 extras (2026-10-04 onwards).

Each check builds the exe twice in memory (stock baseline and baseline + the extra, plus everything the
player has installed, so the caves are tested alongside the real neighbours), runs the GAME'S OWN code
on mock objects, and compares. game.exe on disk is never touched.
Usage: s2check.py [name ...]     (default: every check)
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_PROT_ALL, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_XMM3, UC_X86_REG_XMM4, UC_X86_REG_XMM5,
                               UC_X86_REG_EIP)

IMG = 0x00400000
STACK = 0x00100000
MOCK = 0x07000000
TRAP = 0x07F00000
INSTALLED = ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach",
             "view", "overlay", "racers", "shadows", "nodamage", "modsect", "panini", "fixedstep",
             "engineloop"]
OK = []


def check(label, ok, extra=""):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}{('  ' + extra) if extra else ''}")


class Emu:
    def __init__(self, names):
        exe = racesim.build_exe(names)
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        secs = racemod.sections(exe)
        end = max(base + vsz for base, vsz, _, _ in secs)
        end = max(end, racemod.MOD_VA + racemod.MOD_VSIZE)
        mu.mem_map(IMG, (end - IMG + 0xFFF) & ~0xFFF)
        mu.mem_write(IMG, exe[:0x1000])
        for base, vsz, raw, rsz in secs:
            mu.mem_write(base, exe[raw:raw + rsz])
        mu.mem_map(STACK, 0x100000)
        mu.mem_map(MOCK, 0x400000, UC_PROT_ALL)
        mu.mem_map(TRAP, 0x1000, UC_PROT_ALL)
        mu.mem_write(TRAP, b"\xcc")

    def u32(self, a): return struct.unpack("<I", self.mu.mem_read(a, 4))[0]
    def f32(self, a): return struct.unpack("<f", self.mu.mem_read(a, 4))[0]
    def w32(self, a, v): self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
    def wf(self, a, v): self.mu.mem_write(a, struct.pack("<f", v))

    def run(self, start, stop, regs, count=200000):
        for r, v in regs.items():
            self.mu.reg_write(r, v)
        self.mu.emu_start(start, stop, count=count)


def xmm_f(mu, reg):
    return struct.unpack("<f", (mu.reg_read(reg) & 0xFFFFFFFF).to_bytes(4, "little"))[0]


# ================================================================== awdfix
def check_awdfix():
    print("awdfix: the drive code's applyEngineForce calls, stock vs fixed")
    stock = Emu(INSTALLED)
    fixed = Emu(INSTALLED + ["awdfix"])
    CAR, VEH, WHEELS = MOCK, MOCK + 0x10000, MOCK + 0x11000
    SENT = -12345.0
    for front, rear in ((0, 1), (1, 0), (1, 1), (0, 0), (7, 1), (1, 0x100)):
        for F in (2000.0, 3500.0, -800.0, 0.0):
            got = {}
            for label, e in (("stock", stock), ("fixed", fixed)):
                e.mu.mem_write(CAR, bytes(0x8200))
                e.w32(CAR + 0x7fb0, front)
                e.w32(CAR + 0x7fb4, rear)
                e.w32(CAR + 0x8024, VEH)
                e.w32(VEH + 0xa4, WHEELS)
                for i in range(4):
                    e.wf(WHEELS + i * 0x118 + 0xf8, SENT)
                esp = STACK + 0x80000
                e.mu.mem_write(esp, bytes(0x40))
                e.wf(esp + 4, F)
                e.mu.reg_write(UC_X86_REG_XMM1, 0)
                e.run(0x0043491D, 0x004349A1, {UC_X86_REG_ESI: CAR, UC_X86_REG_ESP: esp,
                                                UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x2222,
                                                UC_X86_REG_EBP: 0x3333})
                w = [e.f32(WHEELS + i * 0x118 + 0xf8) for i in range(4)]
                regs_ok = (e.mu.reg_read(UC_X86_REG_ESP) == esp and e.mu.reg_read(UC_X86_REG_ESI) == CAR
                           and e.mu.reg_read(UC_X86_REG_EBX) == 0x1111
                           and e.mu.reg_read(UC_X86_REG_EDI) == 0x2222
                           and e.mu.reg_read(UC_X86_REG_EBP) == 0x3333
                           and (e.mu.reg_read(UC_X86_REG_XMM1) & 0xFFFFFFFF) == 0)
                got[label] = (w, regs_ok)
            ws, wf_ = got["stock"][0], got["fixed"][0]
            awd = bool(front) and bool(rear)
            want = [(F / 2 if awd else F) if (x != SENT) else SENT for x in ws]
            total_s = sum(x for x in ws if x != SENT)
            total_f = sum(x for x in wf_ if x != SENT)
            two_wheel = 2 * F if (front or rear) else 0.0
            ok = wf_ == want and got["fixed"][1] and got["stock"][1] and abs(total_f - two_wheel) < 1e-3
            kind = "AWD" if awd else "FWD" if front else "RWD" if rear else "none"
            check(f"{kind:<4} flags ({front:#x},{rear:#x}) F={F:>7.1f}: stock push {total_s:>7.1f}, "
                  f"fixed {total_f:>7.1f}", ok, "" if ok else f"stock {ws} fixed {wf_}")


# ================================================================== gravity
def check_gravity():
    print("gravity: the game's world setup -> Bullet's setGravity -> a body added afterwards")
    for g in (racemod.GRAVITY_DEFAULT, 3.71, 24.8, 0.5, 30.0):
        racemod.set_gravity(g)
        res = {}
        for label, names in (("stock", INSTALLED), ("gravity", INSTALLED + ["gravity"])):
            e = Emu(names)
            GAME, WORLD, ARR, OBJ0, BODY = MOCK, MOCK + 0x30000, MOCK + 0x31000, MOCK + 0x32000, MOCK + 0x33000
            e.mu.mem_write(GAME, bytes(0x30000))
            e.mu.mem_write(WORLD, bytes(0x400))
            e.w32(WORLD, 0x0058125C)                      # the real btDiscreteDynamicsWorld vtable
            e.w32(GAME + 0x28288, WORLD)
            # one body already in the world (setGravity walks them) ...
            e.w32(WORLD + 8, 1)
            e.w32(WORLD + 0x10, ARR)
            e.w32(ARR, OBJ0)
            e.mu.mem_write(OBJ0, bytes(0x400))
            e.w32(OBJ0 + 0xcc, OBJ0)
            e.wf(OBJ0 + 0x138, 1 / 1000.0)                # inverse mass: a 1000 kg car
            esp = STACK + 0x80000
            e.mu.mem_write(esp, bytes(0x100))
            e.run(0x004254C7, 0x00425502, {UC_X86_REG_ESI: GAME, UC_X86_REG_ESP: esp,
                                            UC_X86_REG_EAX: 0x5555, UC_X86_REG_EDI: 0x2222})
            wg = [e.f32(WORLD + 0x64 + 4 * i) for i in range(4)]
            old = [e.f32(OBJ0 + 0x140 + 4 * i) for i in range(3)]
            # ... and one added later through the real addRigidBody (dynamic: flags 0, no broadphase)
            e.mu.mem_write(BODY, bytes(0x400))
            e.wf(BODY + 0x138, 1 / 1500.0)
            e.w32(esp, TRAP)
            e.w32(esp + 4, BODY)
            e.run(0x0053B240, TRAP, {UC_X86_REG_ECX: WORLD, UC_X86_REG_ESP: esp})
            new = [e.f32(BODY + 0x140 + 4 * i) for i in range(3)]
            res[label] = (wg, old, new, e.mu.reg_read(UC_X86_REG_ESP) == esp + 8,
                          e.u32(GAME + 0x2828c) == 0x5555)
        sw, so, sn, sok, sstore = res["stock"]
        gw, go, gn, gok, gstore = res["gravity"]
        ok = (sw[1] == -10.0 and abs(gw[1] + g) < 1e-6 and sw[0] == sw[2] == gw[0] == gw[2] == 0
              and abs(so[1] + 10.0 * 1000) < 1e-2 and abs(go[1] + g * 1000) < 1e-2
              and abs(sn[1] + 10.0 * 1500) < 1e-2 and abs(gn[1] + g * 1500) < 1e-2
              and sok and gok and sstore and gstore)
        check(f"g={g:>5g}: world y stock {sw[1]:g} -> {gw[1]:.4g}; 1000 kg body force {so[1]:.0f} -> "
              f"{go[1]:.1f} N; 1500 kg added later {sn[1]:.0f} -> {gn[1]:.1f} N", ok)
    racemod.set_gravity(racemod._saved("gravity_ms2", racemod.GRAVITY_DEFAULT))
    e = Emu(INSTALLED + ["gravity"])
    check("the shared -10 at 0x005692c0 is untouched (Bullet's own readers keep it)",
          e.f32(0x005692C0) == -10.0)


# ================================================================== revboost
DT = 0x012D04A8                                   # game dt, seconds


class Drive:
    """Runs the game's whole drive function 0x004345e0 for one mock car, frame by frame."""
    CAR, VEH, WHEELS = MOCK + 0x40000, MOCK + 0x50000, MOCK + 0x51000

    def __init__(self, names, fmax=2000.0, accel=2.0, front=0, rear=1):
        self.e = e = Emu(names)
        e.mu.mem_write(self.CAR, bytes(0x8200))
        e.w32(self.CAR + 0x8024, self.VEH)
        e.w32(self.VEH + 0xa4, self.WHEELS)
        e.w32(self.CAR + 0x7fb0, front)
        e.w32(self.CAR + 0x7fb4, rear)
        e.wf(self.CAR + 0x7f84, fmax)
        e.wf(self.CAR + 0x7f78, accel)

    def frame(self, v_kmh, thr=0.0, brk=0.0, hand=0, dt=1 / 60):
        e, c = self.e, self.CAR
        e.wf(DT, dt)
        e.wf(c + 0x7f70, v_kmh)
        e.wf(c + 0x7f8c, thr)
        e.wf(c + 0x7f94, brk)
        e.w32(c + 0x7f98, hand)
        for i in range(4):
            e.wf(self.WHEELS + i * 0x118 + 0xf8, 0.0)
        esp = STACK + 0x80000
        e.w32(esp, TRAP)
        e.run(0x004345E0, 0x004349A1, {UC_X86_REG_ECX: c, UC_X86_REG_ESP: esp})
        return sum(e.f32(self.WHEELS + i * 0x118 + 0xf8) for i in range(4))

    def set(self, off, v): self.e.wf(self.CAR + off, v)
    def get(self, off): return self.e.f32(self.CAR + off)


def check_revboost():
    print("revboost: the game's whole drive function, stock vs boosted reverse")
    base = INSTALLED + ["awdfix"]
    accel = 2.0
    boost = lambda v: 1 + max(0.0, 50 - abs(v)) * accel / 40
    cases = [  # (label, F before, hold before, v km/h, thr, brk, hand, boosted?)
        ("throttle from rest", 0.0, 0.0, 0.0, 1.0, 0.0, 0, False),
        ("throttle at 30 km/h", 1500.0, 0.0, 30.0, 1.0, 0.0, 0, False),
        ("throttle at 90 km/h", 2000.0, 0.0, 90.0, 1.0, 0.0, 0, False),
        ("coasting forward", 1200.0, 0.0, 40.0, 0.0, 0.0, 0, False),
        ("coasting backward (pedal let go)", -1500.0, 0.0, -10.0, 0.0, 0.0, 0, False),
        ("braking at 60 km/h", 1500.0, 50.0, 60.0, 0.0, 100.0, 0, False),
        ("reverse pedal, first frames", 300.0, 10.0, 0.5, 0.0, 100.0, 0, False),
        ("handbrake + pedal", -1000.0, 100.0, -5.0, 0.0, 100.0, 1, False),
        ("reverse from rest", 0.0, 100.0, 0.0, 0.0, 100.0, 0, True),
        ("reverse at -5 km/h", -1800.0, 100.0, -5.0, 0.0, 100.0, 0, True),
        ("reverse at -30 km/h", -1500.0, 100.0, -30.0, 0.0, 100.0, 0, True),
        ("reverse at -60 km/h (past the boost)", -1000.0, 100.0, -60.0, 0.0, 100.0, 0, True),
        ("half pedal at -10 km/h", -1500.0, 100.0, -10.0, 0.0, 40.0, 0, True),
    ]
    st, rb = Drive(base), Drive(base + ["revboost"])
    for label, F, hold, v, thr, brk, hand, boosted in cases:
        out = []
        for d in (st, rb):
            d.set(0x7f80, F)
            d.set(0x7f90, hold)
            out.append((d.frame(v, thr, brk, hand), d.get(0x7f80), d.get(0x7f90)))
        (fs, Fs, hs), (fr, Fr, hr) = out
        want = fs * boost(v) if (boosted and fs < 0) else fs
        ok = abs(fr - want) <= 1e-3 * max(1.0, abs(want)) and Fs == Fr and hs == hr
        check(f"{label:<36} push stock {fs:>9.1f} N  revboost {fr:>9.1f} N", ok,
              f"(x{fr / fs:.2f})" if boosted and fs else "")

    # The player's case: back up a 25 deg slope, car 01 (1000 kg, force 2000, accel 2, RWD), from rest,
    # reverse pedal held. 1-D model around the game's own force: gravity m g sin(a) pulls downhill, the
    # driven axle's tyres can push at most friction x its share of m g cos(a) (Bullet caps each wheel's
    # impulse by m_frictionSlip x suspension force); the game reads the speed back in km/h.
    import math
    m, g, a, fric = 1000.0, 10.0, math.radians(25), 1.75
    pull = m * g * math.sin(a)
    grip = fric * m * g * math.cos(a) / 2
    for label, d in (("stock", Drive(base)), ("revboost", Drive(base + ["revboost"]))):
        v = x = 0.0                                       # m/s and metres UP the slope (backwards)
        d.set(0x7f80, 0.0)
        d.set(0x7f90, 0.0)
        peak = 0.0
        for _ in range(60 * 6):
            push = -d.frame(-v * 3.6, brk=100.0)          # the game's force, backwards = positive
            push = min(push, grip)
            acc = (push - pull) / m
            v = max(v + acc / 60, 0.0) if x <= 0 and acc < 0 else v + acc / 60
            x = max(x + v / 60, 0.0)
            peak = max(peak, push)
        climbs = x > 5
        check(f"25 deg slope, 6 s of reverse, {label:<8}: pushes up to {peak:6.0f} N against {pull:.0f} N -> "
              f"{x:5.1f} m up, {v * 3.6:4.1f} km/h", climbs == (label == "revboost"))


# ================================================================== policeeyes / morepolice
WANTED, PLAYER = 0x012D044C, 0x012D0C88


def check_police():
    print("policeeyes: the police AI's chase test at 0x0043cc6b, stock vs eyes")
    see = racemod.POLICE_SEE
    st, ey = Emu(INSTALLED), Emu(INSTALLED + ["policeeyes"])
    COP, ME = MOCK, MOCK + 0x10000

    def chases(e, d, wanted=0.5, kind=2, state=2):
        e.mu.mem_write(COP, bytes(0x2000))
        e.mu.mem_write(ME, bytes(0x2000))
        e.w32(COP + 0xc8c, kind)
        e.w32(ME + 0x1e70, state)
        e.wf(COP + 0xa18, 100.0); e.wf(COP + 0xa1c, 5.0); e.wf(COP + 0xa20, -50.0)
        e.wf(ME + 0xa18, 100.0 + d * 0.6); e.wf(ME + 0xa1c, 5.0); e.wf(ME + 0xa20, -50.0 + d * 0.8)
        e.w32(PLAYER, ME)
        e.wf(WANTED, wanted)
        esp = STACK + 0x80000
        e.mu.mem_write(esp, bytes(0x100))
        # stop at whichever comes first: the chase start (0x0043ccbf) or the skip target (0x0043cd3a)
        hs = [e.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.emu_stop(), begin=x, end=x)
              for x in (0x0043CD3A, 0x0043CCBF)]
        e.run(0x0043CC6B, 0x0043CD3B, {UC_X86_REG_ESI: COP, UC_X86_REG_ESP: esp})
        for h in hs:
            e.mu.hook_del(h)
        return e.mu.reg_read(UC_X86_REG_EIP) == 0x0043CCBF
    for d in (10.0, 39.0, 41.0, see - 1, see + 1, 155.0):
        s, n = chases(st, d), chases(ey, d)
        check(f"police {d:5.1f} m away, wanted 0.5: stock {'CHASES' if s else 'ignores'}, eyes "
              f"{'CHASES' if n else 'ignores'}", s == (d < 40) and n == (d < see))
    for label, kw in (("not wanted (0.2)", dict(wanted=0.2)), ("a traffic car", dict(kind=3)),
                      ("player state != 2", dict(state=1))):
        check(f"30 m, {label}: nobody chases", not chases(st, 30, **kw) and not chases(ey, 30, **kw))

    print("morepolice: the spawner's police decision, stock vs fixed")
    st, mp = Emu(INSTALLED), Emu(INSTALLED + ["morepolice"])
    MGR = MOCK + 0x100000
    CARS = MOCK + 0x200000
    RAND = [0]

    def setup(e):
        def fake_rand(uc, a, s, u):                     # rand() returns RAND[0]: eax, then `ret`
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EAX, RAND[0])
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
        e.mu.hook_add(UC_HOOK_CODE, fake_rand, begin=0x0054ABA3, end=0x0054ABA3)
    for e in (st, mp):
        setup(e)

    def decide(e, alive, spawned, r, wanted=0.5):
        e.mu.mem_write(MGR, bytes(0x14000))
        kinds = [0] + alive                               # slot 0 = the player
        for i, k in enumerate(kinds):
            car = CARS + i * 0x1000
            e.w32(car + 0xc8c, k)
            e.w32(MGR + 0x28 + 4 * i, car)
        e.w32(MGR + 0x128, len(kinds))
        e.w32(MGR + 0x13dc4, spawned)
        e.wf(WANTED, wanted)
        RAND[0] = r
        esp = STACK + 0x80000
        e.mu.mem_write(esp - 0x100, bytes(0x200))
        e.run(0x00442E3C, 0x00442E7C, {UC_X86_REG_EDI: MGR, UC_X86_REG_ESP: esp, UC_X86_REG_EAX: 4,
                                        UC_X86_REG_XMM0: 0, UC_X86_REG_EBP: 0x7777})
        ok = (e.mu.reg_read(UC_X86_REG_ESP) == esp - 4 and e.u32(esp - 4) == 0x7777
              and (e.mu.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF) == 0
              and e.mu.reg_read(UC_X86_REG_EDI) == MGR)
        return e.mu.reg_read(UC_X86_REG_EBP), ok
    three = [3] * 20
    cases = [
        ("no police alive, 0 spawned so far", [3] * 10, 0),
        ("no police alive, 4 spawned earlier (all gone)", [3] * 10, 4),
        ("3 police alive", [2, 2, 2] + three, 3),
        ("4 police alive", [2] * 4 + three, 4),
        (f"{racemod.POLICE_MAX - 1} police alive", [2] * (racemod.POLICE_MAX - 1) + three, 9),
        (f"{racemod.POLICE_MAX} police alive", [2] * racemod.POLICE_MAX + three, 9),
        ("2 racers + 1 police alive", [1, 1, 2] + three, 5),
    ]
    for label, alive, spawned in cases:
        rows = {}
        for name, e in (("stock", st), ("more", mp)):
            hits = 0
            regs_ok = True
            for r in range(101):
                kind, ok = decide(e, alive, spawned, r)
                hits += kind != 0
                regs_ok &= ok
            rows[name] = (hits, regs_ok)
        npol = alive.count(2)
        want_s = 11 if spawned < 4 else 0
        want_m = (101 - racemod.POLICE_CHANCE_THRESH) if npol < racemod.POLICE_MAX else 0
        check(f"{label:<46} police chance stock {rows['stock'][0]:>2}/101, fixed {rows['more'][0]:>2}/101",
              rows["stock"] == (want_s, True) and rows["more"] == (want_m, True))
    k_hi, _ = decide(mp, [3] * 5, 0, 100, wanted=0.9)
    k_lo, _ = decide(mp, [3] * 5, 0, 100, wanted=0.5)
    check(f"wanted 0.9 -> pursuit model ({k_hi}), 0.5 -> patrol model ({k_lo}), as stock", (k_hi, k_lo) == (2, 1))

    see = racemod.EVADE
    print(f"evade: the wanted meter's 'chaser nearby' test at 0x0043f82d (real search 0x00441b70), "
          f"stock 60 m vs evade {see:g} m")
    st, ey = Emu(INSTALLED + ["policeeyes"]), Emu(INSTALLED + ["policeeyes", "evade"])
    MGR, NEAR, DT = 0x02649368, 0x012D0448, 0x012D04A8

    def meter(e, d, state=4, wanted=0.5, dt=0.1):
        e.mu.mem_write(COP, bytes(0x2000))
        e.mu.mem_write(ME, bytes(0x8000))
        e.w32(COP + 0x1e74, state)
        e.wf(ME + 0xa18, 100.0); e.wf(ME + 0xa1c, 5.0); e.wf(ME + 0xa20, -50.0)
        e.wf(COP + 0xa18, 100.0 + d * 0.6); e.wf(COP + 0xa1c, 5.0); e.wf(COP + 0xa20, -50.0 + d * 0.8)
        e.wf(ME + 0x7f70, 60.0)                         # driving, so no "busted" timer
        e.w32(MGR + 0x128, 1)
        e.w32(MGR + 0x28, COP)
        e.wf(WANTED, wanted)
        e.wf(DT, dt)
        e.w32(NEAR, 7)
        esp = STACK + 0x80000
        e.mu.mem_write(esp - 0x100, bytes(0x200))
        e.run(0x0043F82D, 0x0043F909, {UC_X86_REG_ESI: ME, UC_X86_REG_ESP: esp, UC_X86_REG_XMM0: 0})
        return e.f32(WANTED), e.u32(NEAR), e.mu.reg_read(UC_X86_REG_ESP) == esp
    drained = 0.5 - 0.1 * 0.025
    for d in (30.0, 59.0, 61.0, see - 1, see + 1):
        (ws, fs, oks), (we, fe, oke) = meter(st, d), meter(ey, d)
        ok = (abs(ws - (0.5 if d < 60 else drained)) < 1e-6 and fs == (d < 60)
              and abs(we - (0.5 if d < see else drained)) < 1e-6 and fe == (d < see) and oks and oke)
        check(f"chasing cop {d:5.1f} m away: stock {'holds' if fs else 'DRAINS'} ({ws:.4f}), evade "
              f"{'holds' if fe else 'DRAINS'} ({we:.4f})", ok)
    w, f, _ = meter(ey, 30.0, state=2)
    check(f"a cop 30 m away that is NOT chasing: the meter drains as stock ({w:.4f})", abs(w - drained) < 1e-6 and f == 0)
    w, f, _ = meter(ey, see + 10, wanted=0.001)
    check(f"draining stops at 0, as stock (0.001 -> {w:.4f})", w == 0.0)


# ================================================================== wantedhits
def check_wantedhits():
    print("wantedhits: the player-collision handler's wanted changes, stock vs harsher (HUD bars = wanted * 10.5)")
    st, wh = Emu(INSTALLED), Emu(INSTALLED + ["wantedhits"])
    CAR, PED, ME = MOCK, MOCK + 0x10000, MOCK + 0x20000
    PEDS = 0x012D0430
    bars = lambda w: min(10, int(w * 10.5))

    def cop_hit(e, wanted, impact=0.6, kind=2):
        e.mu.mem_write(CAR, bytes(0x2000))
        e.w32(CAR + 0xc8c, kind)
        e.wf(WANTED, wanted)
        e.mu.reg_write(UC_X86_REG_XMM1, struct.unpack("<I", struct.pack("<f", impact))[0])
        e.mu.reg_write(UC_X86_REG_XMM4, struct.unpack("<I", struct.pack("<f", 0.3))[0])
        e.run(0x0043A884, 0x0043A8B3, {UC_X86_REG_EBX: CAR, UC_X86_REG_EAX: 2})
        return e.f32(WANTED), xmm_f(e.mu, UC_X86_REG_XMM3)

    for w0 in (0.0, 0.2, 0.45, 0.7):
        (ws, xs), (ww, xw) = cop_hit(st, w0), cop_hit(wh, w0)
        ok = (abs(ws - max(w0, 0.3)) < 1e-6 and abs(ww - max(w0, racemod.WANTED_COP)) < 1e-6
              and xs == ws and xw == ww)
        check(f"hit a police car at {bars(w0)} bars: stock -> {bars(ws)} bars, harsher -> {bars(ww)} bars", ok)
    (ws, _), (ww, _) = cop_hit(st, 0.1, kind=3), cop_hit(wh, 0.1, kind=3)
    check(f"hit a traffic car: no police floor in either ({ws:.2f} / {ww:.2f})", ws == ww and abs(ws - 0.1) < 1e-6)
    (ws, _), (ww, _) = cop_hit(st, 0.1, impact=0.28), cop_hit(wh, 0.1, impact=0.28)
    check(f"a light touch on a police car (impact 0.28 < 0.3): no floor in either", abs(ws - 0.1) < 1e-6 and ws == ww)

    def ped_hit(e, wanted):
        e.w32(PEDS, 0)
        e.wf(WANTED, wanted)
        e.mu.reg_write(UC_X86_REG_XMM3, struct.unpack("<I", struct.pack("<f", wanted))[0])
        e.mu.reg_write(UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", 1.0))[0])
        e.run(0x0043A975, 0x0043A9AF, {UC_X86_REG_EBX: PED})
        return e.f32(WANTED), e.u32(PEDS)

    for w0 in (0.0, 0.3, 0.55, 0.9):
        (ws, ns), (ww, nw) = ped_hit(st, w0), ped_hit(wh, w0)
        ok = (abs(ws - min(1.0, max(0.26, w0 + 0.2))) < 1e-6
              and abs(ww - min(1.0, max(0.26, w0 + racemod.WANTED_PED))) < 1e-6 and ns == nw == 1)
        check(f"hit a pedestrian at {bars(w0)} bars: stock -> {bars(ws)} (+{bars(ws) - bars(w0)}), "
              f"harsher -> {bars(ww)} (+{bars(ww) - bars(w0)})", ok)


# ================================================================== adaptive
class Physics:
    """The game's world update 0x00421ee0 -> Bullet's REAL stepSimulation (0x0053bfc0) on a stub world
    with no bodies; internalSingleStepSimulation is a stub that logs each step's size."""
    GAME, BW, VT, STUBS = MOCK + 0x100000, MOCK + 0x200000, MOCK + 0x201000, MOCK + 0x202000

    def __init__(self, names):
        self.e = e = Emu(names)
        mu = e.mu
        for a, n in ((0x0053BFC7, 6), (0x0053BFCE, 7), (0x0053C0FF, 7)):   # SEH frame (fs:) -> nops
            mu.mem_write(a, b"\xb8\0\0\0\0\x90" if n == 6 else b"\x90" * n)
        for a in (0x0054A790, 0x0054A8D0, 0x0054A7E0, 0x0054A730):          # profiler -> ret
            mu.mem_write(a, b"\xc3")
        self.steps = []
        self.bad = []
        nargs = {0x0c: 0, 0x54: 0, 0x5c: 1, 0x64: 0}
        for off in range(0, 0x100, 4):
            s = self.STUBS + off * 4
            n = nargs.get(off)
            mu.mem_write(s, (b"\xc2" + struct.pack("<H", 4 * n)) if n else b"\xc3")
            e.w32(self.VT + off, s)
            mu.hook_add(UC_HOOK_CODE, self._stub, begin=s, end=s, user_data=off)
        e.w32(self.VT + 0x14, 0x0053BFC0)                                    # the real stepSimulation
        mu.mem_write(self.GAME, bytes(0x28300))
        e.w32(self.GAME + 0x28288, self.BW)
        e.w32(0x012D0C90, 0)
        mu.mem_write(self.BW, bytes(0x100))
        e.w32(self.BW, self.VT)

    def _stub(self, uc, addr, size, off):
        if off == 0x5c:
            sp = uc.reg_read(UC_X86_REG_ESP)
            self.steps.append(struct.unpack("<f", uc.mem_read(sp + 4, 4))[0])
        elif off == 0x0c:
            uc.reg_write(UC_X86_REG_EAX, 0)                                   # no debug drawer
        elif off not in (0x54, 0x64):
            self.bad.append(off)

    def frame(self, dt):
        e = self.e
        e.wf(0x012D04A8, dt)
        esp = STACK + 0x80000
        before = len(self.steps)
        e.run(0x00421EE0, 0x00421F18, {UC_X86_REG_ECX: self.GAME, UC_X86_REG_ESP: esp, UC_X86_REG_ESI: 0x5151})
        assert e.mu.reg_read(UC_X86_REG_ESI) == self.GAME and e.mu.reg_read(UC_X86_REG_ESP) == esp - 4, \
            "stack/esi not kept"
        return self.steps[before:], e.f32(self.BW + 0x74)


def check_adaptive():
    hz = racemod.FIXED_HZ
    print(f"adaptive: world update -> Bullet's real stepSimulation, floor {hz:g} Hz (fixedstep vs adaptive)")
    sims = {"fixedstep": Physics(INSTALLED), "adaptive": Physics(INSTALLED + ["adaptive"])}
    import random
    for fps in (300, 144, 100, hz + 1, hz, hz - 1, 72, 60, 45, 30, 20, 12, 5):
        rows = {}
        for name, p in sims.items():
            p.e.w32(p.BW + 0x74, 0)
            n_per, sizes, total, left = [], [], 0.0, 0.0
            for _ in range(120):
                dt = min(1.0 / fps, 0.05)
                st, left = p.frame(dt)
                n_per.append(len(st))
                sizes += st
                total += sum(st)
            rows[name] = (n_per, sizes, total, left)
        dt = min(1.0 / fps, 0.05)
        game_t = dt * 120
        f, a = rows["fixedstep"], rows["adaptive"]
        if dt <= 1.0 / hz:     # at or above the floor: one step of dt per frame, nothing left over
            ok = (set(a[0]) == {1} and all(abs(s - dt) <= 1e-6 * dt for s in a[1])
                  and abs(a[2] - game_t) < 1e-4 * game_t and abs(a[3]) < 1e-6)
            mode = f"1 step/frame of {dt * 1000:5.2f} ms = {1 / dt:5.1f} Hz"
        else:                  # below: identical to fixedstep
            ok = a[0] == f[0] and a[1] == f[1] and a[3] == f[3]
            mode = f"{min(a[0])}..{max(a[0])} steps of {1000 / hz:5.2f} ms (= fixedstep)"
        ok = ok and not any(p.bad for p in sims.values())
        rate_a = len(a[1]) / game_t
        rate_f = len(f[1]) / game_t
        check(f"{fps:>5.0f} FPS: adaptive {mode:<38} {rate_a:5.0f} steps/s (fixedstep {rate_f:4.0f})", ok
              and rate_a <= max(1 / dt, hz) * 1.02)
    # jittery frame times across the floor: exact time, every step <= 1/Hz
    p = sims["adaptive"]
    p.e.w32(p.BW + 0x74, 0)
    rnd = random.Random(7)
    total = game = worst = 0.0
    nsteps = 0
    for _ in range(2000):
        dt = min(rnd.choice([rnd.uniform(0.003, 0.0105), rnd.uniform(0.0105, 0.08)]), 0.05)
        st, left = p.frame(dt)
        game += dt
        total += sum(st)
        nsteps += len(st)
        worst = max([worst] + st)
    check(f"2000 jittery frames (3..50 ms, crossing the floor): {total + left:.4f} s simulated of "
          f"{game:.4f} s, longest step {worst * 1000:.2f} ms (floor {1000 / hz:.2f}), {nsteps} steps",
          abs(total + left - game) < 1e-3 and worst <= 1 / hz * (1 + 1e-3))
    before = p.e.f32(p.BW + 0x74)
    st, left = p.frame(0.0)
    check("paused (dt 0): no step, the accumulator untouched", st == [] and left == before)


# ================================================================== smartpolice
HEADING = (0.0, 1.0)


def smart_reference(route, cop, kmh, heading=(0.0, 1.0)):
    """Python twin of cave A: (target index, cap km/h or None). route[0] = YOUR end."""
    global HEADING
    HEADING = heading
    R = racemod
    n = len(route)
    d2 = lambda p: (p[0] - cop[0]) ** 2 + (p[2] - cop[2]) ** 2
    j = min(range(n), key=lambda i: (d2(route[i]), i))
    L = min(max(abs(kmh) * R.SMART_LOOK_K, R.SMART_LOOK_MIN), R.SMART_LOOK_MAX)
    i = j
    while i > 0 and d2(route[i]) < L * L:
        i -= 1
    best = None
    B = R.SMART_BEND
    for k in range(j, 0, -1):
        if d2(route[k]) > R.SMART_DMAX ** 2:
            break
        if k + B < n:
            a = route[k + B]
            u1 = (route[k][0] - a[0], route[k][2] - a[2])
        else:                                             # the car's end: its heading, one chord long
            u1 = (HEADING[0] * 4 * B, HEADING[1] * 4 * B)
        q = route[max(k - B, 0)]
        u2 = (q[0] - route[k][0], q[2] - route[k][2])
        l1, l2 = math.hypot(*u1), math.hypot(*u2)
        if l1 < 1 or l2 < 1:
            continue
        t = math.hypot(u1[0] / l1 - u2[0] / l2, u1[1] / l1 - u2[1] / l2)
        if t < R.SMART_STRAIGHT:
            continue
        v2 = max((l1 + l2) / 2 / t * R.SMART_GRIP * 3.6 ** 2, R.SMART_VMIN ** 2)
        v2 += 2 * R.SMART_DECEL * 3.6 ** 2 * math.sqrt(d2(route[k]))
        best = v2 if best is None else min(best, v2)
    return i, (math.sqrt(best) if best is not None else None)


def check_smartpolice():
    print("smartpolice: cave A (route target + corner speed) and cave B (speed cap), vs a Python twin")
    e = Emu(INSTALLED + ["smartpolice"])
    CAR = MOCK
    SM = racemod.SM

    def route_L(straight, side, step=4.0, turn_left=True):
        """Your end first (the game's order): you are `side` m along a cross street, the corner is
        `straight` m ahead of a car driving north (+z) from (0, 0)."""
        pts = [(0.0, 0.0, z) for z in [step * i for i in range(int(straight / step) + 1)]]
        sgn = -1 if turn_left else 1
        pts += [(sgn * step * i, 0.0, pts[-1][2]) for i in range(1, int(side / step) + 1)]
        return pts[::-1]

    def run_a(route, cop, kmh, heading=(0.0, 1.0)):
        e.mu.mem_write(CAR, bytes(0x9000))
        e.mu.mem_write(CAR + 0x20, struct.pack("<3f", heading[0], 0.0, heading[1]))
        e.mu.mem_write(CAR + 0xa18, struct.pack("<3f", *cop))
        e.wf(CAR + 0x7f70, kmh)
        for i, p in enumerate(route):
            e.mu.mem_write(CAR + 0x1ecc + 12 * i, struct.pack("<3f", *p))
        e.w32(CAR + 0x7f44, len(route))
        e.w32(SM["CAR"], 0)
        esp = STACK + 0x80000
        e.mu.mem_write(esp - 0x40, bytes(0x80))
        e.run(0x0043D28A, 0x0043D2C7, {UC_X86_REG_EAX: len(route), UC_X86_REG_EBX: 0, UC_X86_REG_EBP: 1,
                                        UC_X86_REG_ESI: CAR, UC_X86_REG_EDI: 0x5555, UC_X86_REG_ESP: esp})
        regs = (e.mu.reg_read(UC_X86_REG_EBX), e.mu.reg_read(UC_X86_REG_EBP), e.mu.reg_read(UC_X86_REG_ESI),
                e.mu.reg_read(UC_X86_REG_EDI), e.mu.reg_read(UC_X86_REG_ESP))
        tgt = struct.unpack("<3f", e.mu.mem_read(CAR + 0x1e90, 12))
        return tgt, e.f32(SM["CAP"]), e.u32(SM["CAR"]), regs == (0, 1, CAR, 0x5555, esp)

    cases = [
        ("straight road, you 60 m ahead, 100 km/h", route_L(60, 0), (0.0, 0.0, 0.0), 100.0),
        ("corner 30 m ahead, you 20 m round it, 90 km/h", route_L(30, 20), (0.0, 0.0, 0.0), 90.0),
        ("corner 30 m ahead (right turn), 60 km/h", route_L(30, 20, turn_left=False), (0.0, 0.0, 0.0), 60.0),
        ("corner 10 m ahead, 50 km/h", route_L(10, 24), (0.0, 0.0, 0.0), 50.0),
        ("half a second old route: car already 12 m along it", route_L(40, 20), (0.6, 0.0, 12.3), 80.0),
        ("car 3 m off the route (pushed sideways)", route_L(40, 20), (3.0, 0.0, 6.0), 40.0),
        ("standing still at the corner", route_L(24, 24), (0.0, 0.0, 23.0), 0.0),
        ("corner 80 m ahead (beyond the 70 m check)", route_L(84, 20), (0.0, 0.0, 0.0), 120.0),
        ("car 2 m PAST its route's start, straight road", route_L(60, 0), (0.3, 0.0, 2.0), 90.0),
    ]
    for label, route, cop, kmh in cases:
        tgt, cap, car, regs = run_a(route, cop, kmh)
        i, want = smart_reference(route, cop, kmh)
        t_ok = max(abs(a - b) for a, b in zip(tgt, route[i])) < 1e-4
        c_ok = (cap > 1e14) if want is None else abs(cap - want) <= 0.002 * want + 0.01
        d_tgt = math.hypot(tgt[0] - cop[0], tgt[2] - cop[2])
        check(f"{label:<52} aim {d_tgt:4.1f} m ahead, cap "
              f"{'none' if cap > 1e14 else f'{cap:5.1f} km/h'}", t_ok and c_ok and car == CAR and regs,
              "" if t_ok and c_ok else f"target {tgt} want {route[i]}, cap {cap} want {want}")
    # the corner cap must grow with distance (brake early, not late) and be lowest at the corner
    caps = [run_a(route_L(40, 20), (0.0, 0.0, z), 60.0)[1] for z in (0.0, 10.0, 20.0, 30.0, 38.0)]
    check("approaching a 90-degree corner the cap falls steadily: " + " > ".join(f"{c:.0f}" for c in caps),
          all(a > b for a, b in zip(caps, caps[1:])) and caps[-1] < 50)

    st = Emu(INSTALLED)
    ME = MOCK + 0x20000

    def ram_aim(em, kmh):
        em.mu.mem_write(CAR, bytes(0x9000)); em.mu.mem_write(ME, bytes(0x9000))
        em.mu.mem_write(ME + 0x20, struct.pack("<3f", 0.0, 0.0, 1.0))
        em.mu.mem_write(ME + 0xa18, struct.pack("<3f", 10.0, 0.0, 50.0))
        em.wf(ME + 0x7f70, kmh)
        em.w32(PLAYER, ME)
        em.run(0x0043CF0B, 0x0043CF9B, {UC_X86_REG_ESI: CAR, UC_X86_REG_ESP: STACK + 0x80000})
        return struct.unpack("<3f", em.mu.mem_read(CAR + 0x1e90, 12))[2] - 50.0
    for kmh in (10.0, 50.0, 100.0, 180.0):
        a_st, a_sm = ram_aim(st, kmh), ram_aim(e, kmh)
        check(f"ramming (< 8 m), you at {kmh:3.0f} km/h: stock aims {a_st:4.1f} m ahead of you, smart {a_sm:4.1f} m",
              abs(a_st - min(kmh * 0.2, 20)) < 1e-4 and abs(a_sm - min(kmh * 0.2, racemod.SMART_RAM_LEAD)) < 1e-4)

    def run_b(car_tag, speed):
        e.w32(SM["CAR"], car_tag)
        e.wf(SM["CAP"], 40.0)
        e.mu.reg_write(UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", speed))[0])
        e.mu.reg_write(UC_X86_REG_XMM5, 0)
        e.run(0x0043D3DE, 0x0043D3E6, {UC_X86_REG_ESI: CAR})
        return xmm_f(e.mu, UC_X86_REG_XMM0), xmm_f(e.mu, UC_X86_REG_XMM5), e.u32(SM["CAR"])
    v, x5, c = run_b(CAR, 90.0)
    check(f"cave B: this car's target 90 km/h -> {v:g} (cap 40), flag cleared, xmm5 = {x5:g} as stock",
          v == 40.0 and x5 == 2.0 and c == 0)
    v, x5, c = run_b(CAR, 30.0)
    check(f"cave B: target 30 km/h under the cap stays {v:g}", v == 30.0 and x5 == 2.0)
    v, x5, c = run_b(CAR + 0x1000, 90.0)
    check(f"cave B: cap left by ANOTHER car is ignored ({v:g} km/h kept)", v == 90.0 and x5 == 2.0 and c == CAR + 0x1000)


# ================================================================== policefix
def check_policefix():
    print("policefix: the original chase AI, only the route aim fixed (cave vs the Python twin's target)")
    e = Emu(INSTALLED + ["policefix"])
    CAR = MOCK

    def route_L(straight, side, step=4.0):
        pts = [(0.0, 0.0, step * i) for i in range(int(straight / step) + 1)]
        pts += [(-step * i, 0.0, pts[-1][2]) for i in range(1, int(side / step) + 1)]
        return pts[::-1]

    for label, route, cop, kmh in [
        ("straight road, 100 km/h", route_L(60, 0), (0.0, 0.0, 0.0), 100.0),
        ("corner 30 m ahead, 90 km/h", route_L(30, 20), (0.0, 0.0, 0.0), 90.0),
        ("route 0.5 s old: car already 14 m along it, 100 km/h", route_L(60, 20), (0.4, 0.0, 14.0), 100.0),
        ("car 2 m PAST its route's start", route_L(60, 0), (0.3, 0.0, 2.0), 60.0),
        ("standing still", route_L(24, 24), (0.0, 0.0, 0.0), 0.0),
    ]:
        e.mu.mem_write(CAR, bytes(0x9000))
        e.mu.mem_write(CAR + 0x20, struct.pack("<3f", 0.0, 0.0, 1.0))
        e.mu.mem_write(CAR + 0xa18, struct.pack("<3f", *cop))
        e.wf(CAR + 0x7f70, kmh)
        for i, p in enumerate(route):
            e.mu.mem_write(CAR + 0x1ecc + 12 * i, struct.pack("<3f", *p))
        esp = STACK + 0x80000
        e.mu.mem_write(esp - 0x40, bytes(0x80))
        e.run(0x0043D28A, 0x0043D2C7, {UC_X86_REG_EAX: len(route), UC_X86_REG_EBX: 0, UC_X86_REG_EBP: 1,
                                        UC_X86_REG_ESI: CAR, UC_X86_REG_EDI: 0x5555, UC_X86_REG_ESP: esp})
        regs = (e.mu.reg_read(UC_X86_REG_EBX), e.mu.reg_read(UC_X86_REG_EBP), e.mu.reg_read(UC_X86_REG_ESI),
                e.mu.reg_read(UC_X86_REG_EDI), e.mu.reg_read(UC_X86_REG_ESP)) == (0, 1, CAR, 0x5555, esp)
        tgt = struct.unpack("<3f", e.mu.mem_read(CAR + 0x1e90, 12))
        i, _ = smart_reference(route, cop, kmh)
        ok = max(abs(a - b) for a, b in zip(tgt, route[i])) < 1e-4 and regs and tgt[2] >= cop[2] - 1e-3
        check(f"{label:<54} aims {math.hypot(tgt[0] - cop[0], tgt[2] - cop[2]):4.1f} m ahead (stock: 4 m from YOU)", ok)
    stock = racemod.PATCHES["smartpolice"]
    check("only the aim is patched: no speed cap, re-route interval, 22 m switch or ram lead",
          {va for va, *_ in racemod.PATCHES["policefix"]}.isdisjoint(
              {0x0043CDE2, 0x0043CE1F, 0x0043D3DE, 0x0043CF20}))


# ================================================================== milkyway
def check_milkyway():
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
          log["load"] == [b"Data/Sky/MilkyWay.dds"] and ok_regs and log["moon"] == [SKY])
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
          abs(em[0] - min(1, max(0, (0.5 - R.MW_FADE_START) * R.MW_RAMP)) * R.MW_BRIGHT) < 1e-5 and em[0] == em[1] == em[2]
          and log["tex"] and log["tex"][0][0] == 0x1234)
    ramp = lambda y: min(1.0, max(0.0, (-y - R.MW_FADE_START) * R.MW_RAMP))      # twilight fade
    for y, want in ((-0.3, ramp(-0.3)), (-0.2, ramp(-0.2)), (-0.1, ramp(-0.1)), (-0.081, ramp(-0.081)), (-0.0803, None),
                    (0.05, None)):
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

    # cloud shadow (2026-10-04): hook 0x004287b1 in the clouds pass, before their DrawSubset
    e3, log3 = setup()
    MESH, PP, XM, XVT = MOCK + 0x1000, MOCK + 0x1100, MOCK + 0x1200, MOCK + 0x1300
    subsets = []
    e3.mu.hook_add(UC_HOOK_CODE, (lambda uc, a, s_, u: (
        subsets.append(struct.unpack("<3I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP), 12))[1:]),
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP), 4))[0]),
        uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP) + 12))), begin=TRAP + 0x70, end=TRAP + 0x70)
    e3.w32(SKY + 0x1F0, MESH)
    e3.w32(MESH + 0x18C, PP)
    e3.w32(PP, XM)
    e3.w32(XM, XVT)
    e3.w32(XVT + 0xC, TRAP + 0x70)
    cloud_mat = struct.pack("<17f", *([0.0] * 12 + [0.123, 0.234, 0.345, 1.0, 0.0]))

    def clouds(y):
        e3.wf(NIGHT, y)
        esp = STACK + 0x80000
        e3.mu.mem_write(esp + 0x20, cloud_mat)
        regs = {UC_X86_REG_EBX: SKY, UC_X86_REG_ESI: 0x1111, UC_X86_REG_EDI: 0x2222, UC_X86_REG_EBP: 0x3333,
                UC_X86_REG_ESP: esp}
        e3.run(0x004287B1, 0x004287B7, regs, count=1_000_000)
        return all(e3.mu.reg_read(r) == v for r, v in regs.items()) and e3.mu.reg_read(UC_X86_REG_ECX) == MESH
    ok = clouds(-0.5)
    shade = R.MW_CLOUD_SHADE * min(1.0, max(0.0, (0.5 - R.MW_FADE_START) * R.MW_RAMP))
    check(f"night clouds: one extra DrawSubset(0) of the cloud mesh with ZERO/INVSRCCOLOR and emissive "
          f"{shade:.2f}, then the clouds' own material and ONE/ONE are back; the stock draw continues (ecx = mesh)",
          ok and subsets == [(XM, 0)] and log3["blend"] == [(1, 4), (2, 2)] and len(log3["mat"]) == 2
          and abs(log3["mat"][0][12] - shade) < 1e-6 and log3["mat"][1] == struct.unpack("<17f", cloud_mat))
    n_mat, n_blend = len(log3["mat"]), len(log3["blend"])
    ok = clouds(-0.05) and clouds(0.3)
    check("dusk/day clouds: no extra pass, no state touched (stock clouds)",
          ok and len(subsets) == 1 and len(log3["mat"]) == n_mat and len(log3["blend"]) == n_blend)


# ================================================================== boardkeep
def check_boardkeep():
    keep = racemod.BOARD_KEEP
    print(f"boardkeep: the race manager's despawn test at 0x004432ea (real distance 0x00454d50), stock 175 m vs {keep:g} m")
    MGR, CAM = 0x02649368, MOCK + 0x800

    def step(e, d):
        removed = []
        e.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s_, u: (
            removed.append(1),
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP), 4))[0]),
            uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP) + 4), uc.emu_stop()), begin=0x00440E90, end=0x00440E90)
        e.w32(0x02610010, CAM)
        e.mu.mem_write(CAM + 0x70, struct.pack("<3f", 300.0, 20.0, -900.0))
        e.mu.mem_write(MGR + 0xDD88, struct.pack("<3f", 300.0 + d * 0.6, 18.0, -900.0 - d * 0.8))
        esp = STACK + 0x80000
        e.run(0x004432EA, 0x00443313, {UC_X86_REG_ESI: MGR, UC_X86_REG_EDI: 10, UC_X86_REG_ESP: esp})
        return bool(removed), e.mu.reg_read(UC_X86_REG_ESP) == esp
    for d in (100.0, 174.0, 176.0, keep - 1, keep + 1):
        (rs, oks), (rk, okk) = step(Emu(INSTALLED), d), step(Emu(INSTALLED + ["boardkeep"]), d)
        check(f"board {d:6.1f} m from the camera: stock {'DELETES' if rs else 'keeps'}, boardkeep "
              f"{'DELETES' if rk else 'keeps'}", oks and okk and rs == (d > 175.0) and rk == (d > keep))
    def race_step(e, seen):
        gone = []
        def h_vis(uc, a, s_, u):
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EAX, int(seen))
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, sp + 12)
        def h_del(uc, a, s_, u):
            sp = uc.reg_read(UC_X86_REG_ESP)
            gone.append(1)
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, sp + 8)
        e.mu.hook_add(UC_HOOK_CODE, h_vis, begin=0x00401E40, end=0x00401E40)
        e.mu.hook_add(UC_HOOK_CODE, h_del, begin=0x004540C0, end=0x004540C0)
        e.w32(MGR + 0x13D98, MOCK + 0x5000)
        e.run(0x004419A5, 0x004419E9, {UC_X86_REG_ESI: MGR, UC_X86_REG_ESP: STACK + 0x80000})
        return bool(gone), e.u32(MGR + 0x13D98) != 0
    for seen in (True, False):
        (gs, ks), (gk, kk) = race_step(Emu(INSTALLED), seen), race_step(Emu(INSTALLED + ["boardkeep"]), seen)
        check(f"during a race, board {'in view' if seen else 'OUT of view'}: stock {'DELETES' if gs else 'keeps'}, "
              f"boardkeep {'DELETES' if gk else 'keeps'}",
              (gs, ks) == ((False, True) if seen else (True, False)) and (gk, kk) == (False, True))
    sites = {va for va, *_ in racemod.PATCHES["boardkeep"]}
    check("only the despawn test is repointed; spawn placement 0x00440673 and the minimap 0x00462a29 keep 175",
          0x004432FE in sites and not sites & {0x00440673, 0x00462A29})

# ================================================================== racereset
def check_racereset():
    lim = racemod.RACE_RESET
    print(f"racereset: the racer progress step 0x0043f4f0 (real code), player put back at stock 24 m vs {lim:g} m")
    CAR, AI = MOCK + 0x10000, MOCK + 0x30000

    def step(names, d, player=True):
        e = Emu(INSTALLED + names)
        resets = []

        def stub(nargs, rec=None):
            def h(uc, a, s_, u):
                sp = uc.reg_read(UC_X86_REG_ESP)
                if rec:
                    rec()
                uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 4 + 4 * nargs)
            return h
        # the 'passed this point?' transform (0x00454df0 look-at, D3DX 0x0047a010 inverse / 0x00479391
        # transform) goes through D3DX's CPU-dispatch table, unset in the harness: stub it so the car is
        # 1000 m to the side in the point's frame = progress does not advance (not what is tested here)
        def far_side():
            out = struct.unpack("<I", e.mu.mem_read(e.mu.reg_read(UC_X86_REG_ESP) + 4, 4))[0]
            e.mu.mem_write(out, struct.pack("<3f", 1000.0, 0.0, 0.0))
        for addr, h in ((0x00438E70, stub(0)), (0x0043DF30, stub(2, lambda: resets.append(1))),
                        (0x00441150, stub(1)), (0x004216B0, stub(3)), (0x00454DF0, stub(2)),
                        (0x0047A010, stub(3)), (0x00479391, stub(3, far_side))):
            e.mu.hook_add(UC_HOOK_CODE, h, begin=addr, end=addr)
        car = CAR if player else AI
        e.mu.mem_write(car, bytes(0x8100))
        e.w32(0x012D0C88, CAR)
        e.w32(0x0265D104, 1)
        e.w32(0x0265D0F0, 10)
        e.w32(car + 0x7F44, 10)
        e.w32(car + 0x7F48, 3)
        for i in range(10):                              # route along +z, 20 m apart
            e.mu.mem_write(car + 0x1ECC + 12 * i, struct.pack("<3f", 0.0, 5.0, 20.0 * i))
        e.wf(car + 0x8B4, 2.3)
        e.mu.mem_write(car + 0xA18, struct.pack("<3f", d, 5.0, 60.0))   # beside point 3, d m to the side
        esp = STACK + 0x80000
        e.run(0x0043F4F0, 0x0043F745, {UC_X86_REG_ECX: car, UC_X86_REG_ESP: esp}, count=2_000_000)
        return bool(resets)
    for d in (10.0, 23.0, 25.0, 100.0, lim - 1, lim + 1):
        rs, rr = step([], d), step(["racereset"], d)
        check(f"player {d:6.1f} m off the route point: stock {'RESETS' if rs else 'no reset'}, racereset "
              f"{'RESETS' if rr else 'no reset'}", rs == (d > 24.0) and rr == (d > lim))
    check("an AI racer far off the route is never reset (stock and patched)",
          not step([], 500.0, player=False) and not step(["racereset"], 500.0, player=False))

# ================================================================== rayfast
class RayWorld:
    """The game's REAL updateAabbs (0x0051d930) and rayTest (0x0051e8f0) on a mock collision world of
    box objects. Shapes' getAabb is a Python stub (exact rotated-box AABB); rayTestSingle (0x0051dc50)
    is a stub that records which objects reached the exact test."""
    WORLD, ARR, OBJS, SHAPES, VT, CB, MISC = (MOCK + 0x0, MOCK + 0x1000, MOCK + 0x10000, MOCK + 0x100000,
                                             MOCK + 0x180000, MOCK + 0x181000, MOCK + 0x182000)
    GETAABB, SETAABB, PROF = TRAP + 0x10, TRAP + 0x20, TRAP + 0x30
    OBJ_SZ = 0x100

    def __init__(self, names):
        self.e = e = Emu(names)
        mu = e.mu
        mu.mem_map(0, 0x1000)                              # fs:[0] (SEH chain) with a zero FS base
        mu.mem_write(TRAP + 0x10, b"\xc3" * 0x40)
        self.hits, self.aabb_calls = [], 0
        e.w32(self.VT + 4, self.GETAABB)
        e.w32(self.MISC, self.MISC + 0x10)                 # broadphase object -> vtable
        e.w32(self.MISC + 0x10 + 0xc, self.SETAABB)
        mu.hook_add(UC_HOOK_CODE, self._getaabb, begin=self.GETAABB, end=self.GETAABB)
        mu.hook_add(UC_HOOK_CODE, self._ret(0x10), begin=self.SETAABB, end=self.SETAABB)
        for f in (0x0054A8D0, 0x0054A730):                 # CProfileManager start/stop: cdecl, no work
            mu.hook_add(UC_HOOK_CODE, self._ret(0), begin=f, end=f)
        mu.hook_add(UC_HOOK_CODE, self._single, begin=0x0051DC50, end=0x0051DC50)
        # kernel32!VirtualAlloc through its import slot (the harness does not resolve imports): hand out
        # a zeroed block of mock memory, stdcall 4 args
        self.allocs = 0
        e.w32(0x00568170, TRAP + 0x50)

        def valloc(uc, a, s, u):
            self.allocs += 1
            sp = uc.reg_read(UC_X86_REG_ESP)
            size = struct.unpack("<I", uc.mem_read(sp + 12, 4))[0]
            uc.mem_write(MOCK + 0x200000, bytes(size))
            uc.reg_write(UC_X86_REG_EAX, MOCK + 0x200000)
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, sp + 20)
        mu.hook_add(UC_HOOK_CODE, valloc, begin=TRAP + 0x50, end=TRAP + 0x50)

    def _ret(self, n):
        def h(uc, a, s, u):
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, sp + 4 + n)
        return h

    def _getaabb(self, uc, a, s, u):
        sp = uc.reg_read(UC_X86_REG_ESP)
        ret, tr, mn, mx = struct.unpack("<4I", uc.mem_read(sp, 16))
        hx, hy, hz = struct.unpack("<3f", uc.mem_read(uc.reg_read(UC_X86_REG_ECX) + 0x10, 12))
        m = struct.unpack("<12f", uc.mem_read(tr, 48))
        o = struct.unpack("<3f", uc.mem_read(tr + 48, 12))
        ext = [abs(m[4 * r]) * hx + abs(m[4 * r + 1]) * hy + abs(m[4 * r + 2]) * hz for r in range(3)]
        uc.mem_write(mn, struct.pack("<3f", *[o[i] - ext[i] for i in range(3)]))
        uc.mem_write(mx, struct.pack("<3f", *[o[i] + ext[i] for i in range(3)]))
        self.aabb_calls += 1
        uc.reg_write(UC_X86_REG_EIP, ret)
        uc.reg_write(UC_X86_REG_ESP, sp + 16)

    def _single(self, uc, a, s, u):
        sp = uc.reg_read(UC_X86_REG_ESP)
        self.hits.append(struct.unpack("<I", uc.mem_read(sp + 12, 4))[0])    # arg 3 = the object
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(sp, 4))[0])
        uc.reg_write(UC_X86_REG_ESP, sp + 4)

    def build(self, objs):
        """objs: list of (obj slot, shape slot, (x,y,z), yaw, (hx,hy,hz), activation state)."""
        e = self.e
        e.mu.mem_write(self.WORLD, bytes(0x100))
        e.w32(self.WORLD + 8, len(objs))
        e.w32(self.WORLD + 0x10, self.ARR)
        e.w32(self.WORLD + 0x40, self.MISC)
        for i, (slot, sh, pos, yaw, half, state) in enumerate(objs):
            o, s = self.OBJS + slot * self.OBJ_SZ, self.SHAPES + sh * 0x40
            e.w32(self.ARR + 4 * i, o)
            self.place(slot, pos, yaw)
            e.w32(o + 0xa4, o + 0xe0)                     # broadphase proxy (filter group at +4)
            e.mu.mem_write(o + 0xe4, struct.pack("<H", 0xFFFF))
            e.w32(o + 0xa8, s)
            e.w32(o + 0xac, 0)
            e.w32(o + 0xb8, state)
            e.w32(s, self.VT)
            e.mu.mem_write(s + 0x10, struct.pack("<3f", *half))

    def place(self, slot, pos, yaw):
        c, s = math.cos(yaw), math.sin(yaw)
        self.e.mu.mem_write(self.OBJS + slot * self.OBJ_SZ + 4, struct.pack(
            "<12f3f", c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, *pos))

    def update_aabbs(self):
        esp = STACK + 0x80000
        self.e.w32(esp, TRAP)
        self.e.run(0x0051D930, TRAP, {UC_X86_REG_ECX: self.WORLD, UC_X86_REG_ESP: esp})

    def ray(self, a, b):
        e = self.e
        e.mu.mem_write(self.CB, bytes(0x40))
        e.w32(self.CB, 0x00568EA0)
        e.wf(self.CB + 4, 1.0)
        e.mu.mem_write(self.MISC + 0x100, struct.pack("<3f", *a))
        e.mu.mem_write(self.MISC + 0x110, struct.pack("<3f", *b))
        esp = STACK + 0x80000
        e.mu.mem_write(esp, struct.pack("<5I", TRAP, self.MISC + 0x100, self.MISC + 0x110, self.CB, 0xFFFFFFFF))
        self.hits = []
        self.aabb_calls = 0
        e.run(0x0051E8F0, TRAP, {UC_X86_REG_ECX: self.WORLD, UC_X86_REG_ESP: esp}, count=5_000_000)
        return sorted(self.hits), self.aabb_calls


def check_rayfast():
    import random
    print("rayfast: the game's real updateAabbs + rayTest on a mock world, stock vs rayfast "
          "(objects reaching the exact ray test must be IDENTICAL)")
    st, rf = RayWorld(INSTALLED), RayWorld(INSTALLED + ["rayfast"])
    rnd = random.Random(5)
    objs = []
    for i in range(200):
        car = i < 60
        half = (1.0, 0.7, 2.3) if car else (rnd.uniform(1, 25), rnd.uniform(0.5, 30), rnd.uniform(1, 25))
        pos = (rnd.uniform(-150, 150), half[1] if car else rnd.uniform(-2, 10), rnd.uniform(-150, 150))
        objs.append([i, i, pos, rnd.uniform(-3.2, 3.2), half, 1])
    for o in objs[150:160]:
        o[5] = 2                                          # asleep: updateAabbs skips them

    def rays(n):
        out = []
        for _ in range(n):
            o = rnd.choice(objs)
            x, z = o[2][0] + rnd.uniform(-4, 4), o[2][2] + rnd.uniform(-4, 4)
            if rnd.random() < 0.8:                        # a wheel: 1.5 m straight down
                out.append(((x, 3.0, z), (x, 1.5 - rnd.uniform(0, 3), z)))
            else:                                         # anything else, any length/direction
                out.append(((x, rnd.uniform(0, 20), z), (x + rnd.uniform(-80, 80), rnd.uniform(-5, 20),
                                                        z + rnd.uniform(-80, 80))))
        return out

    def compare(label, nrays=150):
        same, calls_s, calls_f, tests = True, 0, 0, 0
        for a, b in rays(nrays):
            hs, cs = st.ray(a, b)
            hf, cf = rf.ray(a, b)
            same &= hs == hf
            calls_s += cs; calls_f += cf; tests += len(hs)
        check(f"{label:<62} identical: {'yes' if same else 'NO'}; shape AABBs per ray stock {calls_s / nrays:5.1f}, "
              f"rayfast {calls_f / nrays:4.1f}", same and (calls_f < calls_s or calls_s == 0))
        return same

    for w in (st, rf):
        w.build(objs)
        w.update_aabbs()
    compare("fresh step (200 objects, 10 asleep)")

    # integrateTransforms moves the cars AFTER updateAabbs, before the wheel rays
    for o in objs[:60]:
        o[2] = (o[2][0] + rnd.uniform(-0.45, 0.45), o[2][1] + rnd.uniform(-0.1, 0.1), o[2][2] + rnd.uniform(-0.45, 0.45))
        o[3] += rnd.uniform(-0.14, 0.14)                  # up to 8 degrees in one step
        for w in (st, rf):
            w.place(o[0], o[2], o[3])
    compare("cars moved 0.45 m + turned 8 deg since updateAabbs")

    # the game teleports objects / a sleeping object is moved without updateAabbs seeing it
    for o in objs[150:160] + objs[:5]:
        o[2] = (o[2][0] + rnd.uniform(-60, 60), o[2][1], o[2][2] + rnd.uniform(-60, 60))
        for w in (st, rf):
            w.place(o[0], o[2], o[3])
    compare("10 sleeping + 5 awake objects teleported up to 85 m")

    # an object removed (swap-remove) and a new one with another shape in a recycled object slot
    objs[7], objs[-1] = objs[-1], objs[7]
    objs.pop()
    objs[20][1] = 199                                     # same object pointer, a different (bigger) shape
    for w in (st, rf):
        w.build(objs)
    compare("after a swap-remove + a recycled object with another shape")
    for w in (st, rf):
        w.update_aabbs()
    compare("next step (table refreshed)")


CHECKS = {"awdfix": check_awdfix, "gravity": check_gravity, "revboost": check_revboost,
          "police": check_police, "wantedhits": check_wantedhits, "smartpolice": check_smartpolice, "policefix": check_policefix, "milkyway": check_milkyway, "boardkeep": check_boardkeep, "racereset": check_racereset, "rayfast": check_rayfast, "adaptive": check_adaptive}

if __name__ == "__main__":
    for name in (sys.argv[1:] or CHECKS):
        CHECKS[name]()
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    sys.exit(0 if all(OK) else 1)
