import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys, glob, os
b = crpaths.work(r"extracted\Objects\files\Data\Static\InfoScreen")
for f in ("01/Main1.obj", "02/Main1x2.obj"):
    raw = open(os.path.join(b, f), "rb").read()
    txt = bytes(x ^ 0x80 for x in raw).decode("latin-1")
    print("===", f)
    print(txt[:1500])
