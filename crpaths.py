r"""crpaths.py - every machine-specific path of the City Racing RE project, in one place.

The scripts used to hardcode the first laptop's layout (C:\Program Files (x86)\GameTop.com\City Racing RE,
D:\Projects Overflow\City Racing Work, D:\Projects Overflow\City Racing RE backups). They now ask this module.

Lookup order for each setting (first hit wins):
  1. environment variable            CR_GAME_DIR, CR_BACKUPS, CR_MUSIC, CR_PYTHON
  2. local.ini next to this file      [paths] game = ..., backups = ..., music = ...   (gitignored, per machine)
  3. auto-detect                      game: the Inno Setup uninstall entry in the registry, then the usual folder
  4. default                          see below

    python crpaths.py          print what was resolved (and where it came from)
"""
import configparser
import os
import sys

WORK = os.path.dirname(os.path.abspath(__file__))
RETOOLS = os.path.join(WORK, "re-tools")
LOCAL = os.path.join(WORK, "local")                      # per-machine data, gitignored
LOCAL_INI = os.path.join(WORK, "local.ini")

GAME_DIR_NAME = "City Racing RE"
DEFAULT_GAME_DIR = r"C:\Program Files (x86)\GameTop.com" + "\\" + GAME_DIR_NAME
STOCK_NAME = "2026-09-20_original-native"                # the untouched install, see docs/MANIFEST-sha256_2026-09-20.txt

_ini = configparser.ConfigParser()
_ini.read(LOCAL_INI, encoding="utf-8")
SOURCE = {}


def _setting(key, env, auto=None, default=None):
    v = os.environ.get(env)
    if v:
        SOURCE[key] = f"env {env}"
        return v
    v = _ini.get("paths", key, fallback="").strip()
    if v:
        SOURCE[key] = "local.ini"
        return os.path.expandvars(os.path.expanduser(v))
    v = auto() if auto else None
    if v:
        SOURCE[key] = "auto-detected"
        return v
    SOURCE[key] = "default"
    return default


def _find_game():
    """The game folder from the uninstall registry entries (GameTop installs with Inno Setup)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    hits = []
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                            name = winreg.QueryValueEx(sub, "DisplayName")[0]
                            loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                    except OSError:
                        continue
                    if "city racing" in str(name).lower() and loc \
                            and os.path.isfile(os.path.join(loc, "game.exe")):
                        hits.append(loc.rstrip("\\/"))
        except OSError:
            continue
    # prefer the renamed RE copy when several City Racing installs exist
    hits.sort(key=lambda p: os.path.basename(p) != GAME_DIR_NAME)
    if hits:
        return hits[0]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = os.path.join(base, "GameTop.com", GAME_DIR_NAME)
            if os.path.isfile(os.path.join(p, "game.exe")):
                return p
    return None


GAME_DIR = _setting("game", "CR_GAME_DIR", _find_game, DEFAULT_GAME_DIR)
GAME_EXE = os.path.join(GAME_DIR, "game.exe")
LIVE_DATA = os.path.join(GAME_DIR, "Data")
GAMETOP = os.path.dirname(GAME_DIR)

BACKUPS = _setting("backups", "CR_BACKUPS", None, os.path.join(LOCAL, "backups"))
STOCK_DIR = os.path.join(BACKUPS, STOCK_NAME)
STOCK_EXE = os.path.join(STOCK_DIR, "game.exe")
STOCK_DATA = os.path.join(STOCK_DIR, "Data")
RACEMOD_BACKUP = os.path.join(BACKUPS, "game.exe.racemod-original")

MUSIC = _setting("music", "CR_MUSIC", None, os.path.join(LOCAL, "music"))      # newaudio.py's MP3s
ASSETS_OUT = os.path.join(LOCAL, "City Racing Assets")                         # assets.py export default


def work(*parts):
    return os.path.join(WORK, *parts)


def game(*parts):
    return os.path.join(GAME_DIR, *parts)


def stock(*parts):
    return os.path.join(STOCK_DIR, *parts)


def backups(*parts):
    return os.path.join(BACKUPS, *parts)


if __name__ == "__main__":
    for key, val in (("game", GAME_DIR), ("backups", BACKUPS), ("music", MUSIC)):
        print(f"{key:8s} {val}   [{SOURCE[key]}]")
    print(f"{'work':8s} {WORK}")
    print(f"game.exe {'found' if os.path.isfile(GAME_EXE) else 'MISSING'}; "
          f"pristine copy {'found' if os.path.isfile(STOCK_EXE) else 'MISSING (run setup.bat)'}")
