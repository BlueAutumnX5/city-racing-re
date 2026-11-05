"""One-off edit (2026-10-04): the wanted meter's reach gets its own slider (player: "if it connected to
Sharper Police slider, I can never evade, LMAO"). New valued extra `evade` (police_evade_m)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import re


def edit(p, pairs):
    raw = open(p, "rb").read()
    crlf = b"\r\n" in raw
    t = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new in pairs:
        assert t.count(old) == 1, f"{p}: not found exactly once: {old[:90]!r}"
        t = t.replace(old, new)
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))
    print("edited", p, "crlf =", crlf)


W = crpaths.WORK
edit(W + r"\racemod.py", [
    ('''# The same slider also sets the WANTED METER's reach (play test 2026-10-04: "it will inactive and reduce
# the level if it was too far"): every frame''', '''# EVADE (own extra since 2026-10-04; first it shared the policeeyes slider and the player "can never
# evade" at 160). The WANTED METER's reach ("it will inactive and reduce the level if it was too far"):
# every frame'''),
    ('''        (0x0043F848, bytes.fromhex("d905c48e5600"), b"\\xd9\\x05" + struct.pack("<I", POLICE_SEE_CONST),
         f"wanted meter: holds while a chasing police car is within {POLICE_SEE:g} m (stock 60)"),
''', ''),
    ('''POLICE_SEE = POLICE_SEE_DEFAULT
POLICE_MAX = POLICE_MAX_DEFAULT
''', '''POLICE_SEE = POLICE_SEE_DEFAULT
POLICE_MAX = POLICE_MAX_DEFAULT
EVADE_DEFAULT = 80.0
EVADE_RANGE = (20.0, 160.0)
EVADE_CONST = S2_CODE + 0x58                     # float metres
EVADE = EVADE_DEFAULT


def set_evade(m):
    global EVADE
    lo, hi = EVADE_RANGE
    if not lo <= float(m) <= hi:
        raise ValueError(f"evade distance {m} m is outside {lo:g}..{hi:g}")
    EVADE = float(m)
    PATCHES["evade"] = [
        (0x0043F848, bytes.fromhex("d905c48e5600"), b"\\xd9\\x05" + struct.pack("<I", EVADE_CONST),
         f"wanted meter: holds while a chasing police car is within {EVADE:g} m (stock 60)"),
        (EVADE_CONST, bytes(4), struct.pack("<f", EVADE), f"{EVADE:g} m"),
    ]
'''),
    ('''    set_police_max(_saved("police_max", POLICE_MAX_DEFAULT))
''', '''    set_police_max(_saved("police_max", POLICE_MAX_DEFAULT))
    set_evade(_saved("police_evade_m", EVADE_DEFAULT))
'''),
    ('''"policeeyes", "morepolice", "wantedhits", "adaptive", "laa")''',
     '''"policeeyes", "evade", "morepolice", "wantedhits", "adaptive", "laa")'''),
    ('''"wantedhits": ["modsect"],
''', '''"wantedhits": ["modsect"], "evade": ["modsect"],
'''),
    ('''    "morepolice": ("police_max",''', '''    "evade": ("police_evade_m", lambda v: set_evade(v), lambda: EVADE, "m", EVADE_RANGE, EVADE_DEFAULT),
    "morepolice": ("police_max",'''),
])
edit(W + r"\crpanel.py", [
    ('''                   "below.\\n\\nThe same distance keeps your wanted level up: the original game lets it "
                   "drain whenever no chasing police car is within 60 m, so a chase from far away "
                   "used to fade out at once."),''', '''                   "below."),
    "evade": ("Evade distance", "How far you must get from chasing police before your wanted level drops.",
              "The original game lets your wanted level drain whenever no CHASING police car is within "
              "60 m of you. Set your own distance below: bigger = harder to escape.\\n\\n"
              "Tip: keep it below 'Police sight', or a chase can never be shaken off."),'''),
    ('''STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "morepolice",''',
     '''STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "evade", "morepolice",'''),
    ('''    "policeeyes": ("Police sight", 5, "%.0f"),
''', '''    "policeeyes": ("Police sight", 5, "%.0f"),
    "evade": ("Evade distance", 5, "%.0f"),
'''),
    ('''                  "are wanted - and how close a chasing police car must stay to keep your wanted "
                  "level from dropping.\\n\\nOriginal game: 40 m to notice, 60 m to keep the level. Police "
                  "only exist up to about 160 m from you, so higher would do nothing.",''',
     '''                  "are wanted.\\n\\nOriginal game: 40 m. Police only exist up to about 160 m from you, "
                  "so higher would do nothing.",
    "evade": "Your wanted level starts dropping once every chasing police car is farther than this "
             "(in metres).\\n\\nOriginal game: 60 m. Default here: 80 m.",'''),
])
edit(W + r"\Race Chaos.bat", [
    ('''rem   "Race Chaos.bat" extras on morepolice 12    any count 1..20 at once
''', '''rem   "Race Chaos.bat" extras on morepolice 12    any count 1..20 at once
rem   "Race Chaos.bat" extras on evade        wanted level drops only beyond 80 m from chasers (stock 60)
rem   "Race Chaos.bat" extras on evade 100    any distance 20..160 m
'''),
])
