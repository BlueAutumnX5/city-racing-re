"""dial_faces.py - one speedometer face per car with an rpm scale (player 2026-11-01: "paint the speedometer hub
so it has engine RPMs printed in ... x1000 mark with a red zone / dial max that changes per car").

The stock face Data/Interface/HUD/SpeedBar/Main.dds (256x256, dark glass ~50 % alpha) has a fixed green /
yellow / red inner arc (centre 128,127.5, radius ~40-48, 270 deg from bottom-left over the top) that the small
needle sweeps - the drivetrain's tachometer. Here that arc is erased back to glass and repainted per car: a cream
arc with a red zone from the redline to the dial max, a tick per 1000 rpm, the numbers 0..dial/1000 inside the
arc, and "x1000 RPM" in the gap at the bottom. Output: "HUD faces/face_0X.png" + a preview sheet.

    dial_faces.py            faces (PNG + game DDS Main_0X.dds) + "HUD faces/preview.png"
"""
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddsmip  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "extracted", "Textures", "files", "Data", "Interface", "HUD", "SpeedBar", "Main.dds")
OUT = os.path.join(HERE, "HUD faces")
# model: name, redline, dial max (rpm) - the same numbers as engine_curves.py (player 2026-11-01: Alpha
# 10000/11000; dial max Rover 6500, Cosmo 8500, Thunder 5500, Uber 9500)
CARS = {1: ("Galant S500", 5000, 6000), 2: ("Clio NSX", 7000, 8000), 3: ("Rover H1200", 5500, 6500),
        4: ("Cosmo R200", 7500, 8500), 5: ("Thunder-1960", 4800, 5500), 6: ("Accord Z8", 8000, 9000),
        7: ("Alpha GRX8", 10000, 11000), 8: ("Uber Atom-2000", 8500, 9500)}
CX, CY = 128.0, 127.5
START, SWEEP = 135.0, 270.0           # degrees, screen angles (y down): bottom-left, clockwise over the top
ERASE = (34.0, 53.0)                  # the old arc + its glow
ARC = (41.0, 47.0)                    # new arc band
GLOW = (39.0, 49.0)
CREAM = (232, 226, 196)                # numbers and the "x1000 RPM" label
OLIVE = (156, 156, 98)                 # the arc and its ticks: the dial's outer ring colour (player 2026-11-01)
RED = (215, 35, 28)
NUM_R = 29.5
NUM_MAX_R = 37.0                       # numbers stay inside the arc's glow (39)
NUM_SIZES = range(13, 8, -1)           # the largest size that fits each car's scale (player: "bigger numbers")
FONT = r"C:\Windows\Fonts\arialbd.ttf"
S = 4                                  # marks are drawn at 4x, then shrunk (smooth edges)
# km/h scale (measured on Main.dds): 0 at 134.8 deg, 1.5 deg per km/h (the 20s' ticks every 30 deg), 180 at 404.8.
# Its small dashes (radius 96-100, every 5 deg = 3.33 km/h) never met 5 / 10 / 15: replaced by a tick every
# 5 km/h, longer at the 10s (player 2026-11-01), in a brighter version of the dash colour (124,124,16).
KMH_START, KMH_DEG = 134.8, 1.5
DASH_RING = (94.5, 101.5)
DASH_BACK = (0, 0, 0, 184)
KMH_TICK = (196, 196, 60)


def glass(x, y):
    return (0, 0, 0, 136 if (x + y) % 2 == 0 else 119)


def angle(frac):
    return math.radians(START + SWEEP * frac)


def polar(r, a):
    return CX * S + r * S * math.cos(a), CY * S + r * S * math.sin(a)


def number_font(d, dial):
    """the biggest bold font whose numbers 0..dial/1000 neither touch each other nor leave the arc"""
    for size in NUM_SIZES:
        font = ImageFont.truetype(FONT, size * S)
        boxes = [d.textbbox(polar(NUM_R, angle(v * 1000 / dial)), str(v), font=font, anchor="mm",
                            stroke_width=int(0.6 * S)) for v in range(dial // 1000 + 1)]
        apart = all(a[2] + S <= b[0] or b[2] + S <= a[0] or a[3] + S <= b[1] or b[3] + S <= a[1]
                    for a, b in zip(boxes, boxes[1:]))
        inside = all(math.hypot(x - CX * S, y - CY * S) <= NUM_MAX_R * S
                     for b in boxes for x in (b[0], b[2]) for y in (b[1], b[3]))
        if apart and inside:
            return font, size
    return ImageFont.truetype(FONT, NUM_SIZES[-1] * S), NUM_SIZES[-1]


def face(redline, dial):
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    big = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for y in range(256):
        for x in range(256):
            r = math.hypot(x + 0.5 - CX, y + 0.5 - CY)
            if ERASE[0] <= r <= ERASE[1]:
                px[x, y] = glass(x, y)
            elif DASH_RING[0] <= r <= DASH_RING[1]:
                # the old 3.33 km/h dashes (and their dark edges) go; the 20s' cream ticks stay
                a = (math.degrees(math.atan2(y + 0.5 - CY, x + 0.5 - CX)) - KMH_START) % 360
                if a <= 276 and min(a % 30, 30 - a % 30) > 4.0:
                    px[x, y] = DASH_BACK
    red_from = redline / dial

    def band(r0, r1, a0, a1, col):
        steps = max(8, int((a1 - a0) * 120))
        outer = [polar(r1, angle(a0 + (a1 - a0) * k / steps)) for k in range(steps + 1)]
        inner = [polar(r0, angle(a0 + (a1 - a0) * k / steps)) for k in range(steps, -1, -1)]
        d.polygon(outer + inner, fill=col)

    def tick(rpm, r1, width):
        a = angle(rpm / dial)
        col = (RED if rpm >= redline else OLIVE) + (255,)
        d.line([polar(47, a), polar(r1, a)], fill=(0, 0, 0, 220), width=int((width + 1.0) * S))
        d.line([polar(47, a), polar(r1, a)], fill=col, width=int(width * S))

    for v in range(5, 180, 5):                    # km/h: a tick every 5, longer at 10s (20s have their own)
        if v % 20:
            a = math.radians(KMH_START + KMH_DEG * v)
            r0, r1, w = (93.0, 102.5, 1.9) if v % 10 == 0 else (95.5, 100.5, 1.5)
            d.line([polar(r0, a), polar(r1, a)], fill=(0, 0, 0, 220), width=int((w + 1.0) * S))
            d.line([polar(r0, a), polar(r1, a)], fill=KMH_TICK + (255,), width=int(w * S))
    band(GLOW[0], GLOW[1], -0.012, 1.012, (0, 0, 0, 200))
    band(ARC[0], ARC[1], 0.0, red_from, OLIVE + (255,))
    band(ARC[0], ARC[1], red_from, 1.0, RED + (255,))
    for rpm in range(0, dial + 1, 500):          # every 500 rpm: thousands long, halves clearly visible
        tick(rpm, 54.0 if rpm % 1000 == 0 else 52.0, 2.2 if rpm % 1000 == 0 else 1.6)
    font, _ = number_font(d, dial)
    for v in range(dial // 1000 + 1):
        col = (RED if v * 1000 >= redline else CREAM) + (255,)
        d.text(polar(NUM_R, angle(v * 1000 / dial)), str(v), font=font, fill=col, anchor="mm",
               stroke_width=int(0.6 * S), stroke_fill=(0, 0, 0, 230))
    # below the 0 and the last number, between the two arc ends
    d.text((CX * S, (CY + 33) * S), "x1000 RPM", font=ImageFont.truetype(FONT, 7 * S), fill=CREAM + (255,),
           anchor="mm", stroke_width=int(0.5 * S), stroke_fill=(0, 0, 0, 230))
    im.alpha_composite(big.resize((256, 256), Image.LANCZOS))
    im.alpha_composite(kmh_label())
    return im


KMH_ORANGE = (248, 152, 88)            # the dial's own km/h numbers (sampled from "180")
KMH_Y = 180.5                          # the 0 / 180 labels' row (y 176..185), between them, above the speed box
KMH_SQUEEZE = 0.88                     # the dial's digits are a narrow bold face


def kmh_label():
    """'Km/h' between the 0 and 180 of the km/h scale (player 2026-11-01), in their colour and size"""
    font = ImageFont.truetype(FONT, 14 * S)                # Arial Bold 14: capitals 10 px like "180"
    layer = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((CX * S, KMH_Y * S), "Km/h", font=font, fill=KMH_ORANGE + (255,), anchor="mm",
           stroke_width=int(0.7 * S), stroke_fill=(20, 10, 0, 220))
    box = layer.getbbox()
    glyphs = layer.crop(box)
    glyphs = glyphs.resize((int(glyphs.width * KMH_SQUEEZE), glyphs.height), Image.LANCZOS)
    out = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    out.alpha_composite(glyphs, (int(CX * S - glyphs.width / 2), box[1]))
    return out.resize((256, 256), Image.LANCZOS)


def dds_name(m):
    """the face's game file name (racemod `rpmdial` copies it to Data/Interface/HUD/SpeedBar/)"""
    return f"Main_{m:02d}.dds"


def main():
    os.makedirs(OUT, exist_ok=True)
    original = open(SRC, "rb").read()
    faces = {}
    for m, (name, red, dial) in CARS.items():
        faces[m] = face(red, dial)
        faces[m].save(os.path.join(OUT, f"face_{m:02d}.png"))
        # the game texture: same format as Main.dds (DXT3, 256x256, one level), loaded as a loose file
        dds = ddsmip.build(faces[m], like=original)
        open(os.path.join(OUT, dds_name(m)), "wb").write(dds)
        back = ddsmip.levels(dds)[0]
        err = max(abs(a - b) for pa, pb in zip(back.getdata(), faces[m].getdata()) for a, b in zip(pa, pb))
        assert ddsmip.info(dds)["fmt"] == ddsmip.info(original)["fmt"] and back.size == (256, 256), m
        print(f"{dds_name(m)}: {len(dds):,} bytes, DXT round-trip max error {err}")
    # preview: each face over a road-grey backdrop, at 2x, with its name
    cell = 512
    sheet = Image.new("RGB", (cell * 4, (cell + 40) * 2), (24, 24, 24))
    dd = ImageDraw.Draw(sheet)
    label = ImageFont.truetype(FONT, 22)
    for k, (m, im) in enumerate(faces.items()):
        bg = Image.new("RGBA", (256, 256), (88, 86, 82, 255))
        bg.alpha_composite(im)
        x, y = (k % 4) * cell, (k // 4) * (cell + 40)
        sheet.paste(bg.resize((cell, cell), Image.LANCZOS).convert("RGB"), (x, y + 40))
        name, red, dial = CARS[m]
        dd.text((x + 12, y + 8), f"{name}: redline {red}, dial {dial}", font=label, fill=(235, 235, 235))
    sheet.save(os.path.join(OUT, "preview.png"))
    print("written", OUT)


if __name__ == "__main__":
    sys.exit(main())
