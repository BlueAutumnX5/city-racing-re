"""Reproduce the play-test: you are FAST (> 15 km/h, the game's other target-speed formula). Police speed,
how often its aim point is behind it (local z < 0 -> stock crawls at 33.75 km/h), per frame."""
import math, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chasesim
from chasesim import COP, ME
from unicorn import UC_HOOK_CODE

ch = chasesim.Chase(chasesim.BASE + ["smartpolice"])
stats = {"frames": 0, "behind": 0, "tgt_speed": []}


def at_speed(uc, a, s, u):                 # 0x0043d3e6: xmm0 = final target speed
    from unicorn.x86_const import UC_X86_REG_XMM0
    v = struct.unpack("<f", (uc.reg_read(UC_X86_REG_XMM0) & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    z = struct.unpack("<f", uc.mem_read(COP + 0x7f54, 4))[0]
    stats["frames"] += 1
    stats["behind"] += z < 0
    stats["tgt_speed"].append(v)


ch.mu.hook_add(UC_HOOK_CODE, at_speed, begin=0x0043D3E6, end=0x0043D3E6)
orig_run = ch.run


def run_fast(C, ang, P):
    ch.w(ME + 0x7f70, "<f", 70.0)          # pretend you drive at 70 km/h (position fixed)
    return orig_run(C, ang, P)


# monkeypatch: chasesim.run writes ME fields first, so set speed every frame via a hook at the handler entry
ch.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.mem_write(ME + 0x7f70, struct.pack("<f", 70.0)),
               begin=0x0043CDA0, end=0x0043CDA0)
cs = chasesim.cases(ch, 30)
res = {}
speeds = []
for C, ang, P, L in cs:
    r = ch.run(C, ang, P)
    res[r["result"]] = res.get(r["result"], 0) + 1
    speeds += [p[2] for p in r["trace"]]
ts = stats["tgt_speed"]
print(res, f"police speed mean {sum(speeds) / len(speeds):.0f} km/h; aim point BEHIND in "
      f"{100 * stats['behind'] / stats['frames']:.0f}% of frames; target speed median "
      f"{sorted(ts)[len(ts) // 2]:.0f}")
