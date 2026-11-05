r"""City Racing structure-aware corrupter, with intensity levels.

Blind byte-smashing just crashes the loader, which is boring. This corrupts each payload
type in a way that keeps the file *loadable* but wrong - the difference between a game that
won't start and a game that runs while melting.

Four independent channels:

  tex    Textures.pak  - scramble DDS/JPEG pixel data, preserving headers so they still decode
  mesh   World.pak     - jitter .msh vertex floats, leaving counts/offsets alone
  cfg    Objects.pak   - randomise numeric values in the text configs, keeping field names
  place  Objects.pak   - scramble StaticObjects.obj world positions

Every build starts from the VERIFIED PRISTINE BACKUP, so levels never stack and `restore` is
an exact byte-for-byte revert. Corruption is seeded, so a given (level, seed) is reproducible
and re-rollable.

  corrupt.py levels
  corrupt.py preview --level 3 [--seed 1234] [--channels tex,mesh] [--keep-cars]
  corrupt.py apply   --level 3 [--seed 1234] [--channels tex,mesh] [--keep-cars]
  corrupt.py restore

--keep-cars re-applies the CURRENTLY INSTALLED vehicle handling stats after corrupting, so
tuning edits survive. Without it, corruption rebuilds from pristine and your car setup is lost.

Index and count fields (Engine Sound ID, Effect Textures Num, ...) are never corrupted:
randomising those reads off the end of an array and crashes the game rather than glitching it.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import random
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK_DATA = crpaths.STOCK_DATA
LIVE_DATA = crpaths.LIVE_DATA

ALL_CHANNELS = ("tex", "mesh", "cfg", "place")

# level -> per-channel (probability, magnitude)
LEVELS = {
    1: {"name": "mild",
        "tex": (0.005, 0), "mesh": (0.02, 0.05), "cfg": (0.10, 0.2), "place": (0.00, 0)},
    2: {"name": "medium",
        "tex": (0.02, 0), "mesh": (0.08, 0.15), "cfg": (0.25, 0.5), "place": (0.10, 2.0)},
    3: {"name": "heavy",
        "tex": (0.06, 0), "mesh": (0.20, 0.40), "cfg": (0.50, 1.5), "place": (0.30, 10.0)},
    4: {"name": "extreme",
        "tex": (0.15, 0), "mesh": (0.40, 1.00), "cfg": (0.80, 4.0), "place": (0.60, 40.0)},
    5: {"name": "apocalyptic",
        "tex": (0.35, 0), "mesh": (0.70, 3.00), "cfg": (1.00, 10.0), "place": (1.00, 150.0)},
}

DDS_HEADER = 128          # 'DDS ' + 124-byte header
JPEG_MIN_KEEP = 1024      # fallback if no SOS marker found
MSH_HEADER_KEEP = 256     # leave the chunk table alone


# ----------------------------------------------------------------- tex channel

def keep_len(name, data):
    """How many leading bytes must survive for the file to still decode."""
    low = name.lower()
    if low.endswith(".dds"):
        return min(DDS_HEADER, len(data))
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        # everything up to and including the Start-Of-Scan marker carries the
        # quantisation and Huffman tables - destroy those and the decoder bails
        k = data.find(b"\xff\xda")
        if k >= 0:
            return min(k + 14, len(data))
        return min(JPEG_MIN_KEEP, len(data))
    return min(64, len(data))


def corrupt_tex(name, data, rng, prob, _mag):
    """Scramble pixel data while keeping the file decodable.

    DDS is DXT block data - fixed-size blocks, no internal structure, so any byte may be
    changed and the decoder cannot fail.

    JPEG is entropy-coded and delimited by 0xFF MARKER bytes. Writing a random byte can
    invent a marker where none belongs or destroy a real one, and the decoder then bails
    out - which makes the texture fail to load and whatever object needed it report an
    error. So for JPEG we never touch a 0xFF, never touch the byte after one, and never
    write 0xFF. Markers survive, image data does not.
    """
    low = name.lower()
    is_jpeg = low.endswith(".jpg") or low.endswith(".jpeg")
    keep = keep_len(name, data)
    body = bytearray(data[keep:])
    if not body:
        return data, 0
    n = int(len(body) * prob)
    if n <= 0:
        return data, 0
    hits = 0
    for _ in range(n):
        i = rng.randrange(len(body))
        if is_jpeg:
            if body[i] == 0xFF:
                continue                       # leave markers alone
            if i > 0 and body[i - 1] == 0xFF:
                continue                       # leave the marker's payload byte alone
            body[i] = rng.randrange(0xFF)      # 0x00..0xFE - never create a marker
        else:
            body[i] = rng.randrange(256)
        hits += 1
    return data[:keep] + bytes(body), hits


# ---------------------------------------------------------------- mesh channel

def corrupt_mesh(_name, data, rng, prob, mag):
    """Jitter values that parse as plausible geometry floats.

    Counts and offsets are small integers, which reinterpret as denormals far below the
    0.001 threshold, so they are skipped automatically - that is what keeps the file
    structurally intact.
    """
    buf = bytearray(data)
    hits = 0
    for off in range(MSH_HEADER_KEEP, len(buf) - 4, 4):
        if rng.random() >= prob:
            continue
        try:
            v = struct.unpack_from("<f", buf, off)[0]
        except struct.error:
            continue
        if not (v == v) or v in (float("inf"), float("-inf")):
            continue
        a = abs(v)
        if a < 0.001 or a > 10000.0:
            continue
        nv = v * (1.0 + rng.uniform(-mag, mag))
        try:
            struct.pack_into("<f", buf, off, nv)
            hits += 1
        except (struct.error, OverflowError):
            pass
    return bytes(buf), hits


# ------------------------------------------------------- cfg and place channels

NUM_RE = re.compile(r"^-?\d+(?:\.\d*)?f?$")
FIELD_RE = re.compile(r"(?m)^([^:\r\n]+:[ \t]*)([^\r\n]*?)([ \t]*)(\r?)$")

# Fields that are INDICES or COUNTS, never magnitudes. Randomising these reads off the
# end of an array and hard-crashes the game instead of producing interesting glitches.
NEVER_CORRUPT = re.compile(r"(?i)\b(num|id|count|index|class|type|level|version)\b")


def field_name(label):
    return label.split(":", 1)[0].strip()


def fmt_like(original, value):
    """Reformat a scaled number to resemble the original's style."""
    suffix = "f" if original.endswith("f") else ""
    core = original[:-1] if suffix else original
    if "." in core:
        decimals = len(core.split(".", 1)[1])
        if core.endswith("."):
            return f"{value:.0f}." + suffix
        return f"{value:.{max(1, decimals)}f}" + suffix
    return f"{int(round(value))}" + suffix


def scale_token(tok, rng, mag):
    if not NUM_RE.match(tok):
        return tok, False
    try:
        core = tok[:-1] if tok.endswith("f") else tok
        v = float(core.rstrip("."))
    except ValueError:
        return tok, False
    nv = v * (1.0 + rng.uniform(-mag, mag)) if v != 0 else rng.uniform(-mag, mag)
    return fmt_like(tok, nv), True


def corrupt_cfg(_name, text, rng, prob, mag):
    hits = [0]

    def repl(m):
        label, value, trail, cr = m.group(1), m.group(2), m.group(3), m.group(4)
        if not value or "/" in value or "\\" in value:
            return m.group(0)               # never touch file paths
        if NEVER_CORRUPT.search(field_name(label)):
            return m.group(0)               # never touch indices or counts
        toks = value.split(",")
        if not all(NUM_RE.match(t.strip()) for t in toks):
            return m.group(0)               # not numeric - enum name, model name, etc.
        if rng.random() >= prob:
            return m.group(0)
        out = []
        for t in toks:
            s = t.strip()
            nt, ok = scale_token(s, rng, mag)
            if ok:
                hits[0] += 1
            out.append(nt)
        return label + ",".join(out) + trail + cr

    return FIELD_RE.sub(repl, text), hits[0]


# ------------------------------------------------- preserving vehicle handling

VEH_RE = re.compile(r"^Data/Vehicles/\d\d/(Main|Police)\.obj$")

CAR_FIELDS = [
    "Base Health", "Base Weight (kg)", "Base Engine Force", "Base Acceleration",
    "Base Steering", "Front Tyre Driving", "Rear  Tyre Driving",
    "Front Tyre Friction", "Rear  Tyre Friction", "Front Tyre Rolling",
    "Rear  Tyre Rolling", "Suspension Stiffness", "Suspension Damping",
]


def _fre(field):
    return re.compile(r"(?m)^(" + re.escape(field) + r":[ \t]*)(\S+)")


def car_get(text, field):
    m = _fre(field).search(text)
    return m.group(2) if m else None


def car_set(text, field, value):
    return _fre(field).sub(lambda m: m.group(1) + value, text, count=1)


def read_installed_cars():
    """Vehicle stats as currently installed, so corruption can leave handling intact."""
    entries, _, payloads, _ = crpak.load_archive(LIVE_DATA, "Objects")
    out = {}
    for (name, _, _), payload in zip(entries, payloads):
        if not VEH_RE.match(name):
            continue
        text = crpak.xor80(payload).decode("latin-1")
        out[name] = {f: car_get(text, f) for f in CAR_FIELDS}
    return out


COORD_RE = re.compile(r"(?m)^(Object (?:position|orientation):[ \t]*)([^\r\n]*?)([ \t]*)(\r?)$")


def corrupt_place(_name, text, rng, prob, mag):
    hits = [0]

    def repl(m):
        label, value, trail, cr = m.group(1), m.group(2), m.group(3), m.group(4)
        parts = value.split(",")
        if len(parts) != 3:
            return m.group(0)
        if rng.random() >= prob:
            return m.group(0)
        out = []
        for p in parts:
            s = p.strip()
            try:
                v = float(s)
            except ValueError:
                return m.group(0)
            # keep the original decimal precision so line lengths stay comparable
            dec = len(s.split(".", 1)[1]) if "." in s else 0
            out.append(f"{v + rng.uniform(-mag, mag):.{dec}f}")
        hits[0] += 1
        return label + ",".join(out) + trail + cr

    return COORD_RE.sub(repl, text), hits[0]


# ----------------------------------------------------------------------- build

def build(level, seed, channels, keep_cars=False):
    cfgspec = LEVELS[level]
    stats = {c: {"files": 0, "hits": 0} for c in ALL_CHANNELS}
    stats["kept"] = {"files": 0, "hits": 0}
    archives = {}
    installed_cars = read_installed_cars() if keep_cars else {}

    for arc in crpak.ARCHIVES:
        entries, stored, payloads, _ = crpak.load_archive(STOCK_DATA, arc)
        names = [n for n, _, _ in entries]
        out = []
        for name, payload in zip(names, payloads):
            low = name.lower()
            new = payload

            if arc == "Textures" and "tex" in channels:
                p, m = cfgspec["tex"]
                rng = random.Random(f"{seed}|tex|{name}")
                new, h = corrupt_tex(name, new, rng, p, m)
                if h:
                    stats["tex"]["files"] += 1
                    stats["tex"]["hits"] += h

            elif arc == "World" and "mesh" in channels and low.endswith(".msh"):
                p, m = cfgspec["mesh"]
                rng = random.Random(f"{seed}|mesh|{name}")
                new, h = corrupt_mesh(name, new, rng, p, m)
                if h:
                    stats["mesh"]["files"] += 1
                    stats["mesh"]["hits"] += h

            elif arc == "Objects" and low.endswith(".obj"):
                is_place = low.endswith("staticobjects.obj")
                text = crpak.xor80(new).decode("latin-1")
                total = 0
                if is_place and "place" in channels:
                    p, m = cfgspec["place"]
                    rng = random.Random(f"{seed}|place|{name}")
                    text, h = corrupt_place(name, text, rng, p, m)
                    if h:
                        stats["place"]["files"] += 1
                        stats["place"]["hits"] += h
                    total += h
                elif not is_place and "cfg" in channels:
                    p, m = cfgspec["cfg"]
                    rng = random.Random(f"{seed}|cfg|{name}")
                    text, h = corrupt_cfg(name, text, rng, p, m)
                    if h:
                        stats["cfg"]["files"] += 1
                        stats["cfg"]["hits"] += h
                    total += h
                # restore the installed handling stats on top of the corruption,
                # so visual/effect values stay scrambled but the car still drives
                if keep_cars and name in installed_cars:
                    restored = 0
                    for f, want in installed_cars[name].items():
                        if want is None:
                            continue
                        if car_get(text, f) != want:
                            text = car_set(text, f, want)
                            restored += 1
                    if restored:
                        stats["kept"]["files"] += 1
                        stats["kept"]["hits"] += restored
                        total += restored
                if total:
                    new = crpak.xor80(text.encode("latin-1"))

            out.append(new)

        hdr, pak = crpak.build_archive(names, out)
        archives[arc] = (hdr, pak, len(names))

    return archives, stats


def report(level, seed, channels, archives, stats):
    print(f"level {level} ({LEVELS[level]['name']})   seed {seed}   "
          f"channels: {','.join(sorted(channels))}\n")
    print(f"  {'channel':<8} {'prob':>7} {'magnitude':>10} {'files hit':>10} {'edits':>12}")
    print("  " + "-" * 52)
    for c in ALL_CHANNELS:
        p, m = LEVELS[level][c]
        on = c in channels
        print(f"  {c:<8} {p:>7.3f} {m:>10.2f} {stats[c]['files']:>10} "
              f"{stats[c]['hits']:>12,}" + ("" if on else "   (off)"))
    if stats.get("kept", {}).get("hits"):
        print(f"  {'kept':<8} {'':>7} {'':>10} {stats['kept']['files']:>10} "
              f"{stats['kept']['hits']:>12,}   (handling stats restored after corruption)")
    print()
    for arc, (hdr, pak, n) in archives.items():
        stock = os.path.getsize(os.path.join(STOCK_DATA, arc + ".pak"))
        delta = len(pak) - stock
        print(f"  {arc:<9} {n:>4} entries   pak {len(pak):>10,} "
              f"({delta:+,} vs stock)   hdr {len(hdr):,}")


def verify_written():
    print("\n--- verifying installed archives parse ---")
    ok = True
    for arc in crpak.ARCHIVES:
        entries, stored, payloads, blob = crpak.load_archive(LIVE_DATA, arc)
        last = entries[-1][1] + entries[-1][2]
        good = (stored == len(entries)) and (last == len(blob))
        ok &= good
        print(f"  {arc:<9} {len(entries):>4} entries, stored count {stored}, "
              f"pak {len(blob):,}  {'OK' if good else 'BROKEN'}")
    return ok


def write_archives(archives):
    for arc, (hdr, pak, _) in archives.items():
        for ext, blob in (("hdr", hdr), ("pak", pak)):
            dst = os.path.join(LIVE_DATA, f"{arc}.{ext}")
            tmp = dst + ".new"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dst)
    print(f"\nwrote 8 files into {LIVE_DATA}")


def cmd_restore():
    import shutil
    n = 0
    for arc in crpak.ARCHIVES:
        for ext in ("hdr", "pak"):
            src = os.path.join(STOCK_DATA, f"{arc}.{ext}")
            dst = os.path.join(LIVE_DATA, f"{arc}.{ext}")
            shutil.copy2(src, dst)
            same = (crpak.sha256(open(src, "rb").read())
                    == crpak.sha256(open(dst, "rb").read()))
            print(f"  restored {arc}.{ext:<4} byte-identical: {'YES' if same else 'NO'}")
            n += same
    print(f"\n{n}/8 files byte-identical to pristine")
    return 0 if n == 8 else 1


def game_running():
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe"],
                             capture_output=True, text=True).stdout
        return "game.exe" in out
    except Exception:
        return False


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "levels"

    def opt(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    if cmd == "levels":
        print(f"{'lvl':<4} {'name':<14} " + "  ".join(f"{c:>16}" for c in ALL_CHANNELS))
        for lv in sorted(LEVELS):
            row = "  ".join(f"{LEVELS[lv][c][0]:>7.3f}/{LEVELS[lv][c][1]:<8.2f}"
                            for c in ALL_CHANNELS)
            print(f"{lv:<4} {LEVELS[lv]['name']:<14} {row}")
        print("\n(probability / magnitude per channel)")
        sys.exit(0)

    if cmd == "restore":
        if game_running():
            print("ABORT: game.exe is running - exit it first.")
            sys.exit(1)
        sys.exit(cmd_restore())

    if cmd not in ("preview", "apply"):
        print(__doc__)
        sys.exit(0)

    level = int(opt("--level", "2"))
    seed = opt("--seed", "1")
    chans = set((opt("--channels") or ",".join(ALL_CHANNELS)).split(","))
    bad = chans - set(ALL_CHANNELS)
    if bad:
        print(f"unknown channel(s): {bad}; valid: {ALL_CHANNELS}")
        sys.exit(2)
    if level not in LEVELS:
        print(f"level must be one of {sorted(LEVELS)}")
        sys.exit(2)

    keep = "--keep-cars" in args
    archives, stats = build(level, seed, chans, keep_cars=keep)
    report(level, seed, chans, archives, stats)
    if keep:
        print("  --keep-cars: vehicle handling stats taken from the CURRENTLY INSTALLED "
              "archive, so your car edits survive the corruption.\n")

    if cmd == "preview":
        print("\n(preview only - nothing written)")
        sys.exit(0)

    if game_running():
        print("\nABORT: game.exe is running - exit it first.")
        sys.exit(1)
    write_archives(archives)
    sys.exit(0 if verify_written() else 1)
