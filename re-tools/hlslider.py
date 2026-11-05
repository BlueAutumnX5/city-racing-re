"""Live headlight sliders (2026-10-09, player: "slider so I can change how many cars have these headlights").
Memory only, needs the headlights running (Night Mode (live).bat). Each slider writes when released.
The real sliders come with the racemod build in the RE Control Panel."""
import os, subprocess, sys, tkinter as tk

HL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hllive.py")
FLAGS = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW


def setv(name, value):
    r = subprocess.run([sys.executable, HL, "set", name, str(value)], text=True, capture_output=True,
                       creationflags=FLAGS)
    status.set((r.stdout.splitlines() or [r.stderr.strip()[-200:]])[0])


root = tk.Tk()
root.title("Headlights (live)")
root.geometry("+20+20")
root.attributes("-topmost", True)
status = tk.StringVar(value="drag a slider, release to apply")
for label, name, lo, hi, res, start in (("Cars with headlights", "cars", 1, 16, 1, 16),
                                        ("Brightness (gain)", "gain", 5, 80, 1, 40),
                                        ("Added light - lifts dark asphalt, looks 'snowy' if high (blue)", "blue", 0.0, 0.06, 0.001, 0.008),
                                        ("Texture-keeping light - multiply limit (mmax)", "mmax", 1.0, 7.0, 0.5, 7.0),
                                        ("Crowd compression - lower = many cars add less (tone)", "tone", 0.05, 0.5, 0.01, 0.15),
                                        ("Building/object share of the light (ogain)", "ogain", 0.2, 1.5, 0.05, 0.8),
                                        ("Car paint share of the light (bgain)", "bgain", 0.2, 6.0, 0.1, 3.0),
                                        ("Car paint glow in its own colour (bpaint)", "bpaint", 0.0, 0.05, 0.001, 0.012)):
    tk.Label(root, text=label).pack(anchor="w", padx=10, pady=(10, 0))
    s = tk.Scale(root, from_=lo, to=hi, resolution=res, orient="horizontal", length=420)
    s.set(start)
    s.bind("<ButtonRelease-1>", lambda e, n=name, w=s: setv(n, w.get()))
    s.pack(padx=10)
tk.Label(root, textvariable=status, fg="gray30").pack(anchor="w", padx=10, pady=10)
root.mainloop()
