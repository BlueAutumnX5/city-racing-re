import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import glob, os, re
root = crpaths.work(r"extracted\Objects\files\Data\Static")
for f in sorted(glob.glob(root + r"\JumpSites\**\*.obj", recursive=True)):
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    keep = [l.strip() for l in t.splitlines() if re.match(r"(Object|Mesh|Effect Type|Additional|Base Weight)", l.strip())]
    print("==", os.path.relpath(f, root), "|", " | ".join(keep))
