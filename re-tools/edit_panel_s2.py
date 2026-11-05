"""One-off edit (2026-10-04): the Stage 2 extras in crpanel.py - their own tab, tooltips, and a
slider + text box for every valued extra (racemod.VALUED) besides the physics rate."""
import crpaths
p = crpaths.work(r"crpanel.py")
raw = open(p, "rb").read()
crlf = b"\r\n" in raw
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(old, new):
    global t
    assert t.count(old) == 1, f"not found exactly once: {old[:90]!r}"
    t = t.replace(old, new)


# ---- A. words for gamers
rep('''                   "The engine sounds the same as before, just without the gaps."),
}''', '''                   "The engine sounds the same as before, just without the gaps."),
    # ---- Stage 2 (2026-10-04)
    "awdfix": ("AWD fix", "All-wheel-drive cars no longer get double power.",
               "Bug in the original game: an AWD car (front AND rear 'Tyre Driving' set to 1 in the Car "
               "Tuner) pushed every one of its four wheels with the car's FULL engine force, so it had "
               "twice the power of the same car with 2-wheel drive.\\n\\n"
               "With this fix an AWD car has the same power as a 2-wheel-drive one, spread over four "
               "tyres: better grip off the line, not double the speed.\\n\\n"
               "All stock cars are rear-wheel drive, so this only changes cars you set to AWD - right "
               "now your police cars and cars 03 and 05. They will feel weaker: raise their Engine "
               "Force in the Car Tuner if you want them as fast as before."),
    "revboost": ("Stronger reverse", "Reverse pulls like first gear, so you can back up hills.",
                 "In the original game, pressing the gas gets a big 'launch boost' at low speed (up "
                 "to 3.5x the engine force), but reverse never gets it - so reverse has under a third "
                 "of the push, and a normal car can't even back up a steep hill.\\n\\n"
                 "With this, reverse gets the same boost as driving forward. Reverse top speed is "
                 "unchanged. Other cars (traffic, police, racers) also back out of crashes faster."),
    "gravity": ("Custom gravity", "Moon gravity - or any gravity you like.",
                "Changes gravity for the whole physics world: your car, traffic, police and every "
                "loose object.\\n\\nThe original game uses 10 (Earth). The Moon is 1.62: huge, slow "
                "jumps and floaty crashes. Mars is 3.71. Jupiter is 24.8 (cars feel glued down).\\n\\n"
                "Sparks and pedestrians are not physics objects, so they don't change."),
    "policeeyes": ("Sharper police", "Police notice you from further away.",
                   "In the original game a police car only starts chasing you when it is within 40 m "
                   "of you (and you are wanted). With this they spot you from the distance set "
                   "below."),
    "morepolice": ("More police", "Fixes the 'police disappear' bug and adds more patrols.",
                   "Bug in the original game: it only allows 4 police cars to appear EVER until the "
                   "next race or reset - when they drive away, no new police come.\\n\\n"
                   "With this, the limit counts the police that are actually around you right now "
                   "(set below), and a new car is police twice as often (about 1 in 5).\\n\\n"
                   "Police replace normal traffic, so the total number of cars stays the same."),
    "adaptive": ("Physics follows FPS", "The physics rate is a minimum; above it, it matches your FPS.",
                 "Your idea: the 'Physics rate' becomes a FLOOR.\\n\\n"
                 "- FPS above it (say 144): the physics runs once per frame at your FPS (144 Hz) - "
                 "perfectly smooth, in step with the screen.\\n"
                 "- FPS below it (say 40 in the city centre): exactly like now, fixed steps at the "
                 "physics rate.\\n\\n"
                 "It never costs more CPU than the higher of the two. Needs 'Fixed physics rate' (it "
                 "is switched on with it)."),
    "laa": ("Use 4 GB of memory", "Lets the game use 4 GB of RAM instead of 2 GB.",
            "The game is a 32-bit program, which normally only gets 2 GB of memory. With all the "
            "extras (long view distance, 60 cars, big supersampling) it has used up to about 1.7 GB, "
            "close to that limit; running out would crash it.\\n\\n"
            "This flag lets it use up to 4 GB. It changes no game code. Very old games sometimes "
            "dislike it - if the game acts strange with it on, turn it off."),
}
STAGE2 = ("awdfix", "revboost", "gravity", "policeeyes", "morepolice", "adaptive", "laa")
# slider settings for valued extras besides the physics rate: label, step, format
VALUE_ROWS = {
    "gravity": ("Gravity", 0.01, "%.2f"),
    "policeeyes": ("Police sight", 5, "%.0f"),
    "morepolice": ("Police at once", 1, "%.0f"),
}''')

rep('''    "hz": "How many times per second the physics is calculated.''', '''    "gravity": "How strong gravity is, in m/s2.\\n\\n10 = the original game (Earth). 1.62 = the Moon. "
               "3.71 = Mars. 24.8 = Jupiter.",
    "policeeyes": "How close (in metres) a police car must be to notice you and start a chase - if you "
                  "are wanted.\\n\\nOriginal game: 40 m. Police only exist up to about 160 m from you, "
                  "so higher would do nothing.",
    "morepolice": "The most police cars allowed around you at the same time.\\n\\nThe original game "
                  "meant 4 (but its bug made it 4 per race). More = busier chases.",
    "hz": "How many times per second the physics is calculated.''')

# ---- B. the extras loop -> a function, used on two tabs
rep('''        nb.add(tab1, text="  Settings  ")
        nb.add(tab2, text="  What it looks like  ")''', '''        tab3 = ttk.Frame(nb)
        nb.add(tab1, text="  Settings  ")
        nb.add(tab3, text="  Stage 2: gameplay  ")
        nb.add(tab2, text="  What it looks like  ")''')
rep('''        ef = ttk.LabelFrame(tab1, text="Extras")
        ef.pack(fill="x", **pad)
        ef.columnconfigure(1, weight=1)
        r = 0
        for name in racemod.EXTRAS:
''', '''        ef = ttk.LabelFrame(tab1, text="Extras")
        ef.pack(fill="x", **pad)
        self._extra_rows(ef, [n for n in racemod.EXTRAS if n not in STAGE2])
        self._build_calc(tab1)
        s2 = ttk.LabelFrame(tab3, text="Stage 2 extras (new - switch them on to try them)")
        s2.pack(fill="x", **pad)
        self._extra_rows(s2, [n for n in racemod.EXTRAS if n in STAGE2])
        ttk.Label(tab3, style="Small.TLabel", wraplength=900, justify="left",
                  text="Everything here is OFF until you tick it and press Apply. Each one was tested in "
                       "an emulator against the game's own code, but not yet in a real drive - so try "
                       "them one at a time. Untick + Apply puts it back exactly as before."
                  ).pack(fill="x", padx=12, pady=4)
        self._build_actions(pad)

    def _extra_rows(self, ef, names):
        ef.columnconfigure(1, weight=1)
        r = 0
        for name in names:
''')
rep('''            if name in ("panini", "fixedstep"):
                sub = ttk.Frame(ef)
                sub.grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 3))
                (self._panini_rows if name == "panini" else self._fixed_rows)(sub)
                r += 1

        self._build_calc(tab1)

        # actions
''', '''            if name in ("panini", "fixedstep") or name in VALUE_ROWS:
                sub = ttk.Frame(ef)
                sub.grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 3))
                if name == "panini":
                    self._panini_rows(sub)
                elif name == "fixedstep":
                    self._fixed_rows(sub)
                else:
                    self._valued_row(sub, name)
                r += 1

    def _valued_row(self, f, name):
        key, setter, cur, unit, (lo, hi), dflt = racemod.VALUED[name]
        label, step, fmt = VALUE_ROWS[name]
        unit = {"m/s2": "m/s\\u00b2", "m": "metres", "cars": "police cars"}.get(unit, unit)
        self.v_extra[name] = ValueControl(f, 0, label, lo, hi, step, fmt, dflt, unit,
                                          VALUE_TIPS[name], self._changed)

    def _build_actions(self, pad):
        # actions
''')
rep('''        self.check, self.inst = {}, {}''', '''        self.check, self.inst, self.v_extra = {}, {}, {}''')

# ---- C. values in/out
rep('''        return {"fov": self.v_fov, "vfov": self.v_vfov, "scale": self.v_scale, "chase": self.v_chase,
                "hz": self.v_hz}''', '''        return {"fov": self.v_fov, "vfov": self.v_vfov, "scale": self.v_scale, "chase": self.v_chase,
                "hz": self.v_hz, **self.v_extra}''')
rep('''                    hz=float(s.get("fixedstep_hz", racemod.FIXED_HZ_DEFAULT)), panini=pan)''',
    '''                    hz=float(s.get("fixedstep_hz", racemod.FIXED_HZ_DEFAULT)), panini=pan,
                    vals={n: float(s.get(v[0], v[5])) for n, v in racemod.VALUED.items() if n in VALUE_ROWS})''')
rep('''        self.v_hz.set(sv["hz"])
        self._loading = False''', '''        self.v_hz.set(sv["hz"])
        for n, ctl in self.v_extra.items():
            ctl.set(sv["vals"][n])
        self._loading = False''')
rep('''                "fixedstep_hz": self.v_hz.value(),
                "panini":''', '''                "fixedstep_hz": self.v_hz.value(),
                **{racemod.VALUED[n][0]: ctl.value() for n, ctl in self.v_extra.items()},
                "panini":''')
rep('''        if c["fixedstep_hz"] is None or abs(c["fixedstep_hz"] - sv["hz"]) > 1e-6:
            diffs.append("physics rate")''', '''        if c["fixedstep_hz"] is None or abs(c["fixedstep_hz"] - sv["hz"]) > 1e-6:
            diffs.append("physics rate")
        for n, ctl in self.v_extra.items():
            v = ctl.value()
            if v is None or abs(v - sv["vals"][n]) > 1e-6:
                diffs.append(VALUE_ROWS[n][0].lower())''')

out = t.replace("\n", "\r\n") if crlf else t
open(p, "wb").write(out.encode("utf-8"))
print("edited, crlf =", crlf)
