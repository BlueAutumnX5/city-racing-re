r"""Offline post-mortem: what did level-2 corruption actually do to static objects?

Rebuilds the same corruption in memory (same seed) and diffs it against pristine, so we can
see which channel produced something a loader would reject - without running the game.
"""

import random
import re
import struct
import sys

import corrupt as C
import crpak

SEED = "1"
LEVEL = 2


def show_cfg_diffs(limit=6):
    print("=" * 78)
    print("CFG CHANNEL - static object configs, original vs corrupted")
    print("=" * 78)
    entries, _, payloads, _ = crpak.load_archive(C.STOCK_DATA, "Objects")
    p, m = C.LEVELS[LEVEL]["cfg"]
    shown = 0
    for (name, _, _), payload in zip(entries, payloads):
        if not name.startswith("Data/Static/") or not name.endswith(".obj"):
            continue
        text = crpak.xor80(payload).decode("latin-1")
        rng = random.Random(f"{SEED}|cfg|{name}")
        new, hits = C.corrupt_cfg(name, text, rng, p, m)
        if not hits:
            continue
        print(f"\n--- {name}   ({hits} value(s) changed)")
        for a, b in zip(text.splitlines(), new.splitlines()):
            if a != b:
                print(f"    -  {a.strip()}")
                print(f"    +  {b.strip()}")
        shown += 1
        if shown >= limit:
            break


def show_place_diffs(limit=4):
    print("\n" + "=" * 78)
    print("PLACE CHANNEL - StaticObjects.obj placement, original vs corrupted")
    print("=" * 78)
    entries, _, payloads, _ = crpak.load_archive(C.STOCK_DATA, "Objects")
    p, m = C.LEVELS[LEVEL]["place"]
    shown = 0
    for (name, _, _), payload in zip(entries, payloads):
        if not name.lower().endswith("staticobjects.obj"):
            continue
        text = crpak.xor80(payload).decode("latin-1")
        rng = random.Random(f"{SEED}|place|{name}")
        new, hits = C.corrupt_place(name, text, rng, p, m)
        if not hits:
            continue
        print(f"\n--- {name}   ({hits} placement(s) changed)")
        for a, b in zip(text.splitlines(), new.splitlines()):
            if a != b:
                print(f"    -  {a.strip()}")
                print(f"    +  {b.strip()}")
        shown += 1
        if shown >= limit:
            break


ASCII_RUN = re.compile(rb"[\x20-\x7E]{6,}")


def check_mesh_strings():
    print("\n" + "=" * 78)
    print("MESH CHANNEL - do .msh files contain ASCII strings, and did we hit them?")
    print("=" * 78)
    entries, _, payloads, _ = crpak.load_archive(C.STOCK_DATA, "World")
    p, mag = C.LEVELS[LEVEL]["mesh"]

    files_with_strings = 0
    files_hit_in_string = 0
    examples = []
    checked = 0

    for (name, _, _), payload in zip(entries, payloads):
        if not name.lower().endswith(".msh"):
            continue
        checked += 1
        runs = [(m.start(), m.end(), m.group(0)) for m in ASCII_RUN.finditer(payload)]
        if not runs:
            continue
        files_with_strings += 1

        # replay exactly which offsets the mesh corrupter would jitter
        rng = random.Random(f"{SEED}|mesh|{name}")
        hit_offsets = []
        for off in range(C.MSH_HEADER_KEEP, len(payload) - 4, 4):
            if rng.random() >= p:
                continue
            v = struct.unpack_from("<f", payload, off)[0]
            if v != v or v in (float("inf"), float("-inf")):
                continue
            a = abs(v)
            if a < 0.001 or a > 10000.0:
                continue
            hit_offsets.append(off)

        clobbered = []
        for s, e, txt in runs:
            for off in hit_offsets:
                if off < e and off + 4 > s:
                    clobbered.append((off, s, e, txt))
                    break
        if clobbered:
            files_hit_in_string += 1
            if len(examples) < 6:
                off, s, e, txt = clobbered[0]
                examples.append((name, off, txt[:60], len(clobbered)))

    print(f"\n  .msh files scanned              : {checked}")
    print(f"  files containing ASCII strings  : {files_with_strings}")
    print(f"  files where a jitter hit a string: {files_hit_in_string}")
    if examples:
        print("\n  examples of strings we corrupted:")
        for name, off, txt, n in examples:
            print(f"    {name}")
            print(f"       offset 0x{off:x}, {n} string(s) clobbered, e.g. {txt!r}")
    else:
        print("\n  no strings were hit - mesh channel is not corrupting text")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "cfg"):
        show_cfg_diffs()
    if what in ("all", "place"):
        show_place_diffs()
    if what in ("all", "mesh"):
        check_mesh_strings()
