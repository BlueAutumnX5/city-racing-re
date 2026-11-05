r"""fadewatch.py - READ-ONLY check of the `fadein` patch in the running game.

Polls the traffic list ~50x a second. Every car that newly appears is followed for 2 s:
its fade (+0xd00) against the distance fade it would have without the limiter
(clamp(1 - (gd - 140) * 0.1), gd = +0xa24). Reports, per car type:
  - the fade at first sight (traffic/police should start near 0: at most a few frames' worth)
  - the fastest rise seen over >= 0.1 s windows (should stay near 1.0 per second)
  - how many cars the limiter actually held back (fade below the distance fade)
USAGE  fadewatch.py [SECONDS]     (default: until the game closes; summary every 30 s)
Log: fadewatch_HHMMSS.csv (one row per new car: first sight + max rise).
"""
import csv
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from livewatch import Proc, find_pid, MGR, PLAYER

NAMES = {0: "player", 1: "racer", 2: "police", 3: "traffic"}
FOLLOW = 2.0


def dist_alpha(gd):
    return max(0.0, min(1.0, 1 - (gd - 140.0) * 0.1))


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 1e9
    pid = find_pid()
    if not pid:
        print("game.exe is not running"); return
    p = Proc(pid)
    f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       time.strftime("fadewatch_%H%M%S.csv"))
    fh = open(out, "w", newline="")
    w = csv.writer(fh)
    w.writerow(["t", "type", "first_alpha", "first_gd", "first_dist_alpha", "second_alpha",
                "second_gd", "alpha_at_end", "max_rise_per_s", "held_back", "car"])
    print(f"attached read-only to pid {pid}; log -> {out}", flush=True)
    t0 = time.time()
    present, follow = None, {}          # None until the first read: cars already in the world
                                        # at attach time are NOT new (the first build counted
                                        # them, with their current fade, as new spawns)
    stats = {}                       # type -> dict
    next_report = t0 + 30
    while time.time() - t0 < limit and p.alive():
        now = time.time()
        try:
            count = p.u32(MGR + 0x128)
            if not 0 <= count <= 64:
                time.sleep(0.02); continue
            player = p.u32(PLAYER)
            cars = [c for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count))
                    if c and c != player]
        except OSError:
            time.sleep(0.02); continue
        cur = set(cars)
        if present is None:
            present = cur
        for c in cur - present:                                   # newly appeared
            try:
                ty = p.u32(c + 0xc8c); a = f(c + 0xd00); gd = f(c + 0xa24)
            except OSError:
                continue
            follow[c] = dict(t=now, ty=ty, first=a, gd=gd, da=dist_alpha(gd),
                             hist=[(now, a)], rise=0.0, held=False)
        for c in list(follow):
            fc = follow[c]
            if c not in cur or now - fc["t"] > FOLLOW:
                s = stats.setdefault(fc["ty"], dict(n=0, first=[], rise=0.0, held=0))
                s["n"] += 1; s["first"].append(fc["first"]); s["rise"] = max(s["rise"], fc["rise"])
                s["held"] += fc["held"]
                sec = fc.get("second", (None, None))
                w.writerow([round(fc["t"] - t0, 2), NAMES.get(fc["ty"], fc["ty"]),
                            round(fc["first"], 3), round(fc["gd"], 1), round(fc["da"], 3),
                            None if sec[0] is None else round(sec[0], 3),
                            None if sec[1] is None else round(sec[1], 1),
                            round(fc["hist"][-1][1], 3) if fc["hist"] else None,
                            round(fc["rise"], 2), int(fc["held"]), f"{c:#x}"])
                fh.flush()
                del follow[c]
                continue
            try:
                a = f(c + 0xd00); gd = f(c + 0xa24)
            except OSError:
                continue
            fc.setdefault("second", (a, gd))
            if a < dist_alpha(gd) - 0.02:
                fc["held"] = True
            fc["hist"].append((now, a))
            for tp, ap in fc["hist"]:                             # rise over >= 0.1 s
                if now - tp >= 0.1:
                    fc["rise"] = max(fc["rise"], (a - ap) / (now - tp))
            fc["hist"] = [(tp, ap) for tp, ap in fc["hist"] if now - tp < 0.3]
        present = cur
        if now >= next_report:
            report(stats, now - t0)
            next_report = now + 30
        time.sleep(0.02)
    report(stats, time.time() - t0)


def report(stats, el):
    print(f"[{el:6.0f}s] new cars followed for {FOLLOW:g} s:", flush=True)
    for ty in sorted(stats):
        s = stats[ty]
        fs = s["first"]
        big = sum(1 for a in fs if a > 0.05)
        print(f"   {NAMES.get(ty, ty):<8} {s['n']:4d}  first fade: max {max(fs):.3f}, "
              f"{big} above 0.05  | fastest rise {s['rise']:.2f}/s  | held back by the "
              f"limiter: {s['held']}", flush=True)


if __name__ == "__main__":
    main()
