import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os

ROOT = crpaths.work(r"extracted")

def frac_hi(b):
    return sum(1 for c in b if c >= 0x80) / max(1, len(b))

# 1) which .obj is not cleanly XOR80 text?
base = os.path.join(ROOT, "Objects", "files")
for dirpath, _, names in os.walk(base):
    for n in names:
        p = os.path.join(dirpath, n)
        b = open(p, "rb").read()
        de = bytes(c ^ 0x80 for c in b)
        odd = [(i, de[i]) for i in range(len(de))
               if not (32 <= de[i] < 127 or de[i] in (9, 10, 13))]
        if odd:
            rel = os.path.relpath(p, base)
            print(f"[obj outlier] {rel}  size={len(b)}  non-ascii={len(odd)}")
            for i, c in odd[:8]:
                ctx = de[max(0, i-30):i+30].decode("latin-1", "replace").replace("\n", "\\n")
                print(f"    at {i}: byte 0x{c:02x}   ...{ctx}...")

# 2) which .dat files are plain text?
base = os.path.join(ROOT, "World", "files")
plain, binary = [], []
for dirpath, _, names in os.walk(base):
    for n in names:
        if not n.lower().endswith(".dat"):
            continue
        p = os.path.join(dirpath, n)
        b = open(p, "rb").read(4096)
        pr = sum(1 for c in b if 32 <= c < 127 or c in (9, 10, 13)) / max(1, len(b))
        (plain if pr > 0.95 else binary).append((os.path.relpath(p, base), os.path.getsize(p)))

print(f"\n[plain-text .dat] {len(plain)}")
for r, s in sorted(plain):
    print(f"    {s:>8}  {r}")

print(f"\n[binary .dat] {len(binary)} - showing name patterns")
from collections import Counter
pat = Counter()
for r, s in binary:
    parts = r.split(os.sep)
    pat[os.sep.join(parts[:2]) + os.sep + "..." + os.path.basename(r)] += 1
for k, v in sorted(pat.items())[:20]:
    print(f"    {v:>4}x  {k}")
