r"""spawnlife.py - READ-ONLY: how long do spawned traffic/police cars live, and do they drive
toward the camera or away from it?

Polls the traffic list ~20x a second. For every car that appears: spawn distance from the
camera, then 1 s later whether that distance shrank (INBOUND) or grew (OUTBOUND), and when it
disappears its lifetime. Summary every 30 s and at the end; one CSV row per finished car.
USAGE  spawnlife.py [SECONDS]      (default: until the game closes)
"""
import csv
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from livewatch import Proc, find_pid, MGR, PLAYER, CAMERA

NAMES = {2: "police", 3: "traffic"}


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 1e9
    pid = find_pid()
    if not pid:
        print("game.exe is not running"); return
    p = Proc(pid)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), time.strftime("spawnlife_%H%M%S.csv"))
    fh = open(out, "w", newline="")
    w = csv.writer(fh)
    w.writerow(["t", "type", "spawn_d", "d_after_1s", "direction", "lifetime", "end_d", "count", "target"])
    print(f"attached read-only to pid {pid}; log -> {out}", flush=True)
    t0 = time.time()
    present, cars, done = None, {}, []
    next_report = t0 + 30
    while time.time() - t0 < limit and p.alive():
        now = time.time()
        try:
            count = p.u32(MGR + 0x128)
            target = p.u32(MGR + 0x12c)
            if not 0 <= count <= 64:
                time.sleep(0.05); continue
            player = p.u32(PLAYER)
            eye = p.vec(p.u32(CAMERA) + 0x70)
            ptrs = [c for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count)) if c and c != player]
            info = {}
            for c in ptrs:
                ty = p.u32(c + 0xc8c)
                if ty in NAMES:
                    info[c] = (ty, math.dist(p.vec(c + 0xa18), eye))
        except OSError:
            time.sleep(0.05); continue
        cur = set(info)
        if present is None:
            present = cur                       # cars already there at attach time are not spawns
        for c in cur - present:
            ty, d = info[c]
            cars[c] = dict(t=now, ty=ty, d0=d, d1=None, dir="?", last=d)
        for c, k in list(cars.items()):
            if c in info:
                k["last"] = info[c][1]
                if k["d1"] is None and now - k["t"] >= 1.0:
                    k["d1"] = k["last"]
                    k["dir"] = "in" if k["d1"] < k["d0"] - 0.5 else ("out" if k["d1"] > k["d0"] + 0.5 else "still")
            else:
                life = now - k["t"]
                done.append((k["ty"], k["dir"], life))
                w.writerow([round(k["t"] - t0, 2), NAMES[k["ty"]], round(k["d0"], 1),
                            None if k["d1"] is None else round(k["d1"], 1), k["dir"],
                            round(life, 2), round(k["last"], 1), count, target])
                fh.flush()
                del cars[c]
        present = cur
        if now >= next_report:
            report(done, now - t0); next_report = now + 30
        time.sleep(0.05)
    report(done, time.time() - t0)


def report(done, el):
    tr = [d for d in done if d[0] == 3]
    if not tr:
        print(f"[{el:5.0f}s] no finished traffic cars yet", flush=True); return
    def stats(xs):
        xs = sorted(xs)
        return f"n={len(xs):4d}  median life {xs[len(xs) // 2]:5.1f}s  under 3 s: {sum(1 for x in xs if x < 3) / len(xs):4.0%}"
    print(f"[{el:5.0f}s] finished traffic cars: {len(tr)}", flush=True)
    for dr in ("in", "out", "still", "?"):
        xs = [d[2] for d in tr if d[1] == dr]
        if xs:
            print(f"    {dr:<5} {len(xs) / len(tr):4.0%}  {stats(xs)}", flush=True)


if __name__ == "__main__":
    main()
