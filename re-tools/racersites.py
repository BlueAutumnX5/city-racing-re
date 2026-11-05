"""Exact bytes for the racers / racerfree patches, from the PRISTINE baseline: the hook site,
the racer-formula immediate, the traffic-count displacement, and for each of the 19 racer-list
instructions the address and old value of its 4-byte displacement."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys
sys.path.insert(0, crpaths.WORK)
import racemod
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
b = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

def ins_at(va):
    r = racemod.va2raw(b, va)
    return next(md.disasm(b[r:r + 16], va))

for va in (0x442de2, 0x442de8, 0x440816, 0x442da8):
    i = ins_at(va)
    print(f"{va:#x}  {i.bytes.hex():<16} {i.mnemonic} {i.op_str}")

SITES = [0x43fecc, 0x43fed2, 0x43fed8, 0x43fede, 0x43fee4, 0x43feea, 0x43fef0, 0x43fef6,
         0x44103e, 0x4410e5, 0x441101, 0x441121, 0x441134, 0x44116b, 0x4411b6, 0x443516,
         0x468f29, 0x468f5f, 0x468ff4]
print("\nracer-list displacement sites:")
out = []
for va in SITES:
    i = ins_at(va)
    raw = i.bytes
    found = None
    for k in range(len(raw) - 3):
        v = struct.unpack_from("<I", raw, k)[0]
        if 0x13da0 <= v < 0x13dc0 or 0x0265d108 <= v < 0x0265d128:
            found = (va + k, v)
            break
    assert found, f"no displacement found at {va:#x}"
    out.append(found)
    print(f"  {va:#x} {i.mnemonic} {i.op_str:<34} disp @ {found[0]:#x} = {found[1]:#x}")
print("\nPYTHON:", [(hex(a), hex(v)) for a, v in out])
