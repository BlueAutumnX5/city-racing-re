"""Preview of the milkyway layer from the camera: same rotation (racemod._mw_rotation) and texture mapping as
the cave, additive over a stand-in dark night-sky gradient. Writes assets_src/sky_preview_<view>.png."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import racemod
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tex = Image.open(os.path.join(HERE, "assets_src", "MilkyWay.jpg")).convert("RGB")
TW, TH = tex.size
px = tex.load()
gx, gy, gz = racemod._mw_rotation()


def render(name, yaw_deg, pitch_deg, hfov_deg=113.0, w=1200, h=600, gain=1.0):
    im = Image.new("RGB", (w, h))
    out = im.load()
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    f = (w / 2) / math.tan(math.radians(hfov_deg) / 2)
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    for j in range(h):
        for i in range(w):
            x, y, z = (i - w / 2) / f, (h / 2 - j) / f, 1.0                 # camera space, LH, y up
            y, z = y * cp + z * sp, -y * sp + z * cp                        # pitch up
            x, z = x * cy + z * sy, -x * sy + z * cy                        # yaw
            n = math.sqrt(x * x + y * y + z * z)
            x, y, z = x / n, y / n, z / n
            if y < -0.02:                                                   # below the horizon: ground
                out[i, j] = (8, 9, 8)
                continue
            a = x * gx[0] + y * gx[1] + z * gx[2]                           # galactic coords
            b = x * gy[0] + y * gy[1] + z * gy[2]
            c = x * gz[0] + y * gz[1] + z * gz[2]
            l, bb = math.atan2(b, a), math.asin(max(-1, min(1, c)))
            u, v = 0.5 - l / (2 * math.pi), 0.5 - bb / math.pi
            r, g, bl = px[min(TW - 1, int(u * TW)) % TW, min(TH - 1, int(v * TH))]
            base = (6 + 10 * (1 - y), 8 + 12 * (1 - y), 18 + 22 * (1 - y))   # stand-in night gradient
            out[i, j] = tuple(min(255, int(base[k] + gain * (r, g, bl)[k])) for k in range(3))
    path = os.path.join(HERE, "assets_src", f"sky_preview_{name}.png")
    im.save(path)
    print(path)


render("toward_centre", 0, 22)
render("overhead", 0, 75, hfov_deg=120)
