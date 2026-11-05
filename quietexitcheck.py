r"""quietexitcheck.py - EXECUTE the game's exit path 0x0045714d in Unicorn with and without `quietexit`
(player 2026-11-01: the game opened its own folder in Explorer on every exit). Without it ShellExecuteA is
called (empty URL = Explorer on the game folder); with it the call is never reached and the code arrives at
0x00457162 with the stack and registers exactly as before the pushes.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import racemod
import racesim
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_EAX

STUB = 0x05900000
OK = []


def run(names):
    sim = racesim.Sim(names)
    mu = sim.mu
    mu.mem_map(STUB, 0x1000, UC_PROT_ALL)
    mu.mem_write(STUB, b"\x31\xc0\xc2\x18\x00")              # ShellExecuteA stand-in: ret 0x18
    mu.mem_write(0x005681A4, struct.pack("<I", STUB))         # its import slot
    calls = []
    mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: calls.append(a), begin=STUB, end=STUB)
    esp0 = racesim.STACK + 0xF0000
    mu.reg_write(UC_X86_REG_ESP, esp0)
    mu.reg_write(UC_X86_REG_EBP, 0)
    mu.reg_write(UC_X86_REG_EAX, 0x1234)
    mu.emu_start(0x0045714D, 0x00457162, count=50)
    return len(calls), mu.reg_read(UC_X86_REG_ESP) == esp0, mu.reg_read(UC_X86_REG_EAX)


def check(label, ok):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}")


n, flat, _ = run(["slack"])
check(f"stock exit path calls ShellExecuteA ({n}x) - the Explorer window", n == 1 and flat)
n, flat, eax = run(["slack", "quietexit"])
check(f"quietexit: ShellExecuteA never called ({n}x), stack unchanged, registers kept",
      n == 0 and flat and eax == 0x1234)
print(f"\n{sum(OK)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
