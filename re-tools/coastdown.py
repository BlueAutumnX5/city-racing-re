"""coastdown.py - READ-ONLY top-speed + coast-down logger for the player's car (2026-11-01: how does top speed
depend on Base Engine Force? The drive code has no speed cap; the game's own "design speed" is F x 0.06
(+0x7f74, which the AI aims for), and drivesim ASSUMED aero drag through that point - never measured).
Test: hold full throttle on a long straight until the speed stops rising, then Neutral (manual) / N (auto) and
let the car roll for ~10 s on the flat. 20 samples a second -> coastdown.csv:
time, speed km/h (+0x7f70), design speed (+0x7f74), max force (+0x7f84), engine force F (+0x7f80), throttle.
    coastdown.py [seconds=240]        (then: coastdown.py --analyse)
--analyse: the plateau speed vs the design speed, and the deceleration while coasting vs speed, fitted to
a + b*v (rolling + linear) and a + c*v^2 (aero) - whichever fits says how top speed scales with force.
"""
import ctypes
import csv
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "coastdown.csv")
PLAYER = 0x012D0C88


def pid():
    out = subprocess.run(["tasklist", "/fi", "imagename eq game.exe", "/fo", "csv", "/nh"],
                         capture_output=True, text=True).stdout
    parts = out.strip().split('","')
    return int(parts[1]) if len(parts) > 1 else None


def log(seconds):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0010, False, pid())
    buf = ctypes.create_string_buffer(0x40)
    got = ctypes.c_size_t()

    def rd(a, n):
        k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got))
        return buf.raw[:n]
    t0 = time.perf_counter()
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "v", "vd", "fmax", "f", "throttle"])
        while time.perf_counter() - t0 < seconds:
            car = struct.unpack("<I", rd(PLAYER, 4))[0]
            if car:
                v, _, _, _ = struct.unpack("<4f", rd(car + 0x7F70, 16))
                vd = struct.unpack("<f", rd(car + 0x7F74, 4))[0]
                fv, fmax = struct.unpack("<2f", rd(car + 0x7F80, 8))
                th = struct.unpack("<f", rd(car + 0x7F8C, 4))[0]
                w.writerow([f"{time.perf_counter() - t0:.3f}", f"{v:.3f}", f"{vd:.2f}", f"{fmax:.1f}", f"{fv:.1f}",
                            f"{th:.0f}"])
                f.flush()
            time.sleep(0.05)


def analyse():
    rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(open(OUT))]
    vd = rows[-1]["vd"]
    top = max(r["v"] for r in rows)
    print(f"samples {len(rows)}, design speed (F x 0.06) {vd:.1f} km/h, max force {rows[-1]['fmax']:.0f}, "
          f"highest speed reached {top:.1f} km/h ({top / vd * 100:.0f} % of design)")
    # coasting: throttle 0, speed falling, above 15 km/h
    pts = []
    for a, b in zip(rows, rows[1:]):
        if a["throttle"] == 0 and b["throttle"] == 0 and a["v"] > 15 and b["t"] > a["t"]:
            dec = (a["v"] - b["v"]) / 3.6 / (b["t"] - a["t"])
            pts.append(((a["v"] + b["v"]) / 2, dec))
    if len(pts) < 20:
        print("not enough coasting samples (throttle 0, rolling) - coast in Neutral for ~10 s")
        return
    import statistics

    def fit(fx):
        xs = [fx(v) for v, _ in pts]
        ys = [d for _, d in pts]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a = my - b * mx
        res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
        return a, b, res
    a1, b1, r1 = fit(lambda v: v)
    a2, b2, r2 = fit(lambda v: v * v)
    print(f"coasting samples {len(pts)}, {min(p[0] for p in pts):.0f}..{max(p[0] for p in pts):.0f} km/h")
    print(f"  linear : decel = {a1:.3f} + {b1:.5f} * v      (residual {r1:.3f})")
    print(f"  squared: decel = {a2:.3f} + {b2:.7f} * v^2    (residual {r2:.3f})")
    print("  -> " + ("LINEAR drag: top speed scales ~linearly with force" if r1 < r2 else
                     "AERO (v^2) drag: top speed scales ~with the square root of force"))


if __name__ == "__main__":
    if "--analyse" in sys.argv:
        analyse()
    else:
        log(float(sys.argv[1]) if len(sys.argv) > 1 else 240.0)
