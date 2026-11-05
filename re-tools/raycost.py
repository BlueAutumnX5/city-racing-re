"""Instructions executed per wheel ray, stock vs rayfast, on the s2check mock world (N objects).
Usage: raycost.py [N ...]"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2check
from unicorn import UC_HOOK_CODE

for n in [int(a) for a in sys.argv[1:]] or [100, 300, 1000]:
    rnd = random.Random(1)
    objs = []
    for i in range(n):
        car = i < 60
        half = (1.0, 0.7, 2.3) if car else (rnd.uniform(1, 25), rnd.uniform(0.5, 30), rnd.uniform(1, 25))
        pos = (rnd.uniform(-400, 400), half[1] if car else 0.0, rnd.uniform(-400, 400))
        objs.append([i, i, pos, rnd.uniform(-3, 3), half, 1])
    res = {}
    for name, extra in (("stock", []), ("rayfast", ["rayfast"])):
        w = s2check.RayWorld(s2check.INSTALLED + extra)
        w.build(objs)
        w.update_aabbs()
        for o in objs[:20]:                                   # warm the lazy cache like a running game
            w.ray((o[2][0], 3, o[2][2]), (o[2][0], -1, o[2][2]))
        cnt = [0]
        h = w.e.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: cnt.__setitem__(0, cnt[0] + 1))
        rays = 40
        for o in objs[:rays]:
            w.ray((o[2][0] + 1, 3, o[2][2] + 2), (o[2][0] + 1, 0.0, o[2][2] + 2))
        w.e.mu.hook_del(h)
        res[name] = cnt[0] / rays
    print(f"{n:5} objects: stock {res['stock']:9.0f} instructions per wheel ray, rayfast {res['rayfast']:7.0f}"
          f"  ->  {res['stock'] / res['rayfast']:.1f}x less work")
