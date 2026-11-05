"""Dyno-style engine charts (power hp + torque Nm on one chart, 1000 rpm -> redline) for every car and engine
upgrade level 0..3, written to "Engine curves.html" (self-contained, light/dark).

    engine_curves.py            runs the Rust test print_curves (rust/crdrive, the REAL step()), then the page
    engine_curves.py --no-rust  page only, from engine_curves_raw.csv

The charts are drawn HERE as plain SVG and the Stock / Engine 1-3 switch is CSS radio buttons, so the page works
with scripts off (the Claude app shows files outside the session folder as a static snapshot: a JS-drawn page
came out blank there, player 2026-11-01). A small script only adds hover readouts where scripts run.

Two things are drawn per car:
- "Real engine" (solid, power + torque): the realistic curve I propose for the gearbox - the SAME formula as
  model.rs tc(r) = 1 - k (r - peak)^2, with the torque peak, the power peak and the torque at 1000 rpm set per
  engine type (real engines of that kind), scaled so peak power = the car's power ceiling in the game now.
  NOT in the game yet.
- "Game now" (dashed, power only): the most power the current drivetrain gives at each rpm in any gear the
  car can reach (road speed <= its top speed). It is NOT an engine curve: the current model limits power by
  road speed (constant power below the top speed), so it is flat wherever that cap is reached.

Units: the game is SI (Bullet: newtons, metres; km/h shown) and the drive force goes to both driven wheels,
so wheel power = 2 x force x speed. Wheel figures, no drivetrain loss. The game has no rpm, only revs as a
share of the redline (r = 1): idle / redline / dial max are the player's speedometer numbers (Alpha set by the
player, the rest my picks per engine type). hp and Nm share one number axis (in Nm the curves cross at 7121 rpm)."""
import html
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "engine_curves_raw.csv")
OUT = os.path.join(HERE, "Engine curves.html")
HP = 745.7

# model: name, base force, base accel (stock Main.obj), gears, gearbox, idle / redline / dial-max rpm, engine,
#        real-engine shape: torque peak (share of redline), power peak, torque at 1000 rpm (share of peak)
CARS = {
    1: ("Galant S500", 2000, 2.0, 4, "4-speed automatic", 650, 5000, 6000, "big torquey V8", 0.60, 0.90, 0.70),
    2: ("Clio NSX", 1300, 1.0, 5, "5-speed manual", 850, 7000, 8000, "revvy 4-cylinder", 0.64, 0.88, 0.55),
    3: ("Rover H1200", 1700, 1.5, 6, "6-speed automatic", 700, 5500, 6500, "SUV, low-down pull", 0.50, 0.85, 0.75),
    4: ("Cosmo R200", 2300, 2.0, 6, "6-speed manual", 800, 7500, 8500, "sports engine", 0.60, 0.90, 0.55),
    5: ("Thunder-1960", 1800, 1.25, 3, "3-speed automatic", 550, 4800, 5500, "lazy 1960 V8", 0.57, 0.94, 0.72),
    6: ("Accord Z8", 1300, 1.0, 5, "5-speed manual", 900, 8000, 9000, "tiny kei engine", 0.65, 0.90, 0.50),
    # redline 10000 / dial 11000: player 2026-11-01
    7: ("Alpha GRX8", 2200, 2.25, 6, "6-speed manual", 900, 10000, 11000, "rotary", 0.70, 0.94, 0.45),
    8: ("Uber Atom-2000", 2500, 2.5, 6, "6-speed F1 paddles", 1000, 8500, 9500, "high-revving V8", 0.70, 0.96, 0.50),
}
LEVELS = ("Stock", "Engine 1", "Engine 2", "Engine 3")


def run_rust():
    env = dict(os.environ, CR_CARS=",".join(f"{m}:{c[1]}:{c[2]}" for m, c in CARS.items()),
               PATH=os.path.join(os.path.expanduser("~"), ".cargo", "bin") + os.pathsep + os.environ["PATH"])
    r = subprocess.run(["cargo", "test", "print_curves", "--", "--ignored", "--nocapture"],
                       cwd=os.path.join(HERE, "rust", "crdrive"), env=env, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("CURVE ")]
    if len(lines) < 100:
        sys.exit("the Rust curve test printed nothing:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    open(RAW, "w").write("\n".join(lines) + "\n")


def load():
    data = {}
    for line in open(RAW):
        if line.startswith("CURVE model"):
            continue
        m, lvl, g, r, v, f = line[6:].strip().split(",")
        data.setdefault((int(m), int(lvl)), {}).setdefault(int(g), []).append((float(r), float(v), float(f)))
    return data


def shape(rt, rp, t1, r1):
    """model.rs torque curve 1 - k (r - rt)^2: k_hi puts the power peak (r x T) at rp, k_lo gives T(r1) = t1"""
    k_hi = 1.0 / ((rp - rt) ** 2 + 2 * rp * (rp - rt))
    k_lo = (1.0 - t1) / (rt - r1) ** 2
    return lambda r: 1.0 - (k_lo if r < rt else k_hi) * (r - rt) ** 2


def build():
    data = load()
    cars = []
    for m, (name, fb, acc, gears, box, idle, red, dial, note, rt, rp, t1) in CARS.items():
        tc = shape(rt, rp, t1, 1000 / red)
        car = dict(id=m, name=name, box=box, note=note, idle=idle, redline=red, dial=dial, levels=[])
        for lvl in range(4):
            f = fb + 200 * lvl
            vd = f * 0.06
            pcap = 2 * f * vd / 3.6                         # W: the power ceiling of the game now
            rpms = list(range(1000, red + 1, 50))
            raw = [r / red * tc(r / red) for r in rpms]     # power shape
            k = pcap / max(raw)
            real = [[rpm, round(k * p / HP, 1), round(k * p / (rpm * math.pi / 30), 1)] for rpm, p in zip(rpms, raw)]
            # game now: best wheel power at each rpm over the gears the car can reach
            best = {}
            for g, rows in data[(m, lvl)].items():
                for r, v, force in rows:
                    if v <= vd + 0.01:
                        rpm = round(r * red)
                        best[rpm] = max(best.get(rpm, 0), 2 * force * v / 3.6)
            now = [[rpm, round(p / HP, 1)] for rpm, p in sorted(best.items()) if rpm >= 1000]
            per_gear = [round(max((2 * fo * v / 3.6 for r, v, fo in data[(m, lvl)][g] if v <= vd), default=0) / HP)
                        for g in range(1, gears + 1)]
            car["levels"].append(dict(level=lvl, top_kmh=round(vd), real=real, now=now, per_gear=per_gear))
        cars.append(car)
    return cars


def nice(v):
    e = 10 ** math.floor(math.log10(v))
    f = v / e
    return (1 if f <= 1 else 2 if f <= 2 else 5 if f <= 5 else 10) * e


W, H = 520, 262
PL, PR, PT, PB = 40, 44, 22, 28


def svg(car, L, ymax, step):
    red = car["redline"]
    X = lambda x: PL + (x - 1000) / (red - 1000) * (W - PL - PR)
    Y = lambda y: H - PB - y / ymax * (H - PT - PB)
    pts = lambda rows, i: " ".join(f"{X(p[0]):.1f},{Y(p[i]):.1f}" for p in rows)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" data-car="{car["id"]}" data-level="{L["level"]}" '
         f'aria-label="{html.escape(car["name"])} {LEVELS[L["level"]]}: power and torque versus rpm">']
    y = 0
    while y <= ymax + 1e-6:
        o.append(f'<line x1="{PL}" x2="{W - PR}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" class="g"/>'
                 f'<text x="{PL - 6}" y="{Y(y) + 3.5:.1f}" text-anchor="end" class="t">{y:g}</text>')
        y += step
    xs = 1000 if red > 6000 else 500
    for x in range(1000, red + 1, xs):
        o.append(f'<text x="{X(x):.1f}" y="{H - PB + 14}" text-anchor="middle" class="t">{x}</text>')
    o.append(f'<text x="4" y="10" class="t">hp · Nm</text><text x="{W - PR}" y="{H - 2}" text-anchor="end" class="t">rpm</text>'
             f'<line x1="{PL}" x2="{W - PR}" y1="{H - PB}" y2="{H - PB}" class="a"/>')
    o.append(f'<polyline class="now" points="{pts(L["now"], 1)}"/>')
    o.append(f'<polyline class="nm" points="{pts(L["real"], 2)}"/>')
    o.append(f'<polyline class="hp" points="{pts(L["real"], 1)}"/>')
    e = L["real"][-1]
    o.append(f'<text x="{X(e[0]) + 5:.1f}" y="{Y(e[1]) + 3.5:.1f}" class="d">hp</text>'
             f'<text x="{X(e[0]) + 5:.1f}" y="{Y(e[2]) + 3.5:.1f}" class="d">Nm</text>')
    o.append(f'<line class="xh" y1="{PT}" y2="{H - PB}"/><circle class="dh" r="4"/><circle class="dn" r="4"/>'
             f'<rect x="{PL}" y="{PT}" width="{W - PL - PR}" height="{H - PT - PB}" fill="transparent"/></svg>')
    return "".join(o)


def page(cars):
    cards = []
    for car in cars:
        top = max(v for p in car["levels"][3]["real"] for v in p[1:])   # one scale for every level
        step = nice(top / 5)
        ymax = math.ceil(top / step) * step
        h = [f'<div class="card"><h2>{html.escape(car["name"])}</h2><div class="meta">{car["box"]} · {car["note"]} · '
             f'idle {car["idle"]} · redline <b>{car["redline"]}</b> · dial to {car["dial"]} rpm</div>']
        for L in car["levels"]:
            hp = max(L["real"], key=lambda p: p[1])
            nm = max(L["real"], key=lambda p: p[2])
            h.append(f'<div class="lv lv{L["level"]}"><p class="peaks">Peak <b>{hp[1]:.0f} hp</b> at {hp[0]} rpm · '
                     f'<b>{nm[2]:.0f} Nm</b> at {nm[0]} rpm · top speed {L["top_kmh"]} km/h</p>'
                     + svg(car, L, ymax, step) + "</div>")
        cards.append("".join(h) + "</div>")
    rows = []
    for car in cars:
        for L in car["levels"]:
            hp = max(L["real"], key=lambda p: p[1])
            nm = max(L["real"], key=lambda p: p[2])
            first = L["level"] == 0
            revs = f'{car["idle"]} / {car["redline"]} / {car["dial"]}' if first else ""
            rows.append(f'<tr><td>{car["name"] if first else ""}</td><td>{revs}</td>'
                        f'<td>{LEVELS[L["level"]]}</td><td>{L["top_kmh"]} km/h</td><td>{hp[1]:.0f}</td><td>{hp[0]}</td>'
                        f'<td>{nm[2]:.0f}</td><td>{nm[0]}</td><td>{", ".join(map(str, L["per_gear"]))}</td></tr>')
    data = {c["id"]: {"name": c["name"], "levels": [{"real": L["real"], "now": L["now"]} for L in c["levels"]],
                      "redline": c["redline"]} for c in cars}
    return (PAGE.replace("__CARDS__", "\n".join(cards)).replace("__ROWS__", "\n".join(rows))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))).replace("__GEOM__", json.dumps([W, H, PL, PR, PT, PB])))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Engine Dyno Sheets</title>
<style>
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--hp:#2a78d6;--nm:#eb6834;--now:#898781;--chip:#ebeae4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;
--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--hp:#3987e5;--nm:#d95926;--now:#8f8e87;--chip:#2c2c2a}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);--hp:#3987e5;--nm:#d95926;--now:#8f8e87;--chip:#2c2c2a}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 40px}h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--ink2);margin:0 0 12px;max-width:900px}
.bar{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin:4px 0 14px}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--surface)}
.seg label{color:var(--ink2);padding:6px 12px;cursor:pointer;user-select:none}
input.r{position:absolute;opacity:0;pointer-events:none}
#r0:checked~.bar label[for=r0],#r1:checked~.bar label[for=r1],#r2:checked~.bar label[for=r2],#r3:checked~.bar label[for=r3]
{background:var(--chip);color:var(--ink);font-weight:600}
input.r:focus-visible~.bar .seg{outline:2px solid var(--hp);outline-offset:2px}
.lv{display:none}#r0:checked~.grid .lv0,#r1:checked~.grid .lv1,#r2:checked~.grid .lv2,#r3:checked~.grid .lv3{display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2)}.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:18px;height:0;border-top:2px solid;display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.card h2{font-size:16px;margin:0}.meta{color:var(--ink2);font-size:12.5px;margin:2px 0 6px}
.peaks{font-size:12.5px;color:var(--ink2);margin:0 0 4px}.peaks b,.meta b{color:var(--ink);font-weight:600}
svg{width:100%;height:auto;display:block;overflow:visible}
svg .g{stroke:var(--grid)}svg .a{stroke:var(--axis)}svg .t{font-size:10px;fill:var(--muted)}svg .d{font-size:10.5px;fill:var(--ink2)}
svg polyline{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
svg .hp{stroke:var(--hp)}svg .nm{stroke:var(--nm)}svg .now{stroke:var(--now);stroke-width:1.5;stroke-dasharray:5 4}
svg .xh{stroke:var(--muted);stroke-dasharray:3 3;visibility:hidden}
svg .dh,svg .dn{stroke:var(--surface);stroke-width:2;visibility:hidden}svg .dh{fill:var(--hp)}svg .dn{fill:var(--nm)}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;
padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;z-index:9}
table{border-collapse:collapse;width:100%;background:var(--surface);font-size:13px}
th,td{padding:5px 8px;border-bottom:1px solid var(--grid);text-align:right}th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:600}details{margin-top:18px}summary{cursor:pointer;color:var(--ink2);font-weight:600}
.note{color:var(--ink2);font-size:12.5px;margin-top:10px;max-width:900px}
@media (max-width:540px){.grid{grid-template-columns:1fr}}
</style></head><body><main>
<h1>City Racing RE - engine dyno sheets</h1>
<p class="sub">Power and torque at the wheels against engine speed, like a dyno sheet. Solid lines are the
<b>realistic engine curves I propose</b> (not in the game yet), with the same peak power as the game now. The dashed
line is what the game gives you <b>today</b>: the most power at that rpm in any gear.</p>
<input class="r" type="radio" name="lv" id="r0" checked><input class="r" type="radio" name="lv" id="r1">
<input class="r" type="radio" name="lv" id="r2"><input class="r" type="radio" name="lv" id="r3">
<div class="bar"><div class="seg" role="group" aria-label="Engine upgrade"><label for="r0">Stock</label><label for="r1">Engine 1</label>
<label for="r2">Engine 2</label><label for="r3">Engine 3</label></div><div class="legend">
<span><i class="sw" style="border-color:var(--hp)"></i>Power (hp)</span>
<span><i class="sw" style="border-color:var(--nm)"></i>Torque (Nm)</span>
<span><i class="sw" style="border-color:var(--now);border-top-style:dashed"></i>Game now, power (hp)</span></div></div>
<div class="grid">
__CARDS__
</div>
<details><summary>Table view: idle / redline / dial, peaks, top speed, and what each gear gives today</summary>
<table><tr><th>Car</th><th>Idle / redline / dial rpm</th><th>Level</th><th>Top speed</th><th>Peak hp</th><th>at rpm</th>
<th>Peak Nm</th><th>at rpm</th><th>Game now: best hp per gear (1st, 2nd, ...)</th></tr>
__ROWS__
</table></details>
<p class="note"><b>Why the dashed line is not an engine.</b> The current drivetrain caps power by road speed, not by rpm
(constant power below the car's top speed), so it goes flat wherever that cap is reached, and low gears of the slower
cars stay under it. The game itself has no rpm, only "share of the redline", so the rpm numbers are ours.
hp and Nm share one number axis. Hover a chart for exact values (in a normal browser).</p>
</main><div class="tip" id="tip"></div>
<script>
const D = __DATA__, [W, H, PL, PR, PT, PB] = __GEOM__, tip = document.getElementById("tip");
function near(pts, rpm){let b=null;for(const p of pts) if(!b||Math.abs(p[0]-rpm)<Math.abs(b[0]-rpm)) b=p;return b}
document.querySelectorAll("svg[data-car]").forEach(svg => {
  const car = D[svg.dataset.car], L = car.levels[+svg.dataset.level], red = car.redline;
  const ys = [...svg.querySelectorAll("text.t")].filter(t => t.getAttribute("text-anchor") === "end" && /^[0-9.]+$/.test(t.textContent));
  const ymax = Math.max(...ys.map(t => +t.textContent));
  const X = x => PL + (x - 1000) / (red - 1000) * (W - PL - PR), Y = y => H - PB - y / ymax * (H - PT - PB);
  const xh = svg.querySelector(".xh"), dh = svg.querySelector(".dh"), dn = svg.querySelector(".dn");
  svg.addEventListener("mousemove", ev => {
    const b = svg.getBoundingClientRect(), px = (ev.clientX - b.left) / b.width * W;
    const rpm = Math.max(1000, Math.min(red, 1000 + (px - PL) / (W - PL - PR) * (red - 1000)));
    const p = near(L.real, rpm), q = near(L.now, rpm);
    dh.setAttribute("cx", X(p[0])); dh.setAttribute("cy", Y(p[1])); dn.setAttribute("cx", X(p[0])); dn.setAttribute("cy", Y(p[2]));
    xh.setAttribute("x1", X(p[0])); xh.setAttribute("x2", X(p[0]));
    for (const el of [xh, dh, dn]) el.style.visibility = "visible";
    tip.innerHTML = `<b>${car.name}</b> · ${p[0]} rpm<div><i class="sw" style="border-color:var(--hp)"></i> ${p[1]} hp</div>
      <div><i class="sw" style="border-color:var(--nm)"></i> ${p[2]} Nm</div>` +
      (q && Math.abs(q[0] - p[0]) < 150 ? `<div><i class="sw" style="border-color:var(--now);border-top-style:dashed"></i> game now ${q[1]} hp</div>` : "");
    tip.style.display = "block"; tip.style.left = Math.min(innerWidth - 180, ev.clientX + 14) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  svg.addEventListener("mouseleave", () => { for (const el of [xh, dh, dn]) el.style.visibility = ""; tip.style.display = "none"; });
});
</script></body></html>"""


def main():
    if "--no-rust" not in sys.argv:
        run_rust()
    cars = build()
    open(OUT, "w", encoding="utf-8").write(page(cars))
    for c in cars:
        L0 = c["levels"][0]
        hp = max(L0["real"], key=lambda p: p[1])
        nm = max(L0["real"], key=lambda p: p[2])
        print(f"{c['name']:15} {c['idle']:4d}/{c['redline']:5d}/{c['dial']:5d}  {hp[1]:5.0f} hp @ {hp[0]:5d}  "
              f"{nm[2]:4.0f} Nm @ {nm[0]:5d}  L3 {max(p[1] for p in c['levels'][3]['real']):4.0f} hp")
    print("written", OUT)


if __name__ == "__main__":
    main()
