r"""cpuprofile.py - where does the game's CPU time go? (Stage 2 #15a, 2026-10-04)

A sampling profiler for City Racing's MAIN thread, no patch needed: ~500 times a second it pauses the
thread for a few microseconds, reads where it is (EIP) and scans its stack for return addresses, then
lets it run on. After the run it reports, as a share of the main thread's time:
  - subsystems, INCLUSIVE: physics (Bullet), traffic/AI, car driving, rendering, audio, the D3D9
    driver, waiting (Present / vsync / sleeping), ...
  - the hottest game functions (exclusive) and the DLLs the time is spent in.
The game's code has no frame pointers, so call chains come from a stack scan in which every return
address must sit right after a CALL, and a direct call must target the function found one level
deeper (indirect calls are accepted when the next level confirms them) - stale values left on the
stack by earlier calls are rejected.

    cpuprofile.py [seconds=30] [rate=500]      waits for the game, profiles, writes a report
    cpuprofile.py [seconds] [rate] --slow=25    sample ONLY while the game's FPS is below 25 (the drops)
    cpuprofile.py --selftest                   offline proof of the stack decoder + live sampling of a
                                               32-bit test process (no game needed)
The report goes to cpuprofile_<time>.txt next to this file (and to the console).
Run it while driving where the FPS is low (the city centre), game in front.
"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import bisect
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GAME = crpaths.GAME_EXE

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
TH32CS_SNAPTHREAD, TH32CS_SNAPPROCESS = 0x4, 0x2
THREAD_ACCESS = 0x0002 | 0x0008 | 0x0040        # SUSPEND_RESUME | GET_CONTEXT | QUERY_INFORMATION
PROCESS_ACCESS = 0x0400 | 0x0010                # QUERY_INFORMATION | VM_READ
WOW64_CONTEXT_CONTROL = 0x00010001
WOW64_CONTEXT_INTEGER = 0x00010002


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", wt.DWORD), ("Dr", wt.DWORD * 6), ("FloatSave", ctypes.c_byte * 112),
                ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
                ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
                ("Ecx", wt.DWORD), ("Eax", wt.DWORD), ("Ebp", wt.DWORD), ("Eip", wt.DWORD),
                ("SegCs", wt.DWORD), ("EFlags", wt.DWORD), ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
                ("ExtendedRegisters", ctypes.c_byte * 512)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", wt.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


k32.OpenThread.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Wow64SuspendThread.argtypes = [wt.HANDLE]
k32.Wow64SuspendThread.restype = wt.DWORD
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.GetThreadTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]


# ------------------------------------------------------------------ the game's code map
KNOWN = {   # function start -> (name, subsystem). Subsystems are inclusive (a function and all it calls).
    0x00425040: ("main tick", None),
    0x00421ee0: ("physics: world update", "physics"),
    0x0053bfc0: ("Bullet stepSimulation", "physics"),
    0x0053fb40: ("Bullet internalSingleStep", "physics"),
    0x00420d20: ("physics: contact handling", "physics"),
    0x0051e8f0: ("Bullet rayTest (all objects per ray)", "physics"),
    0x00538400: ("vehicle wheel ray (castRay)", "physics"),
    0x0051d930: ("Bullet updateAabbs", "physics"),
    0x0051dc50: ("Bullet rayTestSingle (exact)", "physics"),
    0x0051bbb0: ("shape getAabb (mesh)", "physics"),
    0x005271e0: ("shape getAabb (convex)", "physics"),
    0x0043a420: ("car crash damage", "physics"),
    0x00443ba0: ("traffic update (all cars)", "traffic + AI"),
    0x0043fbe0: ("traffic: per-car step / despawn", "traffic + AI"),
    0x00442c90: ("traffic spawner", "traffic + AI"),
    0x004315e0: ("route builder", "traffic + AI"),
    0x0042d260: ("A* pathfinder", "traffic + AI"),
    0x004345e0: ("car drive (engine/brake)", "cars"),
    0x00421710: ("render: world", "render (game side)"),
    0x00410bd0: ("render: object draw", "render (game side)"),
    0x0040fbd0: ("render: glow", "render (game side)"),
    0x0040c080: ("render: motion blur", "render (game side)"),
    0x00420320: ("render: shadow pass", "render (game side)"),
    0x0041fa20: ("render: reflection A", "render (game side)"),
    0x0041ff40: ("render: reflection B", "render (game side)"),
    0x0046b330: ("HUD draw", "render (game side)"),
    0x0046e6c0: ("audio update", "audio"),
    0x0046cd60: ("engine sound update", "audio"),
    0x004214b0: ("frame clock", None),
}
DLL_GROUP = {  # module name (lower) -> subsystem, for time spent outside game.exe
    "d3d9.dll": "D3D9 + graphics driver", "d3d9on12.dll": "D3D9 + graphics driver",
    "nvd3dum.dll": "D3D9 + graphics driver", "nvwgf2um.dll": "D3D9 + graphics driver",
    "igdumdim32.dll": "D3D9 + graphics driver", "igd9dxva32.dll": "D3D9 + graphics driver",
    "igdumd32.dll": "D3D9 + graphics driver", "d3d11.dll": "D3D9 + graphics driver",
    "dxgi.dll": "D3D9 + graphics driver", "d3d10warp.dll": "D3D9 + graphics driver",
    "dsound.dll": "audio", "dmusic.dll": "audio", "dmime.dll": "audio", "dmsynth.dll": "audio",
    "dmloader.dll": "audio", "dswave.dll": "audio", "audioses.dll": "audio",
    "dinput8.dll": "input", "dinput.dll": "input", "xinput1_3.dll": "input",
}
WAIT_HINT = ("ntdll.dll", "win32u.dll", "kernelbase.dll", "kernel32.dll", "user32.dll")


class CodeMap:
    """Function starts of game.exe (direct call targets + starts after int3 padding) and, for patched
    builds, our caves mapped to the function they were hooked into."""
    def __init__(self, exe_path):
        import racemod
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
        self.data = data = open(exe_path, "rb").read()
        self.secs = racemod.sections(data)
        base, vsz, raw, rsz = self.secs[0]
        self.text = (base, base + vsz)
        code = data[raw:raw + rsz]
        starts = set(KNOWN)
        for i in range(2, len(code)):          # two int3s of padding: one 0xCC can be inside an instruction
            if code[i - 2] == 0xCC and code[i - 1] == 0xCC and code[i] != 0xCC:
                starts.add(base + i)
        md = Cs(CS_ARCH_X86, CS_MODE_32)
        off = 0
        while off < len(code):
            last = None
            for ins in md.disasm(code[off:off + 0x4000], base + off):
                if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
                    t = int(ins.op_str, 16)
                    if base <= t < base + vsz:
                        starts.add(t)
                last = ins.address + ins.size - base
            off = last if last and last > off else off + 1
        self.starts = sorted(starts)
        self._memo = None
        # caves: a 5-byte jmp from a site inside .text to code outside it -> cave belongs to the site's function
        self.caves = []
        try:
            for name, edits in racemod.PATCHES.items():
                for va, orig, new, why in edits:
                    if new[:1] == b"\xe9" and len(new) >= 5 and self.text[0] <= va < self.text[1]:
                        tgt = va + 5 + struct.unpack_from("<i", new, 1)[0]
                        if not self.text[0] <= tgt < self.text[1] or tgt >= 0x00567000:
                            cave_len = max((len(n) for v, o, n, w in edits if v == tgt), default=0x40)
                            if self.read(tgt, 1) not in (b"", b"\0"):
                                self.caves.append((tgt, tgt + cave_len, self.func(va), name))
        except Exception:
            pass

    def read(self, va, n):
        for base, vsz, raw, rsz in self.secs:
            if base <= va < base + max(vsz, rsz):
                r = raw + va - base
                return self.data[r:r + n]
        return b""

    def func(self, va):
        if self._memo is None:
            self._memo = {}
        hit = self._memo.get(va, 0)
        if hit != 0:
            return hit
        r = self._func(va)
        if len(self._memo) < 2_000_000:
            self._memo[va] = r
        return r

    def _func(self, va):
        for a, b, f, _ in self.caves:
            if a <= va < b:
                return f
        if not (self.text[0] <= va < self.text[1]) and not any(a <= va < b for a, b, _, _ in self.caves):
            return None
        i = bisect.bisect_right(self.starts, va) - 1
        return self.starts[i] if i >= 0 else None

    def call_before(self, ret):
        """If `ret` follows a CALL: ('direct', target) or ('indirect', None); else None."""
        b = self.read(ret - 7, 7)
        if len(b) < 7:
            return None
        if b[2] == 0xE8:                                         # call rel32
            return "direct", (ret + struct.unpack_from("<i", b, 3)[0]) & 0xFFFFFFFF
        if b[5] == 0xFF and (b[6] & 0x38) == 0x10 and (b[6] >> 6) == 3:      # call reg
            return "indirect", None
        if b[4] == 0xFF and (b[5] & 0x38) == 0x10 and (b[5] >> 6) == 1:      # call [reg+d8]
            return "indirect", None
        if b[1] == 0xFF and (b[2] & 0x38) == 0x10 and (b[2] >> 6) == 2:      # call [reg+d32]
            return "indirect", None
        if b[5] == 0xFF and (b[6] & 0x38) == 0x10 and (b[6] >> 6) == 0 and b[6] & 7 not in (4, 5):
            return "indirect", None                                          # call [reg]
        if b[1] == 0xFF and b[2] == 0x15:                                    # call [abs32]
            return "indirect", None
        return None

    def chain(self, eip, stack_words):
        """Validated call chain [func(eip), caller, caller's caller, ...] from a raw stack scan."""
        cur = self.func(eip)
        out = [cur] if cur else []
        cands = []
        for w in stack_words:
            if self.func(w) is not None:
                c = self.call_before(w)
                if c:
                    cands.append((w, c))
        i = 0
        while i < len(cands):
            w, (kind, tgt) = cands[i]
            ok = False
            if kind == "direct":
                ok = cur is not None and tgt == cur
            else:                                                # confirm via the next direct link
                fw = self.func(w)
                for w2, (k2, t2) in cands[i + 1:i + 9]:
                    if k2 == "direct" and t2 == fw:
                        ok = True
                        break
            if ok:
                cur = self.func(w)
                out.append(cur)
            i += 1
        return out


# ------------------------------------------------------------------ process plumbing
def find_process(path=GAME):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    found = None
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        if e.szExeFile.lower() == os.path.basename(path).lower():
            h = k32.OpenProcess(0x1000, False, e.th32ProcessID)             # QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                n = wt.DWORD(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and \
                        os.path.normcase(buf.value) == os.path.normcase(path):
                    found = e.th32ProcessID
                k32.CloseHandle(h)
        if found:
            break
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return found


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    t = THREADENTRY32()
    t.dwSize = ctypes.sizeof(t)
    out = []
    ok = k32.Thread32First(snap, ctypes.byref(t))
    while ok:
        if t.th32OwnerProcessID == pid:
            out.append(t.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(t))
    k32.CloseHandle(snap)
    return out


def cpu_time(h):
    c, e, k, u = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    if not k32.GetThreadTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
        return 0
    f = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return f(k) + f(u)


def cycles(h):
    """CPU cycles the thread has run (QueryThreadCycleTime). On this PC GetThreadTimes under-reports
    about 4x (a busy loop shows 22-33% of a core while its cycle counter says 96%) - 2026-10-04."""
    c = ctypes.c_ulonglong()
    k32.QueryThreadCycleTime.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
    return c.value if k32.QueryThreadCycleTime(h, ctypes.byref(c)) else 0


def cycle_rate():
    """Cycles per second of a thread that never stops (this one, spinning 0.3 s)."""
    k32.GetCurrentThread.restype = wt.HANDLE
    me = k32.GetCurrentThread()
    c0, w0 = cycles(me), time.perf_counter()
    while time.perf_counter() - w0 < 0.3:
        pass
    return (cycles(me) - c0) / (time.perf_counter() - w0)


def busiest_thread(pid, window=1.0):
    """The thread that used the most CPU over `window` seconds = the game's main thread."""
    hs = {}
    for tid in threads_of(pid):
        h = k32.OpenThread(THREAD_ACCESS, False, tid)
        if h:
            hs[tid] = (h, cpu_time(h))
    time.sleep(window)
    use = {tid: cpu_time(h) - t0 for tid, (h, t0) in hs.items()}
    best = max(use, key=use.get)
    for tid, (h, _) in hs.items():
        if tid != best:
            k32.CloseHandle(h)
    return best, hs[best][0], use[best] / 1e7 / window, {t: u / 1e7 / window for t, u in use.items()}


def modules_of(hproc):
    arr = (wt.HMODULE * 1024)()
    need = wt.DWORD()
    psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
    psapi.EnumProcessModulesEx(hproc, arr, ctypes.sizeof(arr), ctypes.byref(need), 0x01)   # LIST_MODULES_32BIT
    mods = []

    class MODINFO(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("size", wt.DWORD), ("entry", ctypes.c_void_p)]
    psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
    psapi.GetModuleInformation.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.POINTER(MODINFO), wt.DWORD]
    for i in range(need.value // ctypes.sizeof(wt.HMODULE)):
        name = ctypes.create_unicode_buffer(260)
        psapi.GetModuleBaseNameW(hproc, arr[i], name, 260)
        mi = MODINFO()
        psapi.GetModuleInformation(hproc, arr[i], ctypes.byref(mi), ctypes.sizeof(mi))
        if mi.base:
            mods.append((mi.base, mi.base + mi.size, name.value.lower()))
    return sorted(mods)


FPS_ADDR = 0x005B28C4                           # the game's own FPS (what the debug overlay prints)
GAME_DT_ADDR = 0x012D04A8                       # game frame time, s: exactly 0 while paused (checked live 11-01)
SETTLE = 2.0                                    # s after a pause / alt-tab that are not counted as slow
user32 = ctypes.WinDLL("user32", use_last_error=True)


def game_in_front(pid):
    fpid = wt.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(fpid))
    return fpid.value == pid


def sample(hproc, hthread, seconds, rate, stack_bytes=2048, slow=None, pid=None, skipped=None):
    """slow = N: only sample while the game's FPS is below N AND it is running in front (not paused, not in
    the background) - 2026-11-01: profile the drops, not smooth play, a pause menu or an alt-tab"""
    out = []
    ctx = WOW64_CONTEXT()
    buf = ctypes.create_string_buffer(stack_bytes)
    got = ctypes.c_size_t()
    fps = ctypes.c_float()
    period = 1.0 / rate
    t_end = time.perf_counter() + seconds
    nxt = time.perf_counter()
    cap = int(seconds * rate * 1.5) + 10        # never more than planned: each sample pauses the game
    calm_from = 0.0
    while time.perf_counter() < t_end and len(out) < cap:
        if slow is not None:
            k32.ReadProcessMemory(hproc, ctypes.c_void_p(FPS_ADDR), ctypes.byref(fps), 4, ctypes.byref(got))
            dt = ctypes.c_float()
            k32.ReadProcessMemory(hproc, ctypes.c_void_p(GAME_DT_ADDR), ctypes.byref(dt), 4, ctypes.byref(got))
            # pause / background first (the FPS float is stale then), and SETTLE s after either one: the FPS
            # reads ~4 for a moment on alt-tabbing back (seen live 11-01) - a window switch, not a stutter
            why = "paused" if dt.value == 0.0 else "background" if pid and not game_in_front(pid) else None
            if why:
                calm_from = time.perf_counter() + SETTLE
            elif time.perf_counter() < calm_from:
                why = "settling"
            elif fps.value >= slow:
                why = "fast"
            if why:
                if skipped is not None:
                    skipped[why] = skipped.get(why, 0) + 1
                time.sleep(period)
                nxt = time.perf_counter()
                continue
        if k32.Wow64SuspendThread(hthread) == 0xFFFFFFFF:
            break
        ctx.ContextFlags = WOW64_CONTEXT_CONTROL | WOW64_CONTEXT_INTEGER
        ok = k32.Wow64GetThreadContext(hthread, ctypes.byref(ctx))
        n = 0
        if ok:
            k32.ReadProcessMemory(hproc, ctypes.c_void_p(ctx.Esp), buf, stack_bytes, ctypes.byref(got))
            n = got.value
        k32.ResumeThread(hthread)
        if ok:
            out.append((ctx.Eip, struct.unpack_from(f"<{n // 4}I", buf.raw, 0) if n else ()))
        nxt += period
        d = nxt - time.perf_counter()
        if d > 0:
            time.sleep(d)
        else:
            nxt = time.perf_counter()
    return out


# ------------------------------------------------------------------ analysis
def analyse(samples, cmap, mods, seconds=None, cpu=None):
    from collections import Counter
    n = len(samples)
    sub, excl, modc, incl = Counter(), Counter(), Counter(), Counter()

    def mod_of(a):
        for lo, hi, nm in mods:
            if lo <= a < hi:
                return nm
        return "?"
    for eip, stack in samples:
        m = mod_of(eip)
        modc[m] += 1
        ch = cmap.chain(eip, stack) if (cmap.func(eip) or m != "game.exe") else []
        if m != "game.exe" and not cmap.func(eip):
            # outside the game: attribute to the DLL group, and to the game function that called out
            games = [w for w in stack if cmap.func(w) and cmap.call_before(w)]
            ch = cmap.chain(games[0], stack[stack.index(games[0]) + 1:]) if games else []
        else:
            excl[cmap.func(eip)] += 1
        seen = set()
        for f in ch:
            if f in KNOWN and KNOWN[f][1]:
                seen.add(KNOWN[f][1])
            incl[f] += 0 if f in seen else 1
        grp = DLL_GROUP.get(m)
        if grp:
            seen.add(grp)
        elif m in WAIT_HINT and not seen:
            seen.add("OS / waiting (Present, vsync, sleep, locks)")
        if not seen:
            seen.add("other game code")
        for s in seen:
            sub[s] += 1
    lines = [f"samples: {n}" + (f" over {seconds:.0f} s" if seconds else "")
             + (f"; the main thread used {cpu * 100:.0f}% of one core" if cpu is not None else "")]
    lines.append("\nWHERE THE MAIN THREAD'S TIME GOES (inclusive - a subsystem includes what it calls;")
    lines.append("shares can add up to more than 100% where they nest, e.g. physics calling the driver):")
    for s, c in sub.most_common():
        lines.append(f"  {100 * c / n:5.1f}%  {s}")
    lines.append("\nBY MODULE (where the instruction pointer was):")
    for m, c in modc.most_common(12):
        lines.append(f"  {100 * c / n:5.1f}%  {m}")
    lines.append("\nHOTTEST GAME FUNCTIONS (exclusive, inside game.exe):")
    for f, c in excl.most_common(20):
        if f is None:
            continue
        nm = KNOWN.get(f, ("", None))[0]
        lines.append(f"  {100 * c / n:5.1f}%  0x{f:08x}  {nm}")
    lines.append("\nKNOWN FUNCTIONS, INCLUSIVE:")
    for f, (nm, s) in sorted(KNOWN.items(), key=lambda kv: -incl[kv[0]]):
        if incl[f]:
            lines.append(f"  {100 * incl[f] / n:5.1f}%  0x{f:08x}  {nm}")
    return "\n".join(lines), sub


def main(seconds=30.0, rate=500, slow=None, out_dir=HERE):
    print("waiting for City Racing (our game.exe) to run... start the game and drive.")
    pid = None
    while not pid:
        pid = find_process()
        if not pid:
            time.sleep(2)
    print(f"game found (pid {pid}). Letting it settle 5 s, then finding its main thread...")
    time.sleep(5)
    tid, hth, use, all_use = busiest_thread(pid)
    hproc = k32.OpenProcess(PROCESS_ACCESS, False, pid)
    print(f"main thread {tid} ({use * 100:.0f}% of a core). Profiling {seconds:g} s at {rate} Hz...")
    mods = modules_of(hproc)
    cmap = CodeMap(GAME)
    hz = cycle_rate()                       # cycles/s of a thread that never stops (NOT the sample rate)
    t0 = cycles(hth)
    w0 = time.perf_counter()
    skipped = {}
    smp = sample(hproc, hth, seconds, rate, slow=slow, pid=pid, skipped=skipped)
    if slow is not None:
        print(f"{len(smp)} samples while the FPS was below {slow:g} in front and running "
              f"({len(smp) / rate:.1f} s of slow play); skipped (sample slots): {skipped}")
        if not smp:
            return
    cpu = min(1.0, (cycles(hth) - t0) / hz / (time.perf_counter() - w0)) if hz else None
    rep, _ = analyse(smp, cmap, mods, seconds, cpu)
    others = sorted(((u, t) for t, u in all_use.items() if t != tid), reverse=True)[:6]
    rep += "\n\nOTHER THREADS (share of one core, 1 s before the run):\n" + "\n".join(
        f"  {u * 100:5.1f}%  thread {t}" for u, t in others)
    out = os.path.join(out_dir, f"cpuprofile_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
    with open(out, "w") as f:
        f.write(f"City Racing CPU profile {datetime.datetime.now():%Y-%m-%d %H:%M}, game.exe "
                f"{__import__('hashlib').sha256(open(GAME, 'rb').read()).hexdigest()[:16]}\n\n{rep}\n")
    print("\n" + rep + f"\n\nreport saved: {out}")



def tiny_spin_exe(path):
    """A minimal 32-bit Windows program whose whole code is `jmp $` at 0x00401000: a thread that spins
    at one known address (a precise target for the sampler's self test)."""
    img = bytearray(0x400)
    img[0:2] = b"MZ"
    struct.pack_into("<I", img, 0x3C, 0x80)
    pe = 0x80
    img[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", img, pe + 4, 0x14C, 1, 0, 0, 0, 0xE0, 0x0103)
    o = pe + 24
    struct.pack_into("<HBBIIIIII", img, o, 0x10B, 9, 0, 0x200, 0, 0, 0x1000, 0x1000, 0x2000)
    struct.pack_into("<IIIHHHHHHIIIIHHIIIIII", img, o + 28, 0x400000, 0x1000, 0x200, 5, 1, 0, 0, 5, 1, 0,
                     0x2000, 0x200, 0, 3, 0, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    s = o + 0xE0
    img[s:s + 8] = b".text\0\0\0"
    struct.pack_into("<IIIIIIHHI", img, s + 8, 0x1000, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    img[0x200:0x202] = b"\xEB\xFE"
    open(path, "wb").write(img)


# ------------------------------------------------------------------ self test (no game needed)
def selftest():
    OK = []

    def check(label, cond, extra=""):
        OK.append(bool(cond))
        print(("OK  " if cond else "BAD ") + label + (("  " + str(extra)) if extra else ""))
    import racemod
    cmap = CodeMap(racemod.BACKUP)                                       # the pristine exe
    check(f"{len(cmap.starts)} function starts found in game.exe", len(cmap.starts) > 3000)
    check("known anchors are function starts: spawner, traffic update, stepSimulation",
          all(cmap.func(a) == a for a in (0x00442c90, 0x00443ba0, 0x0053bfc0)))
    # A synthetic main-thread stack, as the real calls lay it out: rand() called from the spawner
    # (call at 0x00442e47 -> return 0x00442e4c), the spawner from the traffic update (0x00443bf6 ->
    # 0x00443bfb), with locals and two DECOYS in between: a stale physics return (0x00421f18, after an
    # indirect `call edx`) and a stale return into A* that no direct call here explains.
    stack = [0x00000005, 0x0012ff00, 0x00442e4c, 0x3f800000, 0x00421f18, 0x00000000, 0x00443bfb,
             0x0042d2a0, 0x00001234]
    ch = cmap.chain(0x0054aba5, stack)
    check("chain rand <- spawner <- traffic update, both decoys rejected",
          ch == [0x0054aba3, 0x00442c90, 0x00443ba0], [hex(x) for x in ch])
    # physics through the indirect vtable call: inside Bullet's stepSimulation, called by `call edx`
    # from the world update (return 0x00421f18), itself called directly from somewhere.
    callers = [w for w in range(0x00421000, 0x00427000) if cmap.call_before(w) == ("direct", 0x00421ee0)]
    check("a direct caller of the world update exists in the main loop", bool(callers),
          [hex(c) for c in callers[:3]])
    if callers:
        ch2 = cmap.chain(0x0053c020, [0x11111111, 0x00421f18, 0x22, callers[0]])
        check("indirect link (call edx -> stepSimulation) confirmed by the next level",
              ch2[:3] == [0x0053bfc0, 0x00421ee0, cmap.func(callers[0])], [hex(x) for x in ch2])
    # the report: 40 samples in traffic (rand <- spawner <- update), 30 in Bullet (via world update),
    # 20 in d3d9.dll called from the shadow pass, 10 in ntdll with no game caller (waiting)
    if callers:
        D3D = (0x60000000, 0x60100000, "d3d9.dll")
        NT = (0x77000000, 0x77100000, "ntdll.dll")
        GAMEMOD = (0x00400000, 0x02711000, "game.exe")
        shadow_ret = next(w for w in range(0x00420320, 0x00420800)
                          if cmap.call_before(w) and cmap.call_before(w)[0] == "indirect")
        main_ret = next(w for w in range(0x00421710, 0x00421900) if cmap.call_before(w) == ("direct", 0x00420320))
        smp = ([(0x0054aba5, tuple(stack))] * 40 + [(0x0053c020, (0x1, 0x00421f18, 0x2, callers[0]))] * 30
               + [(0x60001234, (0x5, shadow_ret, 0x6, main_ret))] * 20 + [(0x77001234, (0x7, 0x8))] * 10)
        rep, sub = analyse(smp, cmap, [GAMEMOD, D3D, NT])
        want = {"traffic + AI": 40, "physics": 30, "D3D9 + graphics driver": 20, "render (game side)": 20,
                "OS / waiting (Present, vsync, sleep, locks)": 10}
        check("report: traffic 40%, physics 30%, driver 20% (called by the render code: render 20% too), "
              "waiting 10%", dict(sub) == want, dict(sub))
        print("\n".join("     " + l for l in rep.splitlines()[:10]))
    # patched build: the adaptive cave belongs to the world update
    names = ["modsect", "fixedstep", "adaptive"]
    import racesim, tempfile
    exe = racesim.build_exe(names)
    tmp = os.path.join(tempfile.gettempdir(), "cpuprofile_test.exe")
    open(tmp, "wb").write(exe)
    pm = CodeMap(tmp)
    os.remove(tmp)
    check("a hooked cave (adaptive physics) maps to the function it was hooked into",
          pm.func(racemod.ADAPT_CAVE + 8) == 0x00421ee0, hex(pm.func(racemod.ADAPT_CAVE + 8) or 0))
    # live mechanics on a real 32-bit native process (no game needed): a generated program spinning on
    # `jmp $` at 0x00401000
    spin = os.path.join(tempfile.gettempdir(), "crspin32.exe")
    tiny_spin_exe(spin)
    p = subprocess.Popen([spin], creationflags=0x08000000)
    try:
        time.sleep(1.0)
        tid, hth, use, all_use = busiest_thread(p.pid)
        hproc = k32.OpenProcess(PROCESS_ACCESS, False, p.pid)
        mods = modules_of(hproc)
        smp = sample(hproc, hth, 2.0, 500)
        check(f"live: picked the busiest of the process's {len(all_use)} threads ({use * 100:.0f}% of a core)",
              use > 0.05 and use == max(all_use.values()))
        check(f"live: {len(smp)} samples in 2 s at 500 Hz", len(smp) > 600, len(smp))
        exact = sum(e == 0x00401000 for e, _ in smp)
        check(f"live: {exact}/{len(smp)} samples read EIP = 0x00401000, the spinning instruction",
              exact > 0.95 * len(smp))
        check("live: the module list maps it to the program itself",
              any(lo <= 0x00401000 < hi and nm == "crspin32.exe" for lo, hi, nm in mods), mods[:2])
        from collections import Counter
        top = Counter(next((nm for lo, hi, nm in mods if lo <= e < hi), "?") for e, _ in smp).most_common(3)
        print("     top modules:", top)
    finally:
        p.kill()
        p.wait()
        try:
            os.remove(spin)
        except OSError:
            pass
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return all(OK)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    slow = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--slow=")), None)
    main(float(args[0]) if args else 30.0, int(args[1]) if len(args) > 1 else 500, slow)
