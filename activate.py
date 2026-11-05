r"""Activate 'dead' roads - stretches of City Racing that have road surface but no
driving line, so nothing ever drives there: no traffic, no police, no race routes.

WHY THEY ARE DEAD
-----------------
A working street is stored as parallel tracks, e.g.  G Y G O  - green kerb, YELLOW
driving line, green, ORANGE driving line. Two places in the city have the green but
never got the yellow or orange:

    working road   G Y G O
    dead road      G - - - - - - - - - G      kerbs, and nothing in between

Traffic follows kind 3/4 and the race generator walks kind 3 ONLY (game.exe 0x00432b40),
so a road with no yellow is invisible to every system in the game.

WHAT THIS DOES
--------------
1. BFS from every existing yellow cell to find green cells with no yellow within 6 - the
   only reliable signature of a dead road. In the stock map this finds exactly two areas
   and nothing else: the lighthouse island with its causeway, and a spur at the bottom.
2. Retag those green cells as yellow, so the driving line follows the kerb the level
   designers already laid down. No guessing where the road goes.
3. Draw a short connecting line from each dead area to the nearest live yellow cell, so
   the walker can actually reach it.
4. Re-audit every line cell in the map and refuse to write anything if a single cell
   would exceed the game's four adjacency slots.

All of the graph safety logic is imported from mapeditor rather than reimplemented, so
there is one implementation of the rules and one place to fix them.

USAGE
    activate.py dryrun        report what it would do, touch nothing
    activate.py apply         do it, then write World.pak
"""

import os
import struct
import sys
import collections
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak
import mapeditor as M

RADIUS = 6      # a live road always has yellow within 1-2 cells; 6 is generous


def orphan_greens(ed):
    """Green cells more than RADIUS away from any yellow, grouped into areas."""
    INF = 255
    dist = bytearray([INF]) * (M.SIDE * M.SIDE)
    q = collections.deque()
    for r in range(M.SIDE):
        for c in range(M.SIDE):
            if ed.kind(c, r) == 3:
                i = r * M.SIDE + c
                dist[i] = 0
                q.append(i)
    while q:
        i = q.popleft()
        if dist[i] >= RADIUS:
            continue
        r0, c0 = divmod(i, M.SIDE)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < M.SIDE and 0 <= c < M.SIDE:
                    j = r * M.SIDE + c
                    if dist[j] == INF:
                        dist[j] = dist[i] + 1
                        q.append(j)

    orph = {r * M.SIDE + c
            for r in range(M.SIDE) for c in range(M.SIDE)
            if ed.kind(c, r) == 2 and dist[r * M.SIDE + c] == INF}

    groups, seen = [], set()
    for s in sorted(orph):
        if s in seen:
            continue
        stack, cells = [s], []
        seen.add(s)
        while stack:
            i = stack.pop()
            cells.append(i)
            r0, c0 = divmod(i, M.SIDE)
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    r, c = r0 + dr, c0 + dc
                    if 0 <= r < M.SIDE and 0 <= c < M.SIDE:
                        j = r * M.SIDE + c
                        if j in orph and j not in seen:
                            seen.add(j)
                            stack.append(j)
        groups.append(sorted(cells))
    groups.sort(key=len, reverse=True)
    return groups


def nearest_live_yellow(ed, cells, exclude):
    """Closest (dead cell, live yellow cell) pair. `exclude` is the set we just created,
    so we connect to the pre-existing network rather than back to ourselves."""
    best = (10 ** 9, None, None)
    live = [(c, r) for r in range(M.SIDE) for c in range(M.SIDE)
            if ed.kind(c, r) == 3 and (r * M.SIDE + c) not in exclude]
    for i in cells:
        r0, c0 = divmod(i, M.SIDE)
        for (c1, r1) in live:
            d = (r1 - r0) ** 2 + (c1 - c0) ** 2
            if d < best[0]:
                best = (d, (c0, r0), (c1, r1))
    return best


def run(do_apply):
    root = tk.Tk()
    root.withdraw()
    ed = M.Editor(root)

    groups = orphan_greens(ed)
    print(f"{len(groups)} dead road area(s) found\n")
    if not groups:
        root.destroy()
        return 0

    created = set()
    for n, cells in enumerate(groups):
        cols = [i % M.SIDE for i in cells]
        rows = [i // M.SIDE for i in cells]
        print(f"area #{n}: {len(cells)} green cells, cols {min(cols)}-{max(cols)} "
              f"rows {min(rows)}-{max(rows)}")

        placed = 0
        ed.refused = 0
        for i in cells:
            c, r = i % M.SIDE, i // M.SIDE
            if ed.set_line(c, r, 3, None):
                placed += 1
                created.add(i)
        print(f"   driving line laid on {placed} cells, {ed.refused} refused")

        d2, a, b = nearest_live_yellow(ed, cells, created)
        if a is None:
            print("   no live yellow to connect to (!)")
            continue
        path = M.bresenham(a, b)
        ed.refused = 0
        link = 0
        prev = None
        for p in path:
            if ed.set_line(p[0], p[1], 3, prev):
                link += 1
                created.add(p[1] * M.SIDE + p[0])
            prev = p
        print(f"   connected {a} -> {b}: {len(path)} cells along the link, "
              f"{link} newly set, {ed.refused} refused")

    over, edge = ed.audit()
    print(f"\naudit: {len(over)} cells over the 4-link limit, {len(edge)} on the border")
    if over or edge:
        print("REFUSING to write - this would corrupt the route array.")
        root.destroy()
        return 1

    # confirm the areas are now reachable: every new cell must have a yellow neighbour
    lonely = [i for i in created
              if not ed.line_nbrs(i % M.SIDE, i // M.SIDE, 3)]
    print(f"new cells with no yellow neighbour at all: {len(lonely)}")

    if not do_apply:
        print("\ndryrun - nothing written. Run 'activate.py apply' to commit.")
        root.destroy()
        return 0

    if M.game_running():
        print("ABORT: game.exe is running - close City Racing first.")
        root.destroy()
        return 1
    ed.on_apply()
    print(ed.status.get())
    root.destroy()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("dryrun", "apply"):
        sys.exit(run(cmd == "apply"))
    print(__doc__)
