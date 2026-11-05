"""One-off edit (2026-10-04): register policeeyes / morepolice."""
import crpaths
p = crpaths.work(r"racemod.py")
t = open(p, newline="").read()
N = "\r\n"


def rep(old, new):
    global t
    old, new = old.replace("\n", N), new.replace("\n", N)
    assert t.count(old) == 1, f"not found exactly once: {old[:80]!r}"
    t = t.replace(old, new)


rep('''          "awdfix", "gravity", "revboost", "laa")''',
    '''          "awdfix", "gravity", "revboost", "policeeyes", "morepolice", "laa")''')
rep('''"gravity": ["modsect"], "revboost": ["modsect"]}''',
    '''"gravity": ["modsect"], "revboost": ["modsect"],
            "policeeyes": ["modsect"], "morepolice": ["modsect"]}''')
rep('''    "gravity": ("gravity_ms2", lambda v: set_gravity(v), lambda: GRAVITY, "m/s2", GRAVITY_RANGE,
                GRAVITY_DEFAULT),
}''', '''    "gravity": ("gravity_ms2", lambda v: set_gravity(v), lambda: GRAVITY, "m/s2", GRAVITY_RANGE,
                GRAVITY_DEFAULT),
    "policeeyes": ("police_see_m", lambda v: set_police_see(v), lambda: POLICE_SEE, "m", POLICE_SEE_RANGE,
                   POLICE_SEE_DEFAULT),
    "morepolice": ("police_max", lambda v: set_police_max(v), lambda: POLICE_MAX, "cars", POLICE_MAX_RANGE,
                   POLICE_MAX_DEFAULT),
}''')
open(p, "w", newline="").write(t)
print("edited")
