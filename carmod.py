r"""City Racing vehicle tuner.

Always builds from the VERIFIED PRISTINE BACKUP and writes to the live install, so every
apply is idempotent and `apply stock` is an exact byte-for-byte restore.

  carmod.py list                          current live-install stats
  carmod.py presets                       show what each preset does
  carmod.py preview <preset> [--cars ...] show the diff, write nothing
  carmod.py apply   <preset> [--cars ...] build and install

  --cars 08          only car 08          --cars 01,08      several
  --cars all         every car (default)  --cars players    all Main.obj, no Police.obj

Preset tiers, anchored on the shipped police tune (2500/2.5/2.5/2.5) which is the
developers' own maximum and therefore known stable:

  stock    exact restore of the original archive
  police   every car gets the shipped police tune - proven safe, mild boost
  fast     quick but planted: full 6000 force, friction back at the police ceiling
  op       strong, grippy and rollover-happy: AWD, ~2.4x force, friction 4.0
  flip     maximum comedy: soft suspension + grip that never releases
  insane   deliberately absurd - expect flips, launches and physics breakdown

No preset raises "Base Health". Repair cost is priced per hit point lost, so inflating
max health inflates the repair bill without buying real durability. Learned the hard way.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK_DATA = crpaths.STOCK_DATA
LIVE_DATA = crpaths.LIVE_DATA

# field -> value. Suspension keeps the game's odd "25.f" style.
PRESETS = {
    "stock": {},
    "police": {
        "Base Engine Force": "2500",
        "Base Acceleration": "2.5",
        "Base Steering": "2.5",
        "Front Tyre Friction": "2.5",
        "Rear  Tyre Friction": "2.5",
    },
    # NOTE: no preset touches "Base Health". Repair cost is priced per hit point lost,
    # so inflating max health inflates the repair bill without buying real durability
    # (damage appears to scale with max health). Health stays at the stock 0100.
    "op": {
        "Base Weight (kg)": "900",
        "Base Engine Force": "6000",
        "Base Acceleration": "5.0",
        "Base Steering": "3.0",
        "Front Tyre Driving": "1",
        "Rear  Tyre Driving": "1",
        "Front Tyre Friction": "4.0",
        "Rear  Tyre Friction": "4.0",
        "Suspension Stiffness": "45.f",
        "Suspension Damping": "1.5",
    },
    # Fast but planted. Friction back to the shipped police ceiling so the tyres can
    # still break traction and SLIDE instead of tipping, steering calmed, and the
    # suspension made stiff + well damped to resist body roll. Keeps the full 6000.
    "fast": {
        "Base Weight (kg)": "1200",
        "Base Engine Force": "6000",
        "Base Acceleration": "5.0",
        "Base Steering": "2.0",
        "Front Tyre Driving": "1",
        "Rear  Tyre Driving": "1",
        "Front Tyre Friction": "2.5",
        "Rear  Tyre Friction": "2.5",
        "Suspension Stiffness": "60.f",
        "Suspension Damping": "2.0",
    },
    # Maximum comedy: grip that never releases, soft undamped suspension so the body
    # leans hard into the roll, light mass and hair-trigger steering.
    "flip": {
        "Base Weight (kg)": "600",
        "Base Engine Force": "8000",
        "Base Acceleration": "6.0",
        "Base Steering": "5.0",
        "Front Tyre Driving": "1",
        "Rear  Tyre Driving": "1",
        "Front Tyre Friction": "7.0",
        "Rear  Tyre Friction": "7.0",
        "Suspension Stiffness": "15.f",
        "Suspension Damping": "0.2",
    },
    "insane": {
        "Base Weight (kg)": "500",
        "Base Engine Force": "25000",
        "Base Acceleration": "12.0",
        "Base Steering": "6.0",
        "Front Tyre Driving": "1",
        "Rear  Tyre Driving": "1",
        "Front Tyre Friction": "8.0",
        "Rear  Tyre Friction": "8.0",
        "Front Tyre Rolling": "2.0",
        "Rear  Tyre Rolling": "2.0",
        "Suspension Stiffness": "80.f",
        "Suspension Damping": "3.0",
    },
}

TUNABLES = [
    "Base Health", "Base Weight (kg)", "Base Engine Force", "Base Acceleration",
    "Base Steering", "Front Tyre Driving", "Rear  Tyre Driving",
    "Front Tyre Friction", "Rear  Tyre Friction", "Front Tyre Rolling",
    "Rear  Tyre Rolling", "Suspension Stiffness", "Suspension Damping",
]

VEH = re.compile(r"^Data/Vehicles/(\d\d)/(Main|Police)\.obj$")


def field_re(field):
    """Match 'Field:<whitespace>value', capturing the prefix so column alignment survives."""
    return re.compile(r"(?m)^(" + re.escape(field) + r":[ \t]*)(\S+)")


def get_field(text, field):
    m = field_re(field).search(text)
    return m.group(2) if m else None


def get_line_field(text, field):
    """Whole rest of the line - for multi-word values like 'Uber Atom-2000'.

    The .obj files use CRLF, and in MULTILINE mode '$' matches only before '\\n',
    never before '\\r' - so the optional \\r here is required, not decorative.
    """
    m = re.search(r"(?m)^" + re.escape(field) + r":[ \t]*([^\r\n]*?)[ \t]*\r?$", text)
    return m.group(1) if m else None


def set_field(text, field, value):
    """Replace only the value, keeping the original whitespace run and line endings."""
    return field_re(field).sub(lambda m: m.group(1) + value, text, count=1)


def select(name, spec):
    m = VEH.match(name)
    if not m:
        return False
    num, kind = m.group(1), m.group(2)
    if spec == "all":
        return True
    if spec == "players":
        return kind == "Main"
    return num in {c.strip().zfill(2) for c in spec.split(",")}


def load_stock():
    entries, stored, payloads, _ = crpak.load_archive(STOCK_DATA, "Objects")
    return [n for n, _, _ in entries], payloads


def apply_preset(preset, cars):
    """Return (names, new_payloads, changes) built from the pristine backup."""
    names, payloads = load_stock()
    changes = []
    out = []
    for name, payload in zip(names, payloads):
        if not select(name, cars) or not PRESETS[preset]:
            out.append(payload)
            continue
        text = crpak.xor80(payload).decode("latin-1")
        model = get_line_field(text, "Vehicle model") or "?"
        diff = []
        for field, val in PRESETS[preset].items():
            old = get_field(text, field)
            if old is None:
                diff.append((field, "(absent)", val, False))
                continue
            if old != val:
                text = set_field(text, field, val)
                diff.append((field, old, val, True))
        if diff:
            changes.append((name, model, diff))
        out.append(crpak.xor80(text.encode("latin-1")))
    return names, out, changes


def cmd_list(data_dir=LIVE_DATA, label="live install"):
    entries, _, payloads, _ = crpak.load_archive(data_dir, "Objects")
    print(f"=== vehicle stats: {label} ===")
    print(f"{'car':<12} {'model':<22} " + " ".join(f"{f.split()[-1][:6]:>7}" for f in TUNABLES))
    for (name, _, _), payload in zip(entries, payloads):
        if not VEH.match(name):
            continue
        text = crpak.xor80(payload).decode("latin-1")
        short = name.replace("Data/Vehicles/", "").replace(".obj", "")
        vals = " ".join(f"{(get_field(text, f) or '-'):>7}" for f in TUNABLES)
        print(f"{short:<12} {(get_line_field(text,'Vehicle model') or '?'):<22} {vals}")


def show_changes(preset, cars, changes):
    if not changes:
        print(f"preset '{preset}' on cars '{cars}': no changes "
              f"({'exact restore of the original archive' if preset=='stock' else 'values already match'})")
        return
    print(f"preset '{preset}' on cars '{cars}' - {len(changes)} vehicles affected\n")
    for name, model, diff in changes:
        short = name.replace("Data/Vehicles/", "").replace(".obj", "")
        print(f"  {short}  ({model})")
        for field, old, new, ok in diff:
            flag = "" if ok else "   <-- FIELD NOT FOUND, skipped"
            print(f"      {field:<22} {old:>8}  ->  {new}{flag}")
        print()


def cmd_apply(preset, cars, write):
    names, payloads, changes = apply_preset(preset, cars)
    show_changes(preset, cars, changes)
    hdr, pak = crpak.build_archive(names, payloads)

    stock_pak = open(os.path.join(STOCK_DATA, "Objects.pak"), "rb").read()
    stock_hdr = open(os.path.join(STOCK_DATA, "Objects.hdr"), "rb").read()
    print(f"built Objects.pak {len(pak)} bytes (stock {len(stock_pak)}), "
          f"hdr {len(hdr)} bytes (stock {len(stock_hdr)})")

    if preset == "stock":
        ident = (crpak.sha256(pak) == crpak.sha256(stock_pak)
                 and crpak.sha256(hdr) == crpak.sha256(stock_hdr))
        print(f"byte-identical to original: {'YES' if ident else 'NO - ABORTING'}")
        if not ident:
            return 1

    if not write:
        print("\n(preview only - nothing written)")
        return 0

    for ext, blob in (("hdr", hdr), ("pak", pak)):
        dst = os.path.join(LIVE_DATA, "Objects." + ext)
        tmp = dst + ".new"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, dst)
        print(f"wrote {dst}")

    # verify what actually landed
    print("\n--- verifying installed archive ---")
    entries, stored, pl, blob = crpak.load_archive(LIVE_DATA, "Objects")
    assert stored == len(entries), f"count mismatch {stored} != {len(entries)}"
    print(f"index parses cleanly: {len(entries)} entries, stored count {stored}, "
          f"pak {len(blob)} bytes")
    bad = 0
    for (name, _, _), payload in zip(entries, pl):
        if not select(name, cars) or not PRESETS[preset]:
            continue
        text = crpak.xor80(payload).decode("latin-1")
        for field, val in PRESETS[preset].items():
            got = get_field(text, field)
            if got is not None and got != val:
                print(f"  MISMATCH {name} {field}: expected {val}, got {got}")
                bad += 1
    print("all tuned fields verified in the installed file" if not bad
          else f"{bad} mismatches")
    return 0 if not bad else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    cars = "all"
    if "--cars" in args:
        cars = args[args.index("--cars") + 1]

    if cmd == "list":
        cmd_list()
    elif cmd == "stock-list":
        cmd_list(STOCK_DATA, "pristine backup")
    elif cmd == "presets":
        for p, d in PRESETS.items():
            print(f"\n[{p}]")
            if not d:
                print("  (exact restore)")
            for k, v in d.items():
                print(f"  {k:<22} = {v}")
    elif cmd in ("preview", "apply"):
        preset = args[1]
        if preset not in PRESETS:
            print(f"unknown preset '{preset}' - choose from {list(PRESETS)}")
            sys.exit(2)
        sys.exit(cmd_apply(preset, cars, write=(cmd == "apply")))
    else:
        print(__doc__)
