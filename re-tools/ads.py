import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, glob, shutil, subprocess
SRC = crpaths.work(r"extracted\Textures\files\Data")
OUT = crpaths.work(r"ads")
FF = r"C:\Program Files\Metadata++\ffmpeg.exe"
os.makedirs(OUT, exist_ok=True)
files = glob.glob(SRC + r"\Interface\InfoScreen\**\*.*", recursive=True) + glob.glob(SRC + r"\Static\InfoScreen\**\*.*", recursive=True)
for f in sorted(files):
    raw = open(f, "rb").read()
    dec = bytes(b ^ 0x80 for b in raw) if raw[:2] not in (b"\xff\xd8", b"DD") else raw
    kind = "jpg" if dec[:2] == b"\xff\xd8" else ("dds" if dec[:4] == b"DDS " else "???")
    rel = os.path.relpath(f, SRC).replace("\\", "_")
    dst = os.path.join(OUT, os.path.splitext(rel)[0] + "." + kind)
    open(dst, "wb").write(dec)
    if kind == "dds":
        png = os.path.splitext(dst)[0] + ".png"
        r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", dst, png], capture_output=True, text=True)
        print(f"{rel:<55} {kind} {len(dec):7d} B  -> png {'OK' if r.returncode == 0 else 'FAIL ' + r.stderr[:80]}")
    else:
        print(f"{rel:<55} {kind} {len(dec):7d} B")
