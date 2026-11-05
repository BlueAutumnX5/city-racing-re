"""One-off edit (2026-10-04): smartpolice corner check reaches the end of the route (your end): points
with fewer than SMART_BEND points before you use point 0 as the outgoing end (shorter chord)."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(a, b):
    global t
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)


rep('''    cap_loop:
        cmp edx, {SMART_BEND}
        jb cap_done''', '''    cap_loop:
        cmp edx, 1
        jb cap_done''')
rep('''        lea ecx, [edx-{SMART_BEND}]
        lea ecx, [ecx+ecx*2]''', '''        lea ecx, [edx-{SMART_BEND}]
        test ecx, ecx
        jge out_ok
        xor ecx, ecx
    out_ok:
        lea ecx, [ecx+ecx*2]''')
rep('''#  police piled up at 35-44 km/h while you drove 62). 5.''', '''#  police piled up at 35-44 km/h while you drove 62). Points closer than SMART_BEND points to YOUR end
#  use point 0 as the outgoing end, so a corner just before you is braked for too (the first version
#  skipped them: chasesim, police arriving at 60 km/h when you stood 20 m round a corner). 5.''')
open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("ok")
