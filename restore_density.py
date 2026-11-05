r"""restore_density.py - put ONLY the traffic density map back to factory, keep everything else.

`trafficmod.py restore` and every `trafficmod.py density ...` rebuild BOTH navigation files
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
from factory, which would also wipe the lighthouse-island / south-spur road activation
(activate.py, 2026-09-22) that lives in GlobalRoute.dat. This swaps in the factory
TrafficDensityMap.dat and takes every other World.pak entry from the LIVE archive.

USAGE   restore_density.py dryrun     compare, write nothing
        restore_density.py apply      backup, install, verify
"""
import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak
import trafficmod as tm

BACKUPS = crpaths.BACKUPS


def entries(d):
    e, _, p, _ = crpak.load_archive(d, "World")
    return {n: pl for (n, _, _), pl in zip(e, p)}, [n for n, _, _ in e]


def compare():
    live, order = entries(assets.LIVE)
    stock, _ = entries(assets.STOCK)
    for name in (tm.DENS, tm.ROUTE):
        a, b = live[name], stock[name]
        diff = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
        print(f"  {name}: {len(a):,} bytes, differs from factory in {diff:,} bytes")
    road = [v for v in live[tm.DENS] if v]
    road_s = [v for v in stock[tm.DENS] if v]
    med = lambda xs: sorted(xs)[len(xs) // 2]
    print(f"  density on road cells: live median {med(road)}, factory median {med(road_s)}")
    return live, order, stock


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dryrun"
    print("current state:")
    live, order, stock = compare()
    if mode != "apply":
        sys.exit(0)
    if tm.game_running():
        sys.exit("ABORT: game.exe is running - close City Racing first.")
    # 1. backup the current live archive
    stamp = datetime.date.today().isoformat()
    bdir = os.path.join(BACKUPS, f"{stamp}_world-before-density-restore")
    os.makedirs(bdir, exist_ok=True)
    for ext in ("hdr", "pak"):
        shutil.copy2(os.path.join(assets.LIVE, f"World.{ext}"), bdir)
    print(f"\nbacked up the live World.hdr/.pak to {bdir}")
    # 2. install the factory density only
    rc = tm.install(new_dens=stock[tm.DENS])
    if rc:
        sys.exit(rc)
    # 3. verify: density == factory, every other entry == the live archive before
    after, order2 = entries(assets.LIVE)
    ok_d = after[tm.DENS] == stock[tm.DENS]
    others = [n for n in order if n != tm.DENS]
    same = sum(after[n] == live[n] for n in others)
    print(f"verify: density == factory: {ok_d}; entry order kept: {order2 == order}; "
          f"other entries unchanged: {same}/{len(others)} "
          f"(GlobalRoute.dat kept: {after[tm.ROUTE] == live[tm.ROUTE]})")
    sys.exit(0 if ok_d and order2 == order and same == len(others) else 1)
