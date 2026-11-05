"""One-off edit (2026-10-04): panel + bat text for wantedhits and the policeeyes wanted-meter reach."""
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
edit(W + r"\crpanel.py", [
    ('''                   "of you (and you are wanted). With this they spot you from the distance set "
                   "below."),''', '''                   "of you (and you are wanted). With this they spot you from the distance set "
                   "below.\\n\\nThe same distance keeps your wanted level up: the original game lets it "
                   "drain whenever no chasing police car is within 60 m, so a chase from far away "
                   "used to fade out at once."),
    "wantedhits": ("Harsher wanted level", "Hitting people or police raises your wanted level more.",
                   "The wanted bar has 10 bars.\\n\\nHitting a pedestrian: +4 bars (original +2).\\n"
                   "Hitting a police car: at least 5 bars (original at least 3). Like the original, "
                   "this is a minimum, not an addition - otherwise one long scrape along a police car "
                   "would fill the bar instantly. Every crash also adds a little by itself, as before."),'''),
    ('''STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "morepolice", "adaptive", "laa")''',
     '''STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "morepolice", "wantedhits", "adaptive", "laa")'''),
    ('''                  "are wanted.\\n\\nOriginal game: 40 m. Police only exist up to about 160 m from you, "
                  "so higher would do nothing.",''', '''                  "are wanted - and how close a chasing police car must stay to keep your wanted "
                  "level from dropping.\\n\\nOriginal game: 40 m to notice, 60 m to keep the level. Police "
                  "only exist up to about 160 m from you, so higher would do nothing.",'''),
])
edit(W + r"\Race Chaos.bat", [
    ('''rem   "Race Chaos.bat" extras on morepolice 12    any count 1..20 at once
''', '''rem   "Race Chaos.bat" extras on morepolice 12    any count 1..20 at once
rem   "Race Chaos.bat" extras on wantedhits   hitting a pedestrian +4 wanted bars (stock 2),
rem                   hitting a police car at least 5 bars (stock 3)
'''),
])
