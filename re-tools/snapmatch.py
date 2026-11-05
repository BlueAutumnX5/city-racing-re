"""Match timed screenshots to carsnap_log.jsonl: for each screenshot's estimated capture time,
take the nearest snapshot and list every car that projects onto the screen, with distance,
game distance, fade alpha (+0xd00) and render alpha (+0x86c). Screen coords are full-res
1920x1080 (the screenshots were 0.6-scale of 1456x819 -> multiply scaled px by 1920/874)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import json, sys
log = [json.loads(l) for l in open(crpaths.work(r"carsnap_log.jsonl"))]
print(f"{len(log)} snapshots, {log[0]['t']:.2f} .. {log[-1]['t']:.2f}")
start, end, n = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
per = (end - start) / n                                  # ~ one screenshot + one wait
for k in range(n):
    # each step = capture (~2.5 s, image grabbed at its start) + 5 s wait
    t = start + 0.3 + k * 7.5
    s = min(log, key=lambda x: abs(x["t"] - t))
    vis = [c for c in s["cars"] if c["sx"] is not None and -50 <= c["sx"] <= 1970 and -50 <= c["sy"] <= 1130]
    print(f"\n=== screenshot {k + 1}: est. t={t:.1f}, snapshot t={s['t']:.1f} (dt {s['t'] - t:+.1f}s), "
          f"eye {s['eye']}, cars on screen {len(vis)} of {len(s['cars'])}")
    for c in sorted(vis, key=lambda c: c["d"]):
        tag = "SOLID" if c["a"] >= 0.999 else ("fading" if c["a"] > 0 else "INVISIBLE")
        print(f"   {c['type']:<8} d={c['d']:6.1f} gd={c['gd']:6.1f} a={c['a']:.2f} ra={c['ra']:.2f} "
              f"screen=({c['sx']:5d},{c['sy']:5d})  scaled=({c['sx'] * 874 / 1920:4.0f},{c['sy'] * 491 / 1080:4.0f})  {tag}")
