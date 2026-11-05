"""Prove it: poison the count before every A* call. If start==end calls leave the poison
untouched, the pathfinder never writes its count on that path."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, random, struct, collections
sys.path.insert(0, crpaths.WORK)
import racesim, racemod
from racesim import u32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX

POISON = 0x7777
names = racemod.LEVELS[3][1] + ["cap"]
sim = racesim.Sim(names)
cur = {}
res = collections.Counter()
rets = collections.Counter()

def on_entry(mu, addr, size, _):
    esp = mu.reg_read(UC_X86_REG_ESP)
    a = struct.unpack("<9I", mu.mem_read(esp + 4, 36))
    mu.mem_write(a[5], struct.pack("<I", POISON))           # poison the count
    cur["a"] = a

def on_return(mu, addr, size, _):
    a = cur.pop("a")
    cnt = u32(mu.mem_read(a[5], 4))
    same = (a[0], a[1]) == (a[2], a[3])
    key = ("start==end" if same else "normal", "count NOT written" if cnt == POISON else "written")
    res[key] += 1
    if same:
        rets[mu.reg_read(UC_X86_REG_EAX)] += 1

sim.mu.hook_add(UC_HOOK_CODE, on_entry, begin=0x0042d260, end=0x0042d260)
for site in (0x00432d3f, 0x00432dcf):
    sim.mu.hook_add(UC_HOOK_CODE, on_return, begin=site, end=site)

random.seed(4)
for _ in range(80):
    sim.race(random.random())
for k, v in sorted(res.items()):
    print(f"  {k[0]:<11} {k[1]:<18} {v:6d}")
print(f"  A* return value (eax) on start==end calls: {dict(rets)}")
