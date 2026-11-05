"""One-off edit (2026-10-04): gravity into EXTRAS/REQUIRES, the VALUED table, and generic value
handling in `setup` and `extras`. Exact-match replacements; aborts if anything is not found."""
import crpaths
p = crpaths.work(r"racemod.py")
t = open(p, newline="").read()
N = "\r\n"


def rep(old, new):
    global t
    old, new = old.replace("\n", N), new.replace("\n", N)
    assert t.count(old) == 1, f"not found exactly once: {old[:80]!r}"
    t = t.replace(old, new)


rep('''          "awdfix")''', '''          "awdfix", "gravity")''')
rep('''"engineloop": ["modsect"], "awdfix": ["modsect"]}''',
    '''"engineloop": ["modsect"], "awdfix": ["modsect"], "gravity": ["modsect"]}
# Extras that carry a number (`extras on fixedstep 60`, `extras on gravity 1.62`, the panel's sliders):
# name -> (state-file key, setter (raises ValueError), current value, unit, (lo, hi), default)
VALUED = {
    "fixedstep": ("fixedstep_hz", lambda v: set_fixed_hz(v), lambda: FIXED_HZ, "Hz", FIXED_HZ_RANGE,
                  FIXED_HZ_DEFAULT),
    "gravity": ("gravity_ms2", lambda v: set_gravity(v), lambda: GRAVITY, "m/s2", GRAVITY_RANGE,
                GRAVITY_DEFAULT),
}''')

# setup: every valued extra's key is honoured and saved
rep('''            if cfg.get("fixedstep_hz") is not None:
                set_fixed_hz(float(cfg["fixedstep_hz"]))
''', '''            for name, (key, setter, cur, unit, rng, dflt) in VALUED.items():
                if cfg.get(key) is not None:
                    setter(float(cfg[key]))
''')
rep('''        print(f"physics rate: {FIXED_HZ:g} Hz (cap {FIXED_MAX_SUBSTEPS})   panini: "
              + ", ".join(f"{k} {v:g}" for k, v in panini.settings().items()) + "\\n")''',
    '''        print(f"physics rate: {FIXED_HZ:g} Hz (cap {FIXED_MAX_SUBSTEPS})   gravity: {GRAVITY:g} m/s2   panini: "
              + ", ".join(f"{k} {v:g}" for k, v in panini.settings().items()) + "\\n")''')
rep('''            s["fixedstep_hz"] = FIXED_HZ
            s["panini"] = panini.settings()''', '''            for name, (key, setter, cur, unit, rng, dflt) in VALUED.items():
                s[key] = cur()
            s["panini"] = panini.settings()''')

# extras CLI: a number goes with the one valued extra named
rep('''        # a number after fixedstep is its physics rate: `extras on fixedstep 60`
        nums = [w for w in which if re.fullmatch(r"\\d+(\\.\\d+)?", w)]
        which = [w for w in which if w not in nums]
        usage = (f"usage: extras on|off {' '.join(EXTRAS)}\\n"
                 f"       extras on fixedstep <Hz>   physics rate, {FIXED_HZ_RANGE[0]}..{FIXED_HZ_RANGE[1]}"
                 f" (now {FIXED_HZ:g})")''',
    '''        # a number after a valued extra is its setting: `extras on fixedstep 60`, `extras on gravity 1.62`
        nums = [w for w in which if re.fullmatch(r"\\d+(\\.\\d+)?", w)]
        which = [w for w in which if w not in nums]
        usage = f"usage: extras on|off {' '.join(EXTRAS)}" + "".join(
            f"\\n       extras on {n} <{u}>   {rng[0]:g}..{rng[1]:g} (now {cur():g}, default {d:g})"
            for n, (k, st, cur, u, rng, d) in VALUED.items())''')
rep('''        hz = None
        if nums:
            if mode != "on" or "fixedstep" not in which or len(nums) != 1:
                print("a rate goes with `extras on fixedstep <Hz>` only\\n" + usage)
                sys.exit(2)
            hz = float(nums[0])
            try:
                set_fixed_hz(hz)
            except ValueError as e:
                print(f"{e}\\n{usage}")
                sys.exit(2)
            print(f"physics rate: {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame")''',
    '''        valued = None
        if nums:
            named = [w for w in which if w in VALUED]
            if mode != "on" or len(named) != 1 or len(nums) != 1:
                print("a number goes with exactly one of: "
                      + ", ".join(f"`extras on {n} <{v[3]}>`" for n, v in VALUED.items()) + "\\n" + usage)
                sys.exit(2)
            valued = named[0]
            try:
                VALUED[valued][1](float(nums[0]))
            except ValueError as e:
                print(f"{e}\\n{usage}")
                sys.exit(2)
            if valued == "fixedstep":
                print(f"physics rate: {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame")
            else:
                print(f"{valued}: {VALUED[valued][2]():g} {VALUED[valued][3]}")''')
rep('''        if rc == 0 and hz is not None:
            s = load_state()
            s["fixedstep_hz"] = FIXED_HZ
            save_state(s)''', '''        if rc == 0 and valued is not None:
            s = load_state()
            s[VALUED[valued][0]] = VALUED[valued][2]()
            save_state(s)''')
rep('''            print(f"physics rate (fixedstep): {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame"
                  f"{'' if 'fixedstep' in cur else '  (fixedstep is off: stock, one step per frame)'}")''',
    '''            print(f"physics rate (fixedstep): {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame"
                  f"{'' if 'fixedstep' in cur else '  (fixedstep is off: stock, one step per frame)'}")
            print(f"gravity: {GRAVITY:g} m/s2{'' if 'gravity' in cur else '  (gravity is off: stock 10)'}")''')
open(p, "w", newline="").write(t)
print("edited")
