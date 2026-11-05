"""Is this process CPU-capped (job object), or is only the CPU-time accounting off? Prints loop speed,
process CPU share, the job's CPU rate control, and the game's own process CPU over 5 s if it runs."""
import ctypes, ctypes.wintypes as wt, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

inj = wt.BOOL()
k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(inj))
print("this process is in a job:", bool(inj.value))


class CPURATE(ctypes.Structure):
    _fields_ = [("ControlFlags", wt.DWORD), ("Value", wt.DWORD)]


r = CPURATE()
ok = k32.QueryInformationJobObject(None, 15, ctypes.byref(r), ctypes.sizeof(r), None)
print("job CPU rate control:", (r.ControlFlags, r.Value) if ok else f"none/unreadable (err {ctypes.get_last_error()})")

t, w, n = time.process_time(), time.perf_counter(), 0
while time.perf_counter() - w < 3:
    n += 1
dt = time.perf_counter() - w
print(f"busy loop: {n / dt / 1e6:.1f} M iterations/s, process CPU {100 * (time.process_time() - t) / dt:.0f}% of a core")

import cpuprofile as cp
pid = cp.find_process()
if pid:
    h = k32.OpenProcess(0x1000, False, pid)
    def ptime():
        c, e, kk, u = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kk), ctypes.byref(u))
        f = lambda x: (x.dwHighDateTime << 32) | x.dwLowDateTime
        return f(kk) + f(u)
    a, w = ptime(), time.perf_counter()
    time.sleep(5)
    print(f"game.exe (all threads): {100 * (ptime() - a) / 1e7 / (time.perf_counter() - w):.0f}% of one core")
else:
    print("game not running")
