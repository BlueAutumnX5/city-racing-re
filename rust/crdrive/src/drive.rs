//! The drivetrain step - pure logic over plain numbers (unit-testable; lib.rs does the game memory).
//! Port of racemod's asm `manual` extra (drivesim-proven), made per-car and extended with automatics.
use crate::model::{Kind, Model};

pub const BOGMIN: f32 = 0.25;
pub const RLIM_EB: f32 = 1.15;
pub const VMIN_EB: f32 = 3.0;
pub const EB_CONVERTER: f32 = 0.4; // an automatic's torque converter slips: this share of the engine braking
pub const REV_OK: f32 = 5.0; // km/h: automatics go into P only this slow (R: any speed, player 2026-11-01)
pub const REFUSE_FLASH: f32 = 0.6; // s: the refused letter blinks on the HUD (player 2026-10-31: option 4)

/// selector positions of an automatic
pub const SEL_P: u8 = 0;
pub const SEL_R: u8 = 1;
pub const SEL_N: u8 = 2;
pub const SEL_D: u8 = 3;
pub const SEL_2: u8 = 4;
pub const SEL_1: u8 = 5;

#[derive(Clone, Copy, Debug)]
pub struct Input {
    pub v: f32,        // km/h, signed (+0x7f70)
    pub accel: f32,    // +0x7f78
    pub f: f32,        // engine force F (+0x7f80)
    pub fmax: f32,     // +0x7f84 (damage included)
    pub fbase: f32,    // +0x7f88
    pub throttle: f32, // +0x7f8c
    pub pedal: f32,    // brake pedal +0x7f94
    pub upgrade: i32,  // engine upgrade level +0x7fdc
    pub trans: i32,    // transmission upgrade level +0x7fe0 (workshop slots: ENGINE TRANSMISSION CHASSIS TIRES)
    pub kc: f32,       // driven wheels touching / driven wheels
    pub clutch: bool,  // Shift held
    pub dt: f32,
    pub power: f32,    // 0..1 (manpower slider)
    pub ai: bool,      // an AI car: shifts itself, keeps the stock throttle ramp (its analog control)
    pub role: u8,      // [car+0xc8c]: 0 player, ROLE_RACER / ROLE_POLICE / ROLE_TRAFFIC
    pub s_top: f32,    // realistic gearing: top speed (force and every gear) x this (model::real_scale)
    pub punch: f32,    // ... and every acceleration x this, (1 - punch) of the drag given back
    pub slope: f32,    // sin(pitch): the car's forward vector y (+0x24); > 0 = nose up the hill
}

/// who drives an AI car ([car+0xc8c]) decides HOW it shifts (player 2026-11-01: human-like AI shifting)
pub const ROLE_RACER: u8 = 1;
pub const ROLE_POLICE: u8 = 2;
pub const ROLE_TRAFFIC: u8 = 3;

#[derive(Clone, Copy, Debug)]
pub struct State {
    pub gear: i32,     // -1 = R, 0 = N, 1..
    pub sel: u8,       // automatics: SEL_*
    pub shift_t: f32,  // time left in the current shift
    pub since: f32,    // time since the last automatic shift
    pub rpm: f32,      // revs from the wheels (or converter/slip)
    pub eng: f32,      // the engine's own revs (shown and heard)
    pub cut: bool,     // the limiter has the fuel / spark cut
    pub cut_t: f32,    // ... for this long
    pub cuts: u32,     // limiter cuts so far (tools / tests: the bounce rate)
    pub free: bool,    // last step the engine ran free of the wheels (neutral, clutch, air)
    pub free_k: f32,   // ... and how fast it meets them again (SYNC_*)
    pub sync: bool,    // engine and car are meeting: shove / lurch
    pub wear: f32,     // over-rev wear, 1 = blown
    pub blown: bool,
    pub dmg_set: bool, // lib.rs: the game's engine damage was set to full for the blown engine
    pub refused: f32,  // a refused P (automatic, rolling): flash its letter this long
    pub refused_ch: u8,
    pub kick_t: f32,   // how long the gas has been down while a kickdown is wanted
    pub up: u32,       // pending key presses (player)
    pub dn: u32,
    // AI driver (human-like shifting): drawn once per car, then fresh per shift
    pub rng: u32,      // xorshift state (lib.rs seeds it from the car)
    pub skill: f32,    // 0 = sloppy traffic driver .. 1 = sharp racer; < 0 = not drawn yet
    pub up_jit: f32,   // this shift's offset from the driver's usual shift point
    pub need: f32,     // this shift's reaction time (s) once the revs are there
    pub over: f32,     // how long the revs have been past the shift point
}

/// a state before any car is known (statics) - new_state() fills in the model
pub const BLANK: State = State { gear: 0, sel: 0, shift_t: 0.0, since: 0.0, rpm: 0.15, eng: 0.15, cut: false,
                                 cut_t: 0.0, cuts: 0, free: false, free_k: SYNC_CLUTCH, sync: false, wear: 0.0, blown: false,
                                 dmg_set: false, refused: 0.0,
                                 refused_ch: 0, kick_t: 0.0, up: 0, dn: 0, rng: 0x9E37_79B9, skill: -1.0,
                                 up_jit: 0.0, need: 0.0, over: 0.0 };

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Output {
    pub force: f32,          // applied drive force (all driven wheels get it)
    pub f: f32,              // new engine force F to write back
    pub brake: Option<f32>,  // force the brake amount (+0x7f90): Park
}

pub fn new_state(m: &Model) -> State {
    State { gear: if m.kind == Kind::Auto { 0 } else { 1 }, sel: SEL_N, rpm: m.idle, eng: m.idle, ..BLANK }
}

#[inline]
fn fabs(x: f32) -> f32 {
    f32::from_bits(x.to_bits() & 0x7fff_ffff)
}

/// the top speed (the power cap): grows with the ENGINE upgrade
pub fn design_speed(i: &Input) -> f32 {
    (i.fbase + 200.0 * i.upgrade as f32) * 0.06 * i.s_top
}

/// The game adds 0.2 "acceleration" per TRANSMISSION level (0x004353f0), which the gearbox turns into low-gear
/// pull; the Transmission upgrade now only lengthens the gears (player 2026-11-01), so take that bonus back out
/// of the car's current value (which also carries the damage reduction, kept).
pub fn launch_accel(accel: f32, base: f32, trans: i32) -> f32 {
    let with = base + 0.2 * trans as f32;
    if base > 0.0 && with > 0.0 { accel * base / with } else { accel }
}

/// every gear this much longer per TRANSMISSION upgrade level
pub const TRANS_STRETCH: f32 = 0.15;

/// what the gears are measured against: the STOCK design speed, so an Engine upgrade only adds power and
/// leaves the shift speeds alone; the Transmission upgrade lengthens every ratio (player 2026-11-01)
pub fn gear_speed(i: &Input) -> f32 {
    i.fbase * 0.06 * i.s_top * (1.0 + TRANS_STRETCH * i.trans as f32)
}

fn wheel_rpm(m: &Model, i: &Input, gear: i32) -> f32 {
    fabs(i.v) / (gear_speed(i) * m.gt_of(gear))
}

/// keys -> gear / selector (one press per step, like the asm)
fn shift_inputs(m: &Model, i: &Input, s: &mut State) {
    let up = if s.up > 0 { s.up -= 1; true } else { false };
    let dn = if s.dn > 0 { s.dn -= 1; true } else { false };
    if m.kind == Kind::Auto {
        // X moves the lever P -> R -> N -> D -> 2 -> 1, Z back
        let slow = i.v < REV_OK && i.v > -REV_OK;
        let mut sel = s.sel;
        if up && sel < SEL_1 { sel += 1; }
        if dn && sel > SEL_P { sel -= 1; }
        if sel == SEL_P && sel != s.sel && !slow {
            // the park pawl refuses while rolling - flash the letter (R is allowed at any speed: player
            // 2026-11-01 "the reverse safety above 5 km/h is messing with me")
            s.refused = REFUSE_FLASH;
            s.refused_ch = b'P';
            sel = s.sel;
        }
        if sel != s.sel {
            s.sel = sel;
            s.gear = match sel {
                SEL_R => -1,
                // D <-> 2 <-> 1 keeps the current gear (auto_shift steps down to the lever's limit);
                // from N/R pick the gear that suits the speed
                SEL_D | SEL_2 | SEL_1 if s.gear >= 1 => s.gear,
                SEL_D | SEL_2 | SEL_1 => {
                    let lim = auto_limit(m, sel);
                    let mut g = 1;
                    while g < lim && wheel_rpm(m, i, g) > 0.75 { g += 1; }
                    g
                }
                _ => 0,
            };
            s.since = 0.0;
        }
        return;
    }
    let mut g = s.gear;
    if up && g < m.gears as i32 {
        g += 1;
        s.shift_t = m.shift_time;
    }
    // N -> R at any speed (player 2026-11-01); rolling forward fast, R just sits on its limiter
    if dn && g > -1 {
        g -= 1;
        s.shift_t = m.shift_time;
    }
    s.gear = g;
}

fn auto_limit(m: &Model, sel: u8) -> i32 {
    match sel {
        SEL_2 => 2.min(m.gears as i32),
        SEL_1 => 1,
        _ => m.gears as i32,
    }
}

/// automatic: decide up/down shifts from the wheel revs
fn auto_shift(m: &Model, i: &Input, s: &mut State) {
    if s.gear < 1 {
        return;
    }
    s.since += i.dt;
    let lim = auto_limit(m, s.sel);
    if s.gear > lim {
        // lever moved to 2/1: drop down once the lower gear can take it
        if wheel_rpm(m, i, s.gear - 1) < 0.95 {
            s.gear -= 1;
            s.shift_t = m.shift_time;
            s.since = 0.0;
        }
        return;
    }
    if fabs(i.v) < 3.0 && s.gear > 1 {
        // stopped: a real automatic is back in 1st (a hard stop has no time for every downshift)
        s.gear = 1;
        s.shift_t = 0.0;
        s.since = 0.0;
        return;
    }
    if s.shift_t > 0.0 {
        return;
    }
    let gas = i.throttle > 0.0;
    // kickdown: gas held -> straight to the lowest gear that stays below the upshift point (5th -> 3rd in one)
    if kickdown(m, i, s, gas, m.kick, (m.up_full - KICK_MARGIN).min(KICK_MAX)) {
        return;
    }
    // coasting / braking: follow the speed down, as long as the lower gear stays below the light upshift point
    if !gas && s.gear > 1 && s.since >= 0.3 && wheel_rpm(m, i, s.gear - 1) < m.up_light - KICK_MARGIN {
        s.gear -= 1;
        s.shift_t = m.shift_time;
        s.since = 0.0;
        return;
    }
    if s.since < 0.6 {
        return;
    }
    if s.gear < lim && wheel_rpm(m, i, s.gear) >= if gas { m.up_full } else { m.up_light } {
        s.gear += 1;
        s.shift_t = m.shift_time;
        s.since = 0.0;
    }
}

/// a kickdown lands this far below the upshift point (no hunting) and never above KICK_MAX revs
const KICK_MARGIN: f32 = 0.06;
const KICK_MAX: f32 = 0.80;

/// kickdown: with the gas held `delay` seconds, drop in ONE shift to the lowest gear whose revs stay <= cap.
/// true = shifted
fn kickdown(m: &Model, i: &Input, s: &mut State, gas: bool, delay: f32, cap: f32) -> bool {
    let mut g = s.gear;
    while gas && g > 1 && wheel_rpm(m, i, g - 1) <= cap {
        g -= 1;
    }
    if g == s.gear {
        s.kick_t = 0.0;
        return false;
    }
    s.kick_t += i.dt;
    if s.kick_t < delay {
        return false;
    }
    s.gear = g;
    s.shift_t = m.shift_time;
    s.since = 0.0;
    s.kick_t = 0.0;
    true
}

// ---- the engine as a spinning mass (player 2026-11-02). Before, its revs eased toward the limiter by a share of
// the gap each frame (an electric motor's curve: it slowed down near the top and never got there) and, in gear or
// in the air, the shown revs were the wheels' from the CAR's speed - so in a jump they followed the airspeed and a
// downshift raised them. Now the engine has its own revs, always: torque spins it up (rev_up), friction and
// pumping slow it (rev_fall), each car's limiter stops it its own way, and the clutch / converter / tyres tie it
// to the wheels only while they can.

/// engine sub-steps, s: a limiter bounce is 4-25 Hz and a frame up to 50 ms
const SUB: f32 = 0.002;
/// how tight the driveline holds the engine to the wheels (/s): a clutch is stiff, a torque converter lets it flare
const LOCK_MANUAL: f32 = 80.0;
const LOCK_AUTO: f32 = 25.0;
/// engine and car meeting again (/s): a clutch let in, the converter taking up (N -> D), tyres landing
const SYNC_CLUTCH: f32 = 8.0;
const SYNC_CONVERTER: f32 = 3.0;
const SYNC_LAND: f32 = 10.0;
/// that far apart (r) they meet with a shove / lurch; this close they are together again
const SYNC_GAP: f32 = 0.03;
const SYNC_DONE: f32 = 0.01;
/// a torque converter passes this share of the flywheel's shove (fluid coupling)
const SHOVE_CONVERTER: f32 = 0.5;
/// one driven wheel up: the engine spins it free and the wheel still down pulls it this fast x its share
const PARTIAL_PULL: f32 = 6.0;
/// all driven wheels up: engine + wheels spin together, heavier than the engine alone (x 1 + this x gear gt)
const AIR_WHEELS: f32 = 0.6;
/// over-rev wear, real time (player 2026-11-02: "like their real life counterparts without any scaling"):
/// safe_over above the redline an engine lasts WEAR_T0 s, every 1/WEAR_K further 1/e as long - 10 min there,
/// ~1 min 7 % further, a money-shift 25 % over is gone in a fraction of a second
pub const WEAR_T0: f32 = 600.0;
pub const WEAR_K: f32 = 34.0;

/// how the engine is held this step
#[derive(Clone, Copy)]
enum Hold {
    /// spinning free (neutral, clutch in, the gear fighting the roll), dragging this much mass (1 = itself)
    Free(f32),
    /// pulled to the revs the wheels give (rc) this fast (/s)
    To(f32, f32),
}

/// e^-x for x >= 0 (no_std: no libm) - (1 - x/256)^256, within ~3 % to x = 17
fn exp_neg(x: f32) -> f32 {
    let mut y = 1.0 - x / 256.0;
    if y <= 0.0 {
        return 0.0;
    }
    for _ in 0..8 {
        y *= y;
    }
    y
}

/// Hard / FuelCut limiter: cut at the redline, fuel back once the revs fell lim_depth (and lim_hold passed).
/// Held to the wheels the revs only fall to rc - friction / pull, so it comes back halfway from there instead
/// (in gear the bounce is the driveline's small give); with the wheels driving it past the limiter it stays cut.
fn limiter(m: &Model, s: &mut State, e: f32, h: f32, hold: Hold) {
    if !matches!(m.limiter, crate::model::Limiter::Hard | crate::model::Limiter::FuelCut) {
        s.cut = false;
        return;
    }
    if !s.cut {
        if e >= 1.0 {
            s.cut = true;
            s.cut_t = 0.0;
            s.cuts = s.cuts.wrapping_add(1);
        }
        return;
    }
    s.cut_t += h;
    let mut back = 1.0 - m.lim_depth;
    if let Hold::To(rc, pull) = hold {
        let floor = rc - m.fric(e) / pull;
        if floor >= 1.0 {
            return;
        }
        back = back.max(floor + 0.4 * (1.0 - floor));
    }
    if e <= back && s.cut_t >= m.lim_hold {
        s.cut = false;
    }
}

/// run the engine for dt: gas 0..1
fn engine(m: &Model, s: &mut State, gas: f32, hold: Hold, dt: f32) {
    let n = ((dt / SUB) as i32 + 1).clamp(1, 40);
    let h = dt / n as f32;
    for _ in 0..n {
        let e = s.eng;
        if s.blown {
            s.eng = (e - 2.0 * m.fric(e) * h).max(0.0); // broken: it winds down and stays down
            continue;
        }
        limiter(m, s, e, h, hold);
        let fuel = if s.cut { 0.0 } else { gas * m.tc(e.max(m.idle)).max(0.0) * m.shape(e) };
        let mass = if let Hold::Free(k) = hold { k } else { 1.0 };
        let mut x = (e + (fuel * m.rev_a() - m.fric(e)) / mass * h).max(m.idle); // the idle control holds idle
        if let Hold::To(rc, pull) = hold {
            x += (rc - x) * (h * pull).min(1.0);
        }
        s.eng = x;
    }
}

/// revs past redline + safe_over wear the engine; worn out = blown (no drive, it winds down, the game's engine
/// damage goes to full: smoke; a repair brings it back - lib.rs)
fn wear(m: &Model, s: &mut State, dt: f32) {
    let over = s.eng - 1.0 - m.safe_over;
    if over > 0.0 && !s.blown {
        let life = WEAR_T0 * exp_neg(WEAR_K * over);
        s.wear += if life > 1e-6 { dt / life } else { 1.0 };
        if s.wear >= 1.0 {
            s.blown = true;
            s.cut = false;
        }
    }
}

/// 0..1, xorshift32
fn rnd(s: &mut State) -> f32 {
    let mut x = s.rng.max(1);
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    s.rng = x;
    (x >> 8) as f32 / 16_777_216.0
}

/// skill range per role: racers are sharp, police nearly so, traffic drivers are in no hurry
fn skill_range(role: u8) -> (f32, f32) {
    match role {
        ROLE_RACER => (0.55, 1.0),
        ROLE_POLICE => (0.45, 0.9),
        ROLE_TRAFFIC => (0.0, 0.35),
        _ => (0.6, 0.6),
    }
}

/// the next shift: where this driver will shift and how quickly they react once the revs are there
fn next_shift(s: &mut State) {
    let sloppy = 1.0 - s.skill;
    s.up_jit = (rnd(s) * 2.0 - 1.0) * (0.01 + 0.03 * sloppy);
    s.need = (0.05 + 0.25 * sloppy) * (0.6 + 0.8 * rnd(s));
    s.over = 0.0;
}

/// a human's manual shift: slower and less even the sloppier the driver, now and then fumbled (x2.2); the
/// F1 robot and the automatics shift in their own time
fn human_shift_time(m: &Model, s: &mut State) -> f32 {
    if m.kind != Kind::Manual {
        return m.shift_time;
    }
    let sloppy = 1.0 - s.skill;
    let t = m.shift_time * (0.9 + 0.8 * sloppy) * (0.85 + 0.3 * rnd(s));
    if rnd(s) < 0.02 + 0.08 * sloppy { t * FUMBLE } else { t }
}
pub const FUMBLE: f32 = 2.2;

fn ai_shift_to(m: &Model, s: &mut State, g: i32) {
    s.gear = g;
    s.shift_t = human_shift_time(m, s);
    s.since = 0.0;
    next_shift(s);
}

/// a manual/F1 driver's upshift point (revs) at throttle t: short-shifts on a light pedal, late at full -
/// along t^2, people only rev a gear out near full throttle (linear put a 30 % pedal at ~0.6 of the redline)
pub fn ai_up_at(skill: f32, t: f32) -> f32 {
    let lo = 0.38 + 0.14 * skill;
    let hi = 0.82 + 0.13 * skill;
    lo + (hi - lo) * t * t
}

/// a manual/F1 driver downshifts off the gas / braking once the revs fall below this (sharp drivers keep
/// the engine on the boil for the corner exit)
pub fn ai_down_at(skill: f32) -> f32 {
    0.30 + 0.25 * skill
}

/// AI cars: every box shifts itself (automatics sit in D), driven like a HUMAN (player 2026-11-01): each car
/// gets a driver whose skill comes from its role (racer / police / traffic) and who varies shift to shift -
/// the shift point follows the throttle (traffic short-shifts, racers rev it out), a reaction time once the
/// revs are there (a slow one bounces off the limiter), slower and sometimes fumbled manual shifts, and
/// downshifts one gear at a time while braking (lib.rs runs this with the stock brake code too). After a
/// big slowdown without braking it block-shifts straight to a gear that suits the speed.
pub fn ai_gear(m: &Model, i: &Input, s: &mut State) {
    let auto = m.kind == Kind::Auto;
    if s.skill < 0.0 {
        let (lo, hi) = skill_range(i.role);
        s.skill = lo + (hi - lo) * rnd(s);
        next_shift(s);
    }
    if s.gear < 1 {
        s.gear = 1;
        s.sel = SEL_D;
    }
    s.since += i.dt;
    if fabs(i.v) < 3.0 && s.gear > 1 {
        // stopped: back in 1st (a hard stop has no time for every downshift)
        s.gear = 1;
        s.shift_t = 0.0;
        s.since = 0.0;
        return;
    }
    let mut g = s.gear;
    while g > 1 && wheel_rpm(m, i, g) < 0.30 {
        g -= 1;
    }
    if g != s.gear && s.shift_t <= 0.0 {
        ai_shift_to(m, s, g);
        return;
    }
    if s.shift_t > 0.0 {
        return;
    }
    let t = (i.throttle / 2000.0).clamp(0.0, 1.0);
    let gas = t > 0.0 && i.pedal <= 0.0;
    let r = wheel_rpm(m, i, s.gear);
    if !gas {
        s.over = 0.0;
        if s.gear > 1 {
            let lower = wheel_rpm(m, i, s.gear - 1);
            let go = if auto {
                s.since >= 0.3 && lower < m.up_light - KICK_MARGIN // the box follows the speed down
            } else {
                s.since >= 0.3 + 0.4 * (1.0 - s.skill) && r < ai_down_at(s.skill) && lower < 0.88
            };
            if go {
                ai_shift_to(m, s, s.gear - 1);
            }
        }
        return;
    }
    // the shift point follows the throttle (a real automatic's too; a driver short-shifts on a light pedal)
    let up_at = if auto {
        m.up_light + (m.up_full - m.up_light) * t
    } else {
        (ai_up_at(s.skill, t) + s.up_jit).min(0.97)
    };
    // out of a corner: kickdown (automatics with their box's delay, a driver after their reaction time) to
    // a gear below THIS throttle's shift point - against the full-throttle one a half-throttle car hunted 4-3-4
    let delay = if auto { m.kick } else { s.need + 0.1 };
    if kickdown(m, i, s, gas, delay, (up_at - KICK_MARGIN).min(KICK_MAX)) {
        let g = s.gear;
        ai_shift_to(m, s, g);
        return;
    }
    if s.since < 0.5 || s.gear >= m.gears as i32 {
        return;
    }
    if r >= up_at {
        s.over += i.dt;
        if auto || s.over >= s.need {
            ai_shift_to(m, s, s.gear + 1);
        }
    } else {
        s.over = 0.0;
    }
}

/// an AI car braking or reversing through the stock code: keep its driver working the gears (braking
/// downshifts, back to 1st at a stop) so it comes off the brake in a sensible gear
pub fn ai_braking(m: &Model, i: &Input, s: &mut State) {
    s.shift_t = (s.shift_t - i.dt).max(0.0);
    ai_gear(m, i, s);
}

/// the drag a car with punch k gets back: (1 - k) of the game's (linear) drag, along the way it rolls, with the
/// driven wheels on the ground - so with the engine x k its top speed holds and every acceleration is x k
pub fn drag_back(i: &Input) -> f32 {
    (1.0 - i.punch) * i.v * crate::model::DRAG_PER_KMH * i.kc.clamp(0.0, 1.0)
}

/// ... and (1 - k) of GRAVITY along the slope (player 2026-11-01: "this racer can't climb" - an 18 deg dirt hill
/// at 6-13 km/h): with the engine x k but gravity untouched, a car kept only k of its climbing force (Real-car
/// Cosmo 0.33, and racers' damaged engines on top). Now everything - drag AND gravity - acts x k, so a car
/// climbs what the original car climbed and only accelerates more gently.
pub fn hill_back(i: &Input) -> f32 {
    use crate::model::{FORCE_PER_MS2, GRAVITY};
    (1.0 - i.punch) * FORCE_PER_MS2 * GRAVITY * i.slope.clamp(-1.0, 1.0) * i.kc.clamp(0.0, 1.0)
}

/// one drive step for a car driven by this gearbox: the gearbox, then the drag given back (realistic gearing)
pub fn step(m: &Model, i: &Input, s: &mut State) -> Output {
    let mut o = gearbox_step(m, i, s);
    // not while braking: rolling back with Down held, drag given back (along the motion = backwards) made the
    // stock code release the brakes as if reversing (drivesim2 2026-11-01); braking at speed the stock brake
    // path applies no drive force anyway
    if i.pedal <= 0.0 && o.brake.is_none() {
        o.force += drag_back(i) + hill_back(i);
    }
    o
}

fn gearbox_step(m: &Model, i: &Input, s: &mut State) -> Output {
    let mut f = i.f.max(0.0); // Down never runs F negative = no automatic reverse
    if !i.ai {
        shift_inputs(m, i, s); // keys first, then the shift timer (the order the asm proved in drivesim)
    }
    s.shift_t = (s.shift_t - i.dt).max(0.0);
    s.refused = (s.refused - i.dt).max(0.0);
    if i.ai {
        ai_gear(m, i, s);
    } else if m.kind == Kind::Auto {
        auto_shift(m, i, s);
    }
    let zero = |f: f32| Output { force: 0.0, f, brake: None };
    let auto = m.kind == Kind::Auto;
    let clutch = i.clutch && !auto;
    let gas = i.throttle > 0.0;
    let gasf = (i.throttle / 2000.0).clamp(0.0, 1.0); // player 2000 = floored, the AI's its own pedal

    if s.gear == 0 || clutch || s.blown {
        // neutral / clutch in: the engine revs freely (a blown one only winds down)
        engine(m, s, gasf, Hold::Free(1.0), i.dt);
        s.rpm = s.eng;
        s.free = true;
        s.free_k = if auto { SYNC_CONVERTER } else { SYNC_CLUTCH };
        s.sync = false;
        wear(m, s, i.dt);
        let mut o = zero(f);
        if auto && s.sel == SEL_P {
            o.brake = Some(100.0);
        }
        return o;
    }

    let vd = design_speed(i);
    let mut r = wheel_rpm(m, i, s.gear);
    s.rpm = r;
    let sign = if s.gear < 0 { -1.0 } else { 1.0 };
    // the gear against the roll (R while rolling forward, ...): clutch / converter slip, the engine runs free
    // and the gear brakes the car as before (no over-rev wear: nothing forces the engine round)
    let wrong = sign * i.v < -VMIN_EB;
    // the revs the wheels hold the engine at: the converter's stall, a slipping clutch in 1st, idle at least
    let rc = if gas && auto && r < m.stall {
        m.stall
    } else if gas && !auto && (s.gear == 1 || s.gear == -1) {
        r.max(m.slip)
    } else {
        r
    }
    .max(m.idle);
    let mut shove = 0.0; // km/h the car gains (+) or loses this step as the flywheel meets it
    if wrong {
        engine(m, s, gasf, Hold::Free(1.0), i.dt);
        s.free = true;
        s.free_k = if auto { SYNC_CONVERTER } else { SYNC_CLUTCH };
        s.sync = false;
    } else if i.kc < 1.0 {
        // driven wheels in the air: they spin with the engine, whatever the car's speed
        let hold = if i.kc <= 0.0 {
            Hold::Free(1.0 + AIR_WHEELS * m.gt_of(s.gear))
        } else {
            Hold::To(rc, PARTIAL_PULL * i.kc)
        };
        engine(m, s, gasf, hold, i.dt);
        s.free = true;
        s.free_k = SYNC_LAND;
        s.sync = false;
        wear(m, s, i.dt);
    } else if s.shift_t > 0.0 {
        // a shift: the driver / the box matches the revs (no shove from a shift, as before)
        s.eng = rc;
        s.free = false;
        s.sync = false;
        wear(m, s, i.dt); // ... but a downshift into too low a gear is a money shift
    } else {
        if s.free && fabs(s.eng - rc) > SYNC_GAP {
            s.sync = true; // clutch let in / N -> D / landing: engine and car meet
        }
        s.free = false;
        if s.sync {
            let before = s.eng;
            let k = s.free_k;
            engine(m, s, gasf, Hold::To(rc, k), i.dt);
            // the spin the flywheel lost (or was forced to gain) went into (came out of) the car: momentum, x J/(1+J)
            // with J = the engine's mass at the wheels in this gear - big in 1st, small in top. Only its stored
            // spin: the torque it keeps making goes through the clutch as the drive force below.
            let d = s.eng - before;
            let j = m.inertia_at(s.gear);
            let pass = if auto { SHOVE_CONVERTER } else { 1.0 };
            shove = -pass * j / (1.0 + j) * d * gear_speed(i) * m.gt_of(s.gear);
            // met - or as close as the gas lets them (it keeps the engine a little ahead): the clutch is in
            let (g0, g1) = (fabs(before - rc), fabs(s.eng - rc));
            if g1 < SYNC_DONE || g1 > g0 - 0.002 {
                s.sync = false;
            }
        } else {
            engine(m, s, gasf, Hold::To(rc, if auto { LOCK_AUTO } else { LOCK_MANUAL }), i.dt);
        }
        wear(m, s, i.dt);
    }
    // the shove as a force over this step (600 units = 1 m/s^2; the tyres' grip clips what they cannot pass)
    let shove_f = sign * crate::model::FORCE_PER_MS2 * shove / 3.6 / i.dt.max(1e-4);
    if i.pedal > 0.0 {
        return zero(f); // brake only
    }
    let mg = 1.0 + i.accel * m.mm(s.gear);
    if !gas {
        if s.shift_t > 0.0 {
            return zero(f);
        }
        let mut force = 0.0;
        if sign * i.v > VMIN_EB {
            let eb = (r.min(RLIM_EB) - m.idle).max(0.0) / (1.0 - m.idle) * i.fmax * i.s_top * m.eb * mg * i.punch;
            force = -eb * if auto { EB_CONVERTER } else { 1.0 };
        } else if auto && fabs(i.v) < 8.0 {
            // idle creep of a torque converter
            force = 0.06 * i.fmax * (1.0 - fabs(i.v) / 8.0);
        }
        return Output { force: sign * force + shove_f, f, brake: None };
    }
    let fe = if i.ai {
        // AI: its throttle command (x2000 = full) acts at once like a pedal, so it no longer launches on the
        // stock 1-2.5 s F ramp while the player has full force (player 2026-11-01: racers left behind at the
        // start). The ramp itself (+0x7f80) is still never written; a ramp already ahead is kept.
        f.max(i.fmax * (i.throttle / 2000.0).min(1.0)) * i.s_top
    } else {
        f = i.fmax; // instant throttle
        f * i.s_top
    };
    let mut shift_k = 1.0;
    if s.shift_t > 0.0 {
        if m.shift_floor <= 0.0 {
            return zero(f);
        }
        shift_k = m.shift_floor;
    }
    if wrong {
        if r >= 1.0 {
            return zero(f); // the gear against the roll: as before, it only brakes below its redline speed
        }
    } else if s.cut {
        return Output { force: shove_f, f, brake: None }; // rev limiter: hard / fuel cut
    }
    let mut m7 = 1.0;
    let mut tr = 1.0;
    if auto {
        // torque converter: the engine sits at least at stall, torque multiplied while it slips
        if r < m.stall {
            tr = 1.0 + (m.tr0 - 1.0) * (1.0 - r / m.stall);
            r = m.stall;
            s.rpm = r;
        }
    } else if s.gear == 1 || s.gear == -1 {
        r = r.max(m.slip);
        s.rpm = r;
    } else if r < m.idle {
        m7 = (r / m.idle).max(BOGMIN);
    }
    let tq = m.tc(r.max(m.idle)) * m.tcn();
    let mut force = tq * m7 * tr * mg * fe;
    // engine power: blend the stock force curve and the realistic constant-power cap
    let av = fabs(i.v).max(1.0);
    let fr = (vd / av).max(1.0) * fe;
    let fs = (1.0 + (50.0 - av).max(0.0) * i.accel / 40.0) * fe;
    force = force.min(fs + i.power * (fr - fs));
    // soft limiter / valve float (hard cuts switched it off above)
    force *= m.shape(if wrong { r } else { s.eng.max(r) });
    Output { force: sign * force * shift_k * i.punch + shove_f, f, brake: None }
}

/// engine revs shown / heard: the engine's own, always (in a jump too)
pub fn shown_rpm(s: &State) -> f32 {
    s.eng
}

/// the rev warning buzzer should sound (the player's car; lib.rs plays it)
pub fn buzzing(m: &Model, s: &State) -> bool {
    m.buzz_at > 0.0 && !s.blown && s.eng >= m.buzz_at
}

/// engine-sound load (stock formula input: pitch = 1 + 0.75 x load)
pub fn sound_load(m: &Model, s: &State) -> f32 {
    ((shown_rpm(s) - m.idle).max(0.0) * m.pitch_top / (1.0 - m.idle)).min(m.pitch_top)
}

/// HUD text: manual "N" "1".."6" "R"; automatic "P" "R" "N" "D 3" "2 1" "1 1"
pub fn gear_text(m: &Model, s: &State, v: f32, out: &mut [u8; 8]) {
    *out = [0; 8];
    if s.refused > 0.0 && ((s.refused / 0.1) as i32) % 2 == 0 {
        out[0] = s.refused_ch; // blink the refused gear
        return;
    }
    let digit = |g: i32| b'0' + g.clamp(0, 9) as u8;
    if m.kind == Kind::Auto {
        match s.sel {
            SEL_P => out[0] = b'P',
            SEL_R => out[0] = b'R',
            SEL_N => out[0] = b'N',
            sel => {
                out[0] = b"D21"[(sel - SEL_D) as usize];
                out[1] = b' ';
                out[2] = digit(s.gear);
            }
        }
    } else {
        let _ = v;
        out[0] = match s.gear { g if g < 0 => b'R', 0 => b'N', g => digit(g) };
    }
}
