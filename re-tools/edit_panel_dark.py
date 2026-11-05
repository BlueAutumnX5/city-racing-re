"""One-off edit (2026-10-04 morning): dark mode for crpanel.py (player: "can you make the Control
Panel a Dark Mode?"). A 'Dark mode' switch at the top, remembered in crpanel_prefs.json, first
launch follows the Windows app theme."""
import crpaths
p = crpaths.work(r"crpanel.py")
raw = open(p, "rb").read()
crlf = b"\r\n" in raw
t = raw.decode("utf-8").replace("\r\n", "\n")


def rep(old, new):
    global t
    assert t.count(old) == 1, f"not found exactly once: {old[:90]!r}"
    t = t.replace(old, new)


rep('''GHOST, INK, BAD_BG, OK_BG = "#9a9a9a", "#000000", "#ffe3e3", "#ffffff"
''', '''GHOST, INK, BAD_BG, OK_BG = "#9a9a9a", "#000000", "#ffe3e3", "#ffffff"
PREFS = os.path.join(HERE, "crpanel_prefs.json")
# ---------------------------------------------------------------- light / dark colours
THEMES = {
    "light": dict(bg=None, fg="#000000", small="#555555", field="#ffffff", ghost="#9a9a9a", ink="#000000",
                  bad_bg="#ffe3e3", tip_bg="#fffbe0", tip_fg="#000000", log_bg="#fbfbfb", log_fg="#000000",
                  canvas="#fbfbfb", good="#1b7a1b", bad="#b00020", warn="#b36b00"),
    "dark": dict(bg="#1f2228", fg="#e6e6e6", small="#a8adb5", field="#2b2f37", ghost="#7d828b", ink="#f2f2f2",
                 bad_bg="#5a2a2e", tip_bg="#2f343d", tip_fg="#eeeeee", log_bg="#17191d", log_fg="#d8d8d8",
                 canvas="#1b1e23", good="#5fd068", bad="#ff6b6b", warn="#ffb347",
                 panel="#272b33", border="#3a3f48", accent="#3d7be0", trough="#3a3f48"),
}
# the light-mode drawing colours on the two chart canvases -> their dark-mode stand-ins
CANVAS_DARK = {"#555555": "#b4b8bf", "#9a9a9a": "#8c9099", "#e3e3e3": "#363b44", "#bdbdbd": "#575d67",
               "#111111": "#f0f0f0", "#8a8a8a": "#9da2aa", "black": "#e6e6e6", "#000000": "#e6e6e6"}
TIP_COLOURS = ["#fffbe0", "#000000"]


def windows_dark():
    """True when Windows apps are set to dark (Settings > Personalization > Colors)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def load_prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except Exception:
        return {}


def save_prefs(p):
    try:
        with open(PREFS, "w") as f:
            json.dump(p, f, indent=2)
    except OSError:
        pass
''')
rep('''        tk.Label(t, text=text, justify="left", wraplength=self.wrap, background="#fffbe0",
                 relief="solid", borderwidth=1, font=("Segoe UI", 9), padx=8, pady=6).pack()''',
    '''        tk.Label(t, text=text, justify="left", wraplength=self.wrap, background=TIP_COLOURS[0],
                 foreground=TIP_COLOURS[1], relief="solid", borderwidth=1, font=("Segoe UI", 9),
                 padx=8, pady=6).pack()''')
rep('''        self.custom_chaos = None
        self._styles()
        self._build()
        self.load_saved()''', '''        self.custom_chaos = None
        prefs = load_prefs()
        self.dark = tk.BooleanVar(value=prefs.get("dark", windows_dark()))
        self.T = THEMES["light"]
        self._styles()
        self._build()
        self.apply_theme()
        self.load_saved()''')
rep('''        self.game_lbl = tk.Label(top, text="checking the game...", font=("Segoe UI", 10, "bold"))
        self.game_lbl.pack(side="right")''', '''        self.game_lbl = tk.Label(top, text="checking the game...", font=("Segoe UI", 10, "bold"))
        self.game_lbl.pack(side="right")
        dm = ttk.Checkbutton(top, text="Dark mode", variable=self.dark, command=self._toggle_dark)
        dm.pack(side="right", padx=14)
        Tip(dm, "Dark colours for this window. Remembered for next time.")''')
rep('''                            fg="#b00020" if val else "#1b7a1b")''', '''                            fg=self.T["bad"] if val else self.T["good"])''')
rep('''        self.dirty_lbl = tk.Label(af, text="", font=("Segoe UI", 9, "bold"), fg="#b36b00")''',
    '''        self.dirty_lbl = tk.Label(af, text="", font=("Segoe UI", 9, "bold"), fg=self.T["warn"])''')
rep('''            self._draw_distances()
            self._draw_steps()
        except tk.TclError:
            pass
''', '''            self._draw_distances()
            self._draw_steps()
            if self.dark.get():
                for c in (self.dist, self.steps):
                    self._darken_canvas(c)
        except tk.TclError:
            pass

    def _darken_canvas(self, c):
        """Swap the chart's light-mode greys/black for dark-mode ones (the colours of the data stay)."""
        for item in c.find_all():
            kind = c.type(item)
            for opt in ("fill", "outline"):
                try:
                    v = c.itemcget(item, opt)
                except tk.TclError:
                    continue
                if kind == "text" and opt == "fill" and v in ("", "black", "#000000"):
                    c.itemconfigure(item, fill=CANVAS_DARK["black"])
                elif v in CANVAS_DARK:
                    c.itemconfigure(item, **{opt: CANVAS_DARK[v]})

    def _toggle_dark(self):
        p = load_prefs()
        p["dark"] = bool(self.dark.get())
        save_prefs(p)
        self.apply_theme()
        self.draw_pictures()

    def apply_theme(self):
        """Light = the Windows 'vista' look as before; dark = the 'clam' theme recoloured."""
        global GHOST, INK, BAD_BG, OK_BG
        dark = bool(self.dark.get())
        T = self.T = THEMES["dark" if dark else "light"]
        st = ttk.Style(self)
        try:
            st.theme_use("clam" if dark else "vista")
        except tk.TclError:
            pass
        if dark:
            bg, fg, panel, border, field = T["bg"], T["fg"], T["panel"], T["border"], T["field"]
            st.configure(".", background=bg, foreground=fg, fieldbackground=field, bordercolor=border,
                         lightcolor=panel, darkcolor=bg, troughcolor=T["trough"], focuscolor=T["accent"],
                         selectbackground=T["accent"], selectforeground="#ffffff", insertcolor=fg)
            st.map(".", foreground=[("disabled", "#6c717a")])
            st.configure("TFrame", background=bg)
            st.configure("TLabel", background=bg, foreground=fg)
            st.configure("TLabelframe", background=bg, bordercolor=border)
            st.configure("TLabelframe.Label", background=bg, foreground=fg)
            st.configure("TNotebook", background=bg, bordercolor=border)
            st.configure("TNotebook.Tab", background=panel, foreground=fg, bordercolor=border, padding=(10, 3))
            st.map("TNotebook.Tab", background=[("selected", "#353a44")], foreground=[("selected", "#ffffff")])
            st.configure("TButton", background=panel, foreground=fg, bordercolor=border, padding=(8, 3))
            st.map("TButton", background=[("disabled", bg), ("pressed", "#2f6bd0"), ("active", "#353a44")],
                   foreground=[("disabled", "#6c717a")])
            for w in ("TCheckbutton", "TRadiobutton"):
                st.configure(w, background=bg, foreground=fg, indicatorbackground=field,
                             indicatorforeground=fg, upperbordercolor=border, lowerbordercolor=border)
                st.map(w, background=[("active", bg)], indicatorbackground=[("selected", T["accent"]),
                                                                           ("active", "#353a44")])
            st.configure("TCombobox", fieldbackground=field, background=panel, foreground=fg,
                         arrowcolor=fg, bordercolor=border)
            st.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)],
                   selectbackground=[("readonly", field)], selectforeground=[("readonly", fg)])
            self.option_add("*TCombobox*Listbox.background", field)
            self.option_add("*TCombobox*Listbox.foreground", fg)
            st.configure("Horizontal.TScale", background=T["accent"], troughcolor=T["trough"], bordercolor=border)
            st.configure("Vertical.TScrollbar", background=panel, troughcolor=bg, arrowcolor=fg, bordercolor=border)
        st.configure("Title.TLabel", font=("Segoe UI", 14, "bold"), foreground=T["fg"])
        st.configure("Name.TCheckbutton", font=("Segoe UI", 10, "bold"))
        st.configure("Small.TLabel", font=("Segoe UI", 9), foreground=T["small"])
        st.configure("Apply.TButton", font=("Segoe UI", 10, "bold"))
        root_bg = T["bg"] or ttk.Style(self).lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(background=root_bg)
        GHOST, INK, BAD_BG, OK_BG = T["ghost"], T["ink"], T["bad_bg"], T["field"]
        TIP_COLOURS[:] = [T["tip_bg"], T["tip_fg"]]
        for w in (self.game_lbl, self.dirty_lbl):
            w.configure(background=root_bg)
        self.dirty_lbl.configure(fg=T["warn"])
        if self.running is not None:
            self.game_lbl.configure(fg=T["bad"] if self.running else T["good"])
        self.log.configure(background=T["log_bg"], foreground=T["log_fg"], insertbackground=T["log_fg"])
        self.log.tag_configure("bad", foreground=T["bad"])
        self.log.tag_configure("good", foreground=T["good"])
        for c in (self.dist, self.steps):
            c.configure(background=T["canvas"])
        for ctl in self._values().values():
            ctl.entry.configure(insertbackground=INK, disabledbackground=OK_BG)
            if ctl.ghost:
                ctl.entry.configure(fg=GHOST, bg=OK_BG)
            else:
                ctl.entry.configure(fg=INK, bg=OK_BG if ctl.valid() or not ctl.var.get().strip() else BAD_BG)
''')

out = t.replace("\n", "\r\n") if crlf else t
open(p, "wb").write(out.encode("utf-8"))
print("edited, crlf =", crlf)
