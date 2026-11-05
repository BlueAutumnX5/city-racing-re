"""Screenshot the control panel's three tabs in dark mode, then light again (no Apply, prefs untouched)."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import ast, ctypes, ctypes.wintypes as wt, os, struct, sys, time, zlib
WORK = crpaths.WORK
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORK)
import crpanel
crpanel.dpi_aware()
from tkinter import ttk
_src = open(os.path.join(OUT, "crpanel_test.py")).read()
_fn = next(n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name == "grab")
u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
exec(ast.get_source_segment(_src, _fn))

app = crpanel.Panel()
app.geometry("+20+20")


def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def shot(name):
    pump(0.6)
    app.lift(); app.attributes("-topmost", True); pump(0.3)
    grab(app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height(), os.path.join(OUT, name))
    app.attributes("-topmost", False)
    print("shot", name)


nb = [w for w in app.winfo_children() if isinstance(w, ttk.Notebook)][0]
pump(1.0)
for dark, tag in ((True, "dark"), (False, "light")):
    app.dark.set(dark)
    app.apply_theme()
    app.draw_pictures()
    for i, n in enumerate(("settings", "stage2", "pictures")):
        nb.select(i)
        shot(f"panel_{tag}_{n}.png")
    if dark:
        t = crpanel.Tip(app.apply_btn, "tooltip colours test")
        t._show(); pump(0.3)
        print("tip bg", t.top.winfo_children()[0].cget("background"))
        t._hide()
print("prefs file exists:", os.path.exists(crpanel.PREFS))
app.destroy()
