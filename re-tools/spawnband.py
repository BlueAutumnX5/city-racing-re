"""From a livewatch CSV: where do traffic spawns land relative to the 140 -> 150 fade band?
Fade uses game distance = camera distance - radius (~2.3 for traffic), so a spawn at camera
distance d starts with alpha = clamp(1 - (d - 2.3 - 140) / 10). Also: how long do cars live."""
import csv, sys, collections
rows = list(csv.DictReader(open(sys.argv[1])))
t0, t1 = float(sys.argv[2]), float(sys.argv[3])
sp = [r for r in rows if r["event"] == "spawn" and r["type"] == "traffic" and t0 <= float(r["t"]) <= t1]
bins = collections.Counter()
seen = collections.Counter()
for r in sp:
    d = float(r["d_camera"])
    a = max(0.0, min(1.0, 1 - (d - 2.3 - 140) / 10))
    k = "invisible (a=0)" if a == 0 else ("SOLID (a=1)" if a == 1 else "part-faded")
    bins[k] += 1
    seen[(k, r["ahead"] or "side")] += 1
n = len(sp)
print(f"{n} traffic spawns between t={t0} and t={t1}")
for k in ("invisible (a=0)", "part-faded", "SOLID (a=1)"):
    print(f"  {k:<16} {bins[k]:4d} ({100 * bins[k] / n:4.1f}%)   "
          + ", ".join(f"{w}: {seen[(k, w)]}" for w in ("ahead", "side", "behind")))
