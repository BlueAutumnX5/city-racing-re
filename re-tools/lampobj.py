import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import glob, os, re
root = crpaths.work(r"extracted\Objects\files\Data\Static\Decors\Lamps")
for f in sorted(glob.glob(root + r"\**\*.obj", recursive=True))[:3]:
    t = bytes(b ^ 0x80 for b in open(f, "rb").read()).decode("latin-1")
    print("=====", os.path.relpath(f, root))
    keep = [l for l in t.splitlines() if re.match(r"(Object|Mesh|Main|Effect|Additional|Part|Base)", l.strip())]
    print("\n".join(keep[:40]))
