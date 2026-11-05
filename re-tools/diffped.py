import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.WORK)
import racemod
S = crpaths.RETOOLS
old = open(S + r"\game_before_ped.exe", "rb").read()
new = open(racemod.GAME, "rb").read()
secs = racemod.sections(new)


def raw2va(r):
    for base, vsz, raw, rsz in secs:
        if raw <= r < raw + rsz:
            return base + (r - raw)
    return r + 0x400000


diff = [i for i in range(len(old)) if old[i] != new[i]]
runs = []
for i in diff:
    if runs and i <= runs[-1][1] + 4:
        runs[-1][1] = i
    else:
        runs.append([i, i])
allowed = [(0x400268, 4, "dataslack"), (0x442d8b, 6, "hook"), (0x44d370, 4, "ped y"),
           (0x44d375, 4, "ped x"), (0x44d37b, 4, "ped z"), (0x44ba2f, 4, "ped despawn"),
           (0x44f180, 4, "grass cutoff"), (0x567364, 4, "grass const"),
           (0x567370, 0x60, "ped code"), (0x569d04, 8, "grass fade")]
bad = 0
for a, b in runs:
    va0, va1 = raw2va(a), raw2va(b)
    w = [n for lo, ln, n in allowed if lo <= va0 and va1 < lo + ln]
    bad += not w
    print(f"  0x{va0:08x}..0x{va1:08x}  {w[0] if w else '*** UNEXPECTED ***'}")
print("differing bytes", len(diff), "; unexpected runs", bad)
stray = [raw2va(i) for i in diff if not any(lo <= raw2va(i) < lo + ln for lo, ln, _ in allowed)]
print("byte-level check: bytes outside every allowed window:", [hex(v) for v in stray] or "none")
