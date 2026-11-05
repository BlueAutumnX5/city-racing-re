r"""Validate `astarfix` before it goes anywhere near the game.

1. Disassemble the patched bytes - the stub must decode to exactly the intended code.
2. Regression on STOCK: same billboards, same seeds, with and without the fix. Every
   route must be identical unless that course actually hit the bug.
3. The poison test again, with the fix: no search may leave the count unwritten.
4. Overflow: level 3 with NO walk cap, fix on vs off, across all cores.
"""
import os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod, racesim
from racesim import u32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

UNCAPPED = {"cap": [(0x00432c60, bytes.fromhex("00080000"), bytes.fromhex("00080000"),
                     "no cap (study)")]}

if __name__ == "__main__":
    # ---- 1. what did we actually write?
    exe = racesim.build_exe(["astarfix"])
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for va, n in ((racemod.ASTAR_ENTRY, 5), (racemod.ASTAR_CAVE, 43)):
        r = racemod.va2raw(exe, va)
        print(f"--- 0x{va:08x}")
        for ins in md.disasm(exe[r:r + n], va):
            print(f"   {ins.address:08x}  {ins.bytes.hex():<14} {ins.mnemonic} {ins.op_str}")

    # ---- 2. regression on stock, same billboards and seeds
    a, b = racesim.Sim([]), racesim.Sim(["astarfix"])
    rng = random.Random(21)
    same = diff = 0
    for _ in range(300):
        st, seed, prog = rng.choice(a.k3), rng.getrandbits(32), rng.random()
        random.seed(seed); ra = a.race(prog, start=st, seed=seed)
        random.seed(seed); rb = b.race(prog, start=st, seed=seed)
        if (ra["why"], ra["cells"]) == (rb["why"], rb["cells"]):
            same += 1
        else:
            diff += 1
    print(f"\nstock vs stock+astarfix, 300 identical setups: {same} identical routes, "
          f"{diff} different")

    # ---- 3. poison test with the fix on
    sim = racesim.Sim(racemod.LEVELS[3][1] + ["cap", "astarfix"])
    cur, bad, tot = {}, [0], [0]
    def ent(mu, addr, size, _):
        esp = mu.reg_read(UC_X86_REG_ESP)
        p = u32(mu.mem_read(esp + 0x18, 4))
        mu.mem_write(p, struct.pack("<I", 0x7777)); cur["p"] = p
    def ret(mu, addr, size, _):
        tot[0] += 1
        if u32(mu.mem_read(cur["p"], 4)) == 0x7777:
            bad[0] += 1
    sim.mu.hook_add(UC_HOOK_CODE, ent, begin=racemod.ASTAR_ENTRY, end=racemod.ASTAR_ENTRY)
    for s in (0x00432d3f, 0x00432dcf):
        sim.mu.hook_add(UC_HOOK_CODE, ret, begin=s, end=s)
    random.seed(4)
    for _ in range(80):
        sim.race(random.random())
    print(f"poison test WITH fix: {bad[0]} of {tot[0]} searches left the count unwritten")

    # ---- 3b. the start==end early-out must not change a single route. Compare it with
    # the plain count-zeroing fix (no early-out), on level 3 where start==end is common.
    racemod.PATCHES["zero_only"] = [
        (racemod.ASTAR_ENTRY, bytes.fromhex("83ec3c5355"),
         b"\xe9" + struct.pack("<i", 0x004dba60 - (racemod.ASTAR_ENTRY + 5)), "entry"),
        (0x004dba60, b"\xcc" * 20,
         bytes.fromhex("8b442418c7000000000083ec3c5355") + b"\xe9"
         + struct.pack("<i", (racemod.ASTAR_ENTRY + 5) - (0x004dba60 + 20)), "stub")]
    import time
    L3 = racemod.LEVELS[3][1] + ["cap"]
    z, e = racesim.Sim(L3 + ["zero_only"]), racesim.Sim(L3 + ["astarfix"])
    rng = random.Random(8)
    same = diff = 0
    tz = te = 0.0
    for _ in range(150):
        st, seed, prog = rng.choice(z.k3), rng.getrandbits(32), rng.random()
        random.seed(seed); t0 = time.time(); rz = z.race(prog, start=st, seed=seed); tz += time.time() - t0
        random.seed(seed); t0 = time.time(); re_ = e.race(prog, start=st, seed=seed); te += time.time() - t0
        if (rz["why"], rz["cells"]) == (re_["why"], re_["cells"]):
            same += 1
        else:
            diff += 1
    print(f"early-out vs zero-only, 150 level-3 setups: {same} identical, {diff} different; "
          f"time {tz:.1f}s -> {te:.1f}s ({tz/max(te,1e-9):.1f}x faster)")

    # ---- 4. the overflow, fix off vs on, walks uncapped (2048)
    for label, names in (("level 3 UNCAPPED, no fix", racemod.LEVELS[3][1] + ["cap"]),
                         ("level 3 UNCAPPED + astarfix", racemod.LEVELS[3][1] + ["cap", "astarfix"])):
        racesim.run(names, 1200, label, extra=UNCAPPED)
