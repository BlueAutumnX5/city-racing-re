"""WHY does the route come out up to 2.8x longer than the walk?
Record every A* call: its endpoints and how many points it appended."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, random, struct, collections
sys.path.insert(0, crpaths.WORK)
import racesim, racemod
from racesim import u32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP

names = racemod.LEVELS[3][1] + ["cap"]
racemod.PATCHES["cap"] = [(0x00432c60, bytes.fromhex("00080000"),
                           struct.pack("<I", 0x800), "uncapped for this study")]
sim = racesim.Sim(names)
calls = []
pending = {}

def on_entry(mu, addr, size, _):
    esp = mu.reg_read(UC_X86_REG_ESP)
    a = struct.unpack("<9I", mu.mem_read(esp + 4, 36))
    ret = u32(mu.mem_read(esp, 4))
    pending["cur"] = (ret, a)

def on_return(mu, addr, size, _):
    ret, a = pending.pop("cur")
    cnt = u32(mu.mem_read(a[5], 4))
    passno = 1 if addr == 0x00432d3f else 2
    calls.append((passno, a[0], a[1], a[2], a[3], cnt))

sim.mu.hook_add(UC_HOOK_CODE, on_entry, begin=0x0042d260, end=0x0042d260)
sim.mu.hook_add(UC_HOOK_CODE, on_return, begin=0x00432d3f, end=0x00432d3f)
sim.mu.hook_add(UC_HOOK_CODE, on_return, begin=0x00432dcf, end=0x00432dcf)

random.seed(4)
worst = []
per_course = []
for t in range(120):
    calls.clear()
    r = sim.race(random.random())
    if r["walk"] == 0:
        continue
    segs = [(p, sc, sr, ec, er, n, max(abs(ec - sc), abs(er - sr))) for p, sc, sr, ec, er, n in calls]
    tot = sum(s[5] for s in segs if s[0] == 2)
    per_course.append((r["count"] / max(1, r["walk"]), r["walk"], r["pass1"], r["count"], segs))
    for s in segs:
        worst.append((s[5] - (s[6] + 1), s))

per_course.sort(key=lambda x: -x[0])
print("worst courses (route/walk):")
for ratio, w, p1, fin, segs in per_course[:5]:
    print(f"  ratio {ratio:.2f}  walk {w}  pass1 {p1}  final {fin}")

print("\nsegments by EXCESS = points appended - (chebyshev distance + 1):")
exc = collections.Counter()
for e, s in worst:
    exc[min(e, 50) if e >= 0 else -1] += 1
for k in sorted(exc):
    print(f"   excess {k:>3}{'+' if k == 50 else ' '}: {exc[k]:6d} calls")

print("\n15 worst individual A* calls:")
worst.sort(key=lambda x: -x[0])
for e, (p, sc, sr, ec, er, n, d) in worst[:15]:
    same = "  <-- START == END" if (sc, sr) == (ec, er) else ""
    print(f"   pass {p}: ({sc},{sr}) -> ({ec},{er})  distance {d:3d}  appended {n:4d}{same}")

se = [s for _, s in worst if (s[1], s[2]) == (s[3], s[4])]
print(f"\ncalls with start == end: {len(se)} of {len(worst)}; "
      f"appended counts for them: {collections.Counter(s[5] for s in se).most_common(8)}")
