r"""Validate the `view` and `overlay` patch groups WITHOUT touching the game.

1. No two patches in any combination overlap or disagree on original bytes.
2. Every patched site disassembles to the intended instruction, and every repointed
   constant reads back the intended value.
3. The PE still parses; .text now covers the slack.
4. Race generation is unaffected: racesim with vs without view, same seeds, same routes.
"""
import os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod, racesim
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

if __name__ == "__main__":
    md = Cs(CS_ARCH_X86, CS_MODE_32)

    # ---- 1. overlap + composition, in the combinations the player can actually reach
    X = ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach", "view",
         "overlay", "racers", "shadows", "nodamage"]                     # as apply() builds
    combos = {
        "view alone":          ["slack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach", "view"],
        "racers alone (stock)": ["dataslack", "racers"],
        "view + overlay":      X,
        "glow alone (stock)":  ["glow"],
        "level 3 + extras":    racemod.LEVELS[3][1] + X,
        "level 6 + extras":    [n for n in racemod.LEVELS[6][1] if not n.startswith("-")] + X,
        "level 7 + extras":    racemod.LEVELS[7][1] + X,
    }
    for label, names in combos.items():
        spans = []
        for n in names:
            for va, orig, new, why in racemod.PATCHES[n]:
                spans.append((va, va + len(orig), n, why))
        spans.sort()
        clash = [(a, b) for a, b in zip(spans, spans[1:]) if b[0] < a[1]]
        exe = racesim.build_exe(names)          # asserts every original byte
        print(f"{label:<20} {len(spans):3d} edits  overlaps: {len(clash)}  build: OK"
              + ("" if not clash else f"   CLASH {clash[0]}"))

    # ---- 2. read back every view/overlay edit from a built exe
    exe = racesim.build_exe(racemod.LEVELS[7][1] + X)
    print("\nview/overlay/glow edits as they will exist in game.exe:")
    # the real size of the view constants block (it grows; a fixed 0x40 once hid a new repoint)
    VBLOCK = next(len(new) for a, o, new, w in racemod.PATCHES["view"] if a == racemod.VIEW_CONSTS)
    for n in ("view", "overlay", "glow", "dataslack", "rdataslack", "rdataexec", "racerfree", "fadein", "spawnreach",
              "racers", "shadows", "nodamage"):
        for va, orig, new, why in racemod.PATCHES[n]:
            r = racemod.va2raw(exe, va)
            got = exe[r:r + len(new)]
            assert got == new, f"0x{va:08x} not applied"
            if len(new) == 4 and racemod.VIEW_CONSTS <= struct.unpack("<I", new)[0] < racemod.VIEW_CONSTS + VBLOCK:
                tgt = struct.unpack("<I", new)[0]
                val = struct.unpack_from("<f", exe, racemod.va2raw(exe, tgt))[0]
                # Find the whole instruction that holds the operand. Guessing "one byte back"
                # mis-decodes 3-byte opcodes (comiss 0f 2f 05 read as `add eax, imm32`), so
                # sweep linearly from many earlier offsets and take the instruction boundary
                # most of them agree on (x86 linear decoding resynchronises within a few
                # instructions). Then it must END with the operand and reference the constant.
                votes, found = {}, {}
                for back in range(8, 64):
                    for ins in md.disasm(exe[r - back:r + 16], va - back):
                        if ins.address <= va < ins.address + ins.size:
                            votes[ins.address] = votes.get(ins.address, 0) + 1
                            found[ins.address] = ins
                            break
                        if ins.address > va:
                            break
                ins = found[max(votes, key=votes.get)]
                ok = ins.address + ins.size == va + 4 and f"{tgt:#x}" in ins.op_str
                assert ok, f"0x{va:08x}: operand is not the last 4 bytes of '{ins.mnemonic} {ins.op_str}'"
                print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str:<34} -> {val:g}   ({why})")
            elif va == 0x0059041c:                                   # the Distance cap is an int
                print(f"  0x{va:08x}  int {struct.unpack('<I', orig)[0]} -> "
                      f"{struct.unpack('<I', new)[0]}   ({why})")
            elif len(new) == 4 and n == "view" and va >= 0x00569000:
                print(f"  0x{va:08x}  const {struct.unpack('<f', orig)[0]:g} -> "
                      f"{struct.unpack('<f', new)[0]:g}   ({why})")
            elif va == racemod.VIEW_CONSTS:
                vals = [struct.unpack_from("<f", new, i)[0] for i in range(0, len(new), 4)]
                print(f"  0x{va:08x}  constants block {vals}")
            else:
                print(f"  0x{va:08x}  {orig.hex()} -> {new.hex()}   ({why})")

    # ---- 2b. the pedestrian-anchor hook, as it will run
    print("\nracerfree hook (0x00442de2) and its code:")
    for va, n in ((0x00442de2, 12), (racemod.RACERFREE_CAVE, 0x70)):
        r = racemod.va2raw(exe, va)
        for ins in md.disasm(exe[r:r + n], va):
            print(f"  {ins.address:08x}  {ins.bytes.hex():<22} {ins.mnemonic} {ins.op_str}")
            if ins.mnemonic == "jmp" and ins.op_str == "0x442dee":
                break

    # ---- 3. PE sanity
    secs = racemod.sections(exe)
    t = [s for s in secs if s[0] == 0x00401000][0]
    d = [s for s in secs if s[0] == 0x00590000][0]
    rd = [s for s in secs if s[0] == 0x00568000][0]
    # ends of everything placed in the slack, taken from the patches themselves
    end_of = lambda name, va: next(va + len(new) for a, o, new, w in racemod.PATCHES[name] if a == va)
    fade_end = max(end_of("fadein", racemod.FADEIN_CAVE),
                   end_of("spawnreach", racemod.SPAWNREACH_CAVE))
    consts_end = end_of("view", racemod.VIEW_CONSTS)
    rate_end = end_of("fadein", racemod.FADEIN_RATE)
    print(f"\n.text: base 0x{t[0]:08x} VirtualSize 0x{t[1]:x} raw 0x{t[3]:x}; "
          f"covers leap + racerfree + fadein + spawnreach code (to 0x{fade_end:08x}): "
          f"{t[0] + t[1] >= max(racemod.RACERFREE_CAVE_END, fade_end) and t[1] <= t[3]}")
    print(f".rdata: VirtualSize 0x{rd[1]:x}, ends 0x{rd[0] + rd[1]:08x}, raw 0x{rd[3]:x}; covers "
          f"view constants (to 0x{consts_end:08x}) and fade-in rate (to 0x{rate_end:08x}): "
          f"{rd[0] + rd[1] >= max(consts_end, rate_end)}; within raw: {rd[1] <= rd[3]}")
    print(f".data: VirtualSize 0x{d[1]:x}, ends 0x{d[0] + d[1]:08x}; covers the racer list: "
          f"{d[0] + d[1] >= racemod.RACER_LIST + 64}; stays inside its last page: "
          f"{d[0] + d[1] <= 0x026fd000}")

    # ---- 4. race generation unaffected
    a = racesim.Sim(["astarfix"])
    b = racesim.Sim(["astarfix"] + X)
    rng = random.Random(5)
    same = 0
    for _ in range(200):
        st, seed, prog = rng.choice(a.k3), rng.getrandbits(32), rng.random()
        random.seed(seed); ra = a.race(prog, start=st, seed=seed)
        random.seed(seed); rb = b.race(prog, start=st, seed=seed)
        same += (ra["why"], ra["cells"]) == (rb["why"], rb["cells"])
    print(f"race generation with view+overlay: {same}/200 routes identical to without")
