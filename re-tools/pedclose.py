"""The pedestrian spawns that appeared in view closer than 35: when, how close, and whether
they come in bursts (camera teleport / reset) or alone (a genuine pop-in)."""
import csv, sys
path = sys.argv[1]
rows = list(csv.DictReader(open(path)))
peds = [r for r in rows if r["event"] == "ped_spawn" and float(r["t"]) > 5]
close = [r for r in peds if float(r["ahead"] or -2) > 0.7 and float(r["d_camera"]) < 35]
print(f"{len(close)} close in-view pedestrian spawns out of {len(peds)}:")
for r in close:
    t = float(r["t"])
    burst = sum(1 for x in peds if abs(float(x["t"]) - t) <= 0.3)
    cars = sum(1 for x in rows if x["event"] == "spawn" and abs(float(x["t"]) - t) <= 0.3)
    print(f"  t={t:7.1f}  d={float(r['d_camera']):5.1f}  cos={float(r['ahead']):.2f}  "
          f"pedestrian spawns within 0.3 s: {burst:2d}   car spawns within 0.3 s: {cars}")
