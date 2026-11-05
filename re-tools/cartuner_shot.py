"""Open the Car Tuner (read-only: no button is pressed), screenshot it, close it."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, sys, time, ctypes
sys.path.insert(0, crpaths.WORK)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import tkinter as tk
import cartuner
import ast, struct, zlib, ctypes.wintypes as wt
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crpanel_test.py')).read()
_fn = next(n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name == 'grab')
u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
exec(ast.get_source_segment(_src, _fn))

root = tk.Tk()
app = cartuner.App(root)
root.geometry("+30+30")
end = time.time() + 2
while time.time() < end:
    root.update()
    time.sleep(0.02)
root.lift(); root.attributes("-topmost", True); root.update(); time.sleep(0.3); root.update()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cartuner_awd.png")
grab(root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height(), out)
print("shot", out, root.winfo_width(), root.winfo_height())
root.destroy()
