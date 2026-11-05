"""One-off edit (2026-10-04): the player's play-test reports.
(1) "the police has a wanted level type thing, where it will inactive and reduce the level if it was too
far ... I just want it to follow the Sharper Police slider too" -> policeeyes also repoints the wanted
meter's 60 m "chaser nearby" search (0x0043f848).
(2) "it adds 2 wanted level when I crash onto pedestrian, and 3 into the police cars. Can you change it
to 4, and 5?" -> new extra `wantedhits`."""
import crpaths
p = crpaths.work(r"racemod.py")
raw = open(p, "rb").read()
crlf = b"\r\n" in raw
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(old, new):
    global t
    assert t.count(old) == 1, f"not found exactly once: {old[:90]!r}"
    t = t.replace(old, new)


rep('''# exists out to ~160 m (TRAFFIC_DESPAWN; 200 once chasing), so 160 is the useful maximum.
''', '''# exists out to ~160 m (TRAFFIC_DESPAWN; 200 once chasing), so 160 is the useful maximum.
# The same slider also sets the WANTED METER's reach (play test 2026-10-04: "it will inactive and reduce
# the level if it was too far"): every frame the police manager (0x0043f82d) looks for the nearest car
# in the chase state (0x00441b70: [car+0x1e74] or [+0x1e78] == 4) within `fld [0x00568ec4]` = 60 m
# (0x0043f848, a 60.0 with 30+ other readers). None found -> wanted -= 0.025/s and the pursuit flag
# [0x012d0448] (police radio, HUD) drops. So a chase started at 160 m drained from the first second.
''')
rep('''        (POLICE_SEE_CONST, bytes(4), struct.pack("<f", POLICE_SEE), f"{POLICE_SEE:g} m"),
    ]
''', '''        (0x0043F848, bytes.fromhex("d905c48e5600"), b"\\xd9\\x05" + struct.pack("<I", POLICE_SEE_CONST),
         f"wanted meter: holds while a chasing police car is within {POLICE_SEE:g} m (stock 60)"),
        (POLICE_SEE_CONST, bytes(4), struct.pack("<f", POLICE_SEE), f"{POLICE_SEE:g} m"),
    ]
''')
rep('''# ---- adaptive: the physics rate as a FLOOR''', '''# ---- wantedhits: harsher wanted meter on hits (play test 2026-10-04: "it adds 2 wanted level when I
# crash onto pedestrian, and 3 into the police cars. Can you change it to 4, and 5?")
# The HUD shows trunc(wanted * 10.5) bars, max 10 (0x004698c9). In the player-collision handler:
#   pedestrian ([obj+0x9d0] == 0x2000, alive [+0x6de4] == 0): wanted += 0.2 ([0x00568bb0], shared with
#     the chase speed formula) at 0x0043a97b, then min 1.0, max 0.26 -> repointed to WANTED_PED = 0.4.
#   police car (type 2, impact > 0.3): wanted = max(wanted, 0.3) at 0x0043a891..0x0043a8ab (xmm4 = 0.3
#     is reused afterwards, so it stays) -> rewritten in place as maxss with WANTED_COP = 0.5. A floor, as
#     stock: contacts repeat every physics step, a true "+0.5" would max the meter on one scrape.
#     (Every car crash also adds impact * 0.0125, untouched.)
WANTED_PED_CONST = S2_CODE + 0x50                # float
WANTED_COP_CONST = S2_CODE + 0x54                # float
WANTED_PED = 0.4                                 # 4 bars (stock 0.2 = 2)
WANTED_COP = 0.5                                 # 5 bars (stock 0.3 = 3)
PATCHES["wantedhits"] = [
    (0x0043A97B, bytes.fromhex("f30f581db08b5600"), bytes.fromhex("f30f581d") + struct.pack("<I", WANTED_PED_CONST),
     f"hitting a pedestrian: wanted +{WANTED_PED * 10.5:.0f} bars (stock +2)"),
    (0x0043A891, bytes.fromhex("f30f101d4c042d010f2fe376150f28dcf30f111d4c042d01eb08"),
     bytes.fromhex("f30f101d4c042d01") + bytes.fromhex("f30f5f1d") + struct.pack("<I", WANTED_COP_CONST)
     + bytes.fromhex("f30f111d4c042d01") + bytes.fromhex("eb08"),
     f"hitting a police car: wanted at least {int(WANTED_COP * 10.5)} bars (stock 3)"),
    (WANTED_PED_CONST, bytes(8), struct.pack("<ff", WANTED_PED, WANTED_COP), "0.4 / 0.5"),
]

# ---- adaptive: the physics rate as a FLOOR''')
rep('''"policeeyes", "morepolice", "adaptive", "laa")''',
    '''"policeeyes", "morepolice", "wantedhits", "adaptive", "laa")''')
rep('''            "policeeyes": ["modsect"], "morepolice": ["modsect"],
''', '''            "policeeyes": ["modsect"], "morepolice": ["modsect"], "wantedhits": ["modsect"],
''')
out = t.replace("\n", "\r\n") if crlf else t
open(p, "wb").write(out.encode("utf-8"))
print("edited, crlf =", crlf)
