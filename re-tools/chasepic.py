"""Picture of chasesim cases: map kinds + static-object cells + stock (blue) and smart (green) paths.
Usage: chasepic.py first_case n_cases -> re-tools/chase_<i>.png"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chasesim
from chasesim import cell_of, SIDE
from PIL import Image, ImageDraw

KC = {0: (0, 0, 0), 1: (70, 70, 70), 2: (140, 140, 140), 3: (230, 200, 40), 4: (230, 120, 30)}
S = 8
OUT = os.path.dirname(os.path.abspath(__file__))
a, n = int(sys.argv[1]), int(sys.argv[2])
stock = chasesim.Chase(chasesim.BASE)
smart = chasesim.Chase(chasesim.BASE + ["smartpolice"])
cs = chasesim.cases(stock, a + n)
for i in range(a, a + n):
    C, ang, P, L = cs[i]
    rs, rm = stock.run(C, ang, P), smart.run(C, ang, P)
    pts = [(p[0], p[1]) for p in rs["trace"] + rm["trace"]] + [(P[0], P[2]), (C[0], C[2])]
    x0, x1 = min(p[0] for p in pts) - 30, max(p[0] for p in pts) + 30
    z0, z1 = min(p[1] for p in pts) - 30, max(p[1] for p in pts) + 30
    c0, c1 = int((x0 + 1200) / 4), int((x1 + 1200) / 4)
    r0, r1 = int((1200 - z1) / 4), int((1200 - z0) / 4)
    im = Image.new("RGB", ((c1 - c0 + 1) * S, (r1 - r0 + 1) * S))
    d = ImageDraw.Draw(im)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            k = stock.sim.kinds[r * SIDE + c]
            col = KC[k]
            if stock.place[r * SIDE + c]:
                col = (170, 30, 30)
            d.rectangle([(c - c0) * S, (r - r0) * S, (c - c0 + 1) * S - 1, (r - r0 + 1) * S - 1], fill=col)
    px = lambda x, z: (((x + 1200) / 4 - c0) * S, ((1200 - z) / 4 - r0) * S)
    for tr, col in ((rs["trace"], (60, 140, 255)), (rm["trace"], (60, 255, 90))):
        d.line([px(p[0], p[1]) for p in tr], fill=col, width=3)
    for (x, z), col in (((P[0], P[2]), (255, 255, 255)), ((C[0], C[2]), (0, 255, 255))):
        X, Y = px(x, z)
        d.ellipse([X - 6, Y - 6, X + 6, Y + 6], outline=col, width=3)
    f = os.path.join(OUT, f"chase_{i}.png")
    im.save(f)
    print(f, "stock", rs["result"], f"{rs['t']:.1f}", "smart", rm["result"], f"{rm['t']:.1f}")
