"""Reproduce the user's 'race line went into the ocean' in the emulator.

Each attempt is a FRESH emulator = a freshly launched game: every route buffer is still
zero. The first race after 'launch' runs with the A* bug live (no astarfix). If the
bug splices unwritten slots into the route, those slots are zero = cell (0,0) = the
top-left corner of the map, which is open sea."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import math, os, random, struct, sys
sys.path.insert(0, crpaths.WORK)
import assets, racesim
from racesim import u32, SIDE, REC

OUT = os.path.dirname(os.path.abspath(__file__))
hit = None
for boot in range(300):
    random.seed(1000 + boot)
    sim = racesim.Sim(["wander"])                  # fresh 'launch', NO astarfix
    r = sim.race(random.random())
    cells = r["cells"][:u32(sim.mu.mem_read(racesim.P_CNT, 4))]
    if not r["ok"] or not cells:
        continue
    zeros = [i for i, c in enumerate(cells) if c == (0, 0)]
    jumps = [i for i in range(1, len(cells))
             if max(abs(cells[i][0] - cells[i-1][0]), abs(cells[i][1] - cells[i-1][1])) > 1]
    if zeros:
        hit = (boot, r, cells, zeros, jumps, sim)
        break
    if boot % 25 == 0:
        print(f"boot {boot}: no ocean yet ({len(jumps)} straight jumps in route)")

if not hit:
    print("no ocean route in 300 fresh launches")
    sys.exit()
boot, r, cells, zeros, jumps, sim = hit
kinds = bytes(min(u32(sim.route, i * REC), 4) for i in range(SIDE * SIDE))
print(f"FOUND on fresh launch #{boot}: route {len(cells)} points, "
      f"{len(zeros)} of them at cell (0,0) = the ocean corner, "
      f"{len(jumps)} straight jumps between non-adjacent points")
x, h, z = struct.unpack_from("<3f", sim.route, 4)
print(f"cell (0,0) in world coords: X={x:.0f} Z={z:.0f}, route kind "
      f"{u32(sim.route, 0)} ({'NOT road - open sea' if u32(sim.route, 0) == 0 else 'road'})")
for i in jumps[:12]:
    a, b = cells[i-1], cells[i]
    d = max(abs(a[0]-b[0]), abs(a[1]-b[1]))
    print(f"   jump at point {i}: {a} -> {b}  ({d} cells = {d*4} world units straight)")

# ---- render the whole map, route drawn as connected lines
S = 2
W = SIDE * S
img = bytearray(W * W * 4)
BG = {0: (14, 18, 30), 1: (40, 44, 54), 2: (52, 66, 58), 3: (96, 86, 44), 4: (86, 54, 44)}
for cy in range(SIDE):
    for cx in range(SIDE):
        col = BG[kinds[cy * SIDE + cx]]
        for dy in range(S):
            o = ((cy * S + dy) * W + cx * S) * 4
            for dx in range(S):
                img[o + dx*4:o + dx*4 + 4] = bytes(col) + b"\xff"

def px(x, y, col, t=1):
    for dy in range(-t, t + 1):
        for dx in range(-t, t + 1):
            X, Y = x + dx, y + dy
            if 0 <= X < W and 0 <= Y < W:
                o = (Y * W + X) * 4
                img[o:o + 4] = bytes(col) + b"\xff"

def line(a, b, col, t):
    (x0, y0), (x1, y1) = [(c * S + S // 2, r_ * S + S // 2) for c, r_ in (a, b)]
    n = max(abs(x1 - x0), abs(y1 - y0), 1)
    for k in range(n + 1):
        px(round(x0 + (x1 - x0) * k / n), round(y0 + (y1 - y0) * k / n), col, t)

n = len(cells)
for i in range(1, n):                              # normal road steps: green -> pink
    a, b = cells[i-1], cells[i]
    if max(abs(a[0]-b[0]), abs(a[1]-b[1])) <= 1:
        t = i / n
        line(a, b, (int(60 + 175 * t), int(225 - 160 * t), int(120 + 110 * t)), 1)
for i in jumps:                                    # straight splices: cyan, thick
    line(cells[i-1], cells[i], (60, 230, 255), 1)
for rad in range(10, 22, 3):                       # the ocean corner: red target
    for a_ in range(0, 360, 2):
        px(int(rad * math.cos(math.radians(a_))) + S, int(rad * math.sin(math.radians(a_))) + S,
           (255, 50, 50), 0)
st = r["start"]
bx, by = (st % SIDE) * S, (st // SIDE) * S
for d in range(-7, 8):
    for e in (-7, 7):
        px(bx + d, by + e, (255, 255, 255), 0); px(bx + e, by + d, (255, 255, 255), 0)
out = os.path.join(OUT, "ocean_route.png")
assets.png_write(out, W, W, bytes(img))
print("wrote", out)
