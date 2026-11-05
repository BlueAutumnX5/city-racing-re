"""Read-only: log chasing police (type 2, AI state 4) - speed, top-speed setting, throttle, brake, distance
to you, your speed - 5 times a second. Usage: copwatch.py [seconds=120] -> re-tools/copwatch_<time>.txt"""
import ctypes, datetime, math, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

MGR, PLAYER = 0x02649368, 0x012D0C88
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
pid = cp.find_process()
if not pid:
    sys.exit("game not running")
h = cp.k32.OpenProcess(0x0010, False, pid)                     # PROCESS_VM_READ only


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


u32 = lambda a: struct.unpack("<I", rd(a, 4))[0]
f32 = lambda a: struct.unpack("<f", rd(a, 4))[0]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"copwatch_{datetime.datetime.now():%H%M%S}.txt")
rows = []
end = time.time() + secs
while time.time() < end:
    me = u32(PLAYER)
    if me:
        mx, mz = f32(me + 0xa18), f32(me + 0xa20)
        mv = f32(me + 0x7f70)
        n = u32(MGR + 0x128)
        for i in range(min(n, 64)):
            c = u32(MGR + 0x28 + 4 * i)
            if not c or u32(c + 0xc8c) != 2 or u32(c + 0x1e74) != 4:
                continue
            d = math.hypot(f32(c + 0xa18) - mx, f32(c + 0xa20) - mz)
            rows.append((time.time(), c, d, f32(c + 0x7f70), f32(c + 0x7f74), f32(c + 0x7f8c), f32(c + 0x7f94),
                         u32(c + 0x7f98), mv, u32(c + 0x7f44)))
    time.sleep(0.2)
with open(out, "w") as f:
    f.write("t car dist speed topspeed throttle brake handbrake your_speed route_points\n")
    for r in rows:
        f.write(f"{r[0]:.1f} {r[1]:08x} {r[2]:.1f} {r[3]:.1f} {r[4]:.1f} {r[5]:.1f} {r[6]:.1f} {r[7]} {r[8]:.1f} {r[9]}\n")
print(out, len(rows), "rows")
far = [r for r in rows if r[2] > 25]
near = [r for r in rows if r[2] <= 25]
for lab, rs in (("police > 25 m from you", far), ("police <= 25 m", near)):
    if rs:
        print(f"{lab}: {len(rs)} samples, speed mean {sum(r[3] for r in rs) / len(rs):.0f} km/h "
              f"(max {max(r[3] for r in rs):.0f}), top-speed setting {sum(r[4] for r in rs) / len(rs):.0f}, "
              f"braking in {100 * sum(r[6] > 1 for r in rs) / len(rs):.0f}%, full throttle in "
              f"{100 * sum(r[5] >= 99 for r in rs) / len(rs):.0f}%, your speed mean {sum(r[8] for r in rs) / len(rs):.0f}")
