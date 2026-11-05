r"""livewatch.py - READ-ONLY live diagnostics for a running City Racing (game.exe).

Opens the process with PROCESS_VM_READ only (it cannot write), samples the game's own
variables ~10x a second, and logs every traffic/police car's spawn and despawn:
distance from the camera and from the player's car, ahead/behind the player's car, and
whether B (look back) was held.

Addresses (static in this build, image base 0x00400000, no relocations):
    0x02649368  traffic manager: +0x28 car list (slot 0 = player), +0x128 count, +0x12c target
    car         +0xa18 position xyz, +0xc8c type (3 traffic, 2 police), +0xd00 fade alpha
    0x012d0c88  the player's car
    0x02610010  camera: +0x70 eye xyz, +0x7c look-at xyz
    0x02610028  physics world: +8 = "Collision objects"
    0x012d0c70  B key held (set on keydown, cleared on keyup)

USAGE  livewatch.py [minutes-to-wait-for-the-game]      (default 30)
Output: a status line every 5 s, a summary when the game exits, events in livewatch_*.csv
"""
import ctypes
import ctypes.wintypes as wt
import csv
import math
import os
import struct
import subprocess
import sys
import time

GLOW = 0x0255d7f0         # renderer glow batches: A +0x25c verts/+0x260 idx, B +0x274/+0x278
GLOW_CAP_A, GLOW_CAP_B = 0x0040b8a3, 0x0040b973     # the caps the RUNNING exe uses
DARK = 0x0264832c         # sky darkness factor (> 0.5 = lights on)
PEDMGR = 0x0255d1f0       # pedestrians: +0 list, +0x100 count (64 slots), +0x104 target
MGR = 0x02649368
PLAYER = 0x012d0c88
CAMERA = 0x02610010
WORLD = 0x02610028
KEY_B = 0x012d0c70
TYPES = {3: "traffic", 2: "police"}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]


def find_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for row in csv.reader(out.splitlines()):
        if row and row[0].lower() == "game.exe":
            return int(row[1])
    return None


class Proc:
    def __init__(self, pid):
        self.h = k32.OpenProcess(0x0010 | 0x1000, False, pid)   # VM_READ | QUERY_LIMITED
        if not self.h:
            raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")

    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) \
                or got.value != n:
            raise OSError("read failed")
        return buf.raw

    def u32(self, a):
        return struct.unpack("<I", self.read(a, 4))[0]

    def vec(self, a):
        return struct.unpack("<3f", self.read(a, 12))

    def alive(self):
        code = wt.DWORD()
        k32.GetExitCodeProcess(self.h, ctypes.byref(code))
        return code.value == 259                                    # STILL_ACTIVE


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def main():
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    deadline = time.time() + wait * 60
    pid = None
    while not pid and time.time() < deadline:
        pid = find_pid()
        if not pid:
            time.sleep(2)
    if not pid:
        print("game never started"); return
    time.sleep(3)
    p = Proc(pid)
    stamp = time.strftime("%H%M%S")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"livewatch_{stamp}.csv")
    f = open(out, "w", newline="")
    w = csv.writer(f)
    w.writerow(["t", "event", "type", "d_camera", "d_player", "ahead", "B_held", "count", "target"])
    print(f"attached read-only to game.exe pid {pid}; events -> {out}", flush=True)

    cap_a, cap_b = p.u32(GLOW_CAP_A), p.u32(GLOW_CAP_B)
    fade_start = struct.unpack("<f", p.read(0x00569838, 4))[0]   # what the running exe uses
    print(f"traffic fade in the running exe starts at {fade_start:g}", flush=True)
    print(f"glow batch caps in the running exe: A {cap_a} vertices, B {cap_b} vertices "
          f"({'glow patch ON' if cap_a > 5000 else 'stock caps'})", flush=True)
    glow_peak_a = glow_peak_b = win_a = win_b = 0
    near_full_a = near_full_b = 0          # 5 s windows whose peak came within 2% of the cap
    ped_known, ped_spawns = {}, []          # ptr -> pos;  (d_camera, cos to the view dir)
    t0 = time.time()
    known = {}            # car ptr -> (type, pos)
    ppos_hist = []        # (t, player pos) for heading
    spawns, despawns = [], []
    counts, targets, colls = [], [], []
    last_status = 0
    while p.alive():
        t = time.time() - t0
        try:
            n = p.u32(MGR + 0x128); tgt = p.u32(MGR + 0x12c)
            if not (0 < n <= 64):
                time.sleep(0.25); continue
            ptrs = struct.unpack(f"<{n}I", p.read(MGR + 0x28, 4 * n))
            player = p.u32(PLAYER)
            ppos = p.vec(player + 0xa18) if player else None
            cam = p.u32(CAMERA)
            eye = p.vec(cam + 0x70)
            b_held = p.u32(KEY_B) != 0
            world = p.u32(WORLD)
            coll = p.u32(world + 8) if world else 0
        except OSError:
            time.sleep(0.25); continue
        counts.append(n); targets.append(tgt); colls.append(coll)
        # pedestrians: where do new ones appear relative to the camera and its view?
        try:
            pn = p.u32(PEDMGR + 0x100)
            look = p.vec(cam + 0x7c)
            lv = [a - b for a, b in zip(look, eye)]
            ll = math.sqrt(sum(v * v for v in lv)) or 1.0
            pnow = {}
            for c in struct.unpack(f"<{pn}I", p.read(PEDMGR, 4 * pn)) if 0 < pn <= 64 else ():
                if not c:
                    continue
                pos = p.vec(c + 0xa18)
                pnow[c] = pos
                prev = ped_known.get(c)
                if prev is None or dist(prev, pos) > 25.0:
                    d = dist(pos, eye)
                    rel = [a - b for a, b in zip(pos, eye)]
                    cosv = sum(r * v for r, v in zip(rel, lv)) / (ll * (d or 1.0))
                    ped_spawns.append((round(t, 1), d, cosv))
                    w.writerow([round(t, 1), "ped_spawn", "pedestrian", f"{d:.1f}", "",
                                f"{cosv:.2f}", int(b_held), pn, ""])
            ped_known = pnow
        except OSError:
            pass
        # The batch counters reset at every render pass, so sample in a burst and keep
        # the maximum: that approaches the per-pass fill level.
        for _ in range(150):
            try:
                blk = struct.unpack("<8I", p.read(GLOW + 0x25c, 32))   # +0x25c .. +0x278
            except OSError:
                break
            va, vb = blk[0], blk[6]                                    # +0x25c, +0x274
            win_a = max(win_a, va); win_b = max(win_b, vb)
        # player heading from the last ~0.6 s of movement
        if ppos:
            ppos_hist.append((t, ppos))
            ppos_hist = [h for h in ppos_hist if t - h[0] <= 0.6]
        fwd = None
        if len(ppos_hist) >= 2:
            d = [b - a for a, b in zip(ppos_hist[0][1], ppos_hist[-1][1])]
            sp = math.hypot(d[0], d[2])
            if sp > 1.0:                       # moving: > ~1.7 units/s
                fwd = (d[0] / sp, d[2] / sp)
        now = {}
        for c in ptrs:
            if not c or c == player:
                continue
            try:
                ty = p.u32(c + 0xc8c); pos = p.vec(c + 0xa18)
            except OSError:
                continue
            now[c] = (ty, pos)
            prev = known.get(c)
            respawn = prev is not None and dist(prev[1], pos) > 25.0
            if prev is None or respawn:
                ahead = ""
                if fwd and ppos:
                    rel = (pos[0] - ppos[0], pos[2] - ppos[2])
                    ahead = "ahead" if rel[0] * fwd[0] + rel[1] * fwd[1] > 0 else "behind"
                dcam = dist(pos, eye)
                try:
                    lk = p.vec(cam + 0x7c)
                    lv = [a - b for a, b in zip(lk, eye)]
                    ll = math.sqrt(sum(v * v for v in lv)) or 1.0
                    cosv = sum((a - b) * v for a, b, v in zip(pos, eye, lv)) / (ll * (dcam or 1.0))
                except OSError:
                    cosv = -2.0
                ev = dict(t=round(t, 1), type=TYPES.get(ty, str(ty)), dcam=dcam,
                          dply=dist(pos, ppos) if ppos else -1, ahead=ahead, B=b_held,
                          cos=cosv)
                spawns.append(ev)
                w.writerow([ev["t"], "spawn", ev["type"], f"{ev['dcam']:.1f}", f"{ev['dply']:.1f}",
                            ahead, int(b_held), n, tgt])
        for c, (ty, pos) in known.items():
            if c not in now:
                despawns.append(dict(type=TYPES.get(ty, str(ty)), dcam=dist(pos, eye)))
                w.writerow([round(t, 1), "despawn", TYPES.get(ty, str(ty)),
                            f"{dist(pos, eye):.1f}", f"{dist(pos, ppos):.1f}" if ppos else "",
                            "", int(b_held), n, tgt])
        known = now
        if t - last_status >= 5:
            last_status = t
            glow_peak_a = max(glow_peak_a, win_a); glow_peak_b = max(glow_peak_b, win_b)
            near_full_a += win_a >= cap_a * 0.98 - 80
            near_full_b += win_b >= cap_b * 0.98 - 49
            try:
                dark = struct.unpack("<f", p.read(DARK, 4))[0]
            except OSError:
                dark = float("nan")
            print(f"          glow A {win_a:5d}/{cap_a}  pools B {win_b:4d}/{cap_b}  "
                  f"darkness {dark:.2f}", flush=True)
            win_a = win_b = 0
            recent = [s for s in spawns if s["t"] >= t - 5]
            print(f"[{t:6.0f}s] vehicles {n - 1:2d} now / target {tgt:2d}  collision objects {coll:4d}"
                  f"  B={'held' if b_held else '-   '}  spawns last 5s: {len(recent)}"
                  + (f"  at {', '.join(f'{s['dcam']:.0f}' for s in recent[:6])}" if recent else ""),
                  flush=True)
            f.flush()
        time.sleep(0.1)
    f.close()

    def stats(xs):
        if not xs:
            return "none"
        xs = sorted(xs)
        return (f"n={len(xs)} min {xs[0]:.0f} median {xs[len(xs) // 2]:.0f} "
                f"max {xs[-1]:.0f}")
    print("\n=== SUMMARY (game exited) ===", flush=True)
    print(f"samples {len(counts)}; vehicles (excluding you) mean {sum(counts) / len(counts) - 1:.1f}, "
          f"max {max(counts) - 1}; target max {max(targets)}; collision objects max {max(colls)}")
    for ty in ("traffic", "police"):
        for b in (False, True):
            ss = [s for s in spawns if s["type"] == ty and s["B"] == b]
            if not ss:
                continue
            a = sum(s["ahead"] == "ahead" for s in ss); bh = sum(s["ahead"] == "behind" for s in ss)
            print(f"{ty:7s} spawns, B {'HELD' if b else 'not held'}: camera distance {stats([s['dcam'] for s in ss])}"
                  f"; from your car {stats([s['dply'] for s in ss if s['dply'] >= 0])}"
                  f"; ahead {a} / behind {bh} (while moving)")
        ds = [d["dcam"] for d in despawns if d["type"] == ty]
        if ds:
            print(f"{ty:7s} despawns: camera distance {stats(ds)}")
    tr = [s for s in spawns if s["type"] == "traffic" and s["t"] > 5 and 0 < s["dcam"] < 300]
    if tr:
        inview = [s for s in tr if s["cos"] > 0.7]         # inside ~45 deg of the view
        solid = [s for s in inview if s["dcam"] < fade_start]
        print(f"traffic spawns INSIDE the camera view: {len(inview)} of {len(tr)}; of those, "
              f"already solid (closer than the fade start {fade_start:g}): {len(solid)} "
              f"({100 * len(solid) / max(1, len(inview)):.1f}%)")
    live = [s for s in ped_spawns if s[0] > 5]            # skip the ones present at attach
    if live:
        front_close = [s for s in live if s[2] > 0.7 and s[1] < 35]   # in view, < 35 away
        print(f"pedestrian spawns: camera distance {stats([s[1] for s in live])}; "
              f"appeared IN VIEW closer than 35: {len(front_close)} of {len(live)}")
    print(f"glow batch A peak {glow_peak_a}/{cap_a} vertices; 5 s windows near full: {near_full_a}")
    print(f"light-pool batch B peak {glow_peak_b}/{cap_b} vertices ({glow_peak_b // 49} pools; "
          f"stock index buffer held 17); windows near full: {near_full_b}")
    print(f"events: {out}")


if __name__ == "__main__":
    main()
