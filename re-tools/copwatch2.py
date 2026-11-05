"""Read-only, deeper: per chasing police car - position, heading, speed, aim point (+0x1e90) and its local
direction (+0x7f4c x / +0x7f54 z: z < 0 = behind -> the stock 33.75 km/h crawl), route count + both ends,
distance to you. 10x a second. Usage: copwatch2.py [seconds=300] -> re-tools/copwatch2_<time>.txt"""
import ctypes, datetime, math, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cpuprofile as cp

MGR, PLAYER = 0x02649368, 0x012D0C88
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300
pid = cp.find_process()
if not pid:
    sys.exit("game not running")
h = cp.k32.OpenProcess(0x0010, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    cp.k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(got))
    return b.raw[:got.value]


u32 = lambda a: struct.unpack("<I", rd(a, 4))[0]
fl = lambda a, n=1: struct.unpack(f"<{n}f", rd(a, 4 * n))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"copwatch2_{datetime.datetime.now():%H%M%S}.txt")
f = open(out, "w")
f.write("t car dist speed x z fx fz aimx aimz loc_x loc_z n r0x r0z rlx rlz you_speed\n")
end, n_rows = time.time() + secs, 0
while time.time() < end:
    me = u32(PLAYER)
    if me:
        mx, _, mz = fl(me + 0xa18, 3)
        mv, = fl(me + 0x7f70)
        cnt = u32(MGR + 0x128)
        for i in range(min(cnt, 64)):
            c = u32(MGR + 0x28 + 4 * i)
            if not c or u32(c + 0xc8c) != 2 or u32(c + 0x1e74) != 4:
                continue
            x, _, z = fl(c + 0xa18, 3)
            fx, _, fz = fl(c + 0x20, 3)
            ax, _, az = fl(c + 0x1e90, 3)
            lx, _, lz = fl(c + 0x7f4c, 3)
            n = u32(c + 0x7f44)
            r0 = fl(c + 0x1ecc, 3)
            rl = fl(c + 0x1ecc + 12 * max(0, min(n, 2048) - 1), 3)
            f.write(f"{time.time():.2f} {c:08x} {math.hypot(x - mx, z - mz):.1f} {fl(c + 0x7f70)[0]:.1f} "
                    f"{x:.1f} {z:.1f} {fx:.2f} {fz:.2f} {ax:.1f} {az:.1f} {lx:.2f} {lz:.2f} {n} "
                    f"{r0[0]:.1f} {r0[2]:.1f} {rl[0]:.1f} {rl[2]:.1f} {mv:.1f}\n")
            n_rows += 1
    time.sleep(0.1)
f.close()
print(out, n_rows, "rows")
