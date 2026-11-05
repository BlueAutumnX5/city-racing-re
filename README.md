# City Racing RE

Private reverse-engineering and modding project for **City Racing** (EA Group / GameTop, 2008, 32-bit D3D9).
It includes the `racemod` exe patcher, the RE Control Panel, the Car Tuner, the Map Editor, the Rust drivetrain
DLL `crdrive.dll`, and the research tools.

**The game itself is not in this repo.** You need the game installed on the PC. Every mod is rebuilt from
your installed copy, checked against `docs/MANIFEST-sha256_2026-09-20.txt` (the untouched 2026-09-20 install).

Windows only for now.

## New PC: first run
> [!IMPORTANT]
> This tool has only been tested on my current system setup. Please report any compatibility issues or error logs in GitHub [**Issues**](https://github.com/BlueAutumnX5/city-racing-re/issues)!
1. Install City Racing from GameTop. The default folder is fine, and so is the renamed `City Racing RE` folder.
2. Double-click **`setup.bat`**. It:
   - finds Python 3.12+, or installs Python 3.14 with `winget`;
   - makes `.venv\` and installs `requirements.txt` into it;
   - finds the game through its uninstall registry entry;
   - copies the untouched game files to `local\backups\2026-09-20_original-native\`. It only does this when
     they match the manifest;
   - makes racemod's baseline: the pristine `game.exe` plus the one-byte no-phone-home edit;
   - unpacks the archives to `extracted\` and paints the per-car speedometer faces (`HUD faces\`);
   - asks to give your account write access to the game folder, if you don't have it yet (one admin prompt).
3. Close the game and run **`Install Data Mods.bat`** once. It writes your Map Editor route edits
   (`mods\GlobalRoute.patch.json`) and the Milky Way sky into the game's archives. The archives come out
   byte-identical to the first laptop's.
4. Open **`RE Control Panel.bat`** and press **Apply**. `crpanel_apply.json` holds the first laptop's last
   settings. Apply rebuilds `game.exe` and copies `crdrive.dll`, the HUD faces and the new audio next to it.

If the installed game is already modded, setup can't take the pristine copy from it. In that case, copy the
`2026-09-20_original-native` folder from the first laptop's backups into `local\backups\`, or point
`local.ini` at it. See `local.ini.example`.

## Launchers

| File | What it does |
|---|---|
| `RE Control Panel.bat` | Every extra with its settings, the chaos switch, and Apply |
| `Race Chaos.bat` | The same as the panel, from the command line (`racemod.py`) |
| `Car Tuner.bat` / `Map Editor.bat` | Edit the car stats in `Objects.pak` / the roads and routes in `World.pak` |
| `Night Mode (live).bat`, `Headlight Sliders (live).bat` | Live tweaks in memory while the game runs |
| `CPU Profile.bat`, `Stutter Profiler.bat` | Read-only performance profiling |
| `build.bat` | Rebuilds `crdrive.dll` with Rust and refreshes `bin\crdrive.dll` |

## Building crdrive.dll

`rust/crdrive` is a `no_std` cdylib for `i686-pc-windows-msvc` with no imports. It links with `rust-lld`,
so you don't need Visual Studio, and it also cross-builds from Linux.

```
rustup target add i686-pc-windows-msvc
cd rust/crdrive
cargo test
cargo build --release --target i686-pc-windows-msvc
```

`racemod` uses `rust/crdrive/target/.../crdrive.dll` when a local build exists. Otherwise it falls back to
the committed `bin\crdrive.dll`.

`rust/night-headlights` is only a scaffold (Cargo.toml, build.rs and the manifest). The app was never
written, so it isn't built.

## Paths

`crpaths.py` resolves each machine-specific path, checking these in order: environment variable
(`CR_GAME_DIR`, `CR_BACKUPS`, `CR_MUSIC`), `local.ini`, auto-detect, default. Run `python crpaths.py` to see
what it found.

## Layout

- top level: the user-facing tools, simulators and validators (`drivesim2.py`, `hudsim.py`,
  `racergodcheck.py`, ...). The validators run the real game code in Unicorn.
- `re-tools/`: RE probes and one-off scripts. Older ones are kept for the record, including the `edit_*.py`
  source editors that have already been applied.
- `docs/`: findings, stock car stats, the install manifest, and `docs/memory/`, the Windows-side Claude's
  project notes (read `city-racing-handoff.md` first).
- `assets_src/`: the Milky Way texture (ESO/S. Brunier, CC BY 4.0, see [`CREDITS.txt`](https://github.com/BlueAutumnX5/city-racing-re/blob/master/assets_src/CREDITS.md)).
- `New audio/`: the player's added music and ambience tracks, which the `newaudio` extra installs.
- `mods/`: data edits stored as patches against the pristine archives.

## License & Credits

- **Toolkit Code:** Licensed under [GNU General Public License v3.0](LICENSE).
- **Third-Party Assets:** Third-party audio and textures are not covered by the GPL and retain their original licenses (see credit files in their respective folders):
  - **Audio (`/New audio/Data/Audio/MusTrks/`):** "-Ricochet Love-" by Waterflame (CC BY-NC-SA 3.0).
  - **Galaxy Texture (`/assets_src/`):** "The Milky Way panorama" by ESO/S. Brunier (CC BY 4.0, modified to DDS).
