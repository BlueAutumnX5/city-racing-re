r"""crsetup.py - get the City Racing RE tools working on a new PC (setup.bat runs it; safe to re-run).

    crsetup.py          check paths, make the pristine backup, unpack the archives, paint the HUD faces,
                        check crdrive.dll / New audio, check write access to the game folder
    crsetup.py data     put this project's archive edits into the LIVE game (game closed): the Map Editor
                        route edits (mods/GlobalRoute.patch.json) and the Milky Way texture (skyprep.py install)

The game itself is never part of the repo. Everything here is rebuilt from the copy installed on this PC,
checked against docs/MANIFEST-sha256_2026-09-20.txt (the untouched 2026-09-20 install).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crpaths  # noqa: E402
import crpak    # noqa: E402

MANIFEST = os.path.join(HERE, "docs", "MANIFEST-sha256_2026-09-20.txt")
# what the tools rebuild from; the rest of the install (saves, Game.ini, uninstaller) may differ freely
REQUIRED = ["game.exe"] + [f"Data\\{a}.{x}" for a in crpak.ARCHIVES for x in ("hdr", "pak")]
MUTABLE_PREFIXES = ("Save\\", "Game.ini", "unins000.dat")
NOADS_RAW = 0x16920C
BASELINE_SHA = "8ceeb06a2c629d8eb379c18ddc5b70890e858063f7fdba2076f54ccaa21216c2"
ROUTE_PATCH =os.path.join(HERE, "mods", "GlobalRoute.patch.json")
# the first laptop's live archives after `crsetup.py data` (2026-11-04): a second PC must land on the same bytes
DATA_EXPECTED = {
    "Textures.hdr": "ab5ece25135a37c0d83311f6c5e48c6ee3077399f352f070be7ffd80222cb640",
    "Textures.pak": "68b99edca04b33af9f9a845872421c4dec450593d7499c11e53a9510c4602371",
    "World.hdr": "e41881ecb2d0e594e4a08042398baa3a6d95da5951dbbc81eda106544aed57b8",
    "World.pak": "1ecb56fb170c424963c82efb7a919fe3cdfbb85bc4e8a319091121ae4cb8f277",
}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest():
    out = {}
    for line in open(MANIFEST, encoding="utf-8"):
        parts = line.split(None, 2)
        if len(parts) == 3 and len(parts[0]) == 64 and parts[1].isdigit():
            out[parts[2].strip()] = parts[0].lower()
    return out


def local(rel):
    return rel.replace("\\", os.sep)


def check_against(root, names, man):
    """[(name, 'ok' | 'missing' | 'differs')]"""
    res = []
    for n in names:
        p = os.path.join(root, local(n))
        res.append((n, "missing" if not os.path.isfile(p) else "ok" if sha(p) == man[n] else "differs"))
    return res


def step_paths():
    print("== Paths")
    for key, val in (("game", crpaths.GAME_DIR), ("backups", crpaths.BACKUPS), ("music", crpaths.MUSIC)):
        print(f"  {key:8s} {val}   [{crpaths.SOURCE[key]}]")
    if os.path.isfile(crpaths.GAME_EXE):
        return True
    print("\n  City Racing was not found. Install it, or tell the tools where it is: make a file local.ini")
    print(f"  next to setup.bat (copy local.ini.example) with\n      [paths]\n      game = D:\\Games\\City Racing")
    return False


def step_pristine(man):
    """The tools rebuild every mod from the untouched files in <backups>\\2026-09-20_original-native."""
    print("== Pristine backup (what every mod is rebuilt from)")
    os.makedirs(crpaths.BACKUPS, exist_ok=True)
    if os.path.isfile(crpaths.STOCK_EXE):
        bad = [(n, s) for n, s in check_against(crpaths.STOCK_DIR, REQUIRED, man) if s != "ok"]
        if not bad:
            print(f"  OK - {crpaths.STOCK_DIR} matches the manifest")
            return True
        print(f"  WARNING - {crpaths.STOCK_DIR} does not match the manifest:")
        for n, s in bad:
            print(f"     {s:8s} {n}")
        return False
    live = check_against(crpaths.GAME_DIR, REQUIRED, man)
    bad = [(n, s) for n, s in live if s != "ok"]
    if bad:
        print("  The installed game is not the untouched 2026-09-20 version, so it cannot be the backup:")
        for n, s in bad:
            print(f"     {s:8s} {n}")
        print("  Fix: copy the folder '2026-09-20_original-native' from the first laptop's backups to")
        print(f"       {crpaths.STOCK_DIR}")
        print("       (or point 'backups =' in local.ini at a folder that has it), then run setup.bat again.")
        return False
    copied = 0
    for n, want in man.items():
        src = os.path.join(crpaths.GAME_DIR, local(n))
        if not os.path.isfile(src) or sha(src) != want:
            if not n.startswith(MUTABLE_PREFIXES):
                print(f"     skipped {n} (missing or changed)")
            continue
        dst = os.path.join(crpaths.STOCK_DIR, local(n))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    ok = all(s == "ok" for _, s in check_against(crpaths.STOCK_DIR, REQUIRED, man))
    print(f"  {'OK' if ok else 'FAILED'} - copied {copied} untouched files to {crpaths.STOCK_DIR}")
    return ok


def step_racemod_baseline():
    """racemod rebuilds game.exe from <backups>\\game.exe.racemod-original. On the first laptop that file is the
    pristine exe with ONE byte blanked (raw 0x16920c, the 'h' of http://www.gametop.com/stats/cityracing.html,
    so the game cannot phone home on exit - see exepatch.py noads). Made the same way here, so Apply gives the
    very same game.exe as on the first laptop."""
    print("== racemod baseline (pristine game.exe + the no-phone-home byte)")
    if os.path.isfile(crpaths.RACEMOD_BACKUP):
        same = sha(crpaths.RACEMOD_BACKUP) == BASELINE_SHA
        print(f"  {'OK' if same else 'present, but not the first laptop baseline (kept as it is)'}")
        return True
    buf = bytearray(open(crpaths.STOCK_EXE, "rb").read())
    if buf[NOADS_RAW:NOADS_RAW + 4] != b"http":
        print("  the pristine game.exe does not hold the URL where expected - not made")
        return False
    buf[NOADS_RAW] = 0
    if hashlib.sha256(buf).hexdigest() != BASELINE_SHA:
        print("  result differs from the first laptop's baseline - not made")
        return False
    with open(crpaths.RACEMOD_BACKUP, "wb") as f:
        f.write(buf)
    print(f"  OK - {crpaths.RACEMOD_BACKUP}")
    return True


def step_write_access():
    print("== Write access to the game folder (the tools rebuild game.exe in place)")
    probe = os.path.join(crpaths.GAME_DIR, ".cr_write_test")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        print("  OK")
        return True
    except OSError:
        pass
    print(f"  No write access to {crpaths.GAME_DIR}.")
    if sys.platform != "win32":
        return False
    ans = input("  Give your Windows account Modify rights on that folder now (one admin prompt)? [y/N] ")
    if ans.strip().lower() != "y":
        print("  Skipped. Without it, Apply in the control panel fails with 'access denied'.")
        return False
    import ctypes
    user = os.environ.get("USERNAME", "")
    args = f'"{crpaths.GAME_DIR}" /grant "{user}":(OI)(CI)M /T /Q'
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "icacls.exe", args, None, 0)
    if rc <= 32:
        print("  The admin prompt was refused or failed.")
        return False
    import time
    for _ in range(30):
        time.sleep(1)
        try:
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            print("  OK - Modify rights granted")
            return True
        except OSError:
            continue
    print("  Still no write access after 30 s.")
    return False


def step_unpack():
    """extracted\\<archive>\\files\\... from the PRISTINE archives (dial_faces, newaudio, many probes read it)."""
    print("== Unpacked archives (extracted\\)")
    for arc in crpak.ARCHIVES:
        out = os.path.join(HERE, "extracted", arc)
        if os.path.isfile(os.path.join(out, "_index.json")):
            print(f"  {arc:9s} already there")
            continue
        entries, _, payloads, _ = crpak.load_archive(crpaths.STOCK_DATA, arc)
        names = []
        for (name, _, _), payload in zip(entries, payloads):
            dst = os.path.join(out, "files", name.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(payload)
            names.append(name)
        with open(os.path.join(out, "_index.json"), "w", encoding="utf-8") as f:
            json.dump({"archive": arc, "names": names}, f, indent=1)
        print(f"  {arc:9s} {len(names)} files")
    return True


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], cwd=HERE)
    return r.returncode == 0


def step_generated():
    print("== Generated files")
    ok = True
    faces = [os.path.join(HERE, "HUD faces", f"Main_{m:02d}.dds") for m in range(1, 9)]
    if all(os.path.isfile(f) for f in faces):
        print("  HUD faces: already there")
    else:
        print("  HUD faces: painting (dial_faces.py) ...")
        ok &= run("dial_faces.py")
    na = os.path.join(HERE, "New audio", "Data", "Audio")
    if os.path.isdir(na):
        print("  New audio: there")
    elif os.path.isdir(crpaths.MUSIC):
        print("  New audio: building from the music folder (newaudio.py) ...")
        ok &= run("newaudio.py")
    else:
        print("  New audio: MISSING - untick 'newaudio' in the control panel, or put the 3 MP3s in")
        print(f"             {crpaths.MUSIC} and run setup.bat again")
    import racemod
    if os.path.isfile(racemod.DT_DLL_SRC):
        print(f"  crdrive.dll: {os.path.relpath(racemod.DT_DLL_SRC, HERE)} ({sha(racemod.DT_DLL_SRC)[:8]})")
    else:
        print("  crdrive.dll: MISSING - run build.bat (needs Rust), or untick 'drivetrain'")
        ok = False
    return ok


def cmd_data():
    """Bring the LIVE archives to this project's state: pristine + route edits + Milky Way."""
    import racemod
    if racemod.game_running():
        sys.exit("ABORT: game.exe is running - close City Racing first.")
    patch = json.load(open(ROUTE_PATCH, encoding="utf-8"))
    entries, _, payloads, _ = crpak.load_archive(crpaths.LIVE_DATA, patch["archive"])
    names = [n for n, _, _ in entries]
    i = names.index(patch["entry"])
    cur = payloads[i]
    if hashlib.sha256(cur).hexdigest() == patch["sha256_after"]:
        print("World.pak: the route edits are already in")
    elif hashlib.sha256(cur).hexdigest() != patch["sha256_before"]:
        sys.exit("World.pak: GlobalRoute.dat is neither stock nor this project's version - left alone "
                 "(Map Editor > Reset to factory first, if you want to replace it)")
    else:
        buf = bytearray(cur)
        for off, old, new in patch["runs"]:
            old, new = bytes.fromhex(old), bytes.fromhex(new)
            assert buf[off:off + len(old)] == old, f"route patch mismatch at {off}"
            buf[off:off + len(new)] = new
        assert hashlib.sha256(buf).hexdigest() == patch["sha256_after"]
        payloads = list(payloads)
        payloads[i] = bytes(buf)
        hdr, pak = crpak.build_archive(names, payloads)
        for ext, blob in (("hdr", hdr), ("pak", pak)):
            dst = os.path.join(crpaths.LIVE_DATA, f"World.{ext}")
            with open(dst + ".new", "wb") as f:
                f.write(blob)
            os.replace(dst + ".new", dst)
        print(f"World.pak: route edits written ({len(patch['runs'])} runs)")
    if not run("skyprep.py", "install"):
        sys.exit("skyprep.py install failed")
    allok = True
    for f, want in DATA_EXPECTED.items():
        same = sha(os.path.join(crpaths.LIVE_DATA, f)) == want
        allok &= same
        print(f"  {f:13s} {'= first laptop' if same else 'DIFFERS from the first laptop'}")
    print("DATA OK" if allok else "DATA DIFFERS (the game may still be fine - see above)")
    return 0 if allok else 1


def main():
    if sys.argv[1:2] == ["data"]:
        return cmd_data()
    if not step_paths():
        return 1
    man = manifest()
    results = {"pristine": step_pristine(man)}
    if results["pristine"]:
        results["baseline"] = step_racemod_baseline()
        results["unpack"] = step_unpack()
        results["generated"] = step_generated()
    results["write access"] = step_write_access()
    print("\n== Summary")
    for k, v in results.items():
        print(f"  {k:13s} {'OK' if v else 'NEEDS ATTENTION'}")
    if all(results.values()):
        print("\nReady. Next: 'Install Data Mods.bat' once (route edits + Milky Way), then 'RE Control Panel.bat' > Apply.")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
