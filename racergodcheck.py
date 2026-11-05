r"""racergodcheck.py - EXECUTE the `racergod` hook (0x0043ab15 -> cave) in Unicorn inside the fully patched exe,
with and without `nodamage` (player 2026-11-01: "racers can't get damage, traffic and police still can").
Runs the crash-damage path from 0x0043ab0d (nodamage's hook, or the stock `addss xmm1, [0.5]`) with esi = a car
of each vehicle type ([car+0xc8c]: 0 player, 1 race opponent, 2 police, 3 traffic) and checks where it goes:
the crash-sound tail 0x0043b444 (no damage) or the damage block (0x0043ab1a with 0x2710 pushed, exactly like
the replaced `push 0x2710`). Other registers untouched.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM1)

BASE = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                               "fadein", "spawnreach", "view", "overlay", "racers", "shadows", "modsect"]
CARS = 0x05800000
TYPES = {"player": 0, "race opponent": 1, "police": 2, "traffic": 3}
ADDR = {name: CARS + 0x10000 * k for k, name in enumerate(TYPES)}
fbits = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
OK = []


def sim(names):
    s = racesim.Sim(names)
    s.mu.mem_map(CARS, 0x10000 * len(TYPES), UC_PROT_ALL)
    for name, t in TYPES.items():
        s.mu.mem_write(ADDR[name] + 0xC8C, struct.pack("<I", t))
    s.mu.mem_write(racemod.PLAYER_CAR, struct.pack("<I", ADDR["player"]))
    return s


def run(s, car):
    mu = s.mu
    esp0 = racesim.STACK + 0xF0000
    regs = {UC_X86_REG_ESI: car, UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x2222, UC_X86_REG_EAX: 0x3333,
            UC_X86_REG_ECX: 0x4444, UC_X86_REG_EDX: 0x5555, UC_X86_REG_EBP: 0x6666, UC_X86_REG_ESP: esp0}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_XMM1, fbits(0.8))
    mu.mem_write(esp0 + 0x10, struct.pack("<f", 0.3))        # the hit's strength (policedmg scales it)
    exits = {0x0043B444: "no damage", 0x0043AB1A: "damage"}
    hit = []
    h = mu.hook_add(1 << 2, lambda uc, a, sz, u: (hit.append(a), uc.emu_stop()) if a in exits else None)
    mu.emu_start(0x0043AB0D, 0xFFFFFFF0, count=60)
    mu.hook_del(h)
    where = exits.get(hit[0] if hit else 0, "NONE")
    esp = mu.reg_read(UC_X86_REG_ESP)
    pushed = struct.unpack("<I", mu.mem_read(esp, 4))[0] if where == "damage" else None
    stack_ok = (esp == esp0 - 4 and pushed == 0x2710) if where == "damage" else esp == esp0
    kept = all(mu.reg_read(r) == v for r, v in regs.items() if r != UC_X86_REG_ESP)
    strength = struct.unpack("<f", mu.mem_read(esp0 + 0x10, 4))[0]
    return where, stack_ok and kept, strength, mu.reg_read(UC_X86_REG_XMM1) & 0xFFFFFFFF


RADIUS = {}                                      # the dent radius (xmm1) per car type without the crash hook


def suite(label, names, want, police_x=1):
    print(f"{label}:")
    racemod.set_police_dmg(police_x)
    s = sim(names)
    for name in TYPES:
        where, clean, strength, radius = run(s, ADDR[name])
        if "nodamage" in names and "crashhook" not in names:
            RADIUS[name] = radius
        # the dent radius (game: strength + 0.5) is never touched by the crash hook
        clean &= "nodamage" not in names or RADIUS.get(name, radius) == radius
        want_s = 0.3 * (police_x if name == "police" else 1)
        ok = where == want[name] and clean and abs(strength - want_s) < 1e-6
        OK.append(ok)
        print(f"  {'OK ' if ok else 'BAD'} {name:<14} -> {where:<9} (want {want[name]}), strength {strength:.2f}"
              f" (want {want_s:.2f}){'' if clean else '  STACK/REGISTERS WRONG'}")


# racergod and policedmg share the `crashhook` (racesim builds exactly the list it gets: add it like modsect)
CH = ["crashhook"]
suite("reference: nodamage only (stock racers), radius per car type", BASE + ["nodamage"],
      {"player": "no damage", "race opponent": "damage", "police": "damage", "traffic": "damage"})
suite("racergod + nodamage", BASE + CH + ["nodamage", "racergod"],
      {"player": "no damage", "race opponent": "no damage", "police": "damage", "traffic": "damage"})
suite("racergod only (your car takes damage)", BASE + CH + ["racergod"],
      {"player": "damage", "race opponent": "no damage", "police": "damage", "traffic": "damage"})
suite("nodamage only (stock racers)", BASE + ["nodamage"],
      {"player": "no damage", "race opponent": "damage", "police": "damage", "traffic": "damage"})
suite("crash hook alone changes nothing", BASE + CH + ["nodamage"],
      {"player": "no damage", "race opponent": "damage", "police": "damage", "traffic": "damage"})
# policedmg (player 2026-11-01): police take 1x / 2x / 3x - only the hit's strength, only police
for x in (1, 2, 3):
    suite(f"policedmg x{x} + nodamage", BASE + CH + ["nodamage", "policedmg"],
          {"player": "no damage", "race opponent": "damage", "police": "damage", "traffic": "damage"}, x)
suite("policedmg x3 + racergod + nodamage", BASE + CH + ["nodamage", "racergod", "policedmg"],
      {"player": "no damage", "race opponent": "no damage", "police": "damage", "traffic": "damage"}, 3)
suite("policedmg x2, your car takes damage", BASE + CH + ["policedmg"],
      {"player": "damage", "race opponent": "damage", "police": "damage", "traffic": "damage"}, 2)
print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
