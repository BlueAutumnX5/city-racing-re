//! Per-car gearbox + engine data (player spec 2026-10-31, memory city-racing-car-gearbox-spec).
//! Units are normalised like the old asm `manual` extra: r = 1.0 at the redline, a gear's GT = its redline
//! speed as a fraction of the STOCK design speed (base force x 0.06): the gt table is the spec's spacing, scaled
//! so top gear (or the gear below an overdrive) meets the stock top speed at TOP_AT of the redline, stretched
//! 15 % per Transmission upgrade (drive.rs gear_speed). The Engine upgrade only raises the top speed
//! Vd = (base force + 200 x level) x 0.06.

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Kind {
    /// clutch pedal (Shift), you shift (X up / Z down), 0.25 s shifts
    Manual,
    /// automated manual (Ferrari F1 style): you shift, robot-fast, clutch button still works
    F1,
    /// torque-converter automatic: shifts itself, selector P R N D 2 1
    Auto,
}

#[derive(Clone, Copy, Debug)]
pub struct Model {
    pub name: &'static str,
    pub kind: Kind,
    pub gears: usize,
    /// the gears' relative redline speeds, gear 1..=gears (unused slots 0); only the spacing counts, gt_of() scales
    /// the set so top gear (or the gear below the overdrive) meets the stock top speed at TOP_AT
    pub gt: [f32; 6],
    pub shift_time: f32,
    /// fraction of the drive force kept while a shift happens (0 = clutch in, autos keep some)
    pub shift_floor: f32,
    /// torque converter: torque ratio at stall and the stall revs (autos only)
    pub tr0: f32,
    pub stall: f32,
    /// automatic shift points (revs): full-throttle upshift, light/coasting upshift
    pub up_full: f32,
    pub up_light: f32,
    pub idle: f32,
    /// torque curve 1 - k (r - peak)^2, k_lo below the peak, k_hi above
    pub tc_peak: f32,
    pub k_lo: f32,
    pub k_hi: f32,
    /// engine braking at the redline as a share of the max drive force (friction + pumping, ~15-20 % on real
    /// engines; less on a rotary); scales with revs above idle and with the gear (2026-11-01: was ~4 %, far too weak)
    pub eb: f32,
    /// engine-sound load at the redline (pitch = 1 + 0.75 x load)
    pub pitch_top: f32,
    /// 1st gear clutch-slip launch revs (manual / F1)
    pub slip: f32,
    /// overdrive gears on top: the stock top speed is met in gear (gears - od), these only cruise lower
    pub od: usize,
    /// automatics: seconds the gas must stay down before a kickdown (old hydraulic boxes are slow)
    pub kick: f32,
    // ---- the engine as a spinning mass (player 2026-11-02: "real engines rev to the limit and bounce")
    /// seconds from idle to the redline, free (neutral), full gas: the flywheel's weight
    pub rev_up: f32,
    /// revs lost per second at the redline off the gas (friction + pumping; less at low revs)
    pub rev_fall: f32,
    pub limiter: Limiter,
    /// Hard / FuelCut: the revs fall this far (r) before the fuel comes back; Soft: the band the torque fades over
    pub lim_depth: f32,
    /// Hard / FuelCut: the shortest cut, s (an old fuel cut re-wets the ports slowly)
    pub lim_hold: f32,
    /// no limiter: valve float starts here (r) and the torque is gone float_w later
    pub float_at: f32,
    pub float_w: f32,
    /// revs above redline + this wear the engine out (real time, no scaling: player 2026-11-02)
    pub safe_over: f32,
    /// the engine's spinning mass seen at the wheels in 1st gear, as a share of the car's mass (higher gears
    /// x (gt1 / gt)^2): what a clutch dump or a landing shoves / drags the car with
    pub inertia: f32,
    /// rev warning buzzer from these revs (0 = none): the rotary Alpha, like the real rotary sports cars
    pub buzz_at: f32,
}

/// how a car's engine stops at the redline (player 2026-11-02, options modal)
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Limiter {
    /// ignition cut: sharp, fast bounce
    Hard,
    /// older fuel cut: deeper, slower "bap-bap-bap"
    FuelCut,
    /// electronic throttle: the power fades in, the revs settle with hardly a bounce
    Soft,
    /// none (Thunder-1960): past the redline into valve float, the power falls away
    None,
}

#[allow(clippy::too_many_arguments)] // one argument per column of the spec table
const fn manual(name: &'static str, gears: usize, gt: [f32; 6], tc_peak: f32, k_lo: f32, k_hi: f32, eb: f32,
                pitch_top: f32) -> Model {
    Model { name, kind: Kind::Manual, gears, gt, shift_time: 0.25, shift_floor: 0.0, tr0: 1.0, stall: 0.0,
            up_full: 0.0, up_light: 0.0, idle: 0.15, tc_peak, k_lo, k_hi, eb, pitch_top, slip: 0.40,
            od: 0, kick: 0.0, rev_up: 0.8, rev_fall: 1.0, limiter: Limiter::Hard, lim_depth: 0.04, lim_hold: 0.02,
            float_at: 1.06, float_w: 0.10, safe_over: 0.05, inertia: 0.28, buzz_at: 0.0 }
}

#[allow(clippy::too_many_arguments)]
const fn auto(name: &'static str, gears: usize, gt: [f32; 6], shift_time: f32, shift_floor: f32, tr0: f32,
              stall: f32, up_full: f32, tc_peak: f32, k_lo: f32, k_hi: f32, pitch_top: f32) -> Model {
    Model { name, kind: Kind::Auto, gears, gt, shift_time, shift_floor, tr0, stall, up_full, up_light: 0.45,
            idle: 0.15, tc_peak, k_lo, k_hi, eb: 0.16, pitch_top, slip: 0.0, od: 0,
            kick: 0.5, rev_up: 1.2, rev_fall: 0.8, limiter: Limiter::FuelCut, lim_depth: 0.06, lim_hold: 0.04,
            float_at: 1.06, float_w: 0.10, safe_over: 0.05, inertia: 0.30, buzz_at: 0.0 }
}

/// index = the "0X" of Data/Vehicles/0X (police cars use their model's entry); 0 = unknown car
pub static MODELS: [Model; 9] = [
    manual("unknown (generic 5-speed)", 5, [0.33, 0.55, 0.80, 1.10, 1.50, 0.0], 0.62, 1.42, 0.6, 0.18, 1.2),
    // 01 Galant S500 - "looks like a Crown Victoria": 4-speed automatic, 4th = overdrive, torquey V8
    //    (3rd -> 4th x1.43 like the real Crown Vic 4-speed: 3rd 1.00, 4th 0.70; player 2026-11-01)
    //    Limiter (player 2026-11-02): fuel cut, deep and slow; a heavy V8 flywheel
    Model { od: 1, rev_up: 1.1, rev_fall: 0.8, inertia: 0.32,
            ..auto("Galant S500", 4, [0.40, 0.70, 1.05, 1.50, 0.0, 0.0], 0.45, 0.30, 2.0, 0.40, 0.84, 0.45, 1.2,
                   0.8, 1.0) },
    // 02 Clio NSX - hatchback: 5-speed manual, small revvy 4-cylinder; hard cut
    Model { rev_up: 0.75, ..manual("Clio NSX", 5, [0.33, 0.55, 0.80, 1.10, 1.50, 0.0], 0.66, 1.5, 0.6, 0.16, 1.25) },
    // 03 Rover H1200 - SUV: 6-speed quick-shift automatic, low-down pull, 6th = overdrive (player 2026-11-01)
    //    Limiter: SOFT (electronic, the power fades in; player 2026-11-02)
    Model { od: 1, kick: 0.2, rev_up: 1.3, limiter: Limiter::Soft, lim_depth: 0.03,
            ..auto("Rover H1200", 6, [0.28, 0.45, 0.65, 0.88, 1.15, 1.50], 0.18, 0.50, 1.8, 0.42, 0.86, 0.45, 1.1, 0.8,
                   1.0) },
    // 04 Cosmo R200 - sports car: 6-speed close-ratio manual; hard cut
    Model { rev_up: 0.65, rev_fall: 1.05,
            ..manual("Cosmo R200", 6, [0.38, 0.54, 0.70, 0.87, 1.05, 1.30], 0.62, 1.42, 0.6, 0.18, 1.2) },
    // 05 Thunder-1960 - finned cruiser: 3-speed automatic, lazy V8. Full-throttle upshift 0.80 = factory
    // 1960s (1966 TorqueFlite WOT shifts ~3600-3900 of ~4800 rpm); 0.90 was tried 10-31, player chose
    // "the more realistic one" 2026-11-01. Hold it in 2 / 1 to rev higher.
    //    Kickdown waits 0.8 s like a 1960 hydraulic box (Galant 0.5 s default, Rover quick 0.2 s; player 2026-11-01)
    //    NO LIMITER (player 2026-11-02): points ignition, past the redline into valve float, the power falls away;
    //    the slowest-revving, heaviest flywheel of all
    Model { kick: 0.8, rev_up: 1.5, rev_fall: 0.55, limiter: Limiter::None, float_at: 1.02, float_w: 0.13,
            safe_over: 0.06, inertia: 0.35,
            ..auto("Thunder-1960", 3, [0.45, 0.85, 1.50, 0.0, 0.0, 0.0], 0.55, 0.35, 2.2, 0.38, 0.80, 0.40,
                   1.2, 0.9, 0.9) },
    // 06 Accord Z8 - kei van: 5-speed manual, tiny revvy engine; hard cut, quick and buzzy
    Model { rev_up: 0.6, rev_fall: 1.1, lim_depth: 0.035, lim_hold: 0.015, inertia: 0.25,
            ..manual("Accord Z8", 5, [0.30, 0.52, 0.78, 1.08, 1.50, 0.0], 0.70, 1.6, 0.6, 0.16, 1.3) },
    // 07 Alpha GRX8 - pop-up coupe: 6-speed manual + ROTARY (weak low end, holds to a high redline, ~no
    //    engine braking, high pitch); revs snap up and hang (light rotor, little friction); hard cut;
    //    rev warning buzzer near the redline like the real rotary sports cars (player 2026-11-02)
    Model { slip: 0.50, rev_up: 0.5, rev_fall: 0.75, lim_depth: 0.03, lim_hold: 0.015, inertia: 0.22, buzz_at: 0.90,
            ..manual("Alpha GRX8 (rotary)", 6, [0.30, 0.47, 0.66, 0.88, 1.15, 1.50], 0.78, 1.7, 0.4, 0.06, 1.5) },
    // 08 Uber Atom-2000 - F355 F1 style: 6-speed automated manual, robot-fast shifts, clutch button works;
    //    race-light flywheel, tight fast hard cut
    Model { kind: Kind::F1, shift_time: 0.10, rev_up: 0.45, rev_fall: 1.2, lim_depth: 0.025, lim_hold: 0.01,
            inertia: 0.20,
            ..manual("Uber Atom-2000", 6, [0.31, 0.48, 0.66, 0.87, 1.12, 1.45], 0.75, 1.6, 0.5, 0.16, 1.4) },
];

/// The STOCK car (no upgrades = as the factory ships it) reaches its stock top speed at this share of the redline
/// in top gear - or in the gear below an overdrive (`od`): each car's ratio table (the spec's spacing) is scaled
/// as a whole so that gear lands here. More Engine without a longer Transmission
/// then hits the rev limiter in top gear (player 2026-11-01); before, every top gear was an overdrive (r 0.67-0.77).
pub const TOP_AT: f32 = 0.95;

impl Model {
    /// a gear's redline speed / the STOCK design speed (reverse = 1st)
    pub fn gt_of(&self, gear: i32) -> f32 {
        let raw = match gear {
            g if g < 0 => self.gt[0],
            0 => 0.0,
            g => self.gt[(g as usize).min(self.gears) - 1],
        };
        raw / (TOP_AT * self.gt[self.gears - 1 - self.od])
    }
    pub fn gt_top(&self) -> f32 {
        self.gt_of(self.gears as i32)
    }
    /// torque curve, not normalised
    pub fn tc(&self, r: f32) -> f32 {
        let d = r - self.tc_peak;
        1.0 - if d < 0.0 { self.k_lo } else { self.k_hi } * d * d
    }
    /// normalisation: the stock car in top gear at its top speed pushes exactly the stock force (= same top speed)
    pub fn tcn(&self) -> f32 {
        1.0 / self.tc(TOP_AT)
    }
    /// gear multiplier m_g = 1 + accel x mm(g): 1st = the stock launch boost (1 + 50 accel/40), top = 1
    pub fn mm(&self, gear: i32) -> f32 {
        let g1 = self.gt_of(1);
        let top = self.gt_top();
        let gg = if gear < 0 { g1 } else { self.gt_of(gear) };
        1.25 * (top / gg - 1.0) / (top / g1 - 1.0)
    }
    /// friction + pumping: revs lost per second off the gas at revs e
    pub fn fric(&self, e: f32) -> f32 {
        self.rev_fall * (0.3 + 0.7 * e.max(0.0))
    }
    /// revs gained per second at full torque, free: rev_up from idle to the redline against the friction
    pub fn rev_a(&self) -> f32 {
        ((1.0 - self.idle) / self.rev_up + 0.65 * self.rev_fall) / 0.9
    }
    /// what is left of the torque at revs e: a soft limiter fades it over lim_depth below the redline, an engine
    /// without one loses it to valve float; hard / fuel cuts switch it off instead (drive.rs `cut`)
    pub fn shape(&self, e: f32) -> f32 {
        match self.limiter {
            Limiter::Soft => ((1.0 - e) / self.lim_depth).clamp(0.0, 1.0),
            Limiter::None if e > self.float_at => (1.0 - (e - self.float_at) / self.float_w).max(0.0),
            _ => 1.0,
        }
    }
    /// the engine's spinning mass at the wheels in this gear / the car's mass
    pub fn inertia_at(&self, gear: i32) -> f32 {
        let q = self.gt_of(1) / self.gt_of(if gear < 0 { 1 } else { gear.max(1) });
        self.inertia * q * q
    }
}

/// Realistic gearing (player 2026-11-01, options modal): the game's drag is linear damping (speed -10 %/s,
/// coast-down measured) = huge, so every car pulls ~1 g to a low top speed and the gears fly by. Two levers:
/// - TOP SPEED goes halfway to the real car's: force x s_top and every gear x s_top (top speed is linear in force);
/// - PUNCH k: the engine (and its braking) x k, and (1 - k) of the drag given back (`drag_back`), so the top speed
///   holds while every acceleration - each gear's length, 0-100 - stretches by 1/k.
#[derive(Clone, Copy, Debug)]
pub struct Real {
    /// the real car's top speed, km/h (police +10 %)
    pub top: f32,
    /// punch k: 50/50 mode (0-100 halfway to the real car's), Real-car mode (the real car's 0-100)
    pub half: f32,
    pub real: f32,
}

/// k calibrated by realcal.py (real drive code + DLL + measured linear drag) to the 0-100 times the player
/// approved: 50/50 6.2/8.2/6.8/4.7/7.7/(15.4)/4.5/3.8 s, Real-car 9.0/10.5/9.5/6.0/10.5/16.0/5.3/4.7 s
pub static REAL: [Real; 9] = [
    Real { top: 0.0, half: 1.0, real: 1.0 }, // unknown car: untouched
    Real { top: 190.0, half: 0.451, real: 0.289 }, // Galant
    Real { top: 180.0, half: 0.969, real: 0.709 }, // Clio
    Real { top: 190.0, half: 0.649, real: 0.456 }, // Rover
    Real { top: 240.0, half: 0.440, real: 0.333 }, // Cosmo
    Real { top: 185.0, half: 0.709, real: 0.496 }, // Thunder
    Real { top: 135.0, half: 1.000, real: 0.958 }, // Accord (already slow: 15.4 s at full punch)
    Real { top: 250.0, half: 0.719, real: 0.528 }, // Alpha
    Real { top: 295.0, half: 0.433, real: 0.330 }, // Uber
];

/// settings +16 (racemod `drivetrain` / `realcar`): which realism
pub const MODE_HALF: u32 = 0;
pub const MODE_REAL: u32 = 1;
pub const MODE_OFF: u32 = 2;

/// (s_top, punch k) of a car: s_top = the halfway top speed / the stock one (from its base force)
pub fn real_scale(model: usize, fbase: f32, police: bool, mode: u32) -> (f32, f32) {
    let r = &REAL[model.min(REAL.len() - 1)];
    let stock = fbase * 0.06;
    if mode == MODE_OFF || r.top <= 0.0 || stock <= 1.0 {
        return (1.0, 1.0);
    }
    let real_top = r.top * if police { 1.1 } else { 1.0 };
    let s_top = (0.5 + 0.5 * real_top / stock).max(1.0);
    (s_top, if mode == MODE_REAL { r.real } else { r.half })
}

/// the game's drag in the drive force's units: linear damping, top speed = force x 0.06 (coast-down 2026-11-01)
pub const DRAG_PER_KMH: f32 = 1.0 / 0.06;
/// the same calibration per m/s^2 of acceleration: drag v_kmh / 0.06 units balances the damping 0.1 x v_ms
/// = v_kmh / 36 m/s^2 -> 600 force units per m/s^2 (the stock driven wheels)
pub const FORCE_PER_MS2: f32 = 600.0;
/// gravity (the `gravity` extra's Earth value; stock is 10)
pub const GRAVITY: f32 = 9.81;

/// "Data/Vehicles/0X/Main.obj" / ".../Police.obj" -> (model 1..=8 or 0, police)
pub fn model_from_path(path: &[u8]) -> (u8, bool) {
    let pre = b"Data/Vehicles/0";
    if path.len() > pre.len() + 2 && path[..pre.len()].eq_ignore_ascii_case(pre) {
        let d = path[pre.len()];
        if (b'1'..=b'8').contains(&d) {
            let police = path.len() > pre.len() + 2 && (path[pre.len() + 2] | 0x20) == b'p';
            return (d - b'0', police);
        }
    }
    (0, false)
}
