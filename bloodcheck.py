r"""bloodcheck.py - racemod `markskeep` (blood half) executed in Unicorn inside the patched exe (player 2026-11-01: "make
blood splats go 1 hour"). 1) The splat countdown 0x0041e414..0x0041e41d stepped through a whole life at 10 Hz:
how long the spreading (r > 0.75), full-colour (0.25 < r <= 0.75) and fading (r <= 0.25) phases last, stock
vs bloodkeep; xmm2/xmm3 kept. 2) The add 0x0041af30 with a FULL pool of 512 live splats: stock returns 0 (new
blood dropped), bloodkeep reaches the init call 0x0041af88 with the record that has the least life left and
its cached ground mesh flag (+0x174) cleared; a pool with a free record still takes the first free one.
"""
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_XMM0, UC_X86_REG_XMM2, UC_X86_REG_XMM3)

BASE = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree",
                               "fadein", "spawnreach", "view", "overlay", "racers", "shadows", "modsect"]
REC = 0x05900000                 # one splat record
POOL = 0x05A00000                # up to BL_N x 0x178
fbits = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
bitsf = lambda b: struct.unpack("<f", struct.pack("<I", b & 0xFFFFFFFF))[0]
OK = []
MK = ["hlsect", "tmsect", "markskeep"]           # racesim builds exactly this list (no REQUIRES)


def check(label, ok):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}")


def phases(names, total=15.0, dt=0.1):
    """seconds spent spreading / full / fading for a splat of life `total`"""
    s = racesim.Sim(names)
    mu = s.mu
    mu.mem_map(REC, 0x1000, UC_PROT_ALL)
    mu.mem_write(REC + 0x3C, struct.pack("<ff", total, total))
    t = {"spread": 0.0, "full": 0.0, "fade": 0.0}
    kept = True
    for _ in range(10_000_000):
        rem = struct.unpack("<f", mu.mem_read(REC + 0x40, 4))[0]
        if rem <= 0:
            break
        r = rem / total
        t["spread" if r > 0.75 else "full" if r > 0.25 else "fade"] += dt
        mu.reg_write(UC_X86_REG_EBX, REC)
        mu.reg_write(UC_X86_REG_XMM3, fbits(dt))
        mu.reg_write(UC_X86_REG_XMM2, fbits(123.0))
        mu.reg_write(UC_X86_REG_ESP, racesim.STACK + 0xF0000)
        mu.emu_start(0x0041E414, 0x0041E41D, count=60)
        new = bitsf(mu.reg_read(UC_X86_REG_XMM0))
        kept &= bitsf(mu.reg_read(UC_X86_REG_XMM2)) == 123.0 and mu.reg_read(UC_X86_REG_XMM3) & 0xFFFFFFFF == fbits(dt)
        mu.mem_write(REC + 0x40, struct.pack("<f", max(new, 0.0)))   # 0x0041e41d..0x0041e42e: clamp + store
    return t, kept


def add(names, lives, free=None):
    """run the add with a pool whose records all live (lives[i] left) except `free`; -> (eax or esi, pool)"""
    s = racesim.Sim(names)
    mu = s.mu
    mu.mem_map(POOL, (racemod.BL_N * 0x178 + 0xFFFF) & ~0xFFFF, UC_PROT_ALL)
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)                  # the fake return address lands here
    mu.mem_write(0x0BADF00D, b"\xf4")
    for i, life in enumerate(lives):
        rec = POOL + i * 0x178
        mu.mem_write(rec, struct.pack("<I", 0 if i == free else 1))
        mu.mem_write(rec + 0x3C, struct.pack("<ff", 20.0, life))
        mu.mem_write(rec + 0x174, struct.pack("<I", 1))
    esp = racesim.STACK + 0xF0000
    mu.mem_write(esp, struct.pack("<7I", 0x0BADF00D, 1, 2, 3, 4, 5, 6))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, POOL)
    hit = []
    mu.hook_add(1 << 2, lambda uc, a, sz, u: (hit.append(a), uc.emu_stop()) if a in (0x0041AF88, 0x0BADF00D)
                else None)
    mu.emu_start(0x0041AF30, 0xFFFFFFF0, count=20000)
    where = hit[0] if hit else None
    rec = mu.reg_read(UC_X86_REG_ESI) if where == 0x0041AF88 else None
    flags = [struct.unpack("<I", mu.mem_read(POOL + i * 0x178 + 0x174, 4))[0] for i in range(len(lives))]
    return where, rec, mu.reg_read(UC_X86_REG_EAX), flags


def main():
    print("1. a 15 s splat's life")
    stock, _ = phases(BASE)
    check(f"stock: spreads {stock['spread']:.1f} s, full {stock['full']:.1f} s, fades {stock['fade']:.1f} s "
          f"(total {sum(stock.values()):.1f} s)", abs(sum(stock.values()) - 15.0) < 0.3)
    racemod.set_marks_keep(60)
    keep, kept = phases(BASE + MK)
    check(f"bloodkeep 60 min: spreads {keep['spread']:.1f} s, full {keep['full'] / 60:.1f} min, fades "
          f"{keep['fade']:.1f} s", abs(keep["spread"] - stock["spread"]) < 0.2
          and abs(keep["full"] - 3600) < 0.03 * 3600 and   # float rounding of tiny steps
          abs(keep["fade"] - stock["fade"]) < 0.2)
    check("xmm2 / xmm3 kept", kept)

    print(f"2. a full pool (stock 512 / markskeep {racemod.BL_N} live splats)")
    rnd = random.Random(5)
    lives = [rnd.uniform(1.0, 3000.0) for _ in range(racemod.BL_N)]
    oldest = min(range(racemod.BL_N), key=lambda i: lives[i])
    where, rec, eax, flags = add(BASE, lives)
    check("stock: the add gives up (returns 0) - the new blood is dropped", where == 0x0BADF00D and eax == 0)
    where, rec, eax, flags = add(BASE + MK, lives)
    check(f"bloodkeep: reuses record {oldest} (least life left, {lives[oldest]:.1f} s) and clears its mesh "
          f"flag; the other {racemod.BL_N - 1} untouched", where == 0x0041AF88
          and rec == POOL + oldest * 0x178 and flags[oldest] == 0 and sum(flags) == racemod.BL_N - 1)
    where, rec, eax, flags = add(BASE + MK, lives, free=300)
    check("with a free record it still takes the free one (stock path)",
          where == 0x0041AF88 and rec == POOL + 300 * 0x178 and sum(flags) == racemod.BL_N)
    where, rec, eax, flags = add(BASE + MK, lives, free=900)
    check("... also past the old 512 (record 900 free -> taken)", where == 0x0041AF88 and rec == POOL + 900 * 0x178)
    print("3. a tyre-mark strip's life (the per-frame update 0x0041b3a0, intensity 4 = alpha 255)")
    for label, names, want in (("stock", BASE, [(5.0, 255), (8.0, 127), (9.9, 6), (10.1, None)]),
                               ("markskeep 60 min", BASE + MK,
                                [(9.9, 255), (1800.0, 255), (3599.0, 255), (3602.0, 127), (3604.1, None)])):
        got = [(age, strip_alpha(names, age)) for age, _ in want]
        check(f"{label}: alpha by age {got}",
              all((a is None and g is None) or (a is not None and g is not None and abs(g - a) <= 2)
                  for (_, a), (_, g) in zip(want, got)))
    print(f"4. a full strip pool (stock 64 / markskeep {racemod.TM_N} live strips)")
    ages = [rnd.uniform(0.0, 3000.0) for _ in range(racemod.TM_N)]
    oldest = max(range(racemod.TM_N), key=lambda i: ages[i])
    check("stock: the allocator returns 0 - the skid leaves no mark", strip_alloc(BASE, ages)[0] == 0)
    ptr, strip = strip_alloc(BASE + MK, ages)
    check(f"markskeep: reuses strip {oldest} (oldest, {ages[oldest]:.0f} s) reset to active / age 0 / no points",
          ptr == STRIPS + oldest * 0xD0C and strip == (1, 0.0, 0))
    ptr, strip = strip_alloc(BASE + MK, ages, free=40)
    check("with a free strip it still takes the free one", ptr == STRIPS + 40 * 0xD0C)
    # 2026-11-02 live: 431 of 1024 strips held ONE point (a stuck AI car flickering in and out of a skid)
    a2 = list(ages)
    a2[10], a2[20] = 5.0, 50.0
    ptr, strip = strip_alloc(BASE + MK, a2, counts={10: 1, 20: 0})
    check(f"full pool with junk (strips of < 2 points, > 1 s old): junk first (strip 10), not the oldest real "
          f"mark {oldest}", ptr == STRIPS + 10 * 0xD0C)
    a3 = list(ages)
    a3[10] = 0.5
    ptr, strip = strip_alloc(BASE + MK, a3, counts={10: 1})
    check("... a junk strip younger than 1 s (a skid just starting) is left alone -> the oldest real mark",
          ptr == STRIPS + oldest * 0xD0C)
    ptr, strip = strip_alloc(BASE + MK, ages, free=racemod.TM_N - 5)
    check(f"... also past the old 64 (strip {racemod.TM_N - 5} free -> taken)", ptr == STRIPS + (racemod.TM_N - 5) * 0xD0C)

    print("5. the jump guard before each point (0x0043937f)")
    for dist in (3.0, 7.9, 8.1, 300.0):
        new, ecx, wheel, stack = guard(BASE + MK, dist)
        want_new = dist > 8.0
        ok = stack and ((ecx == racemod.TM_VA and wheel == racemod.TM_VA) if want_new
                        else (ecx == OLDSTRIP and wheel == OLDSTRIP))
        check(f"point {dist:g} m from the strip's last one -> "
              f"{'a NEW strip in .crtm for that wheel' if want_new else 'same strip'}"
              f" (adds to {ecx:#x}, wheel holds {wheel:#x})", ok)
    print("6. the per-frame update runs over all strips at the new address")
    freed = update_far(BASE + MK)
    check(f"strip {racemod.TM_N - 1} of {racemod.TM_N} (the last) aged past the hour is freed by 0x0041ba80", freed)
    print("7. nothing in the game still uses the OLD manager layout (2026-11-02 crash: the texture id at +0x36100)")
    stale = old_layout_refs(BASE + MK)
    check(f"no instruction left with the old addresses 0x025a18b0 / 0x02610308 or an offset 0x34300..0x36108 / "
          f"0x2f000..0x2f01f {stale}", not stale)
    print(f"8. the moved blood manager ({racemod.BL_N} splats at {racemod.BL_VA:#x})")
    fields, ret = blood_ctor(BASE + MK)
    # +0x2f000 (the texture id) is not the constructor's: the device restore sets it (stock does the same)
    check(f"the constructor (static init) runs there and zeroes the 7 buffer fields behind the {racemod.BL_N} "
          f"records", ret and fields[1:] == [0] * 7)
    # count + 4 must stay under the cap (stock: 511 splats a frame, the 512th refused)
    stock = blood_append(BASE, 2044, racemod.BL_OLD)
    got = [blood_append(BASE + MK, n) for n in (2044, 4 * racemod.BL_N - 8, 4 * racemod.BL_N - 4)]
    check(f"a frame takes 4 vertices a splat to {4 * racemod.BL_N - 4} (stock refused at 2044: {stock}): appends at "
          f"2044 / {4 * racemod.BL_N - 8} / {4 * racemod.BL_N - 4} -> {got}", stock is False and got == [True, True, False])
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


def old_layout_refs(names):
    import re
    import capstone
    exe = racesim.build_exe(names)
    t = [s for s in racemod.sections(exe) if s[0] == 0x00401000][0]
    code = exe[t[2]:t[2] + t[1]]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.skipdata = True
    out = []
    for i in md.disasm(code, 0x00401000):
        for m in re.finditer(r"0x[0-9a-f]+", i.op_str):
            v = int(m.group(), 16)
            if v in (0x025A18B0, racemod.BL_OLD) or (0x34300 <= v <= 0x36108 and v != 0x343FD) \
                    or 0x2F000 <= v <= 0x2F01F:   # 0x343fd: the CRT rand multiplier; 0x2f0xx: the blood fields
                out.append(f"{i.address:#x} {i.mnemonic} {i.op_str}")
    return out


OLDSTRIP = 0x05E00000
WHEEL = 0x05E10000


def guard(names, dist):
    """the car's add-point call with the strip's last point at (10, 0, 10) and the new one `dist` m away"""
    s = racesim.Sim(names)
    mu = s.mu
    mu.mem_map(OLDSTRIP, 0x20000, UC_PROT_ALL)
    mu.mem_write(OLDSTRIP, struct.pack("<If", 1, 5.0))
    mu.mem_write(OLDSTRIP + 0xD08, struct.pack("<I", 3))
    last = OLDSTRIP + 8 + 48 * 2
    mu.mem_write(last, struct.pack("<3f", 10.0, 0.0, 10.0))
    point = WHEEL + 0x100
    mu.mem_write(point, struct.pack("<3f", 10.0 + dist, 0.0, 10.0))
    mu.mem_write(WHEEL + 0x10, struct.pack("<I", OLDSTRIP))
    esp = racesim.STACK + 0xF0000
    mu.mem_write(esp, struct.pack("<If", point, 0.7))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, OLDSTRIP)
    mu.reg_write(UC_X86_REG_EBX, WHEEL)
    hit = []
    mu.hook_add(1 << 2, lambda uc, a, sz, u: (hit.append((uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_ESP))),
                                             uc.emu_stop()) if a == 0x0041B040 else None)
    mu.emu_start(0x0043937F, 0xFFFFFFF0, count=500)
    ecx, sp = hit[0] if hit else (0, 0)
    args = struct.unpack("<If", mu.mem_read(sp + 4, 8)) if hit else (0, 0)
    stack = bool(hit) and sp == esp - 4 and args[0] == point and abs(args[1] - 0.7) < 1e-6
    return None, ecx, struct.unpack("<I", mu.mem_read(WHEEL + 0x10, 4))[0], stack


def update_far(names):
    s = racesim.Sim(names)
    mu = s.mu
    st = racemod.TM_VA + (racemod.TM_N - 1) * 0xD0C
    mu.mem_write(st, struct.pack("<If", 1, racemod.MARKS_KEEP * 60 + 4.5))
    mu.mem_write(st + 0xD08, struct.pack("<I", 5))
    mu.mem_write(0x012D04A8, struct.pack("<f", 0.01))
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<I", 0x0BADF00D))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, racemod.TM_VA)
    mu.emu_start(0x0041BA80, 0x0BADF00D, count=20_000_000)
    return struct.unpack("<I", mu.mem_read(st, 4))[0] == 0 and struct.unpack("<I", mu.mem_read(st + 0xD08, 4))[0] == 0


STRIPS = 0x10000000                              # up to TM_N x 0xd0c (26 MB at 8192)


def strip_alpha(names, age, dt=0.01):
    """a strip with one segment (intensity 4) aged `age` after one update: its alpha (None = freed)"""
    s = racesim.Sim(names)
    mu = s.mu
    mu.mem_map(STRIPS, 0x10000, UC_PROT_ALL)
    mu.mem_write(STRIPS, struct.pack("<If", 1, age - dt))
    mu.mem_write(STRIPS + 0xD08, struct.pack("<I", 1))
    mu.mem_write(STRIPS + 0xC08, struct.pack("<f", 4.0))
    mu.mem_write(STRIPS + 0x14, struct.pack("<I", 0xFF000000))
    mu.mem_write(0x012D04A8, struct.pack("<f", dt))
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<I", 0x0BADF00D))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, STRIPS)
    mu.emu_start(0x0041B3A0, 0x0BADF00D, count=2000)
    if struct.unpack("<I", mu.mem_read(STRIPS, 4))[0] == 0:
        return None
    return struct.unpack("<I", mu.mem_read(STRIPS + 0x14, 4))[0] >> 24


def strip_alloc(names, ages, free=None, counts=None):
    s = racesim.Sim(names)
    mu = s.mu
    mu.mem_map(STRIPS, (racemod.TM_STRIPS + 0xFFFF) & ~0xFFFF, UC_PROT_ALL)
    for i, a in enumerate(ages):
        mu.mem_write(STRIPS + i * 0xD0C, struct.pack("<If", 0 if i == free else 1, a))
        mu.mem_write(STRIPS + i * 0xD0C + 0xD08, struct.pack("<I", (counts or {}).get(i, 7)))
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<I", 0x0BADF00D))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, STRIPS)
    mu.emu_start(0x0041BAD0, 0x0BADF00D, count=2_000_000)   # 2 x TM_N strips
    ptr = mu.reg_read(UC_X86_REG_EAX)
    if not ptr:
        return 0, None
    act, age = struct.unpack("<If", mu.mem_read(ptr, 8))
    return ptr, (act, age, struct.unpack("<I", mu.mem_read(ptr + 0xD08, 4))[0])


def blood_ctor(names):
    """the blood manager's constructor (0x0041a970, reached from the static init 0x00567020) at its new home:
    its 8 fields behind the records, pre-filled with junk -> after the call (all zero?), and did it return"""
    s = racesim.Sim(names)
    mu = s.mu
    f = racemod.BL_VA + racemod.BL_REC
    mu.mem_write(f, b"\xff" * 0x20)
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<I", 0x0BADF00D))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.mem_write(0x0BADF00D, b"\xf4")
    hit = []
    mu.hook_add(1 << 2, lambda uc, a, sz, u: (hit.append(a), uc.emu_stop()) if a == 0x0BADF00D else None)
    mu.emu_start(0x00567020, 0xFFFFFFF0, count=20_000_000)
    return list(struct.unpack("<8I", mu.mem_read(f, 0x20))), bool(hit) and mu.reg_read(UC_X86_REG_EAX) == racemod.BL_VA


def blood_append(names, count, base=None):
    """one splat's 4 vertices appended (0x0041afa0, the 48-byte channel) with `count` already in this frame:
    taken (count + 4) or refused (the buffer is full)"""
    s = racesim.Sim(names)
    mu = s.mu
    base = base or racemod.BL_VA
    f = base + (racemod.BL_REC if base == racemod.BL_VA else 0x2F000)
    dest = 0x10000000
    mu.mem_map(dest, ((4 * racemod.BL_N + 8) * 0x30 + 0xFFFF) & ~0xFFFF, UC_PROT_ALL)
    mu.mem_write(f + 0x10, struct.pack("<I", count))
    mu.mem_write(f + 0x18, struct.pack("<I", dest))
    src = racesim.SCR + 0x1000
    mu.mem_write(src, bytes(range(0xC0)))
    esp = racesim.STACK + 0xF0000
    mu.mem_map(0x0BADF000, 0x1000, UC_PROT_ALL)
    mu.mem_write(esp, struct.pack("<III", 0x0BADF00D, src, 4))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, base)
    mu.emu_start(0x0041AFA0, 0x0BADF00D, count=100_000)
    now = struct.unpack("<I", mu.mem_read(f + 0x10, 4))[0]
    if now == count + 4:
        return bytes(mu.mem_read(dest + count * 0x30, 0xC0)) == bytes(range(0xC0))
    return False if now == count else None


if __name__ == "__main__":
    sys.exit(main())
