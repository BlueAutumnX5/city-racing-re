"""What drivesim2.py expects per model - mirrors rust/crdrive/src/model.rs MODELS (player spec 2026-10-31)."""
MODELS = {
    1: ("Galant S500", "auto", 4),      # 4AT, 4th = overdrive
    2: ("Clio NSX", "manual", 5),
    3: ("Rover H1200", "auto", 6),      # quick-shift
    4: ("Cosmo R200", "manual", 6),     # close-ratio
    5: ("Thunder-1960", "auto", 3),
    6: ("Accord Z8", "manual", 5),      # kei van
    7: ("Alpha GRX8", "manual", 6),     # rotary
    8: ("Uber Atom-2000", "f1", 6),     # F355 F1 style
}
