import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, re, glob, collections
root = crpaths.work(r"extracted\Objects\files\Data")
cnt = collections.Counter(); parts = collections.Counter(); ex = {}
for f in glob.glob(root + r"\**\*.obj", recursive=True):
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    ty = re.search(r"Object Type:\s+(\S+)", t)
    n = re.search(r"Additional Parts Num:\s+(\d+)", t)
    if ty:
        cnt[ty.group(1)] += 1
        if n and int(n.group(1)) > 0:
            parts[ty.group(1)] += 1
            ex.setdefault(ty.group(1), (os.path.relpath(f, root), int(n.group(1)), re.findall(r"Part[^\n]*:\s+(\S+\.obj)", t)[:4]))
print("model files per GTYPE:", dict(cnt))
print("with additional parts:", dict(parts))
for k, v in ex.items():
    print(f"  e.g. {k}: {v[0]} ({v[1]} parts) {v[2]}")
