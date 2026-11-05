r"""carsnap.py - READ-ONLY snapshot of every vehicle in a running (ideally PAUSED) City Racing.

For each car: type, camera distance, the game's own stored distance [+0xa24] (minus radius),
its fade alpha (+0xd00 and the render copy +0x86c), and WHERE ON SCREEN it should be
(projected with the game's camera: vertical FOV 90 deg, aspect = w/h * 0.85, from 0x00425620).
Match the screen positions against a screenshot taken at the same paused moment.

USAGE  carsnap.py [screen_w screen_h]        (default 1920 1080)
       carsnap.py --loop SECONDS [INTERVAL]   log every car twice a second (default) to
                                             carsnap_log.jsonl, with wall-clock timestamps,
                                             to match against screenshots taken meanwhile
"""
import math
import struct
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from livewatch import Proc, find_pid, MGR, PLAYER, CAMERA, TYPES


def snapshot(p, w=1920, h=1080):
    """One reading: camera + every car with type, distances, fade and screen position."""
    cam = p.u32(CAMERA)
    eye, look = p.vec(cam + 0x70), p.vec(cam + 0x7c)
    fwd = [a - b for a, b in zip(look, eye)]
    n = math.sqrt(sum(v * v for v in fwd)) or 1.0
    fwd = [v / n for v in fwd]
    right = [fwd[2], 0.0, -fwd[0]]
    rn = math.sqrt(sum(v * v for v in right)) or 1.0
    right = [v / rn for v in right]
    up = [fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2],
          fwd[0] * right[1] - fwd[1] * right[0]]
    aspect = w / h * 0.85
    count = p.u32(MGR + 0x128)
    player = p.u32(PLAYER)
    cars = []
    for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count)) if 0 < count <= 64 else ():
        if not c or c == player:
            continue
        pos = p.vec(c + 0xa18)
        rel = [a - b for a, b in zip(pos, eye)]
        d = math.sqrt(sum(v * v for v in rel))
        z = sum(r * f for r, f in zip(rel, fwd))
        sx = sy = None
        if z > 0.5:
            sx = (1 + sum(r * v for r, v in zip(rel, right)) / z / aspect) / 2 * w
            sy = (1 - sum(r * v for r, v in zip(rel, up)) / z) / 2 * h
        cars.append(dict(type=TYPES.get(p.u32(c + 0xc8c), str(p.u32(c + 0xc8c))),
                         d=round(d, 1),
                         gd=round(struct.unpack("<f", p.read(c + 0xa24, 4))[0], 1),
                         a=round(struct.unpack("<f", p.read(c + 0xd00, 4))[0], 3),
                         ra=round(struct.unpack("<f", p.read(c + 0x86c, 4))[0], 3),
                         sx=None if sx is None else round(sx), sy=None if sy is None else round(sy)))
    return dict(eye=[round(v, 1) for v in eye], cars=cars)


def loop(seconds, interval=0.5):
    import json, time, os
    pid = find_pid()
    if not pid:
        print("game.exe is not running"); return
    p = Proc(pid)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carsnap_log.jsonl")
    n = 0
    with open(out, "w") as f:
        end = time.time() + seconds
        while time.time() < end and p.alive():
            try:
                s = snapshot(p)
                s["t"] = round(time.time(), 2)
                f.write(json.dumps(s) + "\n"); n += 1
            except OSError:
                pass
            time.sleep(interval)
    print(f"logged {n} snapshots to {out}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        loop(float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 0.5)
        return
    w, h = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1920, 1080)
    pid = find_pid()
    if not pid:
        print("game.exe is not running"); return
    p = Proc(pid)
    cam = p.u32(CAMERA)
    eye, look = p.vec(cam + 0x70), p.vec(cam + 0x7c)
    fwd = [a - b for a, b in zip(look, eye)]
    n = math.sqrt(sum(v * v for v in fwd)); fwd = [v / n for v in fwd]
    up0 = (0.0, 1.0, 0.0)
    right = [up0[1] * fwd[2] - up0[2] * fwd[1], up0[2] * fwd[0] - up0[0] * fwd[2],
             up0[0] * fwd[1] - up0[1] * fwd[0]]
    rn = math.sqrt(sum(v * v for v in right)); right = [v / rn for v in right]
    up = [fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2],
          fwd[0] * right[1] - fwd[1] * right[0]]
    aspect = w / h * 0.85
    fade_start = struct.unpack("<f", p.read(0x00569838, 4))[0]
    fade_w = 1 / struct.unpack("<f", p.read(0x00569834, 4))[0]
    count = p.u32(MGR + 0x128)
    player = p.u32(PLAYER)
    print(f"camera eye ({eye[0]:.0f},{eye[1]:.0f},{eye[2]:.0f}); {count} vehicles incl. you; "
          f"fade {fade_start:g} -> {fade_start + fade_w:g}")
    print(f"{'type':<8} {'dist':>6} {'game d':>7} {'alpha':>6} {'render a':>9}  screen x,y")
    rows = []
    for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count)):
        if not c or c == player:
            continue
        pos = p.vec(c + 0xa18)
        rel = [a - b for a, b in zip(pos, eye)]
        d = math.sqrt(sum(v * v for v in rel))
        z = sum(r * f for r, f in zip(rel, fwd))
        ty = TYPES.get(p.u32(c + 0xc8c), str(p.u32(c + 0xc8c)))
        gd = struct.unpack("<f", p.read(c + 0xa24, 4))[0]
        a1 = struct.unpack("<f", p.read(c + 0xd00, 4))[0]
        a2 = struct.unpack("<f", p.read(c + 0x86c, 4))[0]
        if z > 0.5:
            sx = (1 + sum(r * v for r, v in zip(rel, right)) / z / aspect) / 2 * w
            sy = (1 - sum(r * v for r, v in zip(rel, up)) / z) / 2 * h
            scr = f"{sx:6.0f},{sy:5.0f}" + ("" if 0 <= sx <= w and 0 <= sy <= h else "  (off-screen)")
        else:
            scr = "behind the camera"
        rows.append((d, f"{ty:<8} {d:6.1f} {gd:7.1f} {a1:6.2f} {a2:9.2f}  {scr}"))
    for _, line in sorted(rows):
        print(line)


if __name__ == "__main__":
    main()
