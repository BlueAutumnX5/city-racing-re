"""Detect which payload types are XOR 0x80 obfuscated text vs raw binary."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
from collections import defaultdict

ROOT = crpaths.work(r"extracted")

def classify(b):
    if not b:
        return "empty"
    hi = sum(1 for c in b[:4096] if c >= 0x80)
    frac = hi / len(b[:4096])
    de = bytes(c ^ 0x80 for c in b[:4096])
    printable = sum(1 for c in de if 32 <= c < 127 or c in (9, 10, 13))
    if frac > 0.95 and printable / len(de) > 0.95:
        return "XOR80-text"
    plain = sum(1 for c in b[:4096] if 32 <= c < 127 or c in (9, 10, 13))
    if plain / len(b[:4096]) > 0.95:
        return "plain-text"
    return "binary"

stats = defaultdict(lambda: defaultdict(int))
samples = {}
for arc in ("Objects", "Textures", "World", "SD"):
    base = os.path.join(ROOT, arc, "files")
    for dirpath, _, names in os.walk(base):
        for n in names:
            p = os.path.join(dirpath, n)
            ext = os.path.splitext(n)[1].lower()
            with open(p, "rb") as f:
                head = f.read(4096)
            k = classify(head)
            stats[arc][(ext, k)] += 1
            samples.setdefault((arc, ext, k), (p, head[:64]))

for arc in stats:
    print(f"=== {arc} ===")
    for (ext, k), n in sorted(stats[arc].items()):
        print(f"  {ext:<6} {k:<12} {n:>4}")
    print()

print("=== magic bytes per group ===")
for (arc, ext, k), (p, head) in sorted(samples.items()):
    de = bytes(c ^ 0x80 for c in head)
    show = de if k == "XOR80-text" else head
    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in show[:48])
    print(f"  {arc:<9} {ext:<6} {k:<12} {show[:12].hex(' '):<36} |{txt}|")
