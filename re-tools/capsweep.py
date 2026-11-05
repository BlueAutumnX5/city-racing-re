"""Which walk cap keeps level 3's route inside 2048, with margin? Measured, not assumed."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import io, sys, contextlib, random, struct
sys.path.insert(0, crpaths.WORK)
import racemod, racesim

random.seed(11)
L3 = ["reshuffle", "nostep", "wander", "junction", "cap"]
for cap in (1024, 896, 768):
    racemod.PATCHES["cap"] = [(0x00432c60, bytes.fromhex("00080000"),
                               struct.pack("<I", cap), f"walk cap {cap}")]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        o = racesim.run(L3, 400, f"cap {cap}")
    lines = [l for l in buf.getvalue().splitlines()
             if any(k in l for k in ("FAULT", "outcome", "U-turn", "median", "fill", "ratio"))]
    print(f"--- level 3 with walk cap {cap} ---")
    print("\n".join(lines))
    print()
