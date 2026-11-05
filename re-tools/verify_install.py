import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, struct, hashlib
sys.path.insert(0, crpaths.WORK)
import racemod, racesim
INST = crpaths.GAME_EXE
import json
st = json.load(open(racemod.STATE if hasattr(racemod, "STATE") else crpaths.work(r"racemod_state.json")))
names = st["race"] + ["slack", "dataslack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein", "spawnreach"] + st["extras"]
names = [n for n in names if not n.startswith("-")]
changed = True                                   # every dependency, the way racemod.apply resolves them
while changed:
    changed = False
    for need, deps in racemod.REQUIRES.items():
        if need in names:
            for d in deps:
                if d not in names:
                    names.append(d)
                    changed = True
built = bytes(racesim.build_exe(names))
inst = open(INST, "rb").read()
print("installed == independent build:", built == inst, "  sha256", hashlib.sha256(inst).hexdigest()[:16],
      f"  ({len(inst):,} bytes)")
r = lambda va, n: racemod.read_at(inst, va, n)
for va in (0x004355e8, 0x004358a8, 0x0043bda2, 0x00435a38, 0x00435bf8, 0x0043c180, 0x00435ee8):
    tgt = struct.unpack("<I", r(va, 4))[0]
    print(f"  0x{va:08x} -> [0x{tgt:08x}] = {struct.unpack('<f', r(tgt, 4))[0]:g}")
print("  hook 0x0043fc55:", r(0x0043fc55, 8).hex(), "  rate:", struct.unpack("<f", r(racemod.FADEIN_RATE, 4))[0])
st2 = racemod.state(inst)
print("  extras:", {k: st2[k] for k in racemod.EXTRAS + ("modsect",) if k in st2})
print("  sections:", [hex(s[0]) for s in racemod.sections(inst)])
print("  Game.ini Distance =", racemod.ini_get("Distance"))
