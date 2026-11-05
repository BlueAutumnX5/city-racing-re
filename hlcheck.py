r"""hlcheck.py - EXECUTE the Stage 2 #9 extras (nightlock, darknight, headlights + hlcars) in Unicorn, inside
the fully patched exe (every saved extra + the four new ones), entering each hook at the game's own patched
site and running until the game address the cave jumps back to. Mock COM objects (device, the separate
techHeadlights effect with the 2004 D3DX layout, the cookie texture) log their calls; the game's static
D3DXCreateEffect / D3DXCreateTextureFromFileInMemoryEx and draw helpers are stubbed and logged.
Checks: results of the night caves at several night factors, the effect + cookie created from the .crhl
text/DDS with the right lengths and pool, call sequences, stack balance, preserved registers, the reset
cave's release, NUM cleared by day, MAXCARS = hlcars.
The live prototypes of the same cave sources ran in game 2026-10-09/10 (v15c); this proves the port's
addresses, section layout and hook sites."""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import headlights as hl
import racemod
import racesim
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM0, UC_X86_REG_XMM6)

st = racemod.load_state()
EXTRAS = [n for n in st.get("extras", []) if n in racemod.EXTRAS] + ["nightlock", "darknight", "headlights",
                                                                      "hlcars"]
names = list(EXTRAS)
for need, deps in racemod.REQUIRES.items():          # same closure apply() builds (one level is enough here)
    for dep in deps:
        if need in names and dep not in names:
            names.append(dep)
for need, deps in racemod.REQUIRES.items():
    for dep in deps:
        if need in names and dep not in names:
            names.append(dep)
names = [n for n in racemod.ORDER_FIRST if n in names] + [n for n in names if n not in racemod.ORDER_FIRST]
print("patch set:", ", ".join(names))
SIM = racesim.Sim(names)
MU = SIM.mu
OK = []
u32 = lambda a: struct.unpack("<I", MU.mem_read(a, 4))[0]
f32 = lambda a: struct.unpack("<f", MU.mem_read(a, 4))[0]
w32 = lambda a, v: MU.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
wf = lambda a, *v: MU.mem_write(a, struct.pack(f"<{len(v)}f", *v))
xf = lambda reg: struct.unpack("<f", (MU.reg_read(reg) & 0xFFFFFFFF).to_bytes(4, "little"))[0]


def check(label, ok, extra=""):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}{('  ' + extra) if extra else ''}")


# ------------------------------------------------------------------ mocks
MOCK, STUB = 0x07000000, 0x07100000
MU.mem_map(MOCK, 0x200000, UC_PROT_ALL)
DEV_M = {0x08: ("Release", 0), 0xb4: ("GetTransform", 2), 0xe4: ("SetRenderState", 2), 0x100: ("GetTexture", 2),
         0x104: ("SetTexture", 2), 0x148: ("DrawIndexedPrimitive", 6), 0x164: ("SetFVF", 1),
         0x178: ("SetVertexShaderConstantF", 3), 0x190: ("SetStreamSource", 4), 0x1a0: ("SetIndices", 1),
         0x1b4: ("SetPixelShaderConstantF", 3)}
FX_M = {0x08: ("Release", 0), 0xec: ("SetTechnique", 1), 0x100: ("Begin", 2), 0x104: ("Pass", 1), 0x108: ("End", 0)}
TEX_M = {0x08: ("Release", 0)}
OBJ = {"DEV": (MOCK, DEV_M), "FX": (MOCK + 0x1000, FX_M), "TEX": (MOCK + 0x2000, TEX_M),
       "OLD": (MOCK + 0x3000, TEX_M)}
A = {k: v[0] for k, v in OBJ.items()}
NAME_OF = {v: k for k, v in A.items()}
STUBS = {}
for oname, (addr, meths) in OBJ.items():
    vt = addr + 0x800
    w32(addr, vt)
    for off in range(0, 0x200, 4):
        s = STUB + len(STUBS) * 16
        m = meths.get(off, (f"UNEXPECTED+{off:#x}", 0))
        STUBS[s] = (oname, off, m)
        w32(vt + off, s)
        MU.mem_write(s, b"\xc2" + struct.pack("<H", 4 * (m[1] + 1)))
GAME_FN = {hl.D3DX_CREATE_EFFECT: ("D3DXCreateEffect", 9), hl.D3DX_TEX_FROM_MEM: ("D3DXCreateTextureFromFileInMemoryEx", 15),
           hl.OBJ_DRAW: ("OBJ_DRAW", 1), hl.PART_DRAW: ("PART_DRAW", 0)}
for a, (n, k) in GAME_FN.items():
    MU.mem_write(a, b"\xc2" + struct.pack("<H", 4 * k) if k else b"\xc3")
LOG = []
NPASS = 6


def on_code(uc, addr, size, _):
    esp = uc.reg_read(UC_X86_REG_ESP)
    if addr in GAME_FN:
        n, k = GAME_FN[addr]
        a = [u32(esp + 4 + 4 * i) for i in range(k)]
        hr = 0
        if n == "D3DXCreateEffect":
            w32(a[7], A["FX"])
        elif n == "D3DXCreateTextureFromFileInMemoryEx":
            w32(a[14], A["TEX"])
        uc.reg_write(UC_X86_REG_EAX, hr)
        LOG.append(("game", n, a))
        return
    if addr not in STUBS:
        return
    oname, off, (meth, nargs) = STUBS[addr]
    this = u32(esp + 4)
    a = [u32(esp + 8 + 4 * i) for i in range(nargs)]
    if meth == "GetTexture":
        w32(a[1], A["OLD"])
    if meth == "Begin":
        w32(a[0], NPASS)
    if meth == "GetTransform":
        wf(a[1], 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    uc.reg_write(UC_X86_REG_EAX, 0)
    LOG.append((NAME_OF.get(this, hex(this)), meth, a))


MU.hook_add(UC_HOOK_CODE, on_code, begin=STUB, end=STUB + len(STUBS) * 16)
for a in GAME_FN:
    MU.hook_add(UC_HOOK_CODE, on_code, begin=a, end=a)
ESP0 = racesim.STACK + 0xF0000
REGS = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444}


def run(start, stop, regs=None, count=200000):
    LOG.clear()
    rr = {**REGS, **(regs or {})}
    for r, v in rr.items():
        MU.reg_write(r, v)
    MU.reg_write(UC_X86_REG_ESP, ESP0)
    MU.emu_start(start, stop, count=count)
    pc = MU.reg_read(racesim.UC_X86_REG_EIP) if hasattr(racesim, "UC_X86_REG_EIP") else None
    return all(MU.reg_read(r) == v for r, v in rr.items()) and MU.reg_read(UC_X86_REG_ESP) == ESP0


def calls():
    return [f"{o}.{m}" for o, m, a in LOG]


from unicorn.x86_const import UC_X86_REG_EIP
pc = lambda: MU.reg_read(UC_X86_REG_EIP)

# ------------------------------------------------------------------ 1. nightlock
print("1. nightlock: 0x00426d00 loads the locked phase")
for hour in (0.0, 12.0, 23.5):
    racemod.set_nightlock(hour)
    for va, orig, new, _ in racemod.PATCHES["nightlock"]:
        MU.mem_write(va, new)
    MU.mem_write(ESP0 + 8, struct.pack("<i", 1234567))
    MU.reg_write(UC_X86_REG_EDX, 1234567)
    kept = run(0x00426D00, 0x00426D08)
    want = round(hour / 24 * 2000000) % 2000000
    got = struct.unpack("<i", MU.mem_read(ESP0 + 8, 4))[0]
    check(f"hour {hour:g}: [esp+8] = phase {want}, edx = phase, back at 0x00426d08, stack kept",
          got == want and MU.reg_read(UC_X86_REG_EDX) == want and pc() == 0x00426D08 and kept, f"got {got}")
racemod.set_nightlock(racemod._saved("nightlock_hour", racemod.NIGHTLOCK_DEFAULT))
for va, orig, new, _ in racemod.PATCHES["nightlock"]:
    MU.mem_write(va, new)

# ------------------------------------------------------------------ 2. darknight
print("2. darknight: ambient (0x00427190) and moon (0x00405f9d)")
SKY = 0x02648150
K, T, M = racemod.DARKNIGHT, racemod.DN_TINT, racemod.DN_MOON
for night in (0.0, 0.5, 1.0):
    amb = (0.116, 0.116, 0.231)
    wf(SKY + 0x1B8, *amb)
    wf(SKY + 0x1C4, -9.0)
    wf(SKY + 0x1DC, night)
    MU.reg_write(UC_X86_REG_XMM6, struct.unpack("<I", struct.pack("<f", 0.75))[0])
    kept = run(0x00427190, 0x00427198, regs={UC_X86_REG_ESI: SKY})
    got = [f32(SKY + o) for o in (0x1B8, 0x1BC, 0x1C0)]
    want = [c * (1 - night * (1 - K * t)) for c, t in zip(amb, T)]
    check(f"night {night}: ambient {['%.4f' % g for g in got]} = c x (1 - n(1 - K tint)), +0x1c4 = xmm6, back, kept",
          all(abs(g - w) < 1e-6 for g, w in zip(got, want)) and abs(f32(SKY + 0x1C4) - 0.75) < 1e-7
          and pc() == 0x00427198 and kept)
    wf(0x0264832C, night)
    wf(0x02648318, 0.4)
    kept = run(0x00405F9D, 0x00405FA5)
    want = 0.4 * (1 - night * (1 - M))
    check(f"night {night}: moon intensity {xf(UC_X86_REG_XMM0):.4f} = 0.4 x (1 - n(1 - {M:g})), back at 0x00405fa5",
          abs(xf(UC_X86_REG_XMM0) - want) < 1e-6 and pc() == 0x00405FA5 and kept)

# ------------------------------------------------------------------ 3. headlights
D = {k: racemod.HL_DATA + v for k, v in hl.DATA_LAYOUT.items()}
text = hl.technique_text().encode("latin-1")
print("3. headlights: section contents")
check(".crhl text = techHeadlights effect text", bytes(MU.mem_read(racemod.HL_TEXT, len(text) + 1)) == text + b"\0")
dds = racemod._hl_cookie()
check(".crhl cookie = headlights.cookie_dds()", bytes(MU.mem_read(racemod.HL_DDS, len(dds))) == dds)
check(f"MAXCARS = hlcars ({racemod.HL_CARS})", u32(D["MAXCARS"]) == racemod.HL_CARS)
check("technique name in the data block", bytes(MU.mem_read(D["NAME"], 15)) == b"techHeadlights\0")
for k in ("STATE", "EFF", "TEX", "NUM"):
    check(f"{k} starts 0", u32(D[k]) == 0)
MGR, MAP = hl.MGR, 0x012D0CE0


def world(night, cars=0, reflect=0):
    wf(hl.NIGHT, night)
    w32(0x012D0C9C, reflect)
    w32(0x012D0CA0, 0)
    w32(hl.DEVICE, A["DEV"])
    w32(MGR + 0x128, cars)
    w32(MAP + 0x2158, 0)                 # no land parts
    w32(hl.STATICS + 0x5000, 0)          # no static objects
    w32(hl.NATURE + 0x1924, 0)           # no trees
    w32(hl.NATURE + 0x25B0, 0)           # no rocks


print("   main cave (0x0043124c)")
world(0.0)
w32(D["NUM"], 5)
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
check("day: no calls, NUM cleared (body/late passes stop), back at 0x00431253, registers + stack kept",
      not LOG and u32(D["NUM"]) == 0 and pc() == hl.HOOK_BACK and kept, str(calls()))
world(1.0, reflect=1)
w32(D["NUM"], 3)
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
check("reflection pass: skipped untouched", not LOG and u32(D["NUM"]) == 3 and pc() == hl.HOOK_BACK and kept)
world(1.0)
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
check("night, no cars: NUM 0, nothing created or drawn", not LOG and u32(D["NUM"]) == 0 and u32(D["STATE"]) == 0
      and pc() == hl.HOOK_BACK and kept, str(calls()))
FIRST = None


def first_frame_checks():
    L = [e for e in LOG if e[1] != "GetTransform"]          # view/projection are read first
    c = [f"{o}.{m}" for o, m, a in L]
    check("night, first frame with cars: D3DXCreateEffect, cookie, SetTechnique", c[:3] == [
    "game.D3DXCreateEffect", "game.D3DXCreateTextureFromFileInMemoryEx", "FX.SetTechnique"] and kept
          and pc() == hl.HOOK_BACK, str(c[:4]))
    if c[:3] == ["game.D3DXCreateEffect", "game.D3DXCreateTextureFromFileInMemoryEx", "FX.SetTechnique"]:
        a = L[0][2]
        check(f"effect from .crhl text: device, src {a[1]:#x}, len {a[2]}, out -> EFF, errors -> ERR",
              a[0] == A["DEV"] and a[1] == racemod.HL_TEXT and a[2] == len(text) and a[7] == D["EFF"] and a[8] == D["ERR"])
        a = L[1][2]
        check(f"cookie from .crhl DDS: src {a[1]:#x}, len {a[2]}, MANAGED pool, out -> TEX",
              a[1] == racemod.HL_DDS and a[2] == len(dds) and a[8] == 1 and a[14] == D["TEX"])
        check("SetTechnique(\"techHeadlights\")", L[2][2][0] == D["NAME"])
    check("STATE 1, EFF + TEX set", u32(D["STATE"]) == 1 and u32(D["EFF"]) == A["FX"] and u32(D["TEX"]) == A["TEX"])

# two cars: the player (slot 0) and one 20 m away
CARS = 0x07400000
MU.mem_map(CARS, 0x10000, UC_PROT_ALL)
for i, pos in enumerate(((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))):
    car = CARS + i * 0x4000
    wf(car, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *pos, 1)
    w32(car + 0xA34, 1)
    wf(car + 0xD00, 1.0)
    wf(car + 0xA24, 20.0 * i)
    w32(MGR + 0x28 + 4 * i, car)
world(1.0, cars=2)
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
first_frame_checks()
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
c = calls()
check(f"night, 2 cars, next frame (no create): NUM 2, one Begin/End pair, back, kept ({len(c)} calls)",
      u32(D["NUM"]) == 2 and c.count("FX.Begin") == 1 and c.count("FX.End") == 1 and "FX.SetTechnique" in c
      and not any("UNEXPECTED" in x for x in c) and pc() == hl.HOOK_BACK and kept, " ".join(sorted(set(c))))
p0 = struct.unpack("<16f", MU.mem_read(D["PSC"], 64))
p1 = struct.unpack("<16f", MU.mem_read(D["PSC"] + 64, 64))
check(f"lights at each car + the default lamp midpoint (0, 0.5, 2): ({p0[0]:.2f}, {p0[1]:.2f}, {p0[2]:.2f}), "
      f"z {p1[2]:.2f}; intensity {p0[3]:.2f} / {p1[3]:.2f}",
      max(abs(p0[0]), abs(p0[1] - 0.5), abs(p0[2] - 2.0), abs(p1[2] - 22.0)) < 1e-5 and p0[3] > 0.99 and p1[3] > 0.99)
gets = c.count("DEV.GetTexture")
rels = sum(1 for o, m, a in LOG if o == "OLD" and m == "Release")
check(f"every GetTexture released ({gets} gets, {rels} releases)", gets == rels)

print("   car-body cave (0x004217aa) and late cave (0x004217f0)")
kept = run(hl.BODY_HOOK, hl.BODY_BACK)
c = calls()
check(f"bodies: Begin/End, back at 0x004217af with ecx = traffic manager, kept",
      c.count("FX.Begin") == 1 and c.count("FX.End") == 1 and not any("UNEXPECTED" in x for x in c)
      and pc() == hl.BODY_BACK and MU.reg_read(UC_X86_REG_ECX) == MGR and kept, " ".join(c[:12]))
kept = run(hl.LATE_HOOK, hl.LATE_BACK)
c = calls()
check(f"late: no objects -> back at 0x004217f5 with ecx = nature fields, kept",
      not any("UNEXPECTED" in x for x in c) and pc() == hl.LATE_BACK and MU.reg_read(UC_X86_REG_ECX) == hl.NATURE
      and kept, " ".join(c[:12]))
w32(D["STATE"], 0)
kept = run(hl.BODY_HOOK, hl.BODY_BACK)
check("bodies with no effect yet (STATE 0): nothing drawn", not LOG and pc() == hl.BODY_BACK and kept)
kept = run(hl.LATE_HOOK, hl.LATE_BACK)
check("late with no effect yet: nothing drawn", not LOG and pc() == hl.LATE_BACK and kept)
w32(D["STATE"], 1)

print("   reset cave (0x0040c6a4)")
kept = run(hl.LOST_HOOK, hl.LOST_BACK)
check("device reset: effect Released, EFF 0, STATE 0, back at 0x0040c6a9 with ecx = 0x2647980, kept",
      calls() == ["FX.Release"] and u32(D["EFF"]) == 0 and u32(D["STATE"]) == 0 and pc() == hl.LOST_BACK
      and MU.reg_read(UC_X86_REG_ECX) == 0x2647980 and kept, str(calls()))
kept = run(hl.LOST_HOOK, hl.LOST_BACK)
check("second reset with no effect: no calls", not LOG and pc() == hl.LOST_BACK and kept)
w32(D["TEX"], A["TEX"])
world(1.0, cars=2)
kept = run(hl.HOOK, hl.HOOK_BACK, regs={UC_X86_REG_ESI: MAP})
c = calls()
c = [x for x in c if x != "DEV.GetTransform"]
check("after the reset: effect recreated, the managed cookie kept (no second texture load)",
      c[0] == "game.D3DXCreateEffect" and "game.D3DXCreateTextureFromFileInMemoryEx" not in c and u32(D["STATE"]) == 1
      and kept, " ".join(c[:4]))

print(f"\n{sum(OK)}/{len(OK)} checks passed" + ("" if all(OK) else "  <-- FAILURES"))
sys.exit(0 if all(OK) else 1)
