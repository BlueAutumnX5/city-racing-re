import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, re, glob, collections
base = crpaths.work(r"extracted\Objects\files")
types = {}
for f in glob.glob(base + r"\Data\**\*.obj", recursive=True):
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    m = re.search(r"Object Type:\s+(\S+)", t, re.I)
    if m:
        types[os.path.relpath(f, base).replace("\\", "/").lower()] = m.group(1)
cnt = collections.Counter(); unres = collections.Counter()
for f in glob.glob(base + r"\Data\Landscape\**\StaticObjects.obj", recursive=True):
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    for name in re.findall(r"Object file name:\s+(.+?)\s*$", t, re.M):
        ty = types.get(name.strip().lower())
        if ty: cnt[ty] += 1
        else: unres[name.split("/")[2] if name.count("/") > 2 else name] += 1
print("model files by type:", collections.Counter(types.values()))
print("placements by type:", dict(cnt), " total", sum(cnt.values()))
print("unresolved by folder:", dict(unres))
