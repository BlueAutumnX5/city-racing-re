"""Facts for the `pedanchor` and `grass` patches, from the PRISTINE baseline:
constant readers, exact instruction bytes at every site, and the .data section header."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import struct, sys, bisect
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, crpaths.RETOOLS)
import racemod, xmap
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
m = xmap.load(); S = m["starts"]
fn = lambda a: S[bisect.bisect_right(S, a) - 1]
b = open(racemod.BACKUP, "rb").read()
md = Cs(CS_ARCH_X86, CS_MODE_32)

print("constant readers:")
for c, what in ((0x569d08, "grass fade A (52.5)"), (0x569d04, "grass fade B (105)"),
                (0x56832c, "grass field cutoff (70)"), (0x569c9c, "ped ring (30)"),
                (0x569ad8, "ped fade start (32.5)"), (0x569ad4, "ped fade 1/w"),
                (0x569ad0, "ped despawn (62.5)"), (0x5682f8, "0.5 (for the midpoint)")):
    rs = sorted(m["refs"].get(c, []))
    v = struct.unpack_from("<f", b, racemod.va2raw(b, c))[0]
    print(f"  {c:#x} = {v:g}  {what}: {len(rs)} refs in {len({fn(a) for a in rs})} fns "
          f"{sorted({hex(fn(a)) for a in rs})[:6]}")

print("\ninstruction bytes:")
for va in (0x44f067, 0x44f07a, 0x44f17c, 0x44d36e, 0x44d374, 0x44d379, 0x44ba2e,
           0x442d8b, 0x442d91):
    r = racemod.va2raw(b, va)
    ins = next(md.disasm(b[r:r + 16], va))
    print(f"  {va:#x}  {ins.bytes.hex():<18} {ins.mnemonic} {ins.op_str}")

pe = struct.unpack_from("<I", b, 0x3C)[0]
opt = struct.unpack_from("<H", b, pe + 20)[0]
hdr = pe + 24 + opt + 2 * 40                     # third section = .data
name = b[hdr:hdr + 8].rstrip(b"\0")
vs_off = hdr + 8
print(f"\nsection #3 {name}: VirtualSize field at file offset {vs_off:#x} "
      f"(VA {0x400000 + vs_off:#x}) = {struct.unpack_from('<I', b, vs_off)[0]:#x}")
print("free after .data end 0x026fc57c up to the page end 0x026fd000:",
      "all zero in file? (BSS, not in file)")
print("refs in 0x026fc57c..0x026fd000:", [hex(k) for k in m["refs"] if 0x026fc57c <= k < 0x026fd000])
