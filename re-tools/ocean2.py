"""Revised hypothesis: the bug splices non-adjacent road points into the route, and the
straight line between them crosses WATER. Play several races per 'session', like real
play, and measure every straight jump: length, and how much sea it crosses."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import math, os, random, struct, sys
sys.path.insert(0, crpaths.WORK)
import assets, racesim
from racesim import u32, SIDE, REC

OUT = os.path.dirname(os.path.abspath(__file__))
if __name__ == "__main__":
    best, tally = None, dict(races=0, with_jump=0, jumps=0, wet=0, corner=0)
    for boot in range(60):
        random.seed(5000 + boot)
        sim = racesim.Sim(["wander"])                  # fresh launch, bug live, no astarfix
        kinds = bytes(min(u32(sim.route, i * REC), 4) for i in range(SIDE * SIDE))
        for race_no in range(8):                        # a play session: 8 races in a row
            r = sim.race(random.random())
            if not r["ok"]:
                continue
            cells = r["cells"][:u32(sim.mu.mem_read(racesim.P_CNT, 4))]
            tally["races"] += 1
            tally["corner"] += sum(1 for c in cells if c == (0, 0))
            js = []
            for i in range(1, len(cells)):
                a, b = cells[i - 1], cells[i]
                d = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
                if d <= 1:
                    continue
                water = sum(1 for k in range(1, d)
                            if kinds[round(a[1] + (b[1] - a[1]) * k / d) * SIDE
                                     + round(a[0] + (b[0] - a[0]) * k / d)] == 0)
                js.append((i, a, b, d, water))
            if js:
                tally["with_jump"] += 1
                tally["jumps"] += len(js)
                tally["wet"] += sum(1 for j in js if j[4])
                score = max(j[4] for j in js)
                if best is None or score > best[0]:
                    best = (score, boot, race_no, r, cells, js, kinds)

    print(f"{tally['races']} races over 60 sessions: {tally['with_jump']} had straight "
          f"jumps ({tally['jumps']} jumps total), {tally['wet']} of those jumps cross "
          f"water, {tally['corner']} points at the (0,0) ocean corner")
    if not best:
        sys.exit()
    score, boot, race_no, r, cells, js, kinds = best
    print(f"\nmost dramatic: session {boot}, race #{race_no + 1} of the session")
    for i, a, b, d, w in js:
        print(f"   point {i}: {a} -> {b}  straight {d} cells ({d*4} units), "
              f"{w} cells of it over water")

    S = 2
    W = SIDE * S
    img = bytearray(W * W * 4)
    BG = {0: (14, 20, 36), 1: (40, 44, 54), 2: (52, 66, 58), 3: (96, 86, 44), 4: (86, 54, 44)}
    for cy in range(SIDE):
        for cx in range(SIDE):
            col = bytes(BG[kinds[cy * SIDE + cx]]) + b"\xff"
            for dy in range(S):
                o = ((cy * S + dy) * W + cx * S) * 4
                img[o:o + 4 * S] = col * S

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
    for i in range(1, n):
        a, b = cells[i - 1], cells[i]
        if max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1:
            t = i / n
            line(a, b, (int(60 + 175 * t), int(225 - 160 * t), int(120 + 110 * t)), 1)
    for i, a, b, d, w in js:
        line(a, b, (60, 230, 255), 2)
    st = r["start"]
    bx, by = (st % SIDE) * S, (st // SIDE) * S
    for d in range(-8, 9):
        for e in (-8, 8):
            px(bx + d, by + e, (255, 255, 255), 0); px(bx + e, by + d, (255, 255, 255), 0)
    out = os.path.join(OUT, "ocean_route.png")
    assets.png_write(out, W, W, bytes(img))
    print("wrote", out)
