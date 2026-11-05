"""Replace the pedanchor section of racemod.py (between its header comment and the overlay
comment) with a history note + the dataslack patch. Exact-text surgery with checks."""
import crpaths
p = crpaths.work(r"racemod.py")
src = open(p, encoding="utf-8").read()
start = src.index("# ---- pedanchor: pedestrians keep the STOCK spawn anchor")
end = src.index("# The developer overlay WITHOUT the `Debug out` flag")
new = '''# ---- pedestrians: centred on the camera, like traffic ------------------------------------
#
# Pedestrians are placed around the TRAFFIC spawn anchor [0x026530e4] (= traffic manager
# +0x9d7c): spawner 0x0044d2d0 puts them on a ring around it (0x0044d36e/74/79, ring
# 0x00569c9c), the per-pedestrian step 0x0044b9a0 despawns them beyond 0x00569ad0 from it
# (0x0044ba2e), and fades them by CAMERA distance 32.5 -> 50 (0x00569ad8 / 0x00569ad4).
# History: `view` first moved that anchor 48 ahead and pedestrians popped in centre screen;
# a `pedanchor` hook (2026-09-24, pedcheck.py 3/3) rebuilt the stock 24-ahead point for them.
# Since the traffic anchor became the camera itself, pedestrians simply follow it (the
# player's choice, "follow the traffic cars too"), so that hook was removed: ring 30 -> 55
# (outside the 50 fade end, so they spawn invisible) and despawn 62.5 -> 70 (about the stock
# area, so the same density). Both constants have one reading function each (verified).
#
# The .data tail (0x026fc57c..0x026fd000, BSS, referenced by nothing) holds the racer list;
# `dataslack` raises .data's VirtualSize over it, as `slack` does for .text.
DATA_VSIZE_FIELD = 0x00400268                    # .data VirtualSize, PE section header #3
PATCHES["dataslack"] = [
    (DATA_VSIZE_FIELD, struct.pack("<I", 0x216C57C), struct.pack("<I", 0x216C600),
     ".data VirtualSize covers the racer list at 0x026fc5a0"),
]

'''
src = src[:start] + new + src[end:]
open(p, "w", encoding="utf-8").write(src)
print("replaced", end - start, "chars with", len(new))
