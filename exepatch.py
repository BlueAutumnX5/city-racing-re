r"""City Racing game.exe patcher - widescreen aspect + no exit-to-browser.

Both patches touch the same file and every build starts from the pristine backup, so they
MUST be applied together in one pass or each would undo the other. Hence a single `apply`
that takes the full desired state rather than separate commands.

PATCH 1 - aspect (widescreen)
  game.exe holds exactly ONE 4:3 float, 1.3333334 (bytes ab aa aa 3f), at raw 0x00167ff0
  (RVA 0x001697f0, VA 0x005697f0, .rdata), referenced exactly once at raw 0x00033EDE:
      f3 0f 5c 05 84 8d 56 00    subss  xmm0, [0x00568d84]
      f3 0f 59 05 f0 97 56 00    mulss  xmm0, [0x005697f0]   <- the constant
  No 16:9 constant exists anywhere in the binary, and in play both the 3D world and the HUD
  stretch by ~1.333x at 16:9 - the signature of a projection built for 4:3 and squashed
  across a wider framebuffer.

PATCH 2 - noads (stop opening gametop.com on exit)
  raw 0x169204  "open\0"                                         <- ShellExecuteA verb
  raw 0x16920c  "http://www.gametop.com/stats/cityracing.html/"  <- the URL
  Writing 0x00 over the URL's first byte makes it an empty string; ShellExecuteA then fails
  harmlessly and opens nothing. One byte, fully reversible, no code touched.

Usage:
  exepatch.py show
  exepatch.py apply                        stock exe (both patches off)
  exepatch.py apply --aspect 16:9
  exepatch.py apply --aspect 16:9 --noads
  exepatch.py apply --noads
  exepatch.py restore                      copy pristine back, byte-identical
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import hashlib
import os
import shutil
import struct
import sys

STOCK_EXE = crpaths.STOCK_EXE
LIVE_EXE = crpaths.GAME_EXE

ASPECT_OFF = 0x00167FF0
ASPECT_STOCK = struct.pack("<f", 4.0 / 3.0)          # ab aa aa 3f

URL_OFF = 0x0016920C
URL_STOCK = b"http://www.gametop.com/stats/cityracing.html/\x00"


def sha256(b):
    return hashlib.sha256(b).hexdigest().upper()


def parse_aspect(s):
    """Accept 1.7777778, 16:9, or 1920x1080."""
    s = s.strip().lower()
    if s in ("stock", "4:3", "none"):
        return 4.0 / 3.0
    for sep in (":", "x", "/"):
        if sep in s:
            w, _, h = s.partition(sep)
            return float(w) / float(h)
    return float(s)


def find_bytes(data, pat):
    offs, i = [], 0
    while True:
        k = data.find(pat, i)
        if k < 0:
            break
        offs.append(k)
        i = k + 1
    return offs


def locked(path):
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True


def describe(path, label):
    if not os.path.exists(path):
        print(f"{label:<16} MISSING: {path}")
        return
    d = open(path, "rb").read()
    asp = struct.unpack_from("<f", d, ASPECT_OFF)[0]
    url = d[URL_OFF:URL_OFF + len(URL_STOCK)]
    url_on = url[0] == 0
    print(f"{label:<16} {len(d):>9} bytes  sha {sha256(d)[:16]}")
    print(f"{'':<16} aspect @0x{ASPECT_OFF:06x} = {asp!r}"
          f"   ({'stock 4:3' if abs(asp - 4/3) < 1e-6 else 'PATCHED'})")
    print(f"{'':<16} exit URL @0x{URL_OFF:06x} = "
          f"{'NEUTRALISED (empty string)' if url_on else repr(url[:46])}")
    print()


def cmd_show():
    describe(STOCK_EXE, "pristine backup")
    describe(LIVE_EXE, "live install")


def cmd_apply(aspect_str, noads):
    if locked(LIVE_EXE):
        print("ABORT: game.exe is locked - the game is still running. Exit it first.")
        return 1

    data = bytearray(open(STOCK_EXE, "rb").read())       # always from pristine
    changed = 0

    # --- patch 1: aspect ---
    hits = find_bytes(bytes(data), ASPECT_STOCK)
    if len(hits) != 1 or hits[0] != ASPECT_OFF:
        print(f"ABORT: 4:3 pattern check failed - found {len(hits)} at "
              f"{[hex(o) for o in hits]}, expected 1 at 0x{ASPECT_OFF:06x}")
        return 1
    if aspect_str is None:
        print(f"aspect : left at stock 4:3 ({4/3!r})")
    else:
        aspect = parse_aspect(aspect_str)
        nb = struct.pack("<f", aspect)
        print(f"aspect : 0x{ASPECT_OFF:06x}  {ASPECT_STOCK.hex(' ')} -> {nb.hex(' ')}"
              f"   ({4/3!r} -> {aspect!r})")
        data[ASPECT_OFF:ASPECT_OFF + 4] = nb
        changed += sum(1 for a, b in zip(ASPECT_STOCK, nb) if a != b)

    # --- patch 2: exit URL ---
    got = bytes(data[URL_OFF:URL_OFF + len(URL_STOCK)])
    if got != URL_STOCK:
        print(f"ABORT: URL check failed at 0x{URL_OFF:06x}\n  expected {URL_STOCK!r}\n"
              f"  found    {got!r}")
        return 1
    if noads:
        print(f"noads  : 0x{URL_OFF:06x}  {got[:45].decode()!r} -> empty string "
              f"(first byte 68 -> 00)")
        data[URL_OFF] = 0x00
        changed += 1
    else:
        print("noads  : left enabled (game will still open gametop.com on exit)")

    tmp = LIVE_EXE + ".new"
    with open(tmp, "wb") as f:
        f.write(bytes(data))
    os.replace(tmp, LIVE_EXE)
    print(f"\nwrote {LIVE_EXE}")

    # --- verify what landed ---
    live = open(LIVE_EXE, "rb").read()
    stock = open(STOCK_EXE, "rb").read()
    diffs = [i for i, (a, b) in enumerate(zip(live, stock)) if a != b]
    print(f"verify : size {len(live)} vs stock {len(stock)}  "
          f"{'IDENTICAL' if len(live) == len(stock) else 'SIZE CHANGED - BAD'}")
    print(f"         bytes differing from stock: {len(diffs)} (expected {changed})"
          f"  at {[hex(o) for o in diffs[:8]]}")
    ok = len(live) == len(stock) and len(diffs) == changed
    print(f"         {'OK' if ok else 'UNEXPECTED - consider restore'}")
    print()
    describe(LIVE_EXE, "live install")
    return 0 if ok else 1


def cmd_restore():
    if locked(LIVE_EXE):
        print("ABORT: game.exe is locked - the game is still running. Exit it first.")
        return 1
    shutil.copy2(STOCK_EXE, LIVE_EXE)
    same = sha256(open(LIVE_EXE, "rb").read()) == sha256(open(STOCK_EXE, "rb").read())
    print(f"restored from pristine backup; byte-identical: {'YES' if same else 'NO'}")
    return 0 if same else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "show":
        cmd_show()
    elif args[0] == "apply":
        aspect = None
        if "--aspect" in args:
            aspect = args[args.index("--aspect") + 1]
        sys.exit(cmd_apply(aspect, "--noads" in args))
    elif args[0] == "restore":
        sys.exit(cmd_restore())
    else:
        print(__doc__)
