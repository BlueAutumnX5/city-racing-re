r"""City Racing Car Tuner - a GUI for editing every vehicle stat by hand.

Each cell shows the factory value as grey ghost text. Click a cell and the ghost clears so you
can type your own. **Leave a cell blank and that stat keeps its factory value** - so the grid
only ever shows what you are actually overriding. Hover any column header for the full field
name and what it does.

Safety model, same as the command-line tools: every Apply rebuilds Objects.pak from the
VERIFIED PRISTINE BACKUP and then writes the values shown in the grid. Edits never stack, the
grid always equals the resulting game state, and Restore Stock is byte-exact.

Run with:  pythonw cartuner.py      (no console window)
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crpak

STOCK_DATA = crpaths.STOCK_DATA
LIVE_DATA = crpaths.LIVE_DATA

# (config field name, short header, tooltip body)
FIELDS = [
    ("Base Health", "Health",
     "Damage capacity before the car is written off.\n\n"
     "Stock is 100 on every car in the game.\n\n"
     "LEAVE THIS ALONE. Repair cost is charged per hit point lost, and damage appears to "
     "scale with max health - so raising it to 9999 multiplied repair bills roughly 100x "
     "while buying little or no real durability. Learned the hard way."),

    ("Base Weight (kg)", "Weight",
     "Vehicle mass in kilograms.\n\n"
     "Stock range: 800 (Clio NSX, Accord Z8) to 1200 (Rover, Thunder).\n\n"
     "Lighter means more responsive and quicker to change direction, but also easier to "
     "flip and easier for traffic to shove around. Heavier feels planted but lazy."),

    ("Base Engine Force", "Force",
     "Engine thrust - the main 'how fast' number.\n\n"
     "Stock range: 1300 (Clio, Accord) to 2500 (Uber Atom-2000 and both police cars).\n\n"
     "2500 is the developers' own ceiling: no shipped car exceeds it. Values above that are "
     "extrapolation, and the engine was never tested there."),

    ("Base Acceleration", "Accel",
     "A separate acceleration multiplier, applied alongside Engine Force.\n\n"
     "Stock range: 1.0 to 2.5.\n\n"
     "It is NOT derived from Force divided by Weight - both police cars have Force 2500 and "
     "Accel 2.5 despite weighing 1000 kg and 1200 kg. And Thunder-1960 has MORE force than "
     "Rover H1200 but LESS acceleration. These two values were hand-tuned by feel, so treat "
     "them as two independent knobs that both affect how hard the car pulls."),

    ("Base Steering", "Steer",
     "Steering response rate - how quickly the wheels turn.\n\n"
     "Stock range: 1.25 (Rover, Accord) to 2.5 (both police cars).\n\n"
     "Higher means sharper, twitchier turn-in. Combined with high Friction it is a major "
     "contributor to rollovers, because you reach full lock before the suspension can load up."),

    ("Front Tyre Driving", "F.Drv",
     "Is the FRONT axle powered? 0 = no, 1 = yes.\n\n"
     "Every single stock car is 0 here - the whole game is rear-wheel drive.\n\n"
     "Set this to 1 along with R.Drv for all-wheel drive, which massively improves traction "
     "off the line. The game never ships an AWD car, so this is genuinely outside the "
     "original design.\n\n"
     "BUG in the original game: an AWD car gets DOUBLE engine power (every driven wheel is "
     "pushed with the car's whole Engine Force). The 'AWD fix' switch in the RE Control "
     "Panel (Stage 2 tab) makes AWD the same power as 2-wheel drive, just with more grip. "
     "With the fix ON, an AWD car here is half as strong as before - double its Engine "
     "Force to keep the old speed. The line under the table says whether the fix is on."),

    ("Rear  Tyre Driving", "R.Drv",
     "Is the REAR axle powered? 0 = no, 1 = yes.\n\n"
     "Stock is 1 on every car - all rear-wheel drive.\n\n"
     "Set this to 0 with F.Drv at 1 for front-wheel drive, or leave both at 1 for AWD."),

    ("Front Tyre Friction", "F.Fric",
     "Grip of the FRONT tyres. The most consequential value in the whole table.\n\n"
     "Stock range: 1.25 to 2.5 (police).\n\n"
     "Tyre force acts at ground level while the car's mass sits above it, so cornering "
     "generates a torque that tries to tip the car. At stock grip the tyres BREAK TRACTION "
     "AND SLIDE before that torque gets dangerous - sliding is the safety valve.\n\n"
     "Raise it past about 2.5 and you remove that valve: the tyres refuse to let go, so all "
     "the force goes into rolling the body over instead. This is why 4.0 caused constant "
     "rollovers. Friction is the master dial for rollovers - not weight, not force."),

    ("Rear  Tyre Friction", "R.Fric",
     "Grip of the REAR tyres. Same mechanics as F.Fric.\n\n"
     "Stock range: 1.25 to 2.5 (police).\n\n"
     "Setting rear grip much lower than front gives easy oversteer and drifts. Setting it "
     "much higher gives understeer - the car pushes wide instead of rotating."),

    ("Front Tyre Rolling", "F.Roll",
     "Rolling resistance of the FRONT tyres - drag from the tyre itself.\n\n"
     "Stock is 1.0 on every car, with no variation at all across the whole roster.\n\n"
     "Higher should mean more drag and a lower top speed. Because every shipped car uses "
     "the same value, the real in-game effect is UNVERIFIED - nothing to compare against."),

    ("Rear  Tyre Rolling", "R.Roll",
     "Rolling resistance of the REAR tyres.\n\n"
     "Stock is 1.0 on every car. Same caveat as F.Roll: untested, since the game never "
     "varies it."),

    ("Suspension Stiffness", "Susp K",
     "Spring rate. K is the standard engineering symbol for a spring constant.\n\n"
     "Stock is either 25 (soft) or 35 (stiff). Note the odd '25.f' style in the game's own "
     "files - that suffix is fine to keep or drop.\n\n"
     "HIGHER resists body roll and pitch, which helps against rollovers. LOWER lets the body "
     "lean hard into corners, which makes rollovers far more likely - that is exactly what "
     "the 'flip' preset exploits with a value of 15."),

    ("Suspension Damping", "Susp D",
     "Damping - the shock absorbers. Controls how fast the spring settles.\n\n"
     "Stock is either 0.5 or 1.5.\n\n"
     "HIGHER settles the body quickly after a bump or a turn. LOWER lets it keep bouncing "
     "and oscillating.\n\n"
     "Curiosity: Thunder-1960 ships as 35 stiffness with 0.5 damping - stiff but "
     "underdamped, unlike every other stiff car which pairs 35 with 1.5. It looks like an "
     "oversight, and it is why that car feels bouncy."),
]

PRESETS = {
    "-- preset --": None,
    "stock": {},
    "police": {"Base Engine Force": "2500", "Base Acceleration": "2.5",
               "Base Steering": "2.5", "Front Tyre Friction": "2.5",
               "Rear  Tyre Friction": "2.5"},
    "fast": {"Base Weight (kg)": "1200", "Base Engine Force": "6000",
             "Base Acceleration": "5.0", "Base Steering": "2.0",
             "Front Tyre Driving": "1", "Rear  Tyre Driving": "1",
             "Front Tyre Friction": "2.5", "Rear  Tyre Friction": "2.5",
             "Suspension Stiffness": "60.f", "Suspension Damping": "2.0"},
    "op": {"Base Weight (kg)": "900", "Base Engine Force": "6000",
           "Base Acceleration": "5.0", "Base Steering": "3.0",
           "Front Tyre Driving": "1", "Rear  Tyre Driving": "1",
           "Front Tyre Friction": "4.0", "Rear  Tyre Friction": "4.0",
           "Suspension Stiffness": "45.f", "Suspension Damping": "1.5"},
    "flip": {"Base Weight (kg)": "600", "Base Engine Force": "8000",
             "Base Acceleration": "6.0", "Base Steering": "5.0",
             "Front Tyre Driving": "1", "Rear  Tyre Driving": "1",
             "Front Tyre Friction": "7.0", "Rear  Tyre Friction": "7.0",
             "Suspension Stiffness": "15.f", "Suspension Damping": "0.2"},
    "insane": {"Base Weight (kg)": "500", "Base Engine Force": "25000",
               "Base Acceleration": "12.0", "Base Steering": "6.0",
               "Front Tyre Driving": "1", "Rear  Tyre Driving": "1",
               "Front Tyre Friction": "8.0", "Rear  Tyre Friction": "8.0",
               "Front Tyre Rolling": "2.0", "Rear  Tyre Rolling": "2.0",
               "Suspension Stiffness": "80.f", "Suspension Damping": "3.0"},
}

PRESET_HELP = {
    "stock": "Clears every override - factory values for all cars.",
    "police": "Gives every car the shipped police tune (2500 / 2.5 / 2.5 / 2.5). This is the "
              "developers' own maximum, so it is guaranteed stable - a mild, safe boost.",
    "fast": "Quick but planted: full 6000 force and AWD, but friction back at the police "
            "ceiling so the tyres can still slide instead of tipping, calmer steering, and "
            "stiff well-damped suspension. The one to pick if you actually want to win races.",
    "op": "Strong, grippy and rollover-happy: AWD, 6000 force, friction 4.0. Fast and fun, "
          "but it tips over on sharp turns.",
    "flip": "Maximum comedy: grip that never releases (7.0), soft undamped suspension so the "
            "body leans hard into the roll, 600 kg, hair-trigger steering. Expect barrel rolls "
            "on almost any direction change.",
    "insane": "Deliberately absurd - 25000 force, acceleration 12. Stiff suspension so it "
              "launches rather than tips. Expect physics breakdown.",
}

VEH = re.compile(r"^Data/Vehicles/(\d\d)/(Main|Police)\.obj$")
NUMLIKE = re.compile(r"^-?\d+(?:\.\d*)?f?$")

FG_GHOST = "#adb5bd"
FG_REAL = "#000000"
BG_OVERRIDE = "#fff3bf"
BG_NORMAL = "#ffffff"
BG_BAD = "#ffc9c9"


class Tooltip:
    """Hover tooltip: a bold title line and a wrapped explanatory body."""

    def __init__(self, widget, title, body, delay=300, wrap=420):
        self.widget, self.title, self.body = widget, title, body
        self.delay, self.wrap = delay, wrap
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _ev=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        frame = tk.Frame(tw, background="#343a40", borderwidth=0)
        frame.pack()
        inner = tk.Frame(frame, background="#f8f9fa")
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.title, background="#f8f9fa", foreground="#1864ab",
                 font=("Segoe UI", 9, "bold"), justify="left", anchor="w"
                 ).pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(inner, text=self.body, background="#f8f9fa", foreground="#212529",
                 font=("Segoe UI", 9), justify="left", anchor="w",
                 wraplength=self.wrap).pack(fill="x", padx=10, pady=(0, 9))
        tw.update_idletasks()
        # keep it on screen
        sw = tw.winfo_screenwidth()
        if x + tw.winfo_width() > sw - 10:
            x = max(10, sw - tw.winfo_width() - 10)
        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self, _ev=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def field_re(field):
    return re.compile(r"(?m)^(" + re.escape(field) + r":[ \t]*)(\S+)")


def get_field(text, field):
    m = field_re(field).search(text)
    return m.group(2) if m else None


def set_field(text, field, value):
    return field_re(field).sub(lambda m: m.group(1) + value, text, count=1)


def get_model(text):
    m = re.search(r"(?m)^Vehicle model:[ \t]*([^\r\n]*?)[ \t]*\r?$", text)
    return m.group(1) if m else "?"


def read_cars(data_dir):
    entries, _, payloads, _ = crpak.load_archive(data_dir, "Objects")
    out = []
    for (name, _, _), payload in zip(entries, payloads):
        if not VEH.match(name):
            continue
        text = crpak.xor80(payload).decode("latin-1")
        out.append((name, get_model(text),
                    {f: (get_field(text, f) or "") for f, _, _ in FIELDS}))
    return out


def awdfix_state():
    """'on' / 'off' / '?' - whether the installed game.exe carries racemod's awdfix (the jump it puts at
    0x0043491d = file offset 0x33d1d)."""
    try:
        with open(os.path.join(os.path.dirname(LIVE_DATA), "game.exe"), "rb") as f:
            f.seek(0x33D1D)
            b = f.read(9)
        return "on" if b[:1] == b"\xe9" else "off" if b == bytes.fromhex("83beb07f0000007439") else "?"
    except OSError:
        return "?"


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe"],
                             capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return "game.exe" in out
    except Exception:
        return False


def write_cars(overrides):
    """Rebuild from pristine, applying only non-empty overrides {name: {field: val}}."""
    entries, _, payloads, _ = crpak.load_archive(STOCK_DATA, "Objects")
    names = [n for n, _, _ in entries]
    out, changed = [], 0
    for name, payload in zip(names, payloads):
        ov = overrides.get(name)
        if not ov:
            out.append(payload)
            continue
        text = crpak.xor80(payload).decode("latin-1")
        touched = False
        for field, val in ov.items():
            val = val.strip()
            if not val:
                continue                       # blank = keep factory value
            if get_field(text, field) is None:
                continue
            if get_field(text, field) != val:
                text = set_field(text, field, val)
                changed += 1
                touched = True
        out.append(crpak.xor80(text.encode("latin-1")) if touched else payload)

    hdr, pak = crpak.build_archive(names, out)
    for ext, blob in (("hdr", hdr), ("pak", pak)):
        dst = os.path.join(LIVE_DATA, f"Objects.{ext}")
        tmp = dst + ".new"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, dst)

    e2, stored, _, blob = crpak.load_archive(LIVE_DATA, "Objects")
    ok = (stored == len(e2)) and (e2[-1][1] + e2[-1][2] == len(blob))
    return changed, ok, len(pak)


class App:
    def __init__(self, root):
        self.root = root
        root.title("City Racing - Car Tuner")
        root.configure(padx=10, pady=8)

        self.cars = read_cars(STOCK_DATA)
        self.stock = {n: v for n, _, v in self.cars}
        self.cells = {}
        self.ghost = {}

        self._build_toolbar()
        self._build_grid()
        self._build_status()
        self.load_from(LIVE_DATA, "current game files")

    # ------------------------------------------------------------- ghost text
    def is_ghost(self, key):
        return self.ghost.get(key, False)

    def show_ghost(self, key):
        e = self.cells[key]
        e.delete(0, "end")
        e.insert(0, self.stock[key[0]].get(key[1], ""))
        e.configure(foreground=FG_GHOST, background=BG_NORMAL)
        self.ghost[key] = True

    def set_value(self, key, value):
        stock = self.stock[key[0]].get(key[1], "")
        if not value or value == stock:
            self.show_ghost(key)
            return
        e = self.cells[key]
        e.delete(0, "end")
        e.insert(0, value)
        e.configure(foreground=FG_REAL)
        self.ghost[key] = False
        self.mark(key)

    def value_of(self, key):
        return "" if self.is_ghost(key) else self.cells[key].get().strip()

    def on_focus_in(self, key):
        if self.is_ghost(key):
            e = self.cells[key]
            e.delete(0, "end")
            e.configure(foreground=FG_REAL)
            self.ghost[key] = False
            self.mark(key)

    def on_focus_out(self, key):
        if not self.is_ghost(key) and not self.cells[key].get().strip():
            self.show_ghost(key)

    def mark(self, key):
        e = self.cells[key]
        if self.is_ghost(key):
            e.configure(background=BG_NORMAL)
            return
        val = e.get().strip()
        if val and not NUMLIKE.match(val):
            e.configure(background=BG_BAD)
        elif val and val != self.stock[key[0]].get(key[1], ""):
            e.configure(background=BG_OVERRIDE)
        else:
            e.configure(background=BG_NORMAL)

    # ---------------------------------------------------------------- widgets
    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", pady=(0, 8))
        b1 = ttk.Button(bar, text="Reload current", command=self.on_reload)
        b1.pack(side="left")
        Tooltip(b1, "Reload current",
                "Re-reads the stats from the game's live Objects.pak and fills the grid with "
                "them. Use it to discard edits you have typed but not applied.")
        b2 = ttk.Button(bar, text="Clear all overrides", command=self.on_clear)
        b2.pack(side="left", padx=(6, 0))
        Tooltip(b2, "Clear all overrides",
                "Blanks every cell back to ghost text, meaning 'use the factory value'. "
                "Nothing is written until you press APPLY.")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Preset for").pack(side="left")
        self.scope = tk.StringVar(value="player cars")
        sc = ttk.Combobox(bar, textvariable=self.scope, width=11, state="readonly",
                          values=["player cars", "all cars"])
        sc.pack(side="left", padx=4)
        Tooltip(sc, "Preset scope",
                "'player cars' applies the preset to the 8 driveable cars only, leaving the "
                "two Police cars at stock - which keeps pursuit cars slow and escapable.\n\n"
                "'all cars' includes the Police too.")
        self.preset = tk.StringVar(value="-- preset --")
        cb = ttk.Combobox(bar, textvariable=self.preset, width=12, state="readonly",
                          values=list(PRESETS))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self.on_preset)
        Tooltip(cb, "Presets", "\n\n".join(f"{k}:  {v}" for k, v in PRESET_HELP.items()),
                wrap=460)

        b4 = ttk.Button(bar, text="Restore stock & save", command=self.on_restore)
        b4.pack(side="right")
        Tooltip(b4, "Restore stock & save",
                "Clears every override AND writes it to the game immediately, rebuilding "
                "Objects.pak from the pristine backup. The result is byte-for-byte identical "
                "to the original archive.")
        b3 = ttk.Button(bar, text="APPLY to game", command=self.on_apply)
        b3.pack(side="right", padx=6)
        Tooltip(b3, "APPLY to game",
                "Rebuilds Objects.pak from the pristine backup, writes in every value you "
                "have overridden, installs it, then re-reads and verifies the index.\n\n"
                "Exit the game first - the archive cannot be rewritten while it is open.")

    def _build_grid(self):
        grid = ttk.Frame(self.root)
        grid.pack(fill="both", expand=True)
        bold = ("Segoe UI", 9, "bold")

        h0 = ttk.Label(grid, text="car", font=bold, cursor="question_arrow")
        h0.grid(row=0, column=0, sticky="w", padx=(0, 6))
        Tooltip(h0, "Car slot",
                "The archive path inside Objects.pak - 01..08 are the driveable cars, and "
                "01/Police and 03/Police are the AI pursuit variants of those two models.\n\n"
                "Opponent racers drive these same files, so boosting a car likely boosts it "
                "for the AI too when they use that model.")
        h1 = ttk.Label(grid, text="model", font=bold, cursor="question_arrow")
        h1.grid(row=0, column=1, sticky="w", padx=(0, 10))
        Tooltip(h1, "Model name",
                "The in-game name, read from the 'Vehicle model' line of each config.\n\n"
                "Worth knowing: Accord Z8 is strictly worse than Clio NSX - identical 800 kg "
                "/ 1300 force / 1.0 accel, but lower steering and grip, and better at "
                "nothing. Uber Atom-2000 is the best stock car.")

        for c, (field, short, body) in enumerate(FIELDS):
            lbl = ttk.Label(grid, text=short, font=bold, cursor="question_arrow",
                            foreground="#1864ab")
            lbl.grid(row=0, column=2 + c, padx=2)
            Tooltip(lbl, field, body)

        for r, (name, model, _) in enumerate(self.cars, start=1):
            short = name.replace("Data/Vehicles/", "").replace(".obj", "")
            police = short.endswith("Police")
            ttk.Label(grid, text=short,
                      foreground="#c92a2a" if police else "#1864ab").grid(
                row=r, column=0, sticky="w", padx=(0, 6))
            ttk.Label(grid, text=model).grid(row=r, column=1, sticky="w", padx=(0, 10))
            for c, (field, _, _) in enumerate(FIELDS):
                key = (name, field)
                e = tk.Entry(grid, width=7, justify="right", relief="solid",
                             borderwidth=1)
                e.grid(row=r, column=2 + c, padx=1, pady=1)
                e.bind("<FocusIn>", lambda _e, k=key: self.on_focus_in(k))
                e.bind("<FocusOut>", lambda _e, k=key: self.on_focus_out(k))
                e.bind("<KeyRelease>", lambda _e, k=key: self.mark(k))
                self.cells[key] = e

    def _build_status(self):
        awd = awdfix_state()
        ttk.Label(self.root, anchor="w", foreground="#b36b00" if awd == "on" else "#868e96",
                  text=("AWD fix is ON in game.exe: an AWD car (F.Drv 1 + R.Drv 1) has the SAME power as "
                        "2-wheel drive - double its Force to keep the old (bugged) double power."
                        if awd == "on" else
                        "AWD fix is OFF: like the original game, an AWD car (F.Drv 1 + R.Drv 1) gets "
                        "DOUBLE engine power (a 2005 bug; the fix is on the Control Panel's Stage 2 tab).")
                  ).pack(fill="x", pady=(8, 0))
        self.status = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.status, anchor="w",
                  foreground="#1864ab").pack(fill="x", pady=(8, 0))
        ttk.Label(self.root, anchor="w", foreground="#868e96", justify="left",
                  text=("Hover any blue column header for the full field name and what it "
                        "does.   Grey ghost text = the factory value; click a cell to type "
                        "your own. A blank cell keeps the factory value.   Yellow = your "
                        "override.\n"
                        "The Police rows are the developers' own maximum "
                        "(2500 force / 2.5 accel / 2.5 steer / 2.5 friction) - past that is "
                        "where rollovers and physics breakdown start.")
                  ).pack(fill="x")

    # ----------------------------------------------------------------- actions
    def load_from(self, data_dir, label):
        try:
            cars = read_cars(data_dir)
        except Exception as exc:
            self.status.set(f"failed to read {data_dir}: {exc}")
            return
        n = 0
        for name, _, vals in cars:
            for field, _, _ in FIELDS:
                key = (name, field)
                if key not in self.cells:
                    continue
                v = vals.get(field, "")
                self.set_value(key, v)
                if v and v != self.stock[name].get(field, ""):
                    n += 1
        self.status.set(f"loaded from {label} - {n} value(s) differ from factory stock")

    def on_reload(self):
        self.load_from(LIVE_DATA, "current game files")

    def on_clear(self):
        for key in self.cells:
            self.show_ghost(key)
        self.status.set("all overrides cleared - every stat back to its factory value "
                        "(nothing written yet, press APPLY)")

    def on_preset(self, _ev=None):
        key = self.preset.get()
        spec = PRESETS.get(key)
        if spec is None:
            return
        players_only = self.scope.get() == "player cars"
        for (name, field) in self.cells:
            if players_only and name.endswith("Police.obj"):
                continue
            self.set_value((name, field),
                           "" if key == "stock" else spec.get(field, ""))
        self.preset.set("-- preset --")
        self.status.set(f"filled preset '{key}' into {self.scope.get()} "
                        f"- nothing written yet, press APPLY")

    def collect(self):
        vals, bad = {}, []
        for key in self.cells:
            v = self.value_of(key)
            if v and not NUMLIKE.match(v):
                bad.append(f"{key[0].replace('Data/Vehicles/', '')}  {key[1]} = '{v}'")
            vals.setdefault(key[0], {})[key[1]] = v
        return vals, bad

    def on_apply(self):
        if game_running():
            messagebox.showwarning(
                "Game is running",
                "game.exe is running. Exit the game first - the archive cannot be "
                "rewritten while it is open.")
            return
        vals, bad = self.collect()
        if bad:
            messagebox.showerror("Invalid values",
                                 "These are not numbers:\n\n" + "\n".join(bad[:12]))
            return
        try:
            changed, ok, size = write_cars(vals)
        except Exception as exc:
            messagebox.showerror("Write failed", str(exc))
            self.status.set(f"write failed: {exc}")
            return
        self.status.set(f"APPLIED - {changed} field(s) written, Objects.pak {size:,} bytes, "
                        f"index verified {'OK' if ok else 'BROKEN'}. Launch the game.")
        if not ok:
            messagebox.showerror("Verification failed",
                                 "The rebuilt archive did not verify. Press "
                                 "'Restore stock & save' immediately.")

    def on_restore(self):
        if game_running():
            messagebox.showwarning("Game is running", "Exit the game first.")
            return
        self.on_clear()
        self.on_apply()
        self.status.set("restored factory stock and written to the game")


if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
