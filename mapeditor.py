r"""City Racing Map Editor - paint the AI navigation field and traffic density.

This edits the NAVIGATION data only. It changes where traffic may drive, how far from the
centreline it drives, and how dense it is. It does NOT move any 3D geometry - the roads you
see are unchanged; you are editing the invisible layer the AI follows.

Files edited, both inside World.pak:
    Data/Landscape/GlobalRoute.dat       600x600 x 48-byte records
        0x00 u32   kind   0 = nothing, 1 = drivable area,
                          2 = road surface, 3 = driving line A, 4 = driving line B
        0x04 f32   X      cell centre, or a snapped road point for kind 3/4
        0x08 f32   height
        0x0C f32   Z
        0x10..0x1C u32x4  up to FOUR pointers to neighbouring line cells
        0x20 u8    degree - how many of those four pointers are used
        0x21 u8    waypoint id
        0x22 u8    progress along route 0..100
        0x24 u16x2 (column, row)

Every street is stored as three parallel tracks, measured across a road as  3 | 2 2 2 | 4:
kind 3 and kind 4 are the two driving lines (opposite sides of the road) and kind 2 is the
road surface between them. Kinds 3 and 4 are one cell wide and NEVER touch each other.

The adjacency at 0x10..0x1C is rebuilt by the game every time it loads the file
(game.exe at 0x0042be15 for kind 3, 0x0042bf13 for kind 4): it zeroes the degree byte,
scans the 3x3 neighbourhood, and appends a pointer for each same-kind neighbour.

    THAT LOOP HAS NO BOUNDS CHECK.

There are only four pointer slots, so a line cell with a FIFTH same-kind neighbour writes
over its own degree/waypoint/progress bytes, and a sixth writes hundreds of bytes into
unrelated records. A blob of kind 3 would corrupt the route array. The same loop indexes
row-1 and row+1 without clamping, so a line cell on the outermost row or column reads off
the end of the array. This editor therefore refuses both cases - see max_links() and
BORDER below - which is why the driving lines are drawn with a one-cell LINE tool rather
than the circular brush used for the other layers.
    Data/Landscape/TrafficDensityMap.dat 200x200 u8  (3 route cells per density cell)
        A plain 0..255 scale: 0 = no traffic, 255 = maximum (the city centre).
        There are NO sentinel values. Verified by measuring road coverage under each
        density band: 0 -> 0.09 road cells, 1-99 -> 3.04, 100-199 -> 7.40,
        200-254 -> 8.18, 255 -> 9.00 out of 9. Monotonic, so 255 is simply the busiest.

World space: X = -1198 + 4*col, Z = 1198 - 4*row; both axes span -1198..1198.

Run with:  pythonw mapeditor.py
"""

import base64
import os
import struct
import subprocess
import sys
import tkinter as tk
import zlib
from tkinter import ttk, messagebox


def png_bytes(w, h, rgb):
    """Encode raw RGB to PNG. Tk 9.0 no longer accepts PPM via data=, only PNG."""
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1))
            + chunk(b"IEND", b""))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets
import crpak
from cartuner import Tooltip

SIDE, REC = 600, 48
DSIDE = 200
VIEW = 640          # on-screen viewport; the map itself is SIDE x SIDE x zoom
ROUTE = "Data/Landscape/GlobalRoute.dat"
DENS = "Data/Landscape/TrafficDensityMap.dat"

KIND_COL = {0: (26, 32, 44), 1: (74, 124, 186), 2: (110, 190, 130),
            3: (240, 196, 92), 4: (238, 118, 86)}

# The route array is a static global inside game.exe, so the pointers stored in the file
# are real runtime addresses. Solved from the file itself: of 35,292 pointers, all 35,292
# decode as GR_BASE + cellIndex*48 and all land on an 8-adjacent same-kind cell.
GR_BASE = 0x01967a20
MAXLINK = 4      # only four pointer slots exist per record
BORDER = 1       # the rebuild loop reads row-1 / row+1 without clamping


def bresenham(a, b):
    """Cells along a straight line. Dragging the mouse skips cells, and a driving line
    with a hole in it is not a line at all, so every gap gets filled in."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    out = []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return out
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe"],
                             capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return "game.exe" in out
    except Exception:
        return False


def load_pair(data_dir):
    e, _, p, _ = crpak.load_archive(data_dir, "World")
    gr = dn = None
    for (n, _, _), pl in zip(e, p):
        if n == ROUTE:
            gr = bytearray(pl)
        elif n == DENS:
            dn = bytearray(pl)
    return gr, dn


class Editor:
    def __init__(self, root):
        self.root = root
        root.title("City Racing - Map / Navigation Editor")
        self.gr, self.dn = load_pair(assets.LIVE)
        self.pristine = load_pair(assets.STOCK)
        self.dirty = False
        self.layer = tk.StringVar(value="route")
        self.tool = tk.StringVar(value="road_on")
        self.brush = tk.IntVar(value=4)
        self.dens_val = tk.IntVar(value=200)
        self.lane_scale = tk.DoubleVar(value=1.5)
        self.zoom = tk.IntVar(value=1)
        self.last = None        # previous cell of the current line stroke
        self.refused = 0        # cells the graph-safety check turned down
        self._build()
        self.redraw()

    # ------------------------------------------------------------- data access
    def kind(self, c, r):
        return struct.unpack_from("<I", self.gr, (r * SIDE + c) * REC)[0]

    def set_kind(self, c, r, k):
        struct.pack_into("<I", self.gr, (r * SIDE + c) * REC, k)

    def waypoint(self, c, r):
        return self.gr[(r * SIDE + c) * REC + 33]

    def deviation(self, c, r):
        o = (r * SIDE + c) * REC
        x, _, z = struct.unpack_from("<3f", self.gr, o + 4)
        return x - (-1198 + 4 * c), z - (1198 - 4 * r)

    def scale_deviation(self, c, r, s):
        o = (r * SIDE + c) * REC
        x, h, z = struct.unpack_from("<3f", self.gr, o + 4)
        cx, cz = -1198 + 4 * c, 1198 - 4 * r
        dx, dz = x - cx, z - cz
        if abs(dx) < 1e-4 and abs(dz) < 1e-4:
            return False
        struct.pack_into("<3f", self.gr, o + 4, cx + dx * s, h, cz + dz * s)
        return True

    # ------------------------------------------------------- the driving-line graph
    def line_nbrs(self, c, r, k):
        """Exactly what game.exe's rebuild loop does: walk the 3x3 block in row-major
        order, skip the centre, keep every same-kind neighbour. Scanning in this order
        is why every pointer list in the stock file is sorted ascending - all 17,136."""
        out = []
        for rr in range(r - 1, r + 2):
            for cc in range(c - 1, c + 2):
                if (cc, rr) == (c, r):
                    continue
                if 0 <= cc < SIDE and 0 <= rr < SIDE and self.kind(cc, rr) == k:
                    out.append(rr * SIDE + cc)
        return out

    def max_links(self, c, r):
        """True if this cell would hand the game more neighbours than it has slots for."""
        k = self.kind(c, r)
        return k in (3, 4) and len(self.line_nbrs(c, r, k)) > MAXLINK

    def relink(self, c, r):
        """Rewrite one cell's degree + pointers. The game recomputes these on load, so
        this only keeps the file self-consistent - but it costs nothing and means the
        file always describes the same graph the game will build."""
        o = (r * SIDE + c) * REC
        k = self.kind(c, r)
        struct.pack_into("<4I", self.gr, o + 16, 0, 0, 0, 0)
        if k in (3, 4):
            nb = self.line_nbrs(c, r, k)[:MAXLINK]
            for i, j in enumerate(nb):
                struct.pack_into("<I", self.gr, o + 16 + 4 * i, GR_BASE + j * REC)
            self.gr[o + 32] = len(nb)
        else:
            self.gr[o + 32] = 0

    def relink_block(self, c, r):
        """Any kind change rewires the cell AND its neighbours, in both directions -
        the ones that just gained a link and the ones that just lost one."""
        for rr in range(r - 1, r + 2):
            for cc in range(c - 1, c + 2):
                if 0 <= cc < SIDE and 0 <= rr < SIDE:
                    self.relink(cc, rr)

    def set_line(self, c, r, k, prev):
        """Place one driving-line cell, or refuse if it would overload the graph."""
        if not (BORDER <= c < SIDE - BORDER and BORDER <= r < SIDE - BORDER):
            self.refused += 1
            return False
        if self.kind(c, r) == k:
            return False
        o = (r * SIDE + c) * REC
        snap = bytes(self.gr[o:o + REC])
        self.set_kind(c, r, k)
        # Sit the line on the cell centre. 517 stock line cells do exactly this, so a
        # zero offset is a state the game already ships and handles.
        struct.pack_into("<f", self.gr, o + 4, -1198 + 4 * c)
        struct.pack_into("<f", self.gr, o + 12, 1198 - 4 * r)
        if k == 4:
            self.gr[o + 33] = 255        # every one of the 8,110 stock kind-4 cells
            self.gr[o + 34] = 80         # ... carries exactly these two values
        elif prev is not None and self.kind(*prev) == 3:
            po = (prev[1] * SIDE + prev[0]) * REC
            self.gr[o + 33] = self.gr[po + 33]    # carry the route odometer along
            self.gr[o + 34] = self.gr[po + 34]
        if self.max_links(c, r) or any(
                self.max_links(j % SIDE, j // SIDE)
                for j in self.line_nbrs(c, r, k)):
            self.gr[o:o + REC] = snap    # roll back, untouched
            self.refused += 1
            return False
        self.relink_block(c, r)
        return True

    def dens(self, c, r):
        return self.dn[(r // 3) * DSIDE + (c // 3)]

    def set_dens(self, c, r, v):
        # 0 = no traffic, 255 = maximum. Verified: mean road coverage under each density
        # band rises monotonically 0.09 -> 3.04 -> 7.40 -> 8.18 -> 9.00, so 255 is simply
        # the busiest value, NOT a "blocked" sentinel. Every cell is paintable.
        i = (r // 3) * DSIDE + (c // 3)
        v = max(0, min(255, int(v)))
        if self.dn[i] == v:
            return False
        self.dn[i] = v
        return True

    # ---------------------------------------------------------------- rendering
    def pixel(self, c, r):
        L = self.layer.get()
        if L == "route":
            return KIND_COL.get(self.kind(c, r), (255, 0, 255))
        if L == "density":
            v = self.dens(c, r)
            if v == 0:
                return (22, 26, 36)             # no traffic
            # heat ramp: blue (quiet) -> yellow (busy) -> red (maximum)
            t = v / 255.0
            if t < 0.5:
                u = t * 2
                return (int(40 + 200 * u), int(70 + 150 * u), int(200 - 140 * u))
            u = (t - 0.5) * 2
            return (int(240 - 20 * u), int(220 - 180 * u), int(60 - 20 * u))
        # lane deviation
        k = self.kind(c, r)
        if k == 0:
            return (20, 24, 34)
        dx, dz = self.deviation(c, r)
        m = min(1.0, (dx * dx + dz * dz) ** 0.5 / 4.0)
        g = int(60 + 195 * m)
        return (g, int(60 + 80 * m), 255 - g)

    def redraw(self):
        buf = bytearray()
        for r in range(SIDE):
            for c in range(SIDE):
                buf += bytes(self.pixel(c, r))
        self.base = tk.PhotoImage(data=base64.b64encode(png_bytes(SIDE, SIDE, buf)))
        self.apply_zoom()
        self.status.set(f"{'*modified* ' if self.dirty else ''}layer: {self.layer.get()}")

    def apply_zoom(self):
        """PhotoImage.zoom() scales by an integer factor in C, so this stays instant even
        at 6x - far faster than re-encoding a 3600x3600 PNG."""
        z = self.zoom.get()
        self.disp = self.base.zoom(z) if z > 1 else self.base
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.disp)
        self.canvas.configure(scrollregion=(0, 0, SIDE * z, SIDE * z))
        self.zlbl.config(text=f"{z}x")

    def on_wheel_zoom(self, ev):
        z = max(1, min(8, self.zoom.get() + (1 if ev.delta > 0 else -1)))
        if z != self.zoom.get():
            self.zoom.set(z)
            self.apply_zoom()

    def cell_at(self, ev):
        z = self.zoom.get()
        return (int(self.canvas.canvasx(ev.x) // z),
                int(self.canvas.canvasy(ev.y) // z))

    def touch(self, c, r):
        if 0 <= c < SIDE and 0 <= r < SIDE:
            col = "#%02x%02x%02x" % self.pixel(c, r)
            self.base.put(col, (c, r))
            z = self.zoom.get()
            if z > 1:       # at 1x, disp IS base, so it is already updated
                self.disp.put(col, to=(c * z, r * z, c * z + z, r * z + z))

    # ------------------------------------------------------------------ widgets
    def _build(self):
        wrap = ttk.Frame(self.root, padding=8)
        wrap.pack(fill="both", expand=True)

        cf = ttk.Frame(wrap)
        cf.grid(row=0, column=0, rowspan=2, sticky="nw")
        self.canvas = tk.Canvas(cf, width=VIEW, height=VIEW, bg="#10141c",
                                highlightthickness=1, highlightbackground="#444",
                                cursor="crosshair", scrollregion=(0, 0, SIDE, SIDE))
        hs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        vs = ttk.Scrollbar(cf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_paint)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))
        self.canvas.bind("<Shift-MouseWheel>",
                         lambda e: self.canvas.xview_scroll(-e.delta // 120, "units"))
        self.canvas.bind("<Control-MouseWheel>", self.on_wheel_zoom)
        Tooltip(self.canvas, "The city, seen from above",
                "This is City Racing's whole map - the islands, the bridges between them, "
                "and the big road grid in the bottom right.\n\n"
                "What you are editing here is the INVISIBLE guide that computer-controlled "
                "cars follow. Nothing you paint changes the roads, buildings or scenery "
                "you see while playing. The city looks exactly the same - only the "
                "behaviour of the other cars changes.\n\n"
                "Click and drag to paint. Move the mouse anywhere and the line under the "
                "map tells you what is in that spot.\n\n"
                "Nothing is saved until you press APPLY, so paint as much as you like "
                "first.", delay=700, wrap=440)

        side = ttk.Frame(wrap, padding=(12, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")

        hdr = ttk.Label(side, text="View", font=("Segoe UI", 9, "bold"),
                        cursor="question_arrow")
        hdr.pack(anchor="w")
        Tooltip(hdr, "View - what the picture is showing you",
                "Pick which information the map picture shows. This only changes what you "
                "LOOK at - it does not change what your brush paints. You can watch the "
                "density view while painting roads, for example.")

        for val, txt, tip_title, tip in (
            ("route", "Route kind", "Route kind - where cars are ALLOWED to drive",
             "This is the invisible map the computer-controlled cars follow. It is not the "
             "road you see when playing - it is a permission map that says where traffic "
             "is allowed to go.\n\n"
             "BLACK  - cars will never drive here (mostly water)\n"
             "BLUE   - open ground cars are allowed to cross\n"
             "GREEN  - road surface, the middle of a street\n"
             "YELLOW - a driving line: the exact path cars steer along\n"
             "ORANGE - the second driving line, the other side of the road\n\n"
             "Zoom in to 6x on any street and you will see the pattern: a yellow line, "
             "a green middle, an orange line. Every road in the game is built that way, "
             "and yellow and orange never touch.\n\n"
             "Yellow and orange are the ones that actually steer cars. Blue and green "
             "only say 'this is road'.\n\n"
             "Editing this does NOT move any road you can see. The city looks identical. "
             "It only changes where cars decide to go."),
            ("density", "Traffic density", "Traffic density - how busy each area is",
             "How many cars hang around in each part of the city.\n\n"
             "DARK   - no traffic (no road there)\n"
             "BLUE   - quiet back streets\n"
             "YELLOW - busy main roads\n"
             "RED    - maximum. This is the city centre - the busiest streets in the "
             "game\n\n"
             "It is a simple 0 to 255 scale, 0 = empty, 255 = as busy as it gets. Every "
             "cell can be painted.\n\n"
             "This grid is chunkier than the road one, so density edits always look a bit "
             "blocky compared to road edits.\n\n"
             "Raising density where there is no road does nothing useful - cars still need "
             "a road to drive on."),
            ("lane", "Lane deviation", "Lane deviation - where on the road cars sit",
             "Shows whether cars drive down the dead centre of a road or off to one side. "
             "Brighter means they sit further from the middle.\n\n"
             "Only the green/yellow/orange roads have this - those are the ones where the "
             "game tracks an exact spot on the tarmac rather than just 'somewhere in this "
             "square'."),
        ):
            rb = ttk.Radiobutton(side, text=txt, value=val, variable=self.layer,
                                 command=self.redraw, cursor="question_arrow")
            rb.pack(anchor="w")
            Tooltip(rb, tip_title, tip)

        zf = ttk.Frame(side)
        zf.pack(anchor="w", pady=(8, 0))
        zlab = ttk.Label(zf, text="Zoom", cursor="question_arrow")
        zlab.grid(row=0, column=0, sticky="w")
        Tooltip(zlab, "Zoom - make the map bigger",
                "The whole city is 600 squares across, so at 1x each square is a single "
                "pixel - fine for an overview, hopeless for detail work.\n\n"
                "Zoom in to 4x or 6x and each square becomes a proper block you can aim "
                "at. Use the scrollbars, the mouse wheel, or Shift+wheel to move around.\n\n"
                "Shortcut: hold Ctrl and roll the mouse wheel over the map.")
        for i, z in enumerate((1, 2, 3, 4, 6, 8)):
            ttk.Radiobutton(zf, text=f"{z}x", value=z, variable=self.zoom,
                            command=self.apply_zoom, width=4
                            ).grid(row=1 + i // 3, column=i % 3, sticky="w")
        self.zlbl = ttk.Label(zf, text="1x", foreground="#1864ab")
        self.zlbl.grid(row=0, column=1, columnspan=2, sticky="w", padx=(6, 0))

        ttk.Separator(side).pack(fill="x", pady=8)
        hdr = ttk.Label(side, text="Tool", font=("Segoe UI", 9, "bold"),
                        cursor="question_arrow")
        hdr.pack(anchor="w")
        Tooltip(hdr, "Tool - what your brush does",
                "Pick what happens when you click or drag on the map. The brush is a "
                "circle; its size is set by 'Brush radius' below.\n\n"
                "Nothing reaches the game until you press APPLY, so experiment freely.")

        for val, txt, tip_title, tip in (
            ("road_on", "Road ON  (kind 1)", "Road ON - let cars drive somewhere new",
             "Paint to ALLOW traffic somewhere it currently never goes.\n\n"
             "Use it to widen a street so more cars fit, or to open up an area the game "
             "ignores today.\n\n"
             "One thing to expect: cars also follow a route in order, a bit like numbered "
             "checkpoints. Painting road in the middle of nowhere marks it as allowed, but "
             "cars have no reason to drive there unless it joins onto a road they already "
             "use. Widening an existing street works much better than inventing one."),
            ("road_off", "Road OFF (kind 0)", "Road OFF - block traffic",
             "Paint to BLOCK traffic. Close a street, shut a bridge, empty out a whole "
             "neighbourhood.\n\n"
             "Worth knowing: the cars you RACE against follow this same map, not just "
             "ordinary traffic. Close a bridge and your opponents have to go round too."),
            ("surface2", "Road surface (green)", "Road surface - the middle of the road",
             "Paints the GREEN band: the strip of tarmac between the two driving lines.\n\n"
             "Every street in the game is stored as three stripes side by side - a yellow "
             "line, a green middle, and an orange line. Green is the bit in between.\n\n"
             "This is the safe one. Green carries no steering information, so you can "
             "paint it with a fat brush and nothing can go wrong. Use it to widen a road "
             "before you draw driving lines down it."),
            ("line3", "Draw driving line (yellow)", "Yellow line - cars drive ALONG this",
             "This is the big one. YELLOW is an actual driving line: the exact path cars "
             "steer along, including the cars you race against.\n\n"
             "Draw one across a field, a car park or a beach and traffic will genuinely "
             "drive there - straight off the tarmac. That is how you get races that leave "
             "the road network.\n\n"
             "It draws a LINE, not a blob: click, then drag, and you lay a single-cell "
             "trail behind the mouse. Gaps from a fast drag are filled in automatically.\n\n"
             "Start your line ON an existing yellow line. A line floating in the middle of "
             "nowhere is legal but pointless - cars have no way to reach it. Joining it "
             "onto the network at both ends turns it into a real shortcut.\n\n"
             "WHY IT IS A LINE AND NOT A BRUSH: the game gives each line cell room for "
             "exactly four connections. A round brush would make cells with eight, and "
             "the game writes the extra ones straight over its own data. The editor "
             "refuses any cell that would end up with more than four and tells you how "
             "many it turned down."),
            ("line4", "Draw driving line (orange)", "Orange line - the other side of the road",
             "ORANGE is the second driving line: same idea as yellow, but it is the lane "
             "on the opposite side of the road.\n\n"
             "A normal two-way street in this game is yellow on one side, green tarmac in "
             "the middle, orange on the other. Yellow and orange never touch - there is "
             "always green between them.\n\n"
             "Draw yellow if you just want somewhere new for cars to go. Add orange "
             "alongside it, a cell or two away, if you want proper two-way traffic on "
             "your new road.\n\n"
             "Same rules as yellow: it draws a one-cell line, and the editor refuses any "
             "cell that would get more than four connections."),
            ("dens_set", "Set density", "Set density - make an area busy or quiet",
             "Paint how busy an area is, using the number on the 'Density value' slider "
             "below. High means packed with cars, low means nearly deserted.\n\n"
             "This grid is chunkier than the road grid, so each dab covers a slightly "
             "bigger square than your brush size suggests."),
            ("dens_up", "Density +10", "Density +10 - a bit busier",
             "Makes the area a little busier each time you drag over it.\n\n"
             "Better than 'Set density' when you want a district to get gradually busier "
             "towards the middle, instead of one flat value everywhere."),
            ("dens_down", "Density -10", "Density -10 - a bit quieter",
             "Makes the area a little quieter each time you drag over it. Good for "
             "thinning out a busy district without emptying it completely."),
            ("lane", "Scale lane deviation", "Scale lane deviation - change HOW cars drive",
             "This changes how cars drive, rather than where they are allowed to go.\n\n"
             "Set the 'Lane scale' slider below, then paint over a road:\n\n"
             "  2     cars swing wide, using more of the road\n"
             "  0.5   cars hug the middle more tightly\n"
             "  0     cars drive dead centre, single file\n"
             "  -1    cars drive on the OPPOSITE side of the road\n\n"
             "The -1 is the fun one. It only affects the green/yellow/orange roads, since "
             "those are the ones with an exact driving line to flip."),
        ):
            rb = ttk.Radiobutton(side, text=txt, value=val, variable=self.tool,
                                 cursor="question_arrow")
            rb.pack(anchor="w")
            Tooltip(rb, tip_title, tip)

        ttk.Separator(side).pack(fill="x", pady=8)
        lb = ttk.Label(side, text="Brush radius (cells)", cursor="question_arrow")
        lb.pack(anchor="w")
        Tooltip(lb, "Brush radius - how big your brush is",
                "How wide a circle you paint with.\n\n"
                "Around 4 is about as wide as a big road. 0 paints a single tiny square, "
                "useful for tidying up an edge. 15 or more covers a whole city block at "
                "once.\n\n"
                "The two driving-line tools (yellow and orange) IGNORE this - they always "
                "draw a single-cell line, because that is the only shape the game can "
                "store safely.")
        ttk.Scale(side, from_=0, to=20, variable=self.brush, orient="horizontal",
                  length=170,
                  command=lambda _e: self.blbl.config(
                      text=f"{self.brush.get()}  ({self.brush.get()*4*2+4} world units wide)")
                  ).pack(anchor="w")
        self.blbl = ttk.Label(side, text="4  (36 world units wide)")
        self.blbl.pack(anchor="w")

        lb = ttk.Label(side, text="Density value (0-255)", cursor="question_arrow")
        lb.pack(anchor="w", pady=(8, 0))
        Tooltip(lb, "Density value - how busy, exactly",
                "The busyness level the 'Set density' tool paints. 0 is empty, 255 is the "
                "busiest the game can do.\n\n"
                "For reference, the original game uses roughly:\n"
                "  0       no road, no traffic\n"
                "  12      quiet back street\n"
                "  52      typical road\n"
                "  129     busy main road\n"
                "  255     city centre - the busiest streets in the game\n\n"
                "So painting 255 everywhere makes the whole map as busy as downtown.")
        ttk.Scale(side, from_=0, to=255, variable=self.dens_val, orient="horizontal",
                  length=170,
                  command=lambda _e: self.dlbl.config(text=str(self.dens_val.get()))
                  ).pack(anchor="w")
        self.dlbl = ttk.Label(side, text="200")
        self.dlbl.pack(anchor="w")

        lb = ttk.Label(side, text="Lane scale (-1 mirrors)", cursor="question_arrow")
        lb.pack(anchor="w", pady=(8, 0))
        Tooltip(lb, "Lane scale - how far cars sit from the middle",
                "Used by the 'Scale lane deviation' tool.\n\n"
                "  -1    cars drive on the OTHER SIDE of the road\n"
                "   0    cars drive dead centre\n"
                "   1    no change\n"
                "   2+   cars swing further out than normal\n\n"
                "Why -1 flips them: the game stores each driving spot as a nudge away from "
                "the middle of the road. Flip the nudge to negative and the nudge points "
                "the other way, so the cars end up on the opposite side.")
        ttk.Scale(side, from_=-2.0, to=3.0, variable=self.lane_scale,
                  orient="horizontal", length=170,
                  command=lambda _e: self.llbl.config(
                      text=f"{self.lane_scale.get():.2f}")).pack(anchor="w")
        self.llbl = ttk.Label(side, text="1.50")
        self.llbl.pack(anchor="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        b = ttk.Button(side, text="APPLY to game", command=self.on_apply)
        b.pack(fill="x")
        Tooltip(b, "APPLY to game - save your changes",
                "Writes everything you have painted into the game, then checks the result "
                "is valid before finishing.\n\n"
                "CLOSE CITY RACING FIRST. Windows locks the game's files while it is "
                "running, so this button will refuse and tell you.\n\n"
                "Your other mods are safe: car tuning, textures and 3D models are left "
                "exactly as they are. Only the traffic map changes.")
        b = ttk.Button(side, text="Reload from game", command=self.on_reload)
        b.pack(fill="x", pady=2)
        Tooltip(b, "Reload from game - undo",
                "Throws away everything you have painted since the last APPLY and reloads "
                "what the game currently has.\n\n"
                "This is your undo button. Messed up a stroke? Click here and start again.")
        b = ttk.Button(side, text="Reset to factory", command=self.on_reset)
        b.pack(fill="x")
        Tooltip(b, "Reset to factory - back to the original game",
                "Loads the untouched original traffic map, throwing away every change "
                "including ones you already applied.\n\n"
                "Safe to click just to look: nothing reaches the game until you press "
                "APPLY afterwards.")

        self.status = tk.StringVar()
        ttk.Label(wrap, textvariable=self.status, foreground="#1864ab").grid(
            row=1, column=1, sticky="sw")
        self.hover = tk.StringVar()
        ttk.Label(wrap, textvariable=self.hover, foreground="#555").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(wrap, foreground="#888", justify="left", wraplength=820,
                  text=("You are editing the invisible guide that computer-controlled cars "
                        "follow - not the roads you see. The city will look identical; only "
                        "the traffic behaves differently.\n"
                        "Black = cars never go there.  Blue = open ground.  Green = road "
                        "surface.  YELLOW and ORANGE = the driving lines cars actually "
                        "steer along, one per side of the road.\n"
                        "Yellow and orange are drawn with a one-cell line tool, not the "
                        "brush - click and drag to lay a trail. Draw one across open "
                        "ground and traffic will leave the tarmac and follow it.\n"
                        "Hover over any button or slider for an explanation. Nothing is "
                        "saved until you press APPLY, and close the game before you do.")
                  ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    # ------------------------------------------------------------------ actions
    def on_hover(self, ev):
        c, r = self.cell_at(ev)
        if not (0 <= c < SIDE and 0 <= r < SIDE):
            return
        dx, dz = self.deviation(c, r)
        self.hover.set(
            f"cell ({c},{r})   world X={-1198 + 4*c:.0f} Z={1198 - 4*r:.0f}   "
            f"kind={self.kind(c, r)}  waypoint={self.waypoint(c, r)}  "
            f"density={self.dens(c, r)}  lane offset=({dx:+.2f},{dz:+.2f})")

    def on_press(self, ev):
        self.last = None
        self.on_paint(ev)

    def on_release(self, _ev):
        self.last = None
        if self.refused:
            self.status.set(f"*modified*  layer: {self.layer.get()}   "
                            f"({self.refused} cells refused - see the tooltip)")
            self.refused = 0

    def on_paint(self, ev):
        c0, r0 = self.cell_at(ev)
        t = self.tool.get()

        # The driving lines are one cell wide, so they get a LINE tool, not the brush.
        # Painting them with a disc would hand the game a cell with 8 neighbours and
        # only 4 pointer slots to put them in.
        if t in ("line3", "line4"):
            k = 3 if t == "line3" else 4
            pts = bresenham(self.last, (c0, r0)) if self.last else [(c0, r0)]
            prev, changed = self.last, False
            for p in pts:
                if self.set_line(p[0], p[1], k, prev):
                    changed = True
                prev = p
                self.touch(*p)
            self.last = (c0, r0)
            if changed:
                self.dirty = True
                self.status.set(f"*modified*  layer: {self.layer.get()}")
            return

        rad = self.brush.get()
        changed = False
        for r in range(r0 - rad, r0 + rad + 1):
            for c in range(c0 - rad, c0 + rad + 1):
                if not (0 <= c < SIDE and 0 <= r < SIDE):
                    continue
                if (c - c0) ** 2 + (r - r0) ** 2 > rad * rad:
                    continue
                did = False
                if t in ("road_on", "road_off", "surface2"):
                    want = {"road_on": 1, "road_off": 0, "surface2": 2}[t]
                    if self.kind(c, r) != want:
                        self.set_kind(c, r, want)
                        # this may have erased a driving-line cell, which leaves its
                        # former neighbours pointing at a cell that is no longer a line
                        self.relink_block(c, r)
                        did = True
                elif t == "dens_set":
                    did = self.set_dens(c, r, self.dens_val.get())
                elif t == "dens_up":
                    did = self.set_dens(c, r, self.dens(c, r) + 10)
                elif t == "dens_down":
                    did = self.set_dens(c, r, self.dens(c, r) - 10)
                elif t == "lane":
                    did = self.scale_deviation(c, r, self.lane_scale.get())
                if did:
                    changed = True
                self.touch(c, r)
        if changed:
            self.dirty = True
            self.status.set(f"*modified*  layer: {self.layer.get()}")

    def audit(self):
        """Every kind-3/4 cell the game will load, checked against the two limits its
        own rebuild loop does not check. Cheap - only ~17,000 cells are line cells."""
        over, edge = [], []
        for r in range(SIDE):
            for c in range(SIDE):
                k = self.kind(c, r)
                if k not in (3, 4):
                    continue
                if len(self.line_nbrs(c, r, k)) > MAXLINK:
                    over.append((c, r))
                if not (BORDER <= c < SIDE - BORDER and BORDER <= r < SIDE - BORDER):
                    edge.append((c, r))
        return over, edge

    def on_apply(self):
        if game_running():
            messagebox.showwarning("Game is running",
                                   "Exit City Racing first - World.pak cannot be "
                                   "rewritten while the game has it open.")
            return
        over, edge = self.audit()
        if over or edge:
            messagebox.showerror(
                "Unsafe driving lines - nothing was written",
                f"{len(over)} cell(s) have more than {MAXLINK} connections and "
                f"{len(edge)} sit on the very edge of the map.\n\n"
                "The game would write past the end of its own records while loading "
                "these, which corrupts the map. Nothing has been saved.\n\n"
                + (f"First one: cell {over[0] if over else edge[0]}.\n\n")
                + "Erase it with 'Road surface' or 'Road OFF' and apply again.")
            return
        entries, _, payloads, _ = crpak.load_archive(assets.LIVE, "World")
        names = [n for n, _, _ in entries]
        out = []
        for name, pl in zip(names, payloads):
            if name == ROUTE:
                out.append(bytes(self.gr))
            elif name == DENS:
                out.append(bytes(self.dn))
            else:
                out.append(pl)
        hdr, pak = crpak.build_archive(names, out)
        for ext, blob in (("hdr", hdr), ("pak", pak)):
            dst = os.path.join(assets.LIVE, f"World.{ext}")
            tmp = dst + ".new"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dst)
        e2, stored, _, blob = crpak.load_archive(assets.LIVE, "World")
        ok = stored == len(e2) and e2[-1][1] + e2[-1][2] == len(blob)
        self.dirty = False
        self.status.set(f"APPLIED - World.pak {len(pak):,} bytes, "
                        f"index {'OK' if ok else 'BROKEN'}")
        if not ok:
            messagebox.showerror("Verification failed",
                                 "The rebuilt archive did not verify. "
                                 "Press 'Reset to factory' and apply again.")

    def on_reload(self):
        self.gr, self.dn = load_pair(assets.LIVE)
        self.dirty = False
        self.redraw()

    def on_reset(self):
        self.gr = bytearray(self.pristine[0])
        self.dn = bytearray(self.pristine[1])
        self.dirty = True
        self.redraw()
        self.status.set("reset to factory - press APPLY to write it to the game")


if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    Editor(root)
    root.mainloop()
