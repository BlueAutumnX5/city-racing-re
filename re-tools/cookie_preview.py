"""Render the headlight cookie (headlights.cookie_pixels) as a PNG: true brightness + x8 with a grid.
Usage: cookie_preview.py out.png"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import headlights as h
from PIL import Image, ImageDraw

W, H = h.COOKIE_W, h.COOKIE_H
px = h.cookie_pixels()
sq = lambda v: round(255 * (v / 255.0) ** 2)            # stored sqrt -> true value
img = Image.new("RGB", (W, H))
img.putdata([(sq(px[o + 2]), sq(px[o + 1]), 0) for o in range(0, len(px), 4)])
S = max(1, 1024 // W)
true = img.resize((W * S, H * S), Image.BILINEAR)
boost = img.point(lambda v: min(255, v * 8)).resize((W * S, H * S), Image.BILINEAR)
d = ImageDraw.Draw(boost)
for el in (-30, -20, -10, -5, -2, 0, 5, 10, 20, 30):
    j = (0.5 - math.tan(math.radians(el)) * h.KT) * H * S
    if 0 <= j < H * S:
        d.line([(0, j), (W * S, j)], fill=(255, 255, 255) if el == 0 else (90, 90, 255))
        d.text((4, j + 2), f"{el:+d} deg", fill=(170, 170, 255))
for az in (-60, -45, -30, -15, 0, 15, 30, 45, 60):
    i = (0.5 + math.tan(math.radians(az)) * h.KS) * W * S
    if 0 <= i <= W * S:
        d.line([(i, 0), (i, H * S)], fill=(70, 70, 70))
        d.text((i + 3, H * S - 14), f"{az:+d}", fill=(170, 170, 170))
c = Image.new("RGB", (W * S, H * S * 2 + 30), (20, 20, 20))
c.paste(true, (0, 0)); c.paste(boost, (0, H * S + 30))
ImageDraw.Draw(c).text((6, H * S + 8), "above: true beam (R = left lamp, G = right lamp)   below: x8, grid in degrees", fill=(220, 220, 220))
c.save(sys.argv[1])
print("saved", sys.argv[1], c.size)
