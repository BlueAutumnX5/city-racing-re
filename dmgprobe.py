r"""dmgprobe.py - READ-ONLY: find the car damage/health fields.

Dumps the player's car and several traffic cars (0x81c4-byte car objects) and prints the float
fields where every traffic car agrees on a plausible "healthy" value (0..10000) but the player's
car differs - candidates for health / damage. With `--save NAME` stores the player's car dump in
dmg_NAME.bin; `--diff A B` prints the float fields that changed between two saved dumps (dump
before and after a crash).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from livewatch import Proc, find_pid, MGR, PLAYER

SIZE = 0x81c4
GLOB, GSIZE = 0x012d0000, 0x1000     # player / profile globals (clock at 0x012d04a0)
HERE = os.path.dirname(os.path.abspath(__file__))


def floats(buf):
    return [struct.unpack_from("<f", buf, o)[0] for o in range(0, SIZE - 3, 4)]


def main():
    if len(sys.argv) > 3 and sys.argv[1] == "--diffg":
        a = open(os.path.join(HERE, f"dmgG_{sys.argv[2]}.bin"), "rb").read()
        b = open(os.path.join(HERE, f"dmgG_{sys.argv[3]}.bin"), "rb").read()
        for o in range(0, GSIZE, 4):
            x, y = struct.unpack_from("<f", a, o)[0], struct.unpack_from("<f", b, o)[0]
            xi, yi = struct.unpack_from("<I", a, o)[0], struct.unpack_from("<I", b, o)[0]
            if xi != yi:
                print(f"  {GLOB + o:#010x}  float {x:12.4f} -> {y:12.4f}   int {xi} -> {yi}")
        return
    if len(sys.argv) > 3 and sys.argv[1] == "--diffz":
        a = open(os.path.join(HERE, f"dmgZ_{sys.argv[2]}.bin"), "rb").read()
        b = open(os.path.join(HERE, f"dmgZ_{sys.argv[3]}.bin"), "rb").read()
        for o in range(0, min(len(a), len(b)), 4):
            x, y = struct.unpack_from("<f", a, o)[0], struct.unpack_from("<f", b, o)[0]
            if x != y:
                print(f"  zone {o // 0x50:3d} +{o % 0x50:#04x}  {x:10.4f} -> {y:10.4f}")
        return
    if len(sys.argv) > 3 and sys.argv[1] == "--diff":
        a = open(os.path.join(HERE, f"dmg_{sys.argv[2]}.bin"), "rb").read()
        b = open(os.path.join(HERE, f"dmg_{sys.argv[3]}.bin"), "rb").read()
        fa, fb = floats(a), floats(b)
        ia = struct.unpack(f"<{len(a) // 4}I", a[:len(a) // 4 * 4]); ib = struct.unpack(f"<{len(b) // 4}I", b[:len(b) // 4 * 4])
        for i, (x, y) in enumerate(zip(fa, fb)):
            if x != y and all(abs(v) < 1e6 for v in (x, y)) and not (0x860 <= i * 4 < 0x8a4):
                print(f"  +{i * 4:#06x}  float {x:12.4f} -> {y:12.4f}   int {ia[i]} -> {ib[i]}")
        return
    p = Proc(find_pid())
    player = p.u32(PLAYER)
    count = p.u32(MGR + 0x128)
    cars = [c for c in struct.unpack(f"<{count}I", p.read(MGR + 0x28, 4 * count)) if c and c != player]
    traffic = [c for c in cars if p.u32(c + 0xc8c) == 3][:4]
    pb = p.read(player, SIZE)
    if len(sys.argv) > 2 and sys.argv[1] == "--save":
        open(os.path.join(HERE, f"dmg_{sys.argv[2]}.bin"), "wb").write(pb)
        open(os.path.join(HERE, f"dmgG_{sys.argv[2]}.bin"), "wb").write(p.read(GLOB, GSIZE))
        nz = p.u32(player + 0xcb4) + p.u32(player + 0xcc8)          # damage zones, 0x50 B each
        if 0 < nz < 20000:
            open(os.path.join(HERE, f"dmgZ_{sys.argv[2]}.bin"), "wb").write(p.read(p.u32(player + 0xc98), nz * 0x50))
        ext = [struct.unpack("<f", p.read(player + o, 4))[0] for o in (0x7fd8, 0x818c, 0x8190, 0x8194, 0x8198, 0x1ea0)]
        print(f"  zones {nz}; engine {ext[0]:.4f}; corners {[round(x, 4) for x in ext[1:5]]}; +0x1ea0 {ext[5]:.4f}")
        print(f"saved player car {player:#x} -> dmg_{sys.argv[2]}.bin (+ globals dmgG_)")
        return
    tb = [p.read(c, SIZE) for c in traffic]
    pf, tf = floats(pb), [floats(t) for t in tb]
    print(f"player car {player:#x}; comparing with {len(traffic)} traffic cars")
    for i, v in enumerate(pf):
        tv = [t[i] for t in tf]
        if len(set(tv)) == 1 and tv[0] != v and 0 <= tv[0] <= 10000 and 0 <= v <= 10000 and tv[0] != 0:
            print(f"  +{i * 4:#06x}  player {v:10.3f}   traffic (all) {tv[0]:10.3f}")


if __name__ == "__main__":
    main()
