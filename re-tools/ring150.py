import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.WORK)
import racemod, trafficsim

if __name__ == "__main__":
    names = racemod.LEVELS[7][1] + ["slack", "dataslack", "rdataslack", "glow", "racerfree",
                                    "view", "racers"]
    for which in ("traffic", "police"):
        r = trafficsim.measure(names, which, 300)
        print(f"{which:<8} routes built {r['ok']}/{r['n']} ({100 * r['rate']:.1f}%), "
              f"faults {r['faults']}, mean pts {r['mean_pts']:.1f}, max pts {r['max_pts']}")
