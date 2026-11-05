r"""pedcheck.py - RETIRED 2026-09-24. The `pedanchor` hook it tested was removed when traffic
became camera-centred and pedestrians were set to follow it (see racemod.py, "pedestrians").
Kept for the record: it passed 3/3 on the hook as it was.

pedcheck.py - execute the `pedanchor` hook in the emulator and check it exactly.

Runs the real patched bytes from 0x00442d8b (the hook) through the cave to the jump back at
0x00442d91, with a fake camera and a fake traffic anchor. The terrain-height function is
replaced by a stub that returns a known height and does `ret 4` like all five real exits,
because the emulator has no heightmap loaded.

Checks: the displaced fstp still stores the anchor height; x/z of the pedestrian anchor are
exactly (eye + anchor)/2; y is the stub's height; the stack pointer comes back unchanged;
the x87 register stack is back to its starting depth; esi/edi/ebx/ebp are preserved.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI,
                               UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_FPSW)

NAMES = racemod.LEVELS[7][1] + ["slack", "dataslack", "glow", "pedanchor", "view", "overlay"]


def run(eye, anchor, anchor_h, ground_h):
    sim = racesim.Sim(NAMES)
    mu = sim.mu
    S = racesim.SCR
    cam, anc, flt, stub, pre = S + 0x800, S + 0x900, S + 0xA00, S + 0xB00, S + 0xC00
    mu.mem_write(0x02610010, struct.pack("<I", cam))                 # camera pointer
    mu.mem_write(cam + 0x70, struct.pack("<3f", *eye))
    mu.mem_write(anc, struct.pack("<3f", *anchor))
    mu.mem_write(flt, struct.pack("<2f", anchor_h, ground_h))
    # height stub: fld [flt+4]; ret 4   - patched over the real function in EMULATOR memory
    mu.mem_write(0x0042b9c0, b"\xd9\x05" + struct.pack("<I", flt + 4) + b"\xc2\x04\x00")
    # prelude: put the anchor height on the x87 stack (as the game's own call left it), then
    # jump into the patched hook site
    mu.mem_write(pre, b"\xd9\x05" + struct.pack("<I", flt)
                 + b"\xe9" + struct.pack("<i", 0x00442d8b - (pre + 6 + 5)))
    esp0 = racesim.STACK + 0xF0000
    edi = anc - 0x9d7c
    for reg, v in ((UC_X86_REG_ESP, esp0), (UC_X86_REG_ESI, anc), (UC_X86_REG_EDI, edi),
                   (UC_X86_REG_EBX, 0x11111111), (UC_X86_REG_EBP, 0x22222222)):
        mu.reg_write(reg, v)
    top0 = (mu.reg_read(UC_X86_REG_FPSW) >> 11) & 7
    mu.emu_start(pre, 0x00442d91, count=10_000)
    ped = struct.unpack("<3f", mu.mem_read(racemod.PED_ANCHOR, 12))
    stored_h = struct.unpack("<f", mu.mem_read(edi + 0x9d80, 4))[0]
    top1 = (mu.reg_read(UC_X86_REG_FPSW) >> 11) & 7
    regs = [mu.reg_read(r) for r in (UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX,
                                     UC_X86_REG_EBP, UC_X86_REG_ESP)]
    want = ((eye[0] + anchor[0]) / 2, ground_h, (eye[2] + anchor[2]) / 2)
    ok = (all(abs(a - b) < 1e-3 for a, b in zip(ped, want)) and abs(stored_h - anchor_h) < 1e-6
          and top1 == top0 and regs == [anc, edi, 0x11111111, 0x22222222, esp0])
    print(f"eye {eye} anchor {anchor} -> pedestrian anchor {tuple(round(v, 3) for v in ped)} "
          f"(want {want}); anchor height kept {stored_h}; x87 depth {top0}->{top1}; "
          f"esp {'balanced' if regs[4] == esp0 else 'OFF BY ' + str(regs[4] - esp0)}; "
          f"esi/edi/ebx/ebp {'preserved' if regs[:4] == [anc, edi, 0x11111111, 0x22222222] else 'CHANGED'}"
          f"  => {'OK' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    if "pedanchor" not in racemod.PATCHES:
        sys.exit("pedcheck: the pedanchor patch no longer exists (retired 2026-09-24).")
    results = [
        run((100.0, 12.0, -200.0), (140.0, 5.0, -170.0), 5.0, 7.5),     # look +x,+z
        run((-350.5, 30.0, 812.25), (-398.5, 3.0, 812.25), 3.0, 2.25),  # look -x
        run((0.0, 0.0, 0.0), (0.0, 0.0, 48.0), 0.0, -1.0),             # look +z
    ]
    print(f"\npedanchor hook: {sum(results)}/{len(results)} cases OK")
