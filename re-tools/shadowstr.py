import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re
data = open(crpaths.STOCK_EXE, "rb").read()
strs = sorted(set(m.group().decode("latin-1") for m in re.finditer(rb"[\x20-\x7e]{4,}", data)))
for s in strs:
    if re.search(r"[Ss]hadow|SHADOW|Reflect|Blur|Glow|\[Video\]|Quality|Techniq|Detail", s) and len(s) < 90:
        print("   ", s)
