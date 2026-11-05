"""Tabulate the physical parameters of every vehicle in City Racing."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

# read stock data from the VERIFIED BACKUP, never from the live install
STOCK_DATA = crpaths.STOCK_DATA

FIELDS = [
    "Vehicle model", "Base Health", "Base Weight (kg)", "Base Engine Force",
    "Base Acceleration", "Base Steering", "Front Tyre Driving", "Rear  Tyre Driving",
    "Front Tyre Friction", "Rear  Tyre Friction", "Front Tyre Rolling",
    "Rear  Tyre Rolling", "Suspension Stiffness", "Suspension Damping",
    "Reflection Power", "Engine Sound ID",
]


def parse(text):
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k in FIELDS:
            out[k] = v
    return out


def vehicles():
    entries, _, payloads, _ = crpak.load_archive(STOCK_DATA, "Objects")
    for (name, size, off), payload in zip(entries, payloads):
        if name.startswith("Data/Vehicles/") and name.endswith(".obj"):
            yield name, crpak.xor80(payload).decode("latin-1")


if __name__ == "__main__":
    rows = []
    for name, text in vehicles():
        if "/Wheels/" in name:
            continue
        d = parse(text)
        if "Base Engine Force" not in d:
            continue
        rows.append((name, d))

    hdr = ["car", "model", "HP", "kg", "force", "accel", "steer", "FD/RD",
           "friction F/R", "roll F/R", "susp stf/damp", "refl", "snd"]
    print(f"{hdr[0]:<28} {hdr[1]:<12} {hdr[2]:>5} {hdr[3]:>5} {hdr[4]:>6} "
          f"{hdr[5]:>6} {hdr[6]:>6} {hdr[7]:>6} {hdr[8]:>13} {hdr[9]:>10} "
          f"{hdr[10]:>14} {hdr[11]:>5} {hdr[12]:>4}")
    print("-" * 132)
    for name, d in rows:
        short = name.replace("Data/Vehicles/", "").replace(".obj", "")
        print(f"{short:<28} {d.get('Vehicle model',''):<12} "
              f"{d.get('Base Health',''):>5} {d.get('Base Weight (kg)',''):>5} "
              f"{d.get('Base Engine Force',''):>6} {d.get('Base Acceleration',''):>6} "
              f"{d.get('Base Steering',''):>6} "
              f"{d.get('Front Tyre Driving','')+'/'+d.get('Rear  Tyre Driving',''):>6} "
              f"{d.get('Front Tyre Friction','')+' / '+d.get('Rear  Tyre Friction',''):>13} "
              f"{d.get('Front Tyre Rolling','')+'/'+d.get('Rear  Tyre Rolling',''):>10} "
              f"{d.get('Suspension Stiffness','')+' / '+d.get('Suspension Damping',''):>14} "
              f"{d.get('Reflection Power',''):>5} {d.get('Engine Sound ID',''):>4}")

    # any pricing / upgrade tunables anywhere in Objects.pak?
    print("\n=== searching all 284 .obj for price/upgrade/shop keywords ===")
    entries, _, payloads, _ = crpak.load_archive(STOCK_DATA, "Objects")
    pat = re.compile(r"(?i)\b(price|cost|money|cash|upgrade|tuning|level|shop|reward)\b")
    hits = 0
    for (name, _, _), payload in zip(entries, payloads):
        text = crpak.xor80(payload).decode("latin-1")
        for line in text.splitlines():
            if pat.search(line):
                print(f"  {name}: {line.strip()[:90]}")
                hits += 1
    if not hits:
        print("  none - prices/progression are not in the archives (likely in game.exe)")
