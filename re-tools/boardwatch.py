"""READ-ONLY (2026-10-04): log the race billboard's life, 10x/s, on every change: the board object
[0x02649368+0x13d98], its visible +0xa28 / active +0xa34 / alpha +0x86c / game distance +0xa24, camera
distance to the board spot [+0xdd88], race route count [+0x13d88], flags [0x02610284], [0x0265d104] and
the game state [0x012cc3a4]. Ctrl+C to stop. Usage: boardwatch.py [seconds=600]"""
import math, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from livewatch import Proc, find_pid, CAMERA
MGR = 0x02649368
p = Proc(find_pid())
f = lambda a: struct.unpack("<f", p.read(a, 4))[0]
end = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 600)
last, t0 = None, time.time()
while time.time() < end and p.alive():
    try:
        b = p.u32(MGR + 0x13D98)
        eye = p.vec(p.u32(CAMERA) + 0x70)
        spot = p.vec(MGR + 0xDD88)
        dist = math.dist(eye, spot)
        board = (f"vis {p.u32(b + 0xa28)} act {p.u32(b + 0xa34)} alpha {f(b + 0x86c):.2f} gd {f(b + 0xa24):.0f}"
                 if b else "-")
        key = (b, board.split(" gd")[0], p.u32(MGR + 0x13D88) > 0, p.u32(0x02610284), p.u32(0x0265D104), p.u32(0x012CC3A4))
        if key != last:
            print(f"{time.time() - t0:7.1f}s board {b:#010x} {board:<38} cam->spot {dist:6.1f} m  route {p.u32(MGR + 0x13D88):4d}  "
                  f"f284 {key[3]} race {key[4]} state {key[5]}", flush=True)
            last = key
    except OSError:
        pass
    time.sleep(0.1)
