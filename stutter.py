r"""stutter.py - the player's own stutter profiler (2026-11-01: "make a profiler I can start myself, so if it's
stuttering again I can just use it"). Started by "Stutter Profiler.bat". For N minutes (default 10), together:
  - re-tools/perflog.ps1: every second the game's FPS, cars, the busiest thread, GPU load, paused, in front
  - cpuprofile.py --slow=25: samples the main thread ONLY while the FPS is under 25, in front, not paused
Everything goes to "Stutter reports\<date_time>\", plus summary.txt: how many seconds dropped, when, and which
kind - CPU-BOUND (the main thread is maxed: too much work per frame) or WAITING (the main thread mostly idle:
stalled on the graphics driver / iGPU / Windows). READ-ONLY: nothing in the game is changed.
    stutter.py [minutes=10]          stutter.py --summary <perflog.csv>   (re-summarise an old run)
"""
import csv
import datetime
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpuprofile

SLOW = 25.0
SETTLE_ROWS = 2              # seconds after a pause / alt-tab left out (cpuprofile.SETTLE does the same)
BUSY, IDLE = 80, 40         # busiest thread, % of one core: >= BUSY = CPU-bound, < IDLE = waiting
PWSH = shutil.which("pwsh") or shutil.which("powershell") or r"C:\Program Files\PowerShell\7\pwsh.exe"


def summary(path):
    rows = []
    for r in csv.DictReader(open(path)):
        try:
            rows.append({k: float(r[k]) for k in ("fps", "vehicles", "top_thread_pct", "gpu_rtx", "gpu_intel",
                                                   "paused", "front")} | {"time": r["time"]})
        except (TypeError, ValueError, KeyError):
            pass                                           # the "stopped" line
    # the FPS reads ~4 for a second or two on alt-tabbing back / unpausing (seen live 11-01): those SETTLE
    # seconds are a window switch, not a stutter
    away = -99
    for i, r in enumerate(rows):
        if r["paused"] or not r["front"]:
            away = i
        r["settling"] = not (r["paused"] or not r["front"]) and i - away <= SETTLE_ROWS
    settling = [r for r in rows if r["settling"]]
    play = [r for r in rows if not r["paused"] and r["front"] and not r["settling"]]
    drops = [r for r in play if r["fps"] < SLOW]
    back = [r for r in rows if not r["paused"] and not r["front"] and r["fps"] < SLOW]
    out = [f"{len(rows)} s logged: {len(play)} s driving in front, {sum(r['paused'] for r in rows):.0f} s paused, "
           f"{sum(not r['paused'] and not r['front'] for r in rows):.0f} s with the game in the background, "
           f"{len(settling)} s settling after a pause / window switch (not counted)"]
    if play:
        fps = sorted(r["fps"] for r in play)
        out.append(f"FPS while driving: median {fps[len(fps) // 2]:.0f}, lowest {fps[0]:.0f}")
    if not drops:
        out.append(f"\nNO DROPS: the FPS never went under {SLOW:.0f} while you drove with the game in front.")
    else:
        busy = [r for r in drops if r["top_thread_pct"] >= BUSY]
        idle = [r for r in drops if r["top_thread_pct"] < IDLE]
        out.append(f"\n{len(drops)} s under {SLOW:.0f} FPS while driving in front:")
        out.append(f"  {len(busy):4d} s CPU-BOUND - the main thread maxed out (too much work per frame)")
        out.append(f"  {len(idle):4d} s WAITING  - the main thread mostly idle (driver / iGPU / Windows stall)")
        out.append(f"  {len(drops) - len(busy) - len(idle):4d} s in between")
        cars_d = sum(r["vehicles"] for r in drops) / len(drops)
        ok = [r for r in play if r["fps"] >= SLOW]
        cars_ok = sum(r["vehicles"] for r in ok) / len(ok) if ok else 0
        out.append(f"  cars around you: {cars_d:.0f} during drops vs {cars_ok:.0f} otherwise")
        for key, name in (("gpu_rtx", "RTX 3050"), ("gpu_intel", "Intel iGPU")):
            d = sum(r[key] for r in drops) / len(drops)
            o = sum(r[key] for r in ok) / len(ok) if ok else 0
            out.append(f"  {name} 3D load: {d:.0f} % during drops vs {o:.0f} % otherwise")
        spans, start, prev = [], None, None
        for r in play:
            low = r["fps"] < SLOW
            if low and start is None:
                start = r
            if not low and start is not None:
                spans.append((start, prev))
                start = None
            prev = r
        if start is not None:
            spans.append((start, prev))
        out.append("  when: " + ", ".join(a["time"] if a is b else f"{a['time']}-{b['time']}" for a, b in spans[:20])
                   + (" ..." if len(spans) > 20 else ""))
    if back:
        out.append(f"\n{len(back)} s under {SLOW:.0f} FPS with the game in the BACKGROUND: that is Windows power "
                   f"throttling (EcoQoS), not the game - see the powercfg command from 2026-11-01.")
    return "\n".join(out)


def main():
    if "--summary" in sys.argv:
        print(summary(sys.argv[sys.argv.index("--summary") + 1]))
        return 0
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print("waiting for City Racing RE to run...")
    while not cpuprofile.find_process():
        time.sleep(2)
    out = os.path.join(HERE, "Stutter reports", f"{datetime.datetime.now():%Y-%m-%d_%H%M}")
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "perflog.csv")
    print(f"recording {minutes} min into {out}\n"
          f"drive as usual; pausing or switching windows is fine (that time is left out).\n")
    perf = subprocess.Popen([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             os.path.join(HERE, "re-tools", "perflog.ps1"), "-Minutes", str(minutes),
                             "-CsvPath", log], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        cpuprofile.main(minutes * 60.0, 500, SLOW, out_dir=out)
    except Exception as e:                                 # the game closed mid-run
        print(f"profiler stopped early: {e}")
    try:
        perf.wait(timeout=90)
    except subprocess.TimeoutExpired:
        perf.kill()
    text = summary(log) if os.path.exists(log) else "the per-second log did not start (was the game closed?)"
    open(os.path.join(out, "summary.txt"), "w").write(text + "\n")
    print("\n" + "=" * 70 + "\nSUMMARY\n" + text + f"\n\nall files: {out}\n(tell Claude the folder name to read it)")
    os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
