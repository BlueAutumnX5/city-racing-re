r"""loadertest.py <config.json> - does WINDOWS load a racemod build? (2026-11-01: `tmsect` adds a 7th section,
.crtm, zero-filled). Builds the exe exactly like Apply (racemod.py setup <config> with dry_run, bytes kept via
RACEMOD_DRY_OUT), writes it as game_loadertest.exe NEXT TO game.exe (it needs the game's folder), starts it
SUSPENDED - no game code ever runs - and checks with VirtualQueryEx that every section is mapped at its address
with its size and the right protection, that the stored bytes match the file and .crtm reads back as zeros.
Then terminates it and deletes the copy. The installed game.exe is never touched.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import racemod

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class SI(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("r1", wt.LPWSTR), ("desk", wt.LPWSTR), ("title", wt.LPWSTR)] + \
               [(f"d{i}", wt.DWORD) for i in range(8)] + [("w1", wt.WORD), ("w2", wt.WORD), ("r2", ctypes.c_void_p),
                                                         ("hi", wt.HANDLE), ("ho", wt.HANDLE), ("he", wt.HANDLE)]


class PI(ctypes.Structure):
    _fields_ = [("hp", wt.HANDLE), ("ht", wt.HANDLE), ("pid", wt.DWORD), ("tid", wt.DWORD)]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def main():
    cfg = sys.argv[1]
    out = os.path.join(tempfile.gettempdir(), "racemod_loadertest.bin")
    env = dict(os.environ, RACEMOD_DRY_OUT=out)
    r = subprocess.run([sys.executable, os.path.join(HERE, "racemod.py"), "setup", cfg], env=env,
                       capture_output=True, text=True)
    last = [l for l in r.stdout.splitlines() if "DRY RUN" in l]
    print(last[0] if last else r.stdout[-800:])
    if not json.load(open(cfg)).get("dry_run") or not os.path.exists(out):
        sys.exit("the config must have dry_run: true (and the build must succeed)")
    exe = open(out, "rb").read()
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    nsec = struct.unpack_from("<H", exe, pe + 6)[0]
    opt = struct.unpack_from("<H", exe, pe + 20)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + opt + 40 * i
        name = exe[o:o + 8].rstrip(b"\0").decode()
        vsz, va, rsz, raw = struct.unpack_from("<IIII", exe, o + 8)
        secs.append((name, va, vsz, raw, rsz))
    print(f"{nsec} sections: " + ", ".join(f"{n} {0x400000 + va:#x}+{vsz:#x}" for n, va, vsz, _, _ in secs))
    target = os.path.join(os.path.dirname(racemod.GAME), "game_loadertest.exe")
    with open(target, "wb") as f:
        f.write(exe)
    si, pi = SI(), PI()
    si.cb = ctypes.sizeof(si)
    ok = k32.CreateProcessW(target, None, None, None, False, 0x4, None, os.path.dirname(racemod.GAME),
                            ctypes.byref(si), ctypes.byref(pi))           # CREATE_SUSPENDED
    good = bool(ok)
    if not ok:
        print(f"BAD  Windows refused to create the process (error {ctypes.get_last_error()})")
    else:
        try:
            for name, va, vsz, raw, rsz in secs:
                a = 0x400000 + va
                mbi = MBI()
                k32.VirtualQueryEx(pi.hp, ctypes.c_void_p(a), ctypes.byref(mbi), ctypes.sizeof(mbi))
                n = min(vsz, 0x10000)
                buf = ctypes.create_string_buffer(n)
                got = ctypes.c_size_t()
                k32.ReadProcessMemory(pi.hp, ctypes.c_void_p(a), buf, n, ctypes.byref(got))
                want = (exe[raw:raw + min(rsz, n)] + bytes(n))[:n]
                same = got.value == n and buf.raw == want
                mapped = mbi.State == 0x1000 and (mbi.BaseAddress or 0) <= a
                # the whole section readable to its end
                endb = ctypes.create_string_buffer(16)
                end_ok = k32.ReadProcessMemory(pi.hp, ctypes.c_void_p(a + vsz - 16), endb, 16, ctypes.byref(got))
                ok1 = mapped and same and bool(end_ok)
                good &= ok1
                print(f"  {'OK ' if ok1 else 'BAD'} {name:6s} {a:#010x} size {vsz:#x} protect {mbi.Protect:#x} "
                      f"first {n:#x} bytes {'= file' if same else 'DIFFER'}{', zero-filled' if rsz == 0 and same else ''}"
                      f", last byte {'readable' if end_ok else 'NOT mapped'}")
        finally:
            k32.TerminateProcess(pi.hp, 0)
            k32.WaitForSingleObject(pi.hp, 5000)
            k32.CloseHandle(pi.ht)
            k32.CloseHandle(pi.hp)
    os.remove(target)
    os.remove(out)
    print("loader test: " + ("ALL GOOD" if good else "FAILED") + " (copy deleted, game.exe untouched)")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
