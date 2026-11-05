import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import io, sys, contextlib, random
sys.path.insert(0, crpaths.WORK)
import racesim

random.seed(7)
CONFIGS = [
    ("stock",                       []),
    ("level 3 as shipped",          ["reshuffle", "nostep", "wander", "junction"]),
    ("wander",                      ["wander"]),
    ("wander+nostep+cap",           ["wander", "nostep", "cap"]),
    ("wander+spread+cap",           ["wander", "spread", "cap"]),
    ("reverse+wander",              ["reverse", "wander"]),
    ("reverse+wander+spread+cap",   ["reverse", "wander", "spread", "cap"]),
    ("reverse+wander+nostep+cap",   ["reverse", "wander", "nostep", "cap"]),
]
rows = []
for label, names in CONFIGS:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = racesim.run(names, 400, label)
    txt = buf.getvalue()
    print(txt)
    rows.append((label, out))

print("\n" + "=" * 96)
print(f"{'config':<30}{'fail%':>7}{'Uturn%':>8}{'circle%':>9}{'cross%':>8}"
      f"{'median len':>12}{'max fill':>10}{'overflow':>10}")
for label, o in rows:
    print(f"{label:<30}{o.get('fail',0):7.1f}{o.get('uturn',0):8.1f}{o.get('circle',0):9.1f}"
          f"{o.get('cross',0):8.1f}{o.get('len',0):12}{o.get('fill',0):10}{o.get('over',0):10}")
