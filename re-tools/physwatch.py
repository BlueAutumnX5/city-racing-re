r"""physwatch.py - read-only: wait for game.exe, then log the Bullet world's body count every 2 s
(the overlay's "Collision objects" = [world+8], world = [0x02610028]) with the peak, until the game
exits. Capacity since 2026-09-26: 32766 (btAxisSweep3 maxHandles patch 0x004253af).
Usage: physwatch.py [minutes to wait for the game]
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import livewatch

CAP = 32766


def pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith('"game.exe"'):
            return int(line.split('","')[1])
    return None


def main():
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    end = time.time() + wait * 60
    while (p := pid()) is None:
        if time.time() > end:
            print("gave up: the game did not start")
            return 1
        time.sleep(2)
    print(f"attached to game.exe pid {p}", flush=True)
    proc = livewatch.Proc(p)
    peak, t0, last = 0, time.time(), -1
    while proc.alive():
        try:
            world = proc.u32(0x02610028)
            n = proc.u32(world + 8) if world else 0
        except OSError:
            time.sleep(2)
            continue
        peak = max(peak, n)
        t = int(time.time() - t0)
        if t // 30 != last:
            last = t // 30
            print(f"[{t:5d} s] bodies {n:5d}  peak {peak:5d}  ({100 * peak / CAP:.1f}% of {CAP})", flush=True)
        time.sleep(2)
    print(f"game exited. PEAK physics bodies {peak} of {CAP} ({100 * peak / CAP:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
