"""Does sampling itself slow the sampled thread? Spin a 32-bit busy loop, measure its CPU share alone and
while cpuprofile samples it at 500 Hz."""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

exe = os.path.join(tempfile.gettempdir(), "cr_spin32.exe")
cp.tiny_spin_exe(exe)
p = subprocess.Popen([exe])
try:
    time.sleep(1.0)
    tid, hth, use, _ = cp.busiest_thread(p.pid)
    hproc = cp.k32.OpenProcess(cp.PROCESS_ACCESS, False, p.pid)
    t0, w0 = cp.cpu_time(hth), time.perf_counter()
    time.sleep(5)
    alone = (cp.cpu_time(hth) - t0) / 1e7 / (time.perf_counter() - w0)
    for rate in (500, 200, 100):
        t0, w0 = cp.cpu_time(hth), time.perf_counter()
        smp = cp.sample(hproc, hth, 5, rate)
        sampled = (cp.cpu_time(hth) - t0) / 1e7 / (time.perf_counter() - w0)
        print(f"spinning thread: alone {alone * 100:.0f}% of a core; while sampled at {rate} Hz "
              f"({len(smp) / 5:.0f} samples/s) {sampled * 100:.0f}%")
finally:
    p.kill()
