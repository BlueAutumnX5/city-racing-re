"""Drive crpanel.Panel for real (no Apply): screenshots of both tabs, ghost text, sliders, limits,
tooltips, and a Preview (dry run) that must say IDENTICAL for the saved settings."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import ctypes, ctypes.wintypes as wt, os, struct, sys, time, zlib
WORK = crpaths.WORK
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORK)
import crpanel
crpanel.dpi_aware()
import tkinter as tk
from tkinter import ttk

u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32


def grab(x, y, w, h, path):
    hdc = u32.GetDC(0)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    g32.BitBlt(mdc, 0, 0, w, h, hdc, x, y, 0x00CC0020)
    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("a", ctypes.c_long), ("b", ctypes.c_long),
                    ("c", wt.DWORD), ("d", wt.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp); g32.DeleteDC(mdc); u32.ReleaseDC(0, hdc)
    raw = bytearray()
    px = buf.raw
    for row in range(h):
        raw.append(0)
        line = px[row * w * 4:(row + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3] = line[2::4]; rgb[1::3] = line[1::4]; rgb[2::3] = line[0::4]
        raw += rgb
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
          chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def shot(name):
    pump(0.6)
    app.lift(); app.attributes("-topmost", True); pump(0.3)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    grab(x, y, app.winfo_width(), app.winfo_height(), os.path.join(OUT, name))
    app.attributes("-topmost", False)
    print("shot", name, app.winfo_width(), "x", app.winfo_height())


OK = []
def check(label, cond, extra=""):
    OK.append(bool(cond)); print(("OK  " if cond else "BAD ") + label + (("  " + str(extra)) if extra else ""))


app = crpanel.Panel()
app.geometry("+20+20")
pump(1.5)
nb = [w for w in app.winfo_children() if isinstance(w, ttk.Notebook)][0]
shot("panel_settings.png")

# ghost text: empty box -> grey default, value = default
v = app.v_hz
v.var.set(""); v._focus_out(None); pump(0.1)
check("empty physics box shows the ghost default 60, grey, and means 60",
      v.ghost and v.var.get() == "60" and v.entry.cget("fg") == crpanel.GHOST and v.value() == 60.0)
v._focus_in(None)
check("clicking into a ghost box clears it for typing", v.var.get() == "" and not v.ghost)
v.var.set("90"); v._typed(None)
check("typing 90 moves the slider to 90", abs(float(v.scale.get()) - 90) < 1e-6 and v.value() == 90.0)
v.var.set("500"); v._typed(None)
check("typing 500 (above 288) marks the box red and not valid", v.entry.cget("bg") == crpanel.BAD_BG and not v.valid())
v.var.set("abc"); v._typed(None)
check("typing text marks it invalid", not v.valid() and v.value() is None)
v.scale.set(123.4); pump(0.1)
check("dragging the slider snaps to a whole number and fills the box", v.var.get() == "123" and v.valid())

# sliders + the height range following the width
app.v_fov.scale.set(140); pump(0.2)
lo, hi = crpanel.panini.vfov_range(140)
check(f"width 140 -> height range {lo}-{hi}", abs(app.v_vfov.lo - lo) < 1e-9 and abs(app.v_vfov.hi - hi) < 1e-9)
app.v_fov.scale.set(120); pump(0.2)
check("width 120 pulls the height 100 down into range (85.8)", abs(app.v_vfov.value() - 85.8) < 1e-9, app.v_vfov.value())
app.v_vfov.var.set(""); app.v_vfov._focus_out(None)
check("empty height box shows the default clamped to the range", app.v_vfov.value() == 85.8 and app.v_vfov.ghost)
check("the panel notices unapplied changes", "changed" in app.dirty_lbl.cget("text"), app.dirty_lbl.cget("text"))
cfg = app.config()
check("config: hz 123, panini 120/85.8, race + extras present",
      cfg["fixedstep_hz"] == 123 and cfg["panini"]["fov"] == 120 and cfg["panini"]["vfov"] == 85.8
      and "race" in cfg and "extras" in cfg, cfg)

# tooltip
t = crpanel.Tip(app.apply_btn, "test tip")
t._show(); pump(0.2)
check("a tooltip window opens", t.top is not None and t.top.winfo_exists())
t._hide()

# pictures tab with these (unapplied) values, then with things switched off
nb.select(2)
shot("panel_pictures_120.png")
app.load_saved(); pump(0.3)
sv = app.saved()
check("Undo changes restores the saved values", app.v_hz.value() == sv["hz"]
      and app.v_fov.value() == float(sv["panini"]["fov"]) and app.dirty_lbl.cget("text") == "",
      (app.v_hz.value(), sv["hz"]))
shot("panel_pictures_saved.png")

# sharpness calculator at 160 x 100, 2x, on a 1920 x 1080 screen
app.calc_res.set("1920 x 1080"); app.v_fov.set(160); app.v_vfov.set(100); app.v_scale.set(2.0); app._update_calc()
mid = app.calc_lines[1].cget("text")
r = crpanel.panini.centre_ratio(160, 100)
look = f"{1920 / (r / 2):.0f} x {1080 / (r / 2):.0f}"
check(f"calculator: 160x100 at 2x -> middle enlarged 1.34x, looks like {look}, needs 2.68x",
      "enlarged 1.34x" in mid and look in mid and "2.68x" in mid, mid)
check("calculator buttons offer 2.70x or height 116.0",
      "2.70x" in app.calc_ss_btn.cget("text") and "116.0" in app.calc_v_btn.cget("text"),
      (app.calc_ss_btn.cget("text"), app.calc_v_btn.cget("text")))
app.calc_ss_btn.invoke(); pump(0.2)
check("'set supersampling' fills 2.70 and the middle turns PIN-SHARP",
      app.v_scale.value() == 2.7 and "PIN-SHARP" in app.calc_lines[1].cget("text"))
app.v_scale.set(2.0); app._update_calc()
app.calc_v_btn.invoke(); pump(0.2)
check("'set the height' fills 116.0 and the middle turns PIN-SHARP",
      app.v_vfov.value() == 116.0 and "PIN-SHARP" in app.calc_lines[1].cget("text"))
app.v_vfov.set(100); app.v_scale.set(4.0); app._update_calc()
check("at 4x: 7680 x 4320 drawn, the edges warn about shimmer",
      "7680 x 4320" in app.calc_lines[0].cget("text") and "shimmer" in app.calc_lines[2].cget("text"),
      app.calc_lines[2].cget("text"))
app.v_scale.set(2.0); app._update_calc()
nb.select(0)
shot("panel_calculator.png")
nb.select(2)
for n in ("panini", "view", "fixedstep"):
    app.check[n].set(False)
app._changed(); pump(0.3)
shot("panel_pictures_off.png")
app.load_saved(); pump(0.2)

# Stage 2 tab (2026-10-04): every new extra has a row, valued ones a slider + box
nb.select(1)
shot("panel_stage2.png")
s2 = list(crpanel.STAGE2)
check("Stage 2 tab lists " + ", ".join(s2), all(n in app.check and n in app.inst for n in s2))
check("valued Stage 2 extras have sliders: gravity, police sight, evade distance, police count, Milky Way, billboard keep, race reset",
      set(app.v_extra) == {"gravity", "policeeyes", "evade", "morepolice", "milkyway", "boardkeep", "racereset"})
g = app.v_extra["gravity"]
import racemod
SAVED = racemod.load_state()
saved_g = SAVED.get("gravity_ms2", racemod.GRAVITY_DEFAULT)
saved_see = SAVED.get("police_see_m", racemod.POLICE_SEE_DEFAULT)
check(f"gravity box shows {saved_g:g} (the saved value)", abs(g.value() - saved_g) < 1e-9, g.value())
mp = app.v_extra["morepolice"]
mp.var.set("30"); mp._typed(None)
check("police count 30 (above 20) is red and invalid", not mp.valid() and mp.entry.cget("bg") == crpanel.BAD_BG)
mp.var.set(""); mp._focus_out(None)
check("empty police count = ghost default 8", mp.ghost and mp.value() == 8.0)
s2_all = [n for n in s2 if n != "policefix"]       # policefix and smartpolice exclude each other
for n in s2:
    app.check[n].set(n in s2_all)
g.var.set("3.71"); g._typed(None)
app._changed(); pump(0.2)
d = app.dirty_lbl.cget("text")
# 2026-10-04: once the player runs EVERY Stage 2 extra, "all on" changes no extra - only gravity
extras_differ = {n for n in s2 if n in SAVED.get("extras", [])} != set(s2_all)
check("the panel notices the Stage 2 changes" + ("" if extras_differ else " (gravity only: every extra is already on)"),
      ("extras" in d) == extras_differ and "gravity" in d, d)
cfg = app.config(dry=True)
check(f"config carries gravity 3.71, sight {saved_see:g}, count 8 and all Stage 2 extras",
      cfg["gravity_ms2"] == 3.71 and cfg["police_see_m"] == saved_see and cfg["police_max"] == 8
      and all(n in cfg["extras"] for n in s2_all), cfg)
app.log.configure(state="normal"); app.log.delete("1.0", "end"); app.log.configure(state="disabled")
app.run_setup(dry=True)
end = time.time() + 120
while app.busy and time.time() < end:
    pump(0.2)
log = app.log.get("1.0", "end")
check("Preview with every Stage 2 extra on builds and self-checks OK (nothing written)",
      "DRY RUN" in log and "self-check OK" in log and "different from" in log,
      [l for l in log.splitlines() if "DRY RUN" in l or "REFUSED" in l])
shot("panel_stage2_preview.png")
nb.select(2)
shot("panel_pictures_adaptive.png")
nb.select(1)
app.load_saved(); pump(0.3)
check("Undo puts the Stage 2 boxes back",
      all(app.check[n].get() == (n in SAVED.get("extras", [])) for n in s2) and abs(g.value() - saved_g) < 1e-9)

# Preview = dry run through racemod setup: the saved settings must rebuild the installed exe exactly
nb.select(0)
app.run_setup(dry=True)
end = time.time() + 120
while app.busy and time.time() < end:
    pump(0.2)
log = app.log.get("1.0", "end")
check("Preview with the saved settings says IDENTICAL to the installed game.exe", "IDENTICAL" in log,
      [l for l in log.splitlines() if "DRY RUN" in l])
shot("panel_preview_log.png")
print(f"\n{sum(OK)}/{len(OK)} checks passed")
app.destroy()
