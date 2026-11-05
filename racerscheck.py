r"""racerscheck.py - EXECUTE the racerfree hook and the relocated racer-list code in Unicorn.

1. racerfree (hook 0x00442de2 -> cave): fake traffic manager + cars of given types; checks the
   exit taken (0x004431b3 = skip, 0x00442dee = spawn), the stored effective target, stack
   balance and preserved registers. Includes the critical full-list case.
2. standings 0x00441020 with 12 racers in the NEW list: positions and order vs a Python model
   of the same algorithm; the manager fields after the OLD list must stay untouched.
3. racer finishes 0x00441150 (12 racers, one in the middle): list shift, count, type -> 3,
   finish counter; car method 0x004363d0 stubbed (`ret 4`: every caller pushes one argument).
"""
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow",
                                "racerfree", "fadein", "spawnreach", "view", "overlay", "racers"]
MGR = racemod.TRAFFIC_MGR
LIST = racemod.RACER_LIST
S = racesim.SCR
CARS = 0x05000000                        # fake car structs, 0x8000 bytes apart (unused range)
CAR = lambda i: CARS + i * 0x8000
OK = []


def fresh():
    sim = racesim.Sim(NAMES)
    sim.mu.mem_map(CARS, 0x8000 * 70)
    return sim


def put(mu, a, fmt, *v):
    mu.mem_write(a, struct.pack(fmt, *v))


def get(mu, a, fmt="<I"):
    return struct.unpack(fmt, mu.mem_read(a, struct.calcsize(fmt)))[0]


# ------------------------------------------------------------------ 1. racerfree
def racerfree(types, target):
    sim = fresh(); mu = sim.mu
    put(mu, MGR + 0x128, "<I", len(types))
    for i, ty in enumerate(types):
        put(mu, MGR + 0x28 + 4 * i, "<I", CAR(i) if ty is not None else 0)
        if ty is not None:
            put(mu, CAR(i) + 0xc8c, "<I", ty)
    esp0 = racesim.STACK + 0xF0000
    regs = {UC_X86_REG_EAX: target, UC_X86_REG_EDI: MGR, UC_X86_REG_ESI: 0x33333333,
            UC_X86_REG_EBX: 0x11111111, UC_X86_REG_EBP: 0x22222222, UC_X86_REG_ECX: 0x44444444,
            UC_X86_REG_EDX: 0x55555555, UC_X86_REG_ESP: esp0}
    for r, v in regs.items():
        mu.reg_write(r, v)
    exits = {0x004431b3: "skip", 0x00442dee: "spawn"}
    hit = []
    mu.hook_add(1 << 2, lambda uc, a, s, u: (hit.append(a), uc.emu_stop()) if a in exits else None)
    mu.emu_start(0x00442de2, 0xFFFFFFF0, count=100_000)
    after = {r: mu.reg_read(r) for r in regs if r != UC_X86_REG_EAX}
    kept = all(after[r] == regs[r] for r in after)
    return exits.get(hit[0] if hit else 0, "NONE"), get(mu, MGR + 0x12c), kept


def test_racerfree():
    P, O, POL, T = 0, 1, 2, 3
    cases = [
        ("9 traffic, target 8 (no race)", [P] + [T] * 9, 8, "skip", 8),
        ("5 opponents + 4 traffic, target 8", [P] + [O] * 5 + [T] * 4, 8, "spawn", 13),
        ("FULL LIST 64, target 60 + 8 opp.", [P] + [O] * 8 + [T] * 55, 60, "skip", 64),
        ("63 in list, target 60 + 8 opp.", [P] + [O] * 8 + [T] * 54, 60, "spawn", 64),
        ("null slots + police (6 in list)", [P, None, POL, O, None, T], 3, "skip", 4),
        ("null slots + police (target 6)", [P, None, POL, O, None, T], 6, "spawn", 7),
    ]
    for label, types, target, want_exit, want_t in cases:
        ex, t, kept = racerfree(types, target)
        ok = ex == want_exit and t == want_t and kept
        OK.append(ok)
        print(f"  {label:<36} -> {ex:<5} target stored {t:<3} regs kept {kept}  "
              f"{'OK' if ok else f'FAIL (want {want_exit}, {want_t})'}")


# ------------------------------------------------------------------ 2. standings
def model_standings(progress, base):
    """0x00441020, opponent-race branch, as read from the disassembly."""
    lst = list(range(len(progress)))
    pos = {}
    n = len(lst)
    for ebx in range(n):
        pos[lst[ebx]] = base + ebx
        for esi in range(ebx + 1, n):
            a, b = lst[ebx], lst[esi]
            if progress[a] > progress[b]:
                pos[a] = base + esi
                pos[b] = base + ebx
                lst[ebx], lst[esi] = b, a
    return lst, pos


def test_standings(n=12, seed=4):
    rng = random.Random(seed)
    sim = fresh(); mu = sim.mu
    progress = [rng.uniform(0, 1000) for _ in range(n)]
    put(mu, 0x02668918, "<I", 0)                        # opponent race
    put(mu, 0x02668944, "<I", n)
    guard = bytes(range(32))
    mu.mem_write(MGR + 0x13dc0, guard)                  # fields after the OLD list
    put(mu, MGR + 0x13dc0, "<I", 0)                     # finish counter = 0
    guard = bytes(mu.mem_read(MGR + 0x13dc0, 32))
    for i in range(n):
        put(mu, LIST + 4 * i, "<I", CAR(i))
        put(mu, CAR(i) + 0xc7c, "<f", progress[i])
    esp = racesim.STACK + 0xF0000
    put(mu, esp, "<I", racesim.MAGIC)
    mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_ECX, MGR)
    mu.emu_start(0x00441020, racesim.MAGIC, count=1_000_000)
    got_list = [(get(mu, LIST + 4 * i) - CARS) // 0x8000 for i in range(n)]
    got_pos = {i: get(mu, CAR(i) + 0xc80) for i in range(n)}
    want_list, want_pos = model_standings([struct.unpack("<f", struct.pack("<f", p))[0]
                                           for p in progress], 0)
    untouched = bytes(mu.mem_read(MGR + 0x13dc0, 32)) == guard
    esp_ok = mu.reg_read(UC_X86_REG_ESP) == esp + 4
    ok = got_list == want_list and got_pos == want_pos and untouched and esp_ok
    OK.append(ok)
    print(f"  {n} racers sorted: order {'==' if got_list == want_list else '!='} model, positions "
          f"{'==' if got_pos == want_pos else '!='} model, fields after old list untouched "
          f"{untouched}, stack {'balanced' if esp_ok else 'OFF'}  {'OK' if ok else 'FAIL'}")


# ------------------------------------------------------------------ 3. finish
def test_finish(n=12, idx=5):
    sim = fresh(); mu = sim.mu
    mu.mem_write(0x004363d0, b"\xc2\x04\x00")          # stub: car method (1 stack arg), ret 4
    put(mu, 0x02668944, "<I", n)
    put(mu, 0x012d0c88, "<I", CAR(n - 1))               # the player = the last racer
    for i in range(n):
        put(mu, LIST + 4 * i, "<I", CAR(i))
        put(mu, CAR(i) + 0xc8c, "<I", 1)
        put(mu, CAR(i) + 0xc80, "<I", i)
    guard = bytes(mu.mem_read(MGR + 0x13dc4, 28))
    esp = racesim.STACK + 0xF0000
    put(mu, esp, "<II", racesim.MAGIC, CAR(idx))
    mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_ECX, MGR)
    mu.emu_start(0x00441150, racesim.MAGIC, count=1_000_000)
    left = [(get(mu, LIST + 4 * i) - CARS) // 0x8000 for i in range(n - 1)]
    want = [i for i in range(n) if i != idx]
    cnt = get(mu, 0x02668944)
    fin = get(mu, MGR + 0x13dc0)
    ty = get(mu, CAR(idx) + 0xc8c)
    untouched = bytes(mu.mem_read(MGR + 0x13dc4, 28)) == guard
    esp_ok = mu.reg_read(UC_X86_REG_ESP) == esp + 8
    ok = left == want and cnt == n - 1 and fin == idx + 1 and ty == 3 and untouched and esp_ok
    OK.append(ok)
    print(f"  racer {idx} of {n} finishes: list {'shifted OK' if left == want else left}, count "
          f"{cnt}, finish counter {fin}, its type {ty}, other manager fields untouched "
          f"{untouched}, stack {'balanced' if esp_ok else 'OFF'}  {'OK' if ok else 'FAIL'}")


if __name__ == "__main__":
    print("1. racerfree hook:"); test_racerfree()
    print("2. standings sort (0x00441020):")
    for n in (4, 8, 10, 12):
        test_standings(n, seed=n)
    print("3. racer finishes (0x00441150):"); test_finish(12, 5); test_finish(12, 0); test_finish(10, 8)
    print(f"\n{sum(OK)}/{len(OK)} checks OK")
