import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, re, glob, collections
root = crpaths.work(r"extracted\World\files\Data")
cnt = collections.Counter(); parts = collections.Counter(); ex = {}; eff = collections.Counter()
files = glob.glob(root + r"\**\*.obj", recursive=True)
for f in files:
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    ty = re.search(r"Object Type:\s+(\S+)", t)
    n = re.search(r"Additional Parts Num:\s+(\d+)", t)
    if ty:
        cnt[ty.group(1)] += 1
        for e in re.findall(r"Effect Type:\s+(\S+)", t):
            eff[(ty.group(1), e)] += 1
        if n and int(n.group(1)) > 0:
            parts[ty.group(1)] += 1
            ex.setdefault(ty.group(1), (os.path.relpath(f, root), int(n.group(1)), re.findall(r"[\w/\\]+\.obj", t)[:3]))
print(len(files), "obj files in World.pak")
print("per GTYPE:", dict(cnt))
print("with additional parts:", dict(parts))
for k, v in ex.items():
    print(f"  e.g. {k}: {v[0]} ({v[1]} parts) {v[2]}")
print("effects on buildings:", {e: c for (t, e), c in eff.items() if t == "GTYPE_BUILDING"})
sel = [os.path.relpath(f, root) for f in files if "INFOSCREEN" in bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")]
print("objs using INFOSCREEN:", len(sel), sel[:6])
