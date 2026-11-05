# City Racing (GameTop) — reverse-engineering notes

Taken 2026-09-20. Target: `C:\Program Files (x86)\GameTop.com\City Racing Corrupt`
Game: *City Racing*, EA Group (a Russian studio — not Electronic Arts), 2008. `game.exe` v1.0.0.1.

---

## 1. Backup contents

| Path | What |
|---|---|
| `2026-09-20_original-native\` | Full install, 41 files / 78.4 MB. dgVoodoo wrappers and `GLCache\` excluded. |
| `2026-09-20_dgvoodoo-removed\` | The 6 files the user added (preserved, not deleted). |
| `MANIFEST-sha256_2026-09-20.txt` | SHA256 + size + path for every original file. |
| `tools\` | Python analysis scripts (see §6). |

All 41 files were SHA256-verified against the source after copying: **0 mismatches**.

Baseline hashes (first 16 hex):

```
Objects.pak   84884456EA5C5394      752499
Textures.pak  ECA6EB1639F02780    16123708
World.pak     7FC4339EED28C237    47046741
SD.pak        F1E8AD7505D58A14     9264596
game.exe      9F815DE98062A208     1795288
```

---

## 2. Archive format — fully decoded

`Data\` holds four archive pairs: `Objects`, `Textures`, `World`, `SD`. Each is a `.hdr`
index plus a `.pak` blob.

**`.hdr` layout** — records back to back, then a trailing `uint32` entry count:

```
.hdr   = [record][record]...[uint32 entry count LE]
record = [filename bytes XOR 0x80][0x00][uint32 size LE][uint32 offset LE]
```

The trailing 4 bytes are the **file count**, confirmed against every archive:

| Archive | Tail bytes | uint32 | Entries |
|---|---|---|---|
| Objects | `1c 01 00 00` | 284 | 284 ✓ |
| Textures | `50 01 00 00` | 336 | 336 ✓ |
| World | `36 03 00 00` | 822 | 822 ✓ |
| SD | `77 00 00 00` | 119 | 119 ✓ |

It must be **recomputed**, not copied, if files are ever added or removed.

**Obfuscation is XOR 0x80** — a single bit, its own inverse. Applied to filenames in the
`.hdr` and to all 284 `.obj` payloads in `Objects.pak`. Everything else is stored raw
(literal `DDS `/JFIF/`RIFF` magic).

### How it was cracked

1. A 13 KB `.hdr` beside a 752 KB `.pak` is an index, not data. Dump it as hex + ASCII.
2. Every "text" byte was ≥ 0x80. ASCII only occupies 0x00–0x7F, so a uniform high-range run
   is ASCII with the top bit set. `0xC4→'D'`, `0xE1→'a'`, `0xAF→'/'` spells `Data/`.
3. Two DWORDs followed each name. Guessed `[size][offset]` and checked the arithmetic:
   entry 1's offset (996) = entry 0's offset (0) + size (996); entry 2's (3142) = 996 + 2146.
   Unbroken chain.
4. **The proof:** the last entry's `offset + size` equals the `.pak` size *exactly*, on all
   four archives. Any hidden field, alignment rule or misread size would make that drift.

### Consequences

- No compression, no padding, **no checksums** — files may change size freely, since sizes
  are read from the index and nothing validates them.
- A repacker must rewrite the whole `.pak` (offsets are sequential) and regenerate the `.hdr`.
- Structural sanity confirmed on all four archives: **zero** gaps/overlaps, zero duplicate
  names, zero zero-length entries, and no filesystem-hostile characters in any name — so
  extracting to disk and rebuilding from disk is safe.

### Round-trip test: PASSED (2026-09-20)

`tools\crpak.py` rebuilds all four archives **byte-identically** — SHA256 match on both
`.hdr` and `.pak` — in two independent tests:

| Test | What it proves | Result |
|---|---|---|
| `rt-mem` | The format spec itself (index → rebuild, no filesystem involved) | PASS 4/4 |
| `rt-disk` | The real toolchain (extract all 1561 files to disk, repack from them) | PASS 4/4 |

Running both matters: the in-memory test isolates format logic, while the disk test catches
filename/ordering/case problems the first one can't see. The packer is now trusted.

### Contents

| Archive | Entries | Payloads |
|---|---|---|
| `Objects.pak` | 284 | `.obj` — commented text config files, all XOR 0x80 |
| `Textures.pak` | 336 | 69 DDS (DXT3) + 267 JPG, raw |
| `World.pak` | 822 | 647 `.msh` meshes + 175 `.dat`, raw |
| `SD.pak` | 119 | WAV audio, raw |

`Data/Misc/RacersName.obj` is XOR 0x80 like every other `.obj`, but its text is **CP1251** —
it holds Cyrillic racer names beside the English ones, matching the `_EN`/`_RU` texture pairs.

**The 4 `RenderTechniques_00/_11/_14/_20.dat` in `World.pak` are PLAIN text, not obfuscated.**
They are shader / render-technique definitions (`texture texBaseMap1;` …) keyed to the
`[Video]` quality levels in `Game.ini`. Directly editable — a good lever for visual mods.

The other 171 `.dat` are binary, and their names map out the gameplay data:

| Count | File | Likely role |
|---|---|---|
| 149 | `Data/Landscape/<sector>/MeshShape.dat` | per-sector collision / shape |
| 1 each | `AltitudeMap`, `GlobalRoute`, `PlaceColor`, `StaticObjectsPlaceMap`, `TrafficDensityMap`, `WayPointsMap` | terrain height, AI route, traffic density, waypoints |
| 8 + 2 | `Data/Vehicles/NN/MainExtra.dat`, `PoliceExtra.dat` | per-vehicle extra data |
| 3 + 3 | `Interface/Fonts/*/Main.dat`, `Mask.dat` | font metrics + masks |

`TrafficDensityMap` and `WayPointsMap` are interesting targets beyond the original five goals
(traffic manipulation, AI racing lines). `.msh` files open with a `uint32` count then a chunk
table of counts/offsets.

---

## 3. `game.exe` structure

PE32, ImageBase `0x400000`, 4 sections:

```
.text    va=00001000 vs=0016622b  raw=00000400 rs=00166400
.rdata   va=00168000 vs=00027642  raw=00166800 rs=00027800
.data    va=00190000 vs=0216c57c  raw=0018e000 rs=00022a00
.rsrc    va=022fd000 vs=00003150  raw=001b0a00 rs=00003200
```

**Imports — exactly one graphics DLL:**

```
d3d9.dll      Direct3DCreate9
DSOUND.dll    ord#11
WINMM.dll     timeGetTime
KERNEL32(95) USER32(13) GDI32(2) ADVAPI32(3) SHELL32(1) ole32(3)
```

So `D3D8.dll`, `DDraw.dll`, `D3DImm.dll` and `d3drm.dll` are **inert** — nothing imports them.
Only dgVoodoo's `D3D9.dll` was ever load-bearing. (Caveat: this covers static imports; a
runtime `LoadLibrary` wouldn't appear, though it's implausible here.)

**Portable.** All paths relative (`Data/...`, `Save/Profile%02d.sav`, `.\Game.ini`). The only
registry string is `Software\Microsoft\Direct3D` — D3D's own key, not an install path.

---

## 4. Widescreen — the lead

- **No resolution table in the exe.** Tested interleaved `width,height` pairs, separate width
  arrays (struct-of-arrays), and 16-bit variants: zero hits. The apparent `1024`/`768`
  proximity hits are false positives — bit-flag arithmetic (`or eax,0x400`,
  `and ecx,0x30000`) and 1024-byte buffer sizes.
- Therefore `Mode=` in `Game.ini` is an index into runtime `IDirect3D9::EnumAdapterModes`
  results. **A D3D wrapper changes what that index means** — which is why a native baseline
  matters before decoding it. (`Mode=21` was chosen while dgVoodoo was active; if the game
  misbehaves natively, reset `Mode` first.)
- **Exactly one 4:3 constant in the binary**: `1.3333334` = `ab aa aa 3f` at
  **raw 0x00167ff0** (RVA 0x001697f0, VA 0x005697f0, `.rdata`).
- **Referenced exactly once**, at raw 0x00033EDE (RVA 0x00034ADE, `.text`):

  ```
  f3 0f 5c 05 84 8d 56 00    subss  xmm0, [0x00568d84]
  f3 0f 59 05 f0 97 56 00    mulss  xmm0, [0x005697f0]   <- 4/3
  ```

- **No 16:9 constant anywhere** — `1.7777778` has zero occurrences. Textbook fingerprint of a
  game hardcoding aspect instead of deriving it from the framebuffer.

**Not yet verified:** that this `mulss` is the projection aspect rather than another scalar
(UI scale, conversion factor). Confirm by disassembling the enclosing function, or empirically
by patching the 4 bytes on a copy. No competing candidates exist, so odds are good.

Nearby `.rdata` float pool (raw 0x167fd0–0x168030) also holds `10000`, `40000`, `4000`,
`0.0125`, `90.0`, `45.0`, `60.0` — plausible clip planes and FOV values.

---

## 5. Moddability summary

| Goal | Verdict | Notes |
|---|---|---|
| Corruption with intensity levels | Easy | 4 independent channels: texture payloads (keep DDS headers intact so files still load), `.msh` vertex jitter, config value randomization, placement scrambling. Structure-aware beats blind byte-smashing, which just crashes the loader. |
| Car values | Trivial | Plain text — see below. |
| HUD replacement | Trivial | Raw DDS, no obfuscation. |
| OP mode | Easy | Via car configs. `Save\Profile01.sav` is a 20-byte stub (`"Player"` + `01`, untouched since 2015) — no progress values to edit until the game is actually played. |
| Building scaling | Mixed | No scale field exists. Cheap route: repoint mesh paths between shipped height variants. True scaling needs `.msh` vertex float edits. |
| Widescreen | Good odds | §4. |

### Car config (verbatim, `Data/Vehicles/02/Main.obj` — "Clio NSX")

```
Base Health:          0100        Front Tyre Driving:       0
Base Weight (kg):     800         Rear  Tyre Driving:       1
Base Engine Force:    1300        Front/Rear Tyre Friction: 1.5
Base Acceleration:    1.0         Front/Rear Tyre Rolling:  1.0
Base Steering:        1.5         Suspension Stiffness:     25.f
                                  Suspension Damping:       0.5
Reflection Power:     64          Engine Sound ID:          0
```

8 player cars (`Data/Vehicles/01..08/Main.obj`), police variants for 01 and 03, separate
left/right wheel objects, 10 decal slots each.

### Static placement (`Data/Landscape/<sector>/StaticObjects.obj`)

```
Object file name:   Data/Static/Buildings/LHouses/01/Main02.obj
Object position:    -1011.20,17.47723,1039.368
Object orientation: -1034.04,17.47723,1136.724
```

`orientation` is a **second world-space point** (a look-at target), not Euler angles — the
identical Y value and position-scale magnitudes give it away.

### Gotcha: extension substitution

Configs and the exe reference `.bmp` (`Data/Misc/White.bmp`, buildings' `Main02.bmp`) but the
archives contain only `.dds`/`.jpg`. The loader maps between them. **When replacing a texture,
leave the `.obj` reference as `.bmp` and ship the file as `.dds`/`.jpg`.**

### HUD / interface assets (all in `Textures.pak`, raw DDS)

```
Data/Interface/HUD/SpeedBar/Main.dds     speedometer face
Data/Interface/HUD/SpeedBar/Arrow.dds    needle
Data/Interface/HUD/MapBar/Main.dds       minimap frame
Data/Interface/HUD/Icons/Icons.dds, Sprites.dds, Systems/Systems.dds
```

Plus menu panels in `_EN`/`_RU` pairs (`InfoBar`, `ResultBar`, `AvtoShopBar`, `WorkShopBar`,
`RacerRatingBar`, `Title`), 12 menu backgrounds, 8 in-world billboards
(`InfoScreen/Reklams/Scr01-08.jpg`), and bitmap fonts (`Fonts/Game 01/Main.dds` + `Mask.dat`).

Also present: `Data/Misc/RenderTechniques_00/_11/_14/_20.dat`, tied to the `[Video]` quality
levels in `Game.ini`.

---

## 6. Tools

`tools\` holds the Python scripts used above (Python 3.14 at
`%LOCALAPPDATA%\Programs\Python\Python314\python.exe`):

The working toolkit lives at `D:\Projects Overflow\City Racing Work\`:

| Script | Purpose |
|---|---|
| `crpak.py` | **The main tool.** `diag` / `rt-mem` / `rt-disk <workdir>` / `unpack <arc> <dir>` / `pack <dir> <out.hdr> <out.pak>`. Verified byte-exact. |
| `detect.py`, `detect2.py` | Classify payloads as XOR80-text / plain-text / binary. |

Earlier one-off analysis scripts are in `tools\` beside this file:

| Script | Purpose |
|---|---|
| `list_pak.py` | First-pass index reader (superseded by `crpak.py`). |
| `peek.py` | `peek.py <archive> [filter]` lists entries; `peek.py <archive> x <path>` dumps one deobfuscated text file. |
| `pe.py` | PE header / section / import-table parser. |
| `res2.py` | Resolution-table and aspect-constant scanner. |
| `xref.py` | Cross-references the 4:3 constant; dumps the float pool and code context. |

Both `crpak.py` and `list_pak.py` hardcode the install path (`GAME_DATA` / `GAME`) — update it
if working from a copy. Python 3.14 at `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`.

---

## 7. Current state of the install (2026-09-20)

dgVoodoo has been **removed** from the live install. Each of the 6 files was SHA256-verified
against its copy in `2026-09-20_dgvoodoo-removed\` *before* deletion, so every removal is
provably recoverable. After removal, the live install was compared file-by-file against
`2026-09-20_original-native\`: **41 files, 0 differences** — a clean native baseline.

`Direct3DCreate9` now resolves to Windows' own `C:\Windows\SysWOW64\d3d9.dll`
(10.0.22621.5415, Microsoft). Restore dgVoodoo by copying the 6 files back.

Still to verify by launching the game: that it runs natively, that the dgVoodoo watermark is
gone, and what resolutions the in-game video menu actually offers.

## 8. Environment notes

- The live install is read-only without elevation; an unelevated session cannot write to it.
- **C: is nearly full. D: has ~1.98 TB free.** Keep backups, working copies and pak-repack
  scratch space (~80 MB per rebuild) on D:.
- `GLCache\` in the install is a regenerable NVIDIA shader cache, no game content — excluded
  from the backup.
- `game-shell.exe` / `desktop.exe` are GameTop's ad launcher (it pings `gametop.com/stats/`).
  `game.exe` runs standalone.
- dgVoodoo's config had `dgVoodooWatermark = true`, so an in-game dgVoodoo logo is a quick
  visual check of whether the wrapper is loading. No watermark = clean native baseline.

---

# Part 2 — 2026-09-21

## 9. The world is a 600×600 grid

Several parallel layers in `World.pak` under `Data/Landscape/` share one world grid:

| File | Bytes | Layout | Contents |
|---|---|---|---|
| `AltitudeMap.dat` | 1,440,000 | **600×600 float32** | terrain height, **0.00 – 80.00**, mean 11.82 |
| `WayPointsMap.dat` | 360,000 | 600×600 uint8 | road / AI route network |
| `StaticObjectsPlaceMap.dat` | 360,000 | 600×600 uint8 | building placement |
| `TrafficDensityMap.dat` | 40,000 | **200×200 uint8** | traffic density, exactly ⅓ resolution |
| `GlobalRoute.dat` | 17,280,000 | = 600×600×48 | layout unknown |
| `PlaceColor.dat` | 270,000 | = 600×600×0.75 | unknown |

**`AltitudeMap.dat` is float32, not 1200×1200 bytes.** Both readings fit the file size exactly
(1200² == 600²×4), and the byte reading renders as convincing-looking terrain noise. Only the
float reading gives clean 0–80 heights. A genuine trap — file size alone cannot decide it.

`TrafficDensityMap.dat` is a plain **0..255 scale: 0 = no traffic, 255 = maximum**. There are
NO sentinel values. An earlier reading of `0xFF` as "blocked" was WRONG — corrected in Part 4.
Distribution: p25=12, **p50=52**, p75=129, p90=227, mean 81.2.

**The world is an archipelago** — islands joined by bridges, which is why `Objects.pak` ships
six bridge types (`Data/Static/Bridges/Type-01..06`).

Ready-made images also exist: `Data/Landscape/WorldMap.jpg` (512×512, the game's own map),
`LandscapeTex.jpg` (1024×1024), `RoadsAlpha.jpg` (256×256).

`maps2.py` renders 1800×1800 PNGs from the raw layers with hillshading computed from the float
heights. It carries a **pure-Python PNG writer** (zlib + CRC'd chunks, ~15 lines) because
neither Pillow nor numpy is installed.

## 10. Traffic — open lead, and a wrong turn worth recording

Raising `TrafficDensityMap.dat` is very likely the **wrong lever**: 15% of road cells already
sit at 192–254, so the field is not the constraint. The limiter must be a global cap on
simultaneous vehicles — consistent with opponents consuming the same budget as civilian
traffic.

The `[Video] Traffic` ini key is read at raw **0x053a0a** and **0x054da0**:

```
68 58 a6 56 00   push 0x56a658          ; "Traffic"  (string at raw 0x168e58)
68 74 a6 56 00   push 0x56a674          ; section name
ff d6            call esi               ; profile-read function
a3 20 c1 2c 01   mov [0x012cc120], eax  ; -> global at VA 0x012cc120
```

Next step: trace readers of the global at VA `0x012cc120`. `TrafficDensityMap.dat` has no
direct `.text` string reference, so it is loaded via a table.

## 11. Widescreen — the aspect-constant theory is DISPROVEN

A controlled A/B (same spawn, same resolution, only the aspect byte differing) measured the
player car's bounding box:

```
patched 16:9 : W=427      stock 4:3 : W=426
```

Identical. A real aspect change would have produced ~320 px. **The `1.3333334` constant at raw
0x167ff0 is not the projection aspect.**

Separately, comparing 1024×768 against 1920×1080 proved the 3D genuinely *is* stretched — the
car occupies the same fraction of screen width at both (0.2207 vs 0.2219), and its own
width/height ratio goes 1.41 → 1.84, a factor of 1.30 ≈ the predicted 1.333.

Live memory scanning of the running game (`findproj.py`, pure ctypes `ReadProcessMemory`) found
the real scene projection matrix:

```
0.661765   0          0          0
0          1.000000   0          0
0          0          1.000333   1.000000
0          0         -0.200067   0          near = 0.20   far = 600.03
```

`m00 = 0.661765` is **not present anywhere in game.exe**, so it is computed at runtime — which
is why no aspect-shaped constant was ever findable. `aspect = m11/m00 = 1.5111`, which is
neither 4:3 nor 16:9 and remains unexplained. A separate `aspect = 1.0, far = 100` matrix is
the environment/reflection cube map.

There is exactly **one** `SetTransform` call site, raw **0x0a3726**, pushing `D3DTS_PROJECTION`:

```
83 c3 68        add  ebx, 0x68
53              push ebx                ; the matrix
6a 03           push 3                  ; D3DTS_PROJECTION
8b 46 08        mov  eax, [esi+8]
8b 08           mov  ecx, [eax]
50              push eax
ff 91 b0 00 00  call [ecx+0xB0]         ; IDirect3DDevice9::SetTransform
```

Next step: find what *builds* the matrix at `[ebx+0x68]`.

## 12. Corrupter rules, learned by breaking it

Level 2 across all channels produced a **`CStaticObject` error** on load.

- **JPEG is the fragile format.** 267 of 336 textures are JPEG, which is entropy-coded and
  delimited by `0xFF` marker bytes. A random byte can invent or destroy a marker; the decoder
  then bails, the texture fails to load, and whatever object needed it reports an error.
  **DDS cannot fail this way** — DXT block data has no internal structure.
  Fix: never touch a `0xFF`, never touch the byte after one, never write `0xFF`. Verified
  across all 262 corrupted JPEGs — zero marker changes.
- **Never corrupt index or count fields** (`Engine Sound ID`, `Effect Textures Num`, anything
  matching num/id/count/index/class/type/level/version). Those are array subscripts; randomising
  them reads off the end and hard-crashes rather than glitching.
- A theory that the `mesh` channel was clobbering embedded filenames was **wrong** — the
  "ASCII strings" found in `.msh` are vertex float bytes that happen to be printable.
- `--keep-cars` re-applies the currently installed vehicle handling after corrupting, because
  every tool rebuilds from pristine and the two would otherwise overwrite each other.
- Still unbisected: which channel actually caused the error. Ladder: `tex` → `tex,place` →
  `tex,place,cfg` → all (mesh last, riskiest).

## 13. UAC VirtualStore — resolved

`game.exe` is a 32-bit app with no UAC manifest, so its writes to Program Files were silently
redirected to `%LOCALAPPDATA%\VirtualStore\...`. **Reads are redirected too**, so the game used
the virtualised copies and the Program Files `Game.ini` sat stale since June 2024. The real
save was `Profile02.sav` (129,470 bytes) in VirtualStore — not the 20-byte `Profile01.sav`
decoy in the game folder.

Resolved by granting the user Modify on the game folder, copying the live files back, and
**moving** the VirtualStore copy aside. Step three was essential: leaving it would have kept
shadowing reads while new writes went elsewhere.

Measured `[Video] Mode` mapping on this machine (Intel iGPU, native D3D9): **0 = 1920×1080**,
3 = 1024×768, 21 = 1680×1050. Not sorted by size — it is `EnumAdapterModes` order, so these
indices are driver-specific.

---

# Part 3 — the `.msh` mesh format, and the asset pipeline

## 14. `.msh` — SOLVED, both forms

647 meshes, two layouts. **644 (99.5%) now round-trip byte-exact through Wavefront OBJ.**

### Form A — "simple", 543 files

```
u32   vertexCount
u32   triangleCount
vertex[vertexCount]        stride 44:
    float3 position
    float3 normal
    u32    colour
    float2 uv0             normalised — lightmap
    float2 uv1             large values — tiled texture
u16   index[triangleCount*3]
byte  footer[40]           10 floats; last four are centre(3) + radius(1)
```

Verified on all 543 with four independent checks, zero failures: the size formula holds
exactly, every index is < vertexCount, every normal is unit length, and the footer's centre
equals the arithmetic centroid of the vertices.

Used by all `Data/Landscape/<sector>/` geometry. The breakthrough came from the **smallest**
file — `02_02/SideWalks.msh`, 186 bytes, 3 vertices, 1 triangle — where the colour dwords sat
visibly 44 bytes apart. On a 4 MB mesh that pattern is invisible.

### Form B — "slot", 104 files

```
u32 A[16] @0x00             kind flag: 1 normally, 2 for vehicle slots, 90 for the humans
u32 B[16] @0x40             vertex count per slot
u32 C[16] @0x80             triangle count per slot
bounds[nslots] @0xC0        40 bytes each: min(3f) max(3f) centre(3f) radius(1f)
per slot, contiguous:       vertex[B] stride 32 (pos3, normal3, uv2), u16 index[C*3]
tail                        64–196 bytes, still undecoded, preserved verbatim
```

Stride 32 and 6 bytes/triangle were solved algebraically across all 104 files, then confirmed
by unit-normal tests. `Data/Misc/WPCollCheckBox/Main.msh` proved the bounds block exactly: a
collision box with `B[0]=8, C[0]=12` — eight corners, twelve triangles — bounds min
(-1.5, 0, -1.5), max (1.5, 100, 1.5), centre (0, 50, 0), radius 50.047, against
`sqrt(1.5²+50²+1.5²) = 50.045`.

**The two forms differ for a real reason.** Form A carries vertex colour and two UV sets —
what baked-lightmap terrain needs. Form B carries position, normal and one UV — what a
dynamically-lit object needs. Guessing one universal layout could never have worked.

### Three meshes still resist

`Humans/Female/Main.msh` (the `A=90` animated one), `Static/Buildings/LHouses/01/Main.msh`
and `Vehicles/05/Main.msh` have non-zero gaps between slots. `extract` only writes a `.obj`
sidecar when the round-trip verifies byte-exact, so these are passed through read-only rather
than shipped as lossy.

## 15. Remaining `.dat` formats

| File | Layout |
|---|---|
| `Interface/Fonts/*/Main.dat` | **XOR 0x80 text** — the font's character map in glyph order, 153–154 chars from `@`. `Menu 01` uses a deliberately different order, so glyph order is per-font. |
| `Interface/Fonts/*/Mask.dat` | **1 byte/pixel** glyph bitmap, 256² or 512², only values 0 and 255 — binary alpha, no antialiasing |
| `Landscape/PlaceColor.dat` | **300×300×3 RGB** = 270,000 exactly |
| `Landscape/GlobalRoute.dat` | **600×600×48** = 17,280,000 exactly — 12 floats per world cell; field [1] steps 4 units per cell, matching the ~2396-unit world over 600 cells |

**`MeshShape.dat` (149 files) contains uninitialised memory.** A single 3,800-byte file holds
**43 occurrences of `0xCDCDCDCD`** — MSVC's uninitialised-heap debug fill — plus stale
pointers. These are raw struct dumps from a debug build, so some bytes were never meaningful.

**`Vehicles/*/MainExtra.dat`** opens with cumulative totals that index the matching `.msh`:
`4303, 5612, 0, 2222, ...` where 4303 = 2222+573+176+338+994 (slot vertex counts) and
5612 = 2922+826+178+478+1208 (triangle counts). The rest is dense float data around ±0.5–1.0.

## 16. The asset pipeline

`assets.py` extracts all 1,561 assets to editable formats and rebuilds them byte-exact.
Asset tree at `D:\Projects Overflow\City Racing Assets\` with its own README.

Two bugs surfaced **only from testing the no-op case**, both of which would have silently
degraded every asset on any rebuild:

1. **`%.6f` is not enough for float32.** It needs **9 significant digits** to survive a text
   round-trip. Six left a ~1e-6 drift on every vertex.
2. **Recomputing the bounds footer was wrong even when arithmetically correct.** Summing
   through Python doubles lands on a different float32 than the game stored — mathematically
   identical, bitwise different. The importer now returns the original bytes verbatim when
   geometry is unchanged.

A third needed a NaN-aware comparison: some meshes ship NaN normals with the sign bit set
(`0xFFC00000`), and a text round-trip yields Python's `0x7FC00000`. Same value, different bits.

---

## Route kinds 2/3/4 SOLVED — the road centreline system (2026-09-22)

Every street is stored as **three parallel one-cell tracks**. Measured across a road the
order is always `3 | 2 2 2 | 4`:

- **kind 3 / kind 4 = the two driving lines**, one per side. One cell wide, snapped
  sub-cell X/Z, adjacency pointers. Two disjoint networks that **never touch** (0.00% of
  each one's neighbours are the other) because kind 2 always separates them.
- **kind 2 = road surface** between them. Degree 0, no pointers, no snapped point.
- **kind 1 = drivable ground**, no steering information.

Evidence they are lines: same-kind 8-neighbour counts are kind 3 `2:8302 3:428 4:296`,
kind 4 `2:7524 3:586` — nearly every cell has exactly two neighbours, i.e. a chain.

### The adjacency graph

Pointers at 0x10..0x1C decode as `0x01967a20 + cellIndex*48`. Verified on **all 35,292**:
every pointer valid, every target 8-adjacent and same-kind, degree byte == pointer count on
all 17,136 line cells, pointer list ascending on all 17,136.

`0x01967a20` lies inside game.exe's own `.data` — the map is a **static object** at
`0x017ae180`, route array at `+0x1b98a0`, waypoint map at `+0x161a5c`. The file's pointers
are therefore real runtime addresses.

### The rebuild, and its missing bounds check

game.exe rebuilds the graph on load (`0x0042be15` kind 3, `0x0042bf13` kind 4): zero the
degree byte, walk the 3x3 block row-major skipping the centre, and for each same-kind
neighbour `*(cell + 0x10 + degree*4) = &neighbour; degree++`. That explains the ascending
order, and makes the 586 stale cached entries in the shipped file harmless.

**It checks nothing.** Four slots exist:

- a 5th neighbour overwrites the record's own degree / waypoint / progress bytes
- a 6th then indexes with a corrupted degree and scribbles ~2.6 KB over other records
- row-1 / row+1 are unclamped, so a border line cell reads off the array

So driving lines must be **one cell wide and off the border**. `mapeditor.py` now enforces
both: `set_line()` rolls back any cell that would exceed 4 links, and `audit()` blocks
APPLY outright. Verified — a deliberate solid 5x5 blob of kind 3 placed 18 cells, refused
7, and left **0** cells over the limit.

### game.exe anchors

`rand()` = `0x0054aba3`, `srand()` = `0x0054ab91` (statically linked MSVC CRT, found via
the LCG constants 0x343fd / 0x269ec3). Four `srand` sites seed from `timeGetTime()`; two
seed from `id * 123` — those two are **landscape scatter, not races**.

No race-definition file exists in any archive; courses are built at runtime, and neither
`WPCollCheckBox` nor the race invitation strings have static xrefs. Breakpointing `rand()`
in Cheat Engine while accepting a race is the way in.

---

## Race course generator SOLVED — `game.exe` 0x00432b40 (2026-09-22)

There is **no race-definition file**. A course is a **random walk over the kind-3 (yellow)
driving-line network**, and only that network.

Found by filtering the 215 `rand()` call sites down to the 6 that do grid arithmetic
(`imul ,0x258`) within +/-0x300 bytes — all 6 landed in the AI region. Static string xrefs
were a dead end: `WPCollCheckBox` is assembled at runtime, and the race invitation strings
are space-padded rows in a table with no direct reference.

```
start  nearest kind-3 cell to the billboard      0x00432b78  (the literal `push 3`)
       rand() % degree picks the first neighbour 0x00432b8d
step   gather neighbours, skip the last 4 cells, rand() % candidateCount   0x00432cb8
record (column,row) -> arrays at 0x012cc418 / 0x012cc41c, count at 0x012d0cd4
stop   budget exhausted | dead end | 0x800 = 2048 points   0x00432c5e
reject fewer than 0x1e = 30 points               0x00432cda
```

Plus a **no-backtrack window of 4** cells, and a junction rule at 0x00432c24: reaching a
cell of degree > 2 fewer than 4 cells after the previous one **discards the course and
restarts**. The step budget is the 4th stack argument, computed at the call site
0x00440705 from a float distance ratio — so length normally scales with distance.

**Consequence:** races follow kind 3 ONLY. Drawing new yellow line with `mapeditor.py` is
therefore the way to make races leave the tarmac.

### Correction: the map object is HEAP-allocated, not static

An earlier entry claimed `this = 0x017ae180` was a static global. It is not: the object
would end at 0x02a3a68c, past the image end at 0x02700150, and `.text` has **zero**
references to that address — it always arrives in `ecx`. That is precisely why the loader
rebuilds the adjacency pointers every load, and why whatever is written into those four
dwords in the file is ignored.

### racemod.py

Verified, reversible byte patches: `show` / `level 1..4` / `apply <names>` / `restore`.

| patch | site | effect |
|---|---|---|
| reshuffle | 0x0054abad, 0x0054abb3 | new full-period LCG — every rand() decision changes |
| nostep | 0x00432cc1 | NOP `sub [esp+0x64],1` — walk runs to a dead end or 2048 points |
| wander | 0x00432c7f/85/8b | NOP 3 of the 4 no-backtrack tests; courses may cross themselves |
| junction | 0x00432c2e | junction spacing 4 -> 1, far fewer discarded courses |
| noseed | 0x0054ab91 | `srand()` becomes a bare `ret` — nothing reseeds deterministically |

Levels: 1 mild, 2 long, 3 wild, 4 insane. Round-trip verified byte-identical.

**The baseline snapshot is taken from the LIVE game.exe, not the factory copy**, because
the install carries an unrelated local edit at 0x0056aa0c blanking the `h` of
`http://www.gametop.com/stats/cityracing.html`. Restoring from factory would undo it.

---

## Two "dead" roads found and activated (2026-09-22)

The user spotted two stretches of road with no traffic, no police and no race routes: the
lighthouse island with its causeway, and a spur at the bottom of the map.

**Cause:** they have road surface and kerbs (kind 2) but **no driving line was ever laid**
— no kind 3, no kind 4.

```
working road   G Y G O
dead road      G - - - - - - - - - G     kerbs, nothing in between
```

Traffic follows kind 3/4 and the race generator walks kind 3 only, so a road with no
yellow is invisible to every system in the game.

**Detection:** BFS from every kind-3 cell, then find kind-2 cells with no kind-3 within 6.
In the stock map this returns **exactly two areas and nothing else** — 141 cells total —
matching precisely what the user circled:

| area | cells | cols | rows | gap to live yellow |
|---|---|---|---|---|
| lighthouse island + causeway | 82 | 36-77 | 36-83 | 9.9 cells |
| south spur | 59 | 195-234 | 545-556 | 7.0 cells |

**Fix** (`activate.py`, imports its graph safety from `mapeditor`): retag the orphan green
as yellow so the driving line follows the kerb the designers already laid, then Bresenham
a short link to the nearest live yellow cell.

Result: 141 cells retagged + 12 link cells, **0 refused**, audit clean, and crucially the
yellow network went from split to **9,179 of 9,179 cells reachable from a single start —
one connected network**. Traffic density over both areas was already 254, so density was
never the blocker.

Counts: kind 2 10,939 -> 10,788, kind 3 9,026 -> 9,179.

---

## BUG: the first `nostep` patch deleted every race billboard (2026-09-22)

Reported from play: "I can't find any yellow or blue race billboard anymore." Restoring
game.exe brought them straight back.

**Cause — NOPping an instruction whose FLAGS were load-bearing.** `nostep` originally
replaced all five bytes of `sub dword [esp+0x64], 1` at 0x00432cc1 with NOPs:

```
00432cc1  sub dword [esp+0x64], 1     <- sets ZF
00432cc6  mov edi, [0x12d0cd4]        |
00432ccc  mov ecx, [esp+edx*4+0x2c]   |  none of these touch flags
00432cd0  mov esi, [esi+ecx*4+0x10]   |
00432cd4  jne 0x432c24                <- consumes the SUB's ZF
```

The compiler reused the decrement as the loop condition. With the `sub` gone, `jne` reads
flags left by `div edi` at 0x00432cbf, which x86 leaves **architecturally undefined**.

Chain: walk exits after ~1 step -> fewer than the 0x1e = 30 points required at 0x00432cda
-> generator returns 0 -> caller at 0x0044070c does `test eax,eax / je` -> billboard never
placed. Every billboard in the city, every time.

**Fix:** patch only the immediate — 0x00432cc5 from `01` to `00`. `sub X, 0` still runs and
still sets ZF from the value; it just subtracts nothing.

**Second consequence, also fixed:** `nostep` removes the normal ending (budget hits zero =
success), leaving the 2048-point cap (success) and a dead end (FAILURE). `nostep` now
auto-adds `wander` through a `REQUIRES` table. Proved safe on the live map — yellow cells
have 2 neighbours (8,448), 3 (434) or 4 (297), and **zero** have 1 or 0, so with only the
immediately-previous cell excluded there is always a candidate and no dead end exists.

**Lesson:** on optimised x86, NOPping an arithmetic instruction to "disable" it also
deletes its flag side effects, and a nearby conditional jump may be depending on them.
Neutralise the operand instead of removing the instruction.

---

## Race pipeline fully decoded + racesim emulator + level-3 OVERFLOW (2026-09-23)

### Corrections first

- **The map object is STATIC at `0x012d0ce0`** in the shipping game.exe (`mov ecx,
  0x12d0ce0` at 0x00440700; route array `0x0148a580`, confirmed by `add eax, 0x148a584`
  at 0x00432e42). The previous entry's "heap-allocated" correction was itself wrong. The
  file's pointer base `0x01967a20` (this = `0x017ae180`) comes from a DIFFERENT build,
  the map-authoring tool, which is why it has no references here and why the loader
  rebuilds the graph.
- **Junction rule:** `[esp+0x60]` only resets on a reset, so the rule can only fire in a
  course's first 4 cells. It trims the start. It does not discard courses mid-walk.
- **"The walk cannot dead-end"** only holds with `wander`. Stock walks dead-end **47%**
  of the time at L-shaped line ends. The game silently retries.

### The pipeline

```
setup  0x00440570  srand(timeGetTime()); billboard = kind-3 cell 100..175 units away
                   D = rand()%1001 + 2500*progress + 800;  budget = D / 4.0
walk   0x00432b40  random walk on kind 3, excludes last 4 cells, <= 2048 points
pass 1             A* 0x0042d260 between every 12th point
pass 2             A* between every 7th of those
gates  walk < 30 or dead end -> 0;  finished route < 100 -> no billboard
type   rand()%101 <= 40 -> timed race
```

Map header fields set at runtime: `+0x100` world size 2400.0, `+0x104` grid 600,
`+0x110` cell size 4.0.

### Where the U-turns come from

Diagonal roads are staircases, so the cell two back is also a neighbour. The 4-back
window was the only thing stopping a reversal onto it. `wander` removed three of those
checks, which gives a coin flip on every staircase plus a bounce at every dead end. The
A* passes then re-trace the reversal.

### racesim.py — the real game code in an emulator

Unicorn maps game.exe (patches applied in memory only) plus the live map data, and runs
the loader's graph rebuild, the walker, the nearest-cell finder and the A* pathfinder.
Only `rand()` is hooked, and it reads the LCG constants from emulated memory. The
rebuild matches the disassembly-derived rule on **0/500 mismatches**. Stock gives
**0.6%** of courses with a U-turn, matching the player's "1 in a million".

### Level 3 overflows the route buffer

The finished route has room for **2048 cells** at 0x012cc418. After it come live
globals, and from ~entry 2329 **the map object header** (world/grid/cell size). The A*
passes inflate the walk (each segment carries both endpoints; worst ratio ~1.21), so a
2048-point `nostep` walk became a **2482-cell route**. In the emulator that wrote through
the header and broke every later course.

Fix: new patch `cap` (0x00432c60, walk limit 0x800 -> 0x600 = 1536) keeps the route
under 2048. Also new: `reverse` (drop the last backtrack check) and `spread` (race-length
modulus 1001 -> 6001). A design matrix is being run through racesim before any of these
reach a level.

---

## ROOT CAUSE of the overflow: a stale-count bug in the 2005 A* — fixed (2026-09-23)

A* (0x0042d260) writes its point count only on success (`mov [eax], esi`, 0x0042d7ed).
A search with start == end, or with an unreachable goal, returns 0 without writing it.
The smoothing passes add the previous search's count anyway, then read leftover points
from an OLDER race, and the route detours to that ghost location and back (segments
~7 cells apart suddenly span 239-481 cells). Proven by poisoning the count: all 40,838
start==end searches left it untouched. Level 3's U-turns trigger it ~500x per course.

**astarfix:** the first 5 bytes of A* jump to a 43-byte stub in int3 padding at
0x004dba55. The stub zeroes the count, returns immediately if start == end, and
otherwise replays the displaced bytes and jumps back. Verified: stock 300/300 routes
identical; 0/15,425 stale counts; early-out 150/150 identical and 1.4x faster; uncapped
level 3 over 1,200 courses goes from ~20% faults / 269-283 overflows / ratio 2.26 to
**0 faults / 0 overflows / ratio 0.97**, with U-turns unchanged.

racesim now runs on all 12 cores (1,200 courses in 6-34 s).

### Chaos matrix and the new level ladder (1,200 courses each, 0 overflows anywhere)

| config | fail% | U-turn% | U-turns/race | median len | notes |
|---|---|---|---|---|---|
| stock | 50 | 0.3 | 0.0 | 581 | failures silently retried |
| 1 mild | 45 | 0.9 | 0.0 | 562 | |
| 2 twisty (wander+spread) | 0 | 97.4 | 6.1 | 1154 (179..1973) | length lottery |
| 3 wild (nostep+wander) | 0 | 100 | 10.1 | 1884 | always long |
| 4 insane (+noseed) | 0 | 99.8 | 10.2 | 1880 | |
| 5 anarchy (+reverse) | 1 | 100 | 20.5 | 286 | Brownian: stays ~40 cells from billboard |
| wander+reverse (no nostep) | 98 | - | - | 152 | rejected: billboards would vanish |

Simulator bug found and fixed along the way: the harness hardcoded the distance modulus,
so `spread` initially looked like a no-op. It is now read from the patched image.

---

## Level 6 "Chaos" and Level 7 "Chaos Leap" (2026-09-24, both designed by the player)

**Level 6 chaos** = wander + spread with the A* bug deliberately LIVE, via the marker
`-astarfix`. 2,400 courses: straight jumps in ~1% of races, over water 0.13%, but 5%
emulator faults and 154 overflows. Kept at the player's request so they can switch.

**Level 7 chaos leap** = `leap` + wander + spread. `leap` is new x86, assembled with
keystone and verified with capstone, living in the 469 zero bytes after .text's
VirtualSize (raised from 0x16622b to 0x166400 at file offset 0x218):

- walker `0x00432cd0` -> `0x00567280`: after each normal step, 128/32768 chance to jump
  to a random yellow cell 60..200 cells away. `pushfd`/`popfd` preserve the flags the
  loop's `jne` needs.
- A* `0x0042d260` -> `0x00567230`: astarfix, plus "gap > 16 cells -> don't fill". Normal
  smoothing gaps are <= 12, so only leaps stay straight.

2,400 courses: **0 faults, 0 overflows, 0 failed billboards, 0 checkpoints off a road**.
73% of races have a straight leap (1.45 on average), **68% cross open water**, longest
1,496 units.

Also confirmed: the player's two once-in-a-lifetime stock sightings (a race line into
the ocean; a river crossed straight instead of at the bridge) are this same A* bug.
racesim reproduced a 1,164-unit straight splice across two sea channels. The spliced
point is a raw walk point from earlier in the same race, not the (0,0) sea corner I
first guessed (0 corner hits in 779 races).
