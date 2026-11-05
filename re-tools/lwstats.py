"""Analyse a livewatch CSV: spawn distance histogram (camera), outliers, and what share of
forward spawns would pop in solid under different fade-start values."""
import csv, collections, sys
path = sys.argv[1]
rows = list(csv.DictReader(open(path)))
by_t = collections.defaultdict(list)
for r in rows:
    by_t[r["t"]].append(r)

print("outlier spawns (camera < 40 or > 300) and what else happened in the same 0.1 s sample:")
for r in rows:
    d = float(r["d_camera"])
    if r["event"] == "spawn" and (d < 40 or d > 300):
        same = by_t[r["t"]]
        far = sum(1 for x in same if x["event"] == "despawn" and float(x["d_camera"]) > 200)
        print(f"  t={r['t']:>6} {r['type']:<7} camera {d:5.0f} car {float(r['d_player']):5.0f}  "
              f"same sample: {len(same)} events, {far} despawns >200 away")

sp = [r for r in rows if r["event"] == "spawn" and r["type"] == "traffic" and r["B_held"] == "0"
      and 40 <= float(r["d_camera"]) <= 300]
print(f"\nnormal traffic spawns (B not held, 40..300 from camera): {len(sp)}")
bins = collections.Counter(int(float(r["d_camera"]) // 10) * 10 for r in sp)
for b in sorted(bins):
    print(f"  {b:3d}-{b + 9:3d}  {'#' * bins[b]} {bins[b]}")
ahead = [r for r in sp if r["ahead"] == "ahead"]
print(f"\nof those, spawned AHEAD of your moving car: {len(ahead)}")
for start in (78, 90, 100, 105):
    solid = sum(1 for r in ahead if float(r["d_camera"]) < start)
    print(f"  fade starting at {start:3d}: {solid:3d} of {len(ahead)} ahead-spawns "
          f"({100 * solid / max(1, len(ahead)):4.1f}%) appear already fully solid")
