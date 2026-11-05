"""Locate the GameTop URL strings and the ShellExecuteA import in each binary."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re
import struct

TARGETS = {
    "game.exe": crpaths.GAME_EXE,
    "game-shell.exe": crpaths.game(r"game-shell.exe"),
    "desktop.exe": crpaths.game(r"desktop.exe"),
}

for name, path in TARGETS.items():
    try:
        d = open(path, "rb").read()
    except OSError as e:
        print(f"=== {name}: {e}")
        continue
    print(f"=== {name}  ({len(d)} bytes) ===")

    # ASCII strings of interest
    for pat, label in ((rb"https?://[\x20-\x7E]{4,120}", "URL"),
                       (rb"[\x20-\x7E]*gametop[\x20-\x7E]*", "gametop"),
                       (rb"ShellExecute\w*", "import"),
                       (rb"[\x20-\x7E]*wrap-links[\x20-\x7E]*", "wrap-links"),
                       (rb"open\x00", "verb 'open'")):
        seen = set()
        for m in re.finditer(pat, d, re.IGNORECASE):
            s = m.group(0)
            key = (label, s)
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{label:<10}] raw 0x{m.start():06x}  {s[:110]!r}")
    # UTF-16 URLs too
    for m in re.finditer(rb"(?:h\x00t\x00t\x00p\x00)(?:[\x20-\x7E]\x00){4,120}", d):
        s = m.group(0).decode("utf-16-le", "replace")
        print(f"  [URL-utf16 ] raw 0x{m.start():06x}  {s[:110]!r}")
    print()
