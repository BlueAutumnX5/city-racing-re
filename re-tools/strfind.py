"""Strings in the pristine exe's .rdata/.data matching a regex, with every code reference to each.
Usage: strfind.py <regex> [maxlen]"""
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdis import *

pat = re.compile(sys.argv[1], re.I)
maxlen = int(sys.argv[2]) if len(sys.argv) > 2 else 120
hits = {}
for nm, va, sz, raw, rsz in SECS:
    if nm not in (".rdata", ".data"):
        continue
    blob = data[raw:raw + rsz]
    for m in re.finditer(rb"[\x20-\x7e]{4,}", blob):
        s = m.group().decode("latin-1")
        if pat.search(s) and len(s) <= maxlen:
            hits[va + m.start()] = s
refs = {a: [] for a in hits}
want = set(hits)
for ins in text_insns():
    for mm in re.finditer(r"0x[0-9a-f]{6,8}", ins.op_str):
        v = int(mm.group(0), 16)
        if v in want:
            refs[v].append(ins.address)
for a, s in sorted(hits.items()):
    print(f"0x{a:08x}  {s!r:<60} refs: {' '.join(hex(r) for r in refs[a][:6])}")
