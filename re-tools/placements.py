import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, re, glob, collections
base = crpaths.work(r"extracted")
files = glob.glob(base + r"\**\StaticObjects.obj", recursive=True)
print(len(files), "StaticObjects.obj files; e.g.", files[:1])
types = {}
for f in glob.glob(base + r"\Objects\files\Data\**\*.obj", recursive=True):
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    m = re.search(r"Object Type:\s+(\S+)", t)
    if m:
        types[os.path.relpath(f, base + r"\Objects\files").replace("\\", "/").lower()] = m.group(1)
cnt = collections.Counter(); unknown = collections.Counter()
sample = None
for f in files:
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    sample = sample or t[:600]
    for name in re.findall(r"(Data/[\w/]+\.obj)", t, re.I):
        ty = types.get(name.lower())
        if ty: cnt[ty] += 1
        else: unknown[name] += 1
print("placements by type:", dict(cnt))
print("unresolved names:", sum(unknown.values()), list(unknown.items())[:5])
print("--- sample ---"); print(sample)
