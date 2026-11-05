"""Context around each reader of a constant: the function start, a few instructions before
and after the reference (resynced from the function start so the decode is exact)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.RETOOLS)
from adis import annotate, S
import bisect

SITES = [int(a, 16) for a in sys.argv[2:]]
BEFORE = int(sys.argv[1])
for a in SITES:
    f = S[bisect.bisect_right(S, a) - 1]
    lines = annotate(f, a + 0x30).splitlines()
    i = next(k for k, l in enumerate(lines) if l.strip().startswith(f"{a:08x}"))
    print(f"--- {a:#x} (fn {f:#x})")
    print("\n".join(lines[max(0, i - BEFORE): i + 4]))
