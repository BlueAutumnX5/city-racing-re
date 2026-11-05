//! Native unit tests of the gearbox logic (`cargo test`); the real game hooks are proven in drivesim2.py.
use crate::drive::*;
use crate::model::*;

fn inp(m: &Model, v: f32, throttle: f32) -> Input {
    let _ = m;
    Input { v, accel: 2.0, f: 2000.0, fmax: 2000.0, fbase: 2000.0, throttle, pedal: 0.0, upgrade: 0, trans: 0,
            kc: 1.0, clutch: false, dt: 1.0 / 60.0, power: 1.0, ai: false, role: 0, s_top: 1.0, punch: 1.0, slope: 0.0 }
}

#[test]
fn paths_give_models() {
    assert_eq!(model_from_path(b"Data/Vehicles/08/Main.obj"), (8, false));
    assert_eq!(model_from_path(b"Data/Vehicles/03/Police.obj"), (3, true));
    assert_eq!(model_from_path(b"Data/Vehicles/09/Main.obj"), (0, false));
    assert_eq!(model_from_path(b"Data/Other/01/Main.obj"), (0, false));
}

#[test]
fn table_matches_the_spec() {
    let k = |i: usize| (MODELS[i].kind, MODELS[i].gears);
    assert_eq!(k(1), (Kind::Auto, 4)); // Galant 4AT (4th = OD)
    assert_eq!(k(2), (Kind::Manual, 5)); // Clio
    assert_eq!(k(3), (Kind::Auto, 6)); // Rover quick-shift
    assert_eq!(k(4), (Kind::Manual, 6)); // Cosmo close-ratio
    assert_eq!(k(5), (Kind::Auto, 3)); // Thunder
    assert_eq!(k(6), (Kind::Manual, 5)); // Accord kei
    assert_eq!(k(7), (Kind::Manual, 6)); // Alpha rotary
    assert_eq!(k(8), (Kind::F1, 6)); // Uber F1
    for m in &MODELS {
        for g in 1..m.gears {
            assert!(m.gt[g] > m.gt[g - 1], "{}: ratios must rise", m.name);
        }
        // top gear at the design speed pushes exactly like stock
        let g_ts = (m.gears - m.od) as i32; // the gear that meets the stock top speed
        assert!((m.tc(1.0 / m.gt_of(g_ts)) * m.tcn() - 1.0).abs() < 1e-5);
        assert!((m.mm(m.gears as i32)).abs() < 1e-6 && (m.mm(1) - 1.25).abs() < 1e-6);
    }
}

#[test]
fn automatic_shifts_up_with_speed_and_down_when_slowing() {
    let m = &MODELS[1]; // Galant 4AT
    let mut s = new_state(m);
    s.up = 1; // N -> D
    let mut i = inp(m, 0.0, 2000.0);
    step(m, &i, &mut s);
    assert_eq!((s.sel, s.gear), (SEL_D, 1));
    let mut gears = vec![];
    for k in 0..400 {
        i.v = k as f32 * 0.4; // 0 .. 160 km/h over 400 steps
        step(m, &i, &mut s);
        if gears.last() != Some(&s.gear) {
            gears.push(s.gear);
        }
    }
    assert_eq!(gears, vec![1, 2, 3, 4], "upshifts in order");
    i.throttle = 0.0;
    for k in (0..400).rev() {
        i.v = k as f32 * 0.4;
        step(m, &i, &mut s);
    }
    assert_eq!(s.gear, 1, "back in 1st when stopped");
}

#[test]
fn selector_2_and_1_hold_low_gears() {
    let m = &MODELS[3]; // Rover 6AT
    let mut s = new_state(m);
    let mut i = inp(m, 0.0, 2000.0);
    s.up = 3; // N -> D -> 2 -> 1 (one per step)
    for _ in 0..3 {
        step(m, &i, &mut s);
    }
    assert_eq!(s.sel, SEL_1);
    for k in 0..300 {
        i.v = k as f32 * 0.3;
        let o = step(m, &i, &mut s);
        assert_eq!(s.gear, 1);
        if wheel_r(m, &i, 1) >= 1.0 {
            assert_eq!(o.force, 0.0, "limiter, never an upshift in 1");
        }
    }
}

fn wheel_r(m: &Model, i: &Input, g: i32) -> f32 {
    i.v.abs() / (gear_speed(i) * m.gt_of(g))
}

#[test]
fn reverse_at_any_speed_park_only_when_slow() {
    let m = &MODELS[5]; // Thunder 3AT
    let mut s = new_state(m);
    let mut i = inp(m, 30.0, 0.0);
    s.dn = 1; // N -> R at 30 km/h: allowed (player 2026-11-01)
    step(m, &i, &mut s);
    assert_eq!((s.sel, s.gear), (SEL_R, -1));
    s.dn = 1; // R -> P while rolling: refused
    step(m, &i, &mut s);
    assert_eq!(s.sel, SEL_R, "no park pawl at 30 km/h");
    i.v = 0.0;
    i.throttle = 2000.0;
    let o = step(m, &i, &mut s);
    assert!(o.force < 0.0, "R drives backwards");
    s.dn = 1;
    i.throttle = 0.0;
    let o = step(m, &i, &mut s);
    assert_eq!(s.sel, SEL_P);
    assert_eq!(o.brake, Some(100.0));
}

#[test]
fn manual_and_f1_shift_on_keys_with_their_own_shift_times() {
    for (idx, want) in [(2usize, 0.25f32), (8, 0.10)] {
        let m = &MODELS[idx];
        let mut s = new_state(m);
        let i = inp(m, 20.0, 2000.0);
        s.up = 1;
        let o = step(m, &i, &mut s);
        assert_eq!(s.gear, 2);
        assert!((s.shift_t - (want - i.dt)).abs() < 1e-6);
        assert_eq!(o.force, 0.0, "no drive while the clutch is in");
    }
}

#[test]
fn rotary_is_weak_low_and_strong_high() {
    let rot = &MODELS[7];
    let v8 = &MODELS[1];
    // raw torque shapes (1.0 = each engine's own peak): every car is normalised at TOP_AT, so compare shapes
    let lo = |m: &Model| m.tc(0.3);
    let hi = |m: &Model| m.tc(0.95);
    assert!(lo(rot) < lo(v8) && hi(rot) > hi(v8));
    assert!(rot.eb < 0.5 * MODELS[4].eb, "barely any engine braking (under half the Cosmo's)");
}

#[test]
fn gear_text() {
    let mut t = [0u8; 8];
    let m = &MODELS[1];
    let mut s = new_state(m);
    s.sel = SEL_D;
    s.gear = 3;
    crate::drive::gear_text(m, &s, 50.0, &mut t);
    assert_eq!(&t[..3], b"D 3");
    s.sel = SEL_P;
    crate::drive::gear_text(m, &s, 0.0, &mut t);
    assert_eq!(t[0], b'P');
    let m = &MODELS[8];
    let mut s = new_state(m);
    s.gear = -1;
    crate::drive::gear_text(m, &s, -3.0, &mut t);
    assert_eq!(t[0], b'R');
}

#[test]
fn manual_reverse_at_any_speed_and_refused_park_flashes_p() {
    let mut t = [0u8; 8];
    // Clio manual from N, Z at 30 km/h: R goes in (player 2026-11-01)
    let m = &MODELS[2];
    let mut s = new_state(m);
    s.gear = 0;
    let i = inp(m, 30.0, 0.0);
    s.dn = 1;
    step(m, &i, &mut s);
    assert_eq!(s.gear, -1, "Clio: R at 30 km/h");
    // Thunder automatic rolling in R, Z towards P: refused, P blinks with R
    let m = &MODELS[5];
    let mut s = new_state(m);
    s.sel = SEL_R;
    s.gear = -1;
    s.dn = 1;
    step(m, &i, &mut s);
    assert_eq!(s.sel, SEL_R, "Thunder: still R");
    let mut shown = vec![];
    for _ in 0..45 {
        crate::drive::gear_text(m, &s, 30.0, &mut t);
        shown.push(t[0]);
        step(m, &i, &mut s);
    }
    assert!(shown.contains(&b'P') && shown.contains(&b'R'), "P blinks with R");
    assert_eq!(*shown.last().unwrap(), b'R', "back to R after the flash");
}

#[test]
fn ai_shifts_itself_and_keeps_its_throttle_ramp() {
    for idx in 1..=8usize {
        let m = &MODELS[idx];
        let mut s = new_state(m);
        let mut i = inp(m, 0.0, 1000.0);
        i.ai = true;
        i.f = 500.0; // the AI's own (stock) ramp, not yet at max
        let o = step(m, &i, &mut s);
        assert_eq!(o.f, 500.0, "{}: AI keeps its F", m.name);
        assert_eq!(s.gear, 1, "{}: AI starts in 1st (automatics in D)", m.name);
        // launch: full throttle pushes at once, whatever the ramp says (no more start-line lag)
        let launch = |f: f32, throttle: f32| {
            let mut j = inp(m, 0.0, throttle);
            j.ai = true;
            j.f = f;
            step(m, &j, &mut new_state(m)).force
        };
        assert_eq!(launch(0.0, 2000.0), launch(2000.0, 2000.0), "{}: AI full force from F = 0", m.name);
        assert_eq!(launch(0.0, 4000.0), launch(2000.0, 2000.0), "{}: x4000 is still full", m.name);
        let half = launch(0.0, 1000.0);
        assert!(half > 0.0 && half < launch(2000.0, 2000.0), "{}: half throttle = less force", m.name);
        let mut gears = vec![1];
        for k in 0..600 {
            i.v = k as f32 * 0.25; // 0 .. 150 km/h
            i.f = 2000.0;
            step(m, &i, &mut s);
            if *gears.last().unwrap() != s.gear {
                gears.push(s.gear);
            }
        }
        assert!(gears.windows(2).all(|w| w[1] == w[0] + 1) && gears.len() >= 2, "{}: {:?}", m.name, gears);
        i.v = 2.0; // stopped (after braking/reversing in the stock code)
        step(m, &i, &mut s);
        assert_eq!(s.gear, 1, "{}: straight back to 1st", m.name);
    }
}

/// Not a check: prints full-throttle drive force per car, upgrade level, gear and revs, for the
/// power/torque charts (engine_curves.py). Run: `cargo test print_curves -- --ignored --nocapture`.
/// CR_CARS = "model:base_force:base_accel,..." (the stock Main.obj values).
#[test]
#[ignore]
fn print_curves() {
    let cars = std::env::var("CR_CARS").expect("set CR_CARS");
    println!("CURVE model,level,gear,r,v_kmh,force");
    for spec in cars.split(',') {
        let p: Vec<&str> = spec.split(':').collect();
        let id: usize = p[0].parse().unwrap();
        let (fbase, accel0): (f32, f32) = (p[1].parse().unwrap(), p[2].parse().unwrap());
        let m = &MODELS[id];
        for lvl in 0..4 {
            let fmax = fbase + 200.0 * lvl as f32;
            for g in 1..=m.gears as i32 {
                for k in 10..100 {
                    let r = k as f32 / 100.0;
                    let v = r * fbase * 0.06 * m.gt_of(g); // gears sit on the stock design speed
                    let i = Input { v, accel: accel0 + 0.2 * lvl as f32, f: fmax, fmax, fbase, throttle: 2000.0,
                                    pedal: 0.0, upgrade: lvl, trans: 0, kc: 1.0, clutch: false, dt: 1.0 / 60.0,
                                    power: 1.0, ai: false, role: 0, s_top: 1.0, punch: 1.0, slope: 0.0 };
                    let mut s = new_state(m);
                    s.gear = g;
                    s.sel = SEL_D;
                    s.since = 0.0; // no automatic shift during the sample
                    let o = step(m, &i, &mut s);
                    println!("CURVE {id},{lvl},{g},{r:.2},{v:.3},{:.3}", o.force);
                }
            }
        }
    }
}


/// Engine upgrade = power only (same shift speeds); Transmission upgrade = 15 % longer gears per level. The stock
/// car meets its top speed at 95 % of the redline in top gear (overdrive cars: in the gear below, the overdrive
/// cruises at low revs); more Engine on the stock Transmission hits the rev limiter in that gear instead;
/// Transmission 3 lets even Engine 3 reach its full top speed. Wherever the
/// top speed is below the limiter, top gear still pushes the stock force there, minus at most 5 % when the top
/// speed falls right at the redline (past the torque peak, like a real car geared to its limit). Player 2026-11-01.
#[test]
fn engine_adds_power_transmission_lengthens_gears() {
    // stock Main.obj base force per model (police cars are stronger = more room)
    const FBASE: [f32; 9] = [0.0, 2000.0, 1300.0, 1700.0, 2300.0, 1800.0, 1300.0, 2200.0, 2500.0];
    for idx in 1..=8usize {
        let m = &MODELS[idx];
        let mut i = inp(m, 60.0, 2000.0);
        i.fbase = FBASE[idx];
        let r0 = wheel_r(m, &i, 2);
        i.upgrade = 3;
        assert_eq!(wheel_r(m, &i, 2), r0, "{}: Engine 3 leaves 2nd gear's revs alone", m.name);
        i.trans = 3;
        let r3 = wheel_r(m, &i, 2);
        assert!((r0 / r3 - 1.45).abs() < 1e-4, "{}: Transmission 3 = 45 % longer ({r0} -> {r3})", m.name);
        for up in 0..4 {
            for tr in 0..4 {
                let mut i = inp(m, 0.0, 2000.0);
                i.fbase = FBASE[idx];
                i.upgrade = up;
                i.trans = tr;
                i.fmax = i.fbase + 200.0 * up as f32;
                i.f = i.fmax;
                i.v = design_speed(&i);
                let g_ts = (m.gears - m.od) as i32; // top gear, or the gear below an overdrive
                let r_top = wheel_r(m, &i, g_ts);
                if up == 0 && tr == 0 {
                    assert!((r_top - TOP_AT).abs() < 1e-4, "{}: stock top speed at 95 % ({r_top})", m.name);
                }
                if tr == 0 && up > 0 {
                    assert!(r_top > 1.0, "{}: E{up} T0 hits the rev limiter in gear {g_ts} ({r_top})", m.name);
                    continue;
                }
                if tr == 3 {
                    assert!(r_top < 1.0, "{}: E{up} T3 reaches its full top speed ({r_top})", m.name);
                }
                if r_top >= 1.0 && m.od == 0 {
                    continue; // rev-limited in top gear: that is the point
                }
                // an overdrive still reaches the top speed, at low revs
                assert!(m.od == 0 || wheel_r(m, &i, m.gears as i32) < 0.9, "{}: overdrive cruises", m.name);
                let mut s = new_state(m);
                s.gear = m.gears as i32;
                s.sel = SEL_D;
                s.since = 0.0;
                let k = step(m, &i, &mut s).force / i.fmax;
                assert!((0.95..=1.0001).contains(&k), "{}: E{up} T{tr} top-gear force at top speed x{k}", m.name);
            }
        }
    }
}

/// Automatic kickdown (player 2026-11-01: "braking at gear 5 to gear-3 speed, then gas: it stays in 5th"):
/// gas held for the box's own delay -> ONE shift to the lowest gear below the upshift point; coasting down
/// follows the speed one gear at a time and never shifts back up.
#[test]
fn automatic_kicks_down_after_its_delay_and_coasts_down() {
    let rover = &MODELS[3];
    let thunder = &MODELS[5];
    for (m, from, v, want) in [(rover, 5, 45.0, 3), (thunder, 3, 40.0, 2)] {
        let mut s = new_state(m);
        s.sel = SEL_D;
        s.gear = from;
        s.since = 5.0;
        let mut i = inp(m, v, 2000.0);
        i.fbase = if m.name.starts_with("Rover") { 1700.0 } else { 1800.0 };
        let mut t = 0.0;
        while s.gear == from && t < 3.0 {
            step(m, &i, &mut s);
            t += i.dt;
        }
        assert_eq!(s.gear, want, "{}: kicks down to {want}", m.name);
        assert!((t - m.kick).abs() < 0.05, "{}: after its {} s delay (took {t:.2})", m.name, m.kick);
    }
    assert!(thunder.kick > MODELS[1].kick && MODELS[1].kick > rover.kick, "clunky 1960 box slowest, Rover quickest");
    // coast down from top speed, no gas
    let mut s = new_state(rover);
    s.sel = SEL_D;
    s.gear = 6;
    let mut i = inp(rover, 140.0, 0.0);
    i.fbase = 1700.0;
    let mut gears = vec![6];
    while i.v > 0.0 {
        i.v -= 0.05; // 3 km/h per second
        step(rover, &i, &mut s);
        if *gears.last().unwrap() != s.gear {
            gears.push(s.gear);
        }
    }
    assert!(gears.windows(2).all(|w| w[1] == w[0] - 1), "coasting: one gear at a time, never up: {gears:?}");
    assert_eq!(*gears.last().unwrap(), 1);
}

/// Engine braking (2026-11-01: was ~4 % of the drive force, 0.001-0.08 g): manual top gear at 90 % revs now
/// 0.03-0.08 g like a real car, low gears stronger, the rotary Alpha weak, automatics ~40 % (converter slip).
#[test]
fn engine_braking_is_real_strength() {
    const FBASE: [f32; 9] = [0.0, 2000.0, 1300.0, 1700.0, 2300.0, 1800.0, 1300.0, 2200.0, 2500.0];
    const ACCEL: [f32; 9] = [0.0, 2.0, 1.0, 1.5, 2.0, 1.25, 1.0, 2.25, 2.5];
    const MASS: [f32; 9] = [0.0, 1000.0, 800.0, 1200.0, 1000.0, 1200.0, 800.0, 1000.0, 1000.0];
    let decel = |idx: usize, gear: i32| {
        let m = &MODELS[idx];
        let mut i = inp(m, 0.0, 0.0);
        i.fbase = FBASE[idx];
        i.fmax = FBASE[idx];
        i.f = FBASE[idx];
        i.accel = ACCEL[idx];
        i.v = 0.9 * gear_speed(&i) * m.gt_of(gear);
        let mut s = new_state(m);
        s.gear = gear;
        s.sel = SEL_D;
        s.since = 0.0;
        -2.0 * step(m, &i, &mut s).force / MASS[idx] / 9.81
    };
    for idx in 1..=8usize {
        let m = &MODELS[idx];
        let (top, low) = (decel(idx, m.gears as i32), decel(idx, 1));
        assert!(low > top && top > 0.0, "{}: 1st brakes harder than top ({low:.3} vs {top:.3} g)", m.name);
        let (lo, hi) = match (m.kind, idx) {
            (Kind::Auto, _) => (0.008, 0.035),
            (_, 7) => (0.008, 0.025), // rotary
            _ => (0.03, 0.08),
        };
        assert!((lo..=hi).contains(&top), "{}: top gear at 90 % revs {top:.3} g", m.name);
    }
}

/// Clutch dump (player: Shift + gas, then let go) and the landing kick (gas while the driven wheels are in the
/// air, then touch down) push harder for a moment and fade; one driven wheel up = a smaller kick; the AI gets
/// the landing kick too (it has no clutch pedal). Never tested before 2026-11-01.
#[test]
fn clutch_dump_and_landing_kick() {
    let m = &MODELS[4]; // Cosmo 6MT
    let base = |ai: bool, v: f32| {
        let mut i = inp(m, v, 2000.0);
        i.ai = ai;
        let mut s = new_state(m);
        s.gear = if ai { 2 } else { 1 };
        (i, s)
    };
    // clutch dump in 1st at 5 km/h
    let (mut i, mut s) = base(false, 5.0);
    let plain = step(m, &i, &mut new_state(m)).force;
    i.clutch = true;
    for _ in 0..60 {
        step(m, &i, &mut s);
    }
    assert!(s.eng > 0.9, "clutch in + gas: revs up ({})", s.eng);
    i.clutch = false;
    let dump = step(m, &i, &mut s).force;
    assert!(dump > 1.5 * plain, "the dump kicks ({dump} vs {plain})");
    for _ in 0..60 {
        step(m, &i, &mut s);
    }
    let later = step(m, &i, &mut s).force;
    assert!(later < 1.05 * plain, "and fades within a second ({later} vs {plain})");
    // landing kick: 1 s airborne with gas, then touch down; one wheel up = smaller
    // (2nd gear at half revs: the kick is the gap between free revs and wheel revs, so near the limiter it is small)
    for ai in [false, true] {
        let land = |kc_air: f32| {
            let (mut i, mut s) = base(ai, 30.0);
            s.gear = 2;
            let plain = step(m, &i, &mut s).force; // on the ground first: engine = wheel revs
            i.kc = kc_air;
            for _ in 0..60 {
                step(m, &i, &mut s);
            }
            i.kc = 1.0;
            step(m, &i, &mut s).force / plain
        };
        let (both, one) = (land(0.0), land(0.5));
        assert!(both > 1.3 && one > 1.05 && one < both, "ai {ai}: landing kick both {both:.2}, one wheel {one:.2}");
    }
}

/// HUD widescreen fix (player 2026-11-01): at 1920x1080 the game's x scale is 2.4 but y is 1.8. A batch is
/// narrowed by 1.8/2.4 and pinned to its own edge, so the speedometer (virtual 621..801) stays in the
/// bottom-right corner, its needle pivot (711) moves with the dial, centred pieces stay centred, 4:3 is
/// untouched, and a full-width backdrop is left alone.
#[test]
fn hud_unstretch_keeps_edges_and_groups() {
    use crate::hud::*;
    let (w, sx, sy) = (1920.0f32, 2.4f32, 1.8f32);
    let quad = |xs: [f32; 4]| {
        let mut v = vec![0u8; 4 * 0x1c];
        for (i, x) in xs.iter().enumerate() {
            v[i * 0x1c..i * 0x1c + 4].copy_from_slice(&(x * sx).to_le_bytes());
        }
        v
    };
    let xs = |v: &[u8]| (0..4).map(|i| f32::from_le_bytes(v[i * 0x1c..i * 0x1c + 4].try_into().unwrap()))
        .collect::<Vec<_>>();
    // speedometer dial 621..801 virtual: right edge stays at the screen edge, width x0.75
    let mut dial = quad([621.0, 801.0, 621.0, 801.0]);
    unstretch(&mut dial, 4, 0x1c, sx, sy, w);
    let d = xs(&dial);
    assert!((d[1] - (w + (801.0 * sx - w) * 0.75)).abs() < 0.01 && ((d[1] - d[0]) - 180.0 * sy).abs() < 0.01);
    // a needle around the pivot 711 maps with the same map: its pivot stays at the dial's centre
    let mut needle = quad([700.0, 760.0, 700.0, 760.0]);
    unstretch(&mut needle, 4, 0x1c, sx, sy, w);
    let pivot = |x: f32| w + (x * sx - w) * 0.75;
    assert!((xs(&needle)[0] - pivot(700.0)).abs() < 0.01);
    assert!(((d[0] + d[1]) * 0.5 - pivot(711.0)).abs() < 0.01, "dial centre = needle pivot");
    // centred piece stays centred; a left piece keeps x = 0
    let mut mid = quad([350.0, 450.0, 350.0, 450.0]);
    unstretch(&mut mid, 4, 0x1c, sx, sy, w);
    let m = xs(&mid);
    assert!(((m[0] + m[1]) * 0.5 - w * 0.5).abs() < 0.01);
    let mut left = quad([0.0, 120.0, 0.0, 120.0]);
    unstretch(&mut left, 4, 0x1c, sx, sy, w);
    assert_eq!(xs(&left)[0], 0.0);
    // full-width backdrop and a 4:3 screen: untouched
    let mut full = quad([0.0, 800.0, 0.0, 800.0]);
    let before = full.clone();
    unstretch(&mut full, 4, 0x1c, sx, sy, w);
    assert_eq!(full, before);
    let mut four3 = quad([621.0, 801.0, 621.0, 801.0]);
    let before = four3.clone();
    unstretch(&mut four3, 4, 0x1c, 1.6, 1.6, 1280.0);
    assert_eq!(four3, before);
    assert_eq!((prim_verts(4, 2), prim_verts(5, 2), prim_verts(6, 3)), (6, 4, 5));
}

/// rpm dial: the needle reads rpm / dial max over 270 degrees on every car's own face (redline where the
/// red zone starts), and the face files are Main_01..08.dds.
#[test]
fn rpm_dial_needle_and_faces() {
    use crate::hud::*;
    for m in 1..=8usize {
        let (red, dial) = DIAL[m];
        assert!((dial_angle(m, 0.0)).abs() < 1e-6);
        assert!((dial_angle(m, 1.0) - red / dial * ARC).abs() < 1e-5, "redline at the red zone");
        assert_eq!(dial_angle(m, 1.3), ARC, "an over-rev stops at the dial's end");
        let mut name = [0u8; 48];
        face_name(m, &mut name);
        let want = format!("Data/Interface/HUD/SpeedBar/Main_{m:02}.dds");
        assert_eq!(&name[..want.len()], want.as_bytes());
        assert_eq!(name[want.len()], 0);
    }
    assert_eq!(DIAL[7], (10000.0, 11000.0), "Alpha: player's numbers");
    assert_eq!((DIAL[3].1, DIAL[4].1, DIAL[5].1, DIAL[8].1), (6500.0, 8500.0, 5500.0, 9500.0));
}

/// The Transmission upgrade no longer adds launch (player 2026-11-01): its +0.2 accel per level is taken back
/// out; the damage reduction in the game's value stays.
#[test]
fn transmission_adds_no_launch() {
    assert_eq!(launch_accel(2.0, 2.0, 0), 2.0);
    assert!((launch_accel(2.6, 2.0, 3) - 2.0).abs() < 1e-6, "T3 on a 2.0 car: back to 2.0");
    assert!((launch_accel(2.6 * 0.7, 2.0, 3) - 2.0 * 0.7).abs() < 1e-6, "damage (x0.7) kept");
    assert_eq!(launch_accel(1.5, 0.0, 2), 1.5, "no base value: left alone");
    // in a drive step: T3 pulls exactly like T0 in 1st gear
    let m = &MODELS[4];
    let force = |trans: i32| {
        let mut i = inp(m, 10.0, 2000.0);
        i.trans = trans;
        i.accel = launch_accel(2.0 + 0.2 * trans as f32, 2.0, trans);
        let mut s = new_state(m);
        s.gear = 1;
        step(m, &i, &mut s).force
    };
    assert_eq!(force(0), force(3), "T3 launch = T0 launch");
}

/// Human-like AI shifting (player 2026-11-01): one driver per car, skill by role, varying shift to shift.
#[test]
fn ai_drives_like_a_human() {
    // first upshift from 1st with the speed rising 6 km/h/s: (revs at the shift, the shift's duration)
    let first_up = |m: &Model, role: u8, seed: u32, t: f32| {
        let mut s = new_state(m);
        s.rng = seed;
        s.gear = 1;
        let mut i = inp(m, 5.0, 2000.0 * t);
        i.ai = true;
        i.role = role;
        let g_v = 2000.0 * 0.06 * m.gt_of(1);
        loop {
            step(m, &i, &mut s);
            if s.gear == 2 {
                return (i.v / g_v, s.shift_t, s.skill);
            }
            i.v += 0.1;
            assert!(i.v < 1.2 * g_v, "{} role {role}: never shifted out of 1st", m.name);
        }
    };
    let mean = |x: &[f32]| x.iter().sum::<f32>() / x.len() as f32;
    for idx in [2usize, 4, 6, 7, 8] {
        let m = &MODELS[idx];
        let runs = |role: u8, t: f32| (1..=40u32).map(|k| first_up(m, role, k * 7919, t)).collect::<Vec<_>>();
        let racers = runs(ROLE_RACER, 1.0);
        let traffic = runs(ROLE_TRAFFIC, 1.0);
        let cruising = runs(ROLE_TRAFFIC, 0.3);
        let r_rac: Vec<f32> = racers.iter().map(|x| x.0).collect();
        let r_trf: Vec<f32> = traffic.iter().map(|x| x.0).collect();
        let r_cru: Vec<f32> = cruising.iter().map(|x| x.0).collect();
        // racers rev it out (a slow reaction may touch the limiter), traffic shifts earlier, cruising short-shifts
        assert!(r_rac.iter().all(|&r| (0.85..=1.06).contains(&r)), "{}: racer shift revs {r_rac:?}", m.name);
        assert!(mean(&r_trf) < mean(&r_rac) - 0.04, "{}: traffic {} vs racers {}", m.name, mean(&r_trf), mean(&r_rac));
        assert!(r_cru.iter().all(|&r| r < 0.60) && mean(&r_cru) < 0.53, "{}: light-throttle traffic short-shifts {r_cru:?}",
                m.name);
        // every driver is different, the same driver is the same
        let spread = r_rac.iter().cloned().fold(0.0f32, f32::max) - r_rac.iter().cloned().fold(9.0f32, f32::min);
        assert!(spread > 0.02, "{}: racers all alike ({spread})", m.name);
        assert_eq!(first_up(m, ROLE_RACER, 4242, 1.0).0, first_up(m, ROLE_RACER, 4242, 1.0).0);
        // skill by role
        assert!(racers.iter().all(|x| (0.55..=1.0).contains(&x.2)) && traffic.iter().all(|x| x.2 <= 0.35));
        let t_rac: Vec<f32> = racers.iter().map(|x| x.1).collect();
        let t_trf: Vec<f32> = traffic.iter().map(|x| x.1).collect();
        if m.kind == Kind::Manual {
            // a person's shift: racers about the box's time, traffic slower, sloppy drivers fumble now and then
            assert!(mean(&t_trf) > 1.2 * mean(&t_rac), "{}: shift time traffic {} racers {}", m.name,
                    mean(&t_trf), mean(&t_rac));
            assert!((0.8 * m.shift_time..1.3 * m.shift_time).contains(&mean(&t_rac)), "{}: racers {}", m.name,
                    mean(&t_rac));
            let fumbles = (1..=400u32).filter(|&k| first_up(m, ROLE_TRAFFIC, k * 104_729, 1.0).1
                                              > 1.9 * 1.25 * m.shift_time).count();
            assert!((4..=60).contains(&fumbles), "{}: {fumbles}/400 traffic shifts fumbled", m.name);
        } else {
            // the F1 robot shifts in its own time whoever drives
            assert!(t_rac.iter().chain(&t_trf).all(|&t| t == m.shift_time), "{}: F1 shift times", m.name);
        }
    }
    // braking from high in 5th: one gear at a time while the stock code brakes, never into over-revs, 1st at
    // the stop - so it comes off the brake in a gear that pulls
    let m = &MODELS[4]; // Cosmo 6MT
    for role in [ROLE_RACER, ROLE_TRAFFIC] {
        for seed in [11u32, 222, 3333] {
            let mut s = new_state(m);
            s.rng = seed;
            s.gear = 5;
            let mut i = inp(m, 0.8 * 120.0 * m.gt_of(5), 0.0);
            i.ai = true;
            i.role = role;
            i.pedal = 1.0;
            let mut seen = vec![5];
            while i.v > 0.0 {
                ai_braking(m, &i, &mut s);
                if *seen.last().unwrap() != s.gear {
                    let r = i.v / (120.0 * m.gt_of(s.gear));
                    assert!(r < 0.9 || s.gear == 1, "role {role}: downshift to {} at {r:.2} revs", s.gear);
                    seen.push(s.gear);
                }
                i.v -= 0.4; // ~0.7 g
            }
            assert_eq!(*seen.last().unwrap(), 1, "role {role}: 1st at the stop {seen:?}");
            assert!(seen.windows(2).all(|w| w[1] < w[0]), "role {role}: only down while braking {seen:?}");
            // a racer works down gear by gear; a lazy driver braking hard may skip (5 -> 2), like people do
            if role == ROLE_RACER {
                assert!(seen.windows(2).filter(|w| w[0] - w[1] == 1).count() >= 3,
                        "seed {seed}: a racer downshifts gear by gear {seen:?}");
            }
        }
    }
    // an automatic's shift point follows the throttle; it never hunts at part throttle
    let m = &MODELS[1]; // Galant 4AT
    let half = first_up(m, ROLE_TRAFFIC, 5, 0.5).0;
    let full = first_up(m, ROLE_TRAFFIC, 5, 1.0).0;
    assert!(half < full - 0.1, "Galant: half throttle {half:.2} vs full {full:.2}");
}

/// Realistic gearing (player 2026-11-01): top speed halfway to the real car's, every acceleration x k with the
/// top speed held - engine x k plus (1 - k) of the game's linear drag (v / 0.06) given back.
#[test]
fn realistic_gearing_scales_acceleration_and_holds_top_speed() {
    // halfway top speeds from the stock base forces; police +10 % real; Off = untouched
    let (s, k) = real_scale(1, 2000.0, false, MODE_HALF);
    assert!((s * 120.0 - 155.0).abs() < 0.01 && k == REAL[1].half, "Galant {s} {k}");
    let (sp, _) = real_scale(1, 2000.0, true, MODE_HALF);
    assert!((sp * 120.0 - (120.0 + 209.0) / 2.0).abs() < 0.01, "Galant police {}", sp * 120.0);
    assert_eq!(real_scale(1, 2000.0, false, MODE_REAL).1, REAL[1].real);
    assert_eq!(real_scale(1, 2000.0, false, MODE_OFF), (1.0, 1.0));
    assert_eq!(real_scale(0, 2000.0, false, MODE_HALF), (1.0, 1.0), "unknown car untouched");
    for idx in 1..=8usize {
        let m = &MODELS[idx];
        let fbase = 2000.0;
        let (s_top, _) = real_scale(idx, fbase, false, MODE_HALF);
        for k in [1.0f32, 0.6, 0.3] {
            // what is left after the game's drag AND gravity along the slope (sin pitch)
            let net = |v: f32, g: i32, gas: f32, k: f32, slope: f32| {
                let mut i = inp(m, v, gas);
                i.fbase = fbase;
                i.fmax = fbase;
                i.s_top = s_top;
                i.punch = k;
                i.slope = slope;
                let mut st = new_state(m);
                st.gear = g;
                st.sel = SEL_D;
                st.since = 0.0;
                step(m, &i, &mut st).force - v * DRAG_PER_KMH - FORCE_PER_MS2 * GRAVITY * slope
            };
            for g in 1..=m.gears as i32 {
                for v in [10.0f32, 40.0, 80.0, 130.0] {
                    for gas in [2000.0f32, 0.0] {
                        for slope in [0.0f32, 0.31, -0.2] {
                            let (a1, ak) = (net(v, g, gas, 1.0, slope), net(v, g, gas, k, slope));
                            assert!((ak - k * a1).abs() <= 1e-3 * a1.abs().max(1.0),
                                    "{} g{g} {v} km/h gas {gas} slope {slope}: net {ak} vs k x {a1}", m.name);
                        }
                    }
                }
            }
            // an 18 deg climb in 1st at 10 km/h: whatever the original car had left, this one has k x it -
            // never less than k x (so a hill the original climbs is climbed)
            let up = net(10.0, 1, 2000.0, k, 0.31);
            assert!((up - k * net(10.0, 1, 2000.0, 1.0, 0.31)).abs() < 1e-2 * up.abs().max(1.0), "{} hill", m.name);
        }
        // top speed: the new design speed is where full throttle in the top-speed gear meets the drag
        let vd = 2000.0 * 0.06 * s_top;
        let g = (m.gears - m.od) as i32;
        let mut i = inp(m, vd, 2000.0);
        i.fmax = 2000.0;
        i.s_top = s_top;
        i.punch = 0.5;
        let mut st = new_state(m);
        st.gear = g;
        st.sel = SEL_D;
        let left = step(m, &i, &mut st).force - vd * DRAG_PER_KMH;
        assert!(left.abs() < 0.03 * vd * DRAG_PER_KMH, "{}: at {vd:.0} km/h {left:.0} left over", m.name);
    }
}

// ---- the engine as a spinning mass (player 2026-11-02) ----

/// free revs, neutral, floored for `secs` at frame time dt: (time to 50 % and 95 % of the way idle -> redline,
/// lowest and highest revs over the last second, limiter cuts per second over the last second)
fn free_rev(m: &Model, dt: f32, secs: f32) -> (f32, f32, f32, f32, f32) {
    let mut s = new_state(m);
    s.gear = 0;
    s.sel = SEL_N;
    let mut i = inp(m, 0.0, 2000.0);
    i.dt = dt;
    let (half, top) = (m.idle + 0.5 * (1.0 - m.idle), m.idle + 0.95 * (1.0 - m.idle));
    let (mut t_half, mut t_top) = (f32::NAN, f32::NAN);
    let (mut lo, mut hi, mut cuts0) = (f32::MAX, f32::MIN, 0);
    let n = (secs / dt) as usize;
    let last = n - (1.0 / dt) as usize;
    for k in 0..n {
        if k == last {
            cuts0 = s.cuts;
        }
        step(m, &i, &mut s);
        let t = (k + 1) as f32 * dt;
        if t_half.is_nan() && s.eng >= half { t_half = t; }
        if t_top.is_nan() && s.eng >= top { t_top = t; }
        if k >= last {
            lo = lo.min(s.eng);
            hi = hi.max(s.eng);
        }
    }
    (t_half, t_top, lo, hi, (s.cuts - cuts0) as f32)
}

/// Neutral, floored: the revs CLIMB (torque, not the old ease that slowed near the top and never arrived) in about
/// the car's rev_up, then each car's own limiter: hard cuts bounce fast and shallow, the Galant's fuel cut deep and
/// slow, the Rover's soft limiter hardly moves, the Thunder (none) runs past the redline into valve float and
/// stays there. The same at 30 and 144 FPS. Run with --nocapture for the table.
#[test]
fn free_revs_climb_and_bounce_off_each_cars_limiter() {
    use crate::model::Limiter;
    println!("model            rise  half/rise  last-second revs     cuts/s  (30 FPS)");
    for (idx, m) in MODELS.iter().enumerate().skip(1) {
        let (t_half, t_top, lo, hi, cuts) = free_rev(m, 1.0 / 144.0, 4.0);
        let (_, _, lo30, hi30, cuts30) = free_rev(m, 1.0 / 30.0, 4.0);
        println!("{idx} {:22} {t_top:.2}s  {:.2}   {lo:.3}..{hi:.3}  {cuts:4.0}   ({lo30:.3}..{hi30:.3} {cuts30:.0})",
                 m.name, t_half / t_top);
        assert!((t_top / m.rev_up - 0.95).abs() < 0.3, "{}: idle -> redline {t_top:.2} s vs {}", m.name, m.rev_up);
        let shape = t_half / t_top;
        assert!((0.35..0.7).contains(&shape), "{}: climbs steadily (half way at {shape:.2} of the time)", m.name);
        match m.limiter {
            Limiter::Hard => {
                assert!(hi < 1.015 && lo > 0.99 - m.lim_depth, "{}: hard cut {lo:.3}..{hi:.3}", m.name);
                assert!((6.0..30.0).contains(&cuts), "{}: hard cut bounces {cuts} /s", m.name);
            }
            Limiter::FuelCut => {
                assert!(hi < 1.015 && lo < 1.0 - 0.8 * m.lim_depth, "{}: fuel cut {lo:.3}..{hi:.3}", m.name);
                assert!((2.5..8.0).contains(&cuts), "{}: fuel cut bounces {cuts} /s", m.name);
            }
            Limiter::Soft => assert!(hi <= 1.0 && hi - lo < 0.01 && hi > 0.97, "{}: soft {lo:.3}..{hi:.3}", m.name),
            Limiter::None => assert!(lo > 1.02 && hi < 1.12 && hi - lo < 0.01, "{}: valve float {lo:.3}..{hi:.3}",
                                     m.name),
        }
        // 30 FPS: the engine runs in 2 ms sub-steps, so the same bounce
        assert!((cuts30 - cuts).abs() <= 0.25 * cuts + 1.0, "{}: {cuts30} cuts/s at 30 FPS vs {cuts}", m.name);
        assert!((hi30 - hi).abs() < 0.01 && (lo30 - lo).abs() < 0.02, "{}: 30 FPS range", m.name);
    }
}

/// Player 2026-11-02: "airborne, let go of the gas, the RPM still follows the airspeed; higher if I shift down".
/// Now in the air the driven wheels spin with the engine: off the gas the revs fall toward idle whatever the speed,
/// a downshift does not move them, the gas revs them to the limiter.
#[test]
fn in_the_air_the_revs_are_the_engines() {
    let m = &MODELS[4]; // Cosmo
    let mut i = inp(m, 0.0, 2000.0);
    let mut s = new_state(m);
    s.gear = 4;
    i.v = 0.8 * gear_speed(&i) * m.gt_of(4);
    for _ in 0..30 {
        step(m, &i, &mut s);
    }
    assert!((shown_rpm(&s) - 0.8).abs() < 0.03, "on the ground: the wheels' revs ({})", shown_rpm(&s));
    i.kc = 0.0;
    i.throttle = 0.0;
    for _ in 0..90 {
        step(m, &i, &mut s); // 1.5 s in the air, same airspeed
    }
    assert!(shown_rpm(&s) < 0.3, "lifted in the air: toward idle ({})", shown_rpm(&s));
    let before = shown_rpm(&s);
    s.dn = 1;
    step(m, &i, &mut s);
    assert_eq!(s.gear, 3);
    assert!(shown_rpm(&s) <= before + 0.01, "a downshift in the air does not raise them ({before} -> {})",
            shown_rpm(&s));
    i.throttle = 2000.0;
    for _ in 0..60 {
        step(m, &i, &mut s);
    }
    assert!(shown_rpm(&s) > 0.95, "gas in the air: up to the limiter ({})", shown_rpm(&s));
}

/// the extra force over `secs` against the same car with its engine already at the wheels' revs: the momentum
/// (force x s) a landing / clutch dump / neutral drop added
fn extra_impulse(m: &Model, i: &Input, s: &State, secs: f32) -> f32 {
    let (mut a, mut b) = (*s, *s);
    b.eng = 0.0; // steady twin: snap it to the wheels on its first step
    b.free = false;
    let mut total = 0.0;
    for k in 0..(secs / i.dt) as usize {
        let fa = step(m, i, &mut a).force;
        if k == 0 {
            b.eng = a.rpm.max(m.idle);
        }
        let fb = step(m, i, &mut b).force;
        total += (fa - fb) * i.dt;
    }
    total
}

/// Landing (player 2026-11-02: "lurch, try to make it realistic"; and the forward shove: "Realistic or not?").
/// The engine's spinning mass meets the car: revved up in the air it SHOVES the car on, lifted to idle it DRAGS it
/// back - the same momentum both ways, whether or not the gas is down, much bigger in 1st than in top gear (the
/// flywheel seen through a short gear is heavy), at most what the flywheel actually held.
#[test]
fn landing_shoves_or_drags_by_the_flywheels_momentum() {
    let m = &MODELS[4]; // Cosmo
    let jump = |gear: i32, r: f32, gas_air: bool, gas_land: bool| {
        let mut i = inp(m, 0.0, 2000.0);
        i.v = r * gear_speed(&i) * m.gt_of(gear);
        let mut s = new_state(m);
        s.gear = gear;
        for _ in 0..30 {
            step(m, &i, &mut s);
        }
        i.kc = 0.0;
        i.throttle = if gas_air { 2000.0 } else { 0.0 };
        for _ in 0..60 {
            step(m, &i, &mut s);
        }
        i.kc = 1.0;
        i.throttle = if gas_land { 2000.0 } else { 0.0 };
        let gap = s.eng - s.rpm.max(m.idle);
        (extra_impulse(m, &i, &s, 1.0), gap, i.v)
    };
    for gas_land in [false, true] {
        let (lurch, gap, _) = jump(2, 0.7, false, gas_land);
        assert!(gap < -0.3 && lurch < 0.0, "lifted in the air: a lurch back (gap {gap:.2}, {lurch:.0})");
        let (shove, gap, _) = jump(2, 0.5, true, gas_land);
        assert!(gap > 0.3 && shove > 0.0, "revved in the air: a shove (gap {gap:.2}, {shove:.0})");
    }
    // momentum: ~ J/(1+J) x the rev gap in km/h, 600 units = 1 m/s^2
    let (low, gap1, _) = jump(1, 0.3, true, true);
    let (top, gap6, _) = jump(6, 0.3, true, true);
    let i = inp(m, 0.0, 2000.0);
    let kmh = |g: i32, gap: f32| {
        let j = m.inertia_at(g);
        j / (1.0 + j) * gap * gear_speed(&i) * m.gt_of(g) / 3.6 * FORCE_PER_MS2
    };
    println!("1st: {low:.0} (flywheel {:.0}), 6th: {top:.0} (flywheel {:.0})", kmh(1, gap1), kmh(6, gap6));
    // the flywheel's momentum at the wheels goes with the gear ratio (its spin x ratio / wheel radius): 1st here is
    // 3.4x 6th, a little less as 1st's heavy flywheel slows the car with it (J / (1 + J))
    assert!(low > 2.2 * top, "1st shoves much harder than top ({low:.0} vs {top:.0})");
    assert!(low < 1.1 * kmh(1, gap1) && low > 0.5 * kmh(1, gap1), "1st: the flywheel's momentum");
}

/// Player 2026-11-02: "the car jerks forward if we rev the engine and put it in Drive or Reverse". A neutral drop:
/// the converter takes up the revved engine - forward in D, backward in R (half the flywheel's shove gets
/// through the fluid coupling; the heavy V8 flywheel makes up the rest).
#[test]
fn neutral_drop_shoves_the_way_of_the_gear() {
    let m = &MODELS[1]; // Galant automatic
    let drop = |press_up: bool, rev: bool| {
        let mut i = inp(m, 0.0, if rev { 2000.0 } else { 0.0 });
        let mut s = new_state(m);
        s.sel = SEL_N;
        for _ in 0..90 {
            step(m, &i, &mut s);
        }
        if press_up { s.up = 1 } else { s.dn = 1 }
        i.throttle = 2000.0;
        let mut total = 0.0;
        for _ in 0..30 {
            total += step(m, &i, &mut s).force * i.dt;
        }
        (total, s.sel)
    };
    let (d_rev, sel) = drop(true, true);
    let (d_cold, _) = drop(true, false);
    assert_eq!(sel, SEL_D);
    // 600 units x s = 1 m/s: a revved drop adds a few km/h in a jolt on top of the launch
    assert!(d_rev - d_cold > 300.0, "revved N -> D shoves forward ({d_rev:.0} vs {d_cold:.0})");
    let (r_rev, sel) = drop(false, true);
    let (r_cold, _) = drop(false, false);
    assert_eq!(sel, SEL_R);
    assert!(r_rev - r_cold < -300.0, "revved N -> R shoves backward ({r_rev:.0} vs {r_cold:.0})");
    // the same rev gap through a clutch (Clio, dump in 1st) pushes harder than through the converter
    let c = &MODELS[2];
    let mut i = inp(c, 0.0, 2000.0);
    i.clutch = true;
    let mut s = new_state(c);
    for _ in 0..90 {
        step(c, &i, &mut s);
    }
    i.clutch = false;
    let dump = extra_impulse(c, &i, &s, 0.5);
    println!("neutral drop D {:.0} / R {:.0}, Clio clutch dump {dump:.0}", d_rev - d_cold, r_rev - r_cold);
    assert!(dump > 0.0);
}

/// In gear at the limiter the power pulses on and off and the revs flutter a little (the driveline's give); the
/// Thunder (no limiter) held in 1 just runs out of breath past the redline; in D it shifts at 80 % anyway.
#[test]
fn in_gear_limiter_pulses_and_the_thunder_fades() {
    let c = &MODELS[2]; // Clio, hard cut
    let mut i = inp(c, 0.0, 2000.0);
    let mut s = new_state(c);
    s.gear = 2;
    i.v = 1.0 * gear_speed(&i) * c.gt_of(2);
    let (mut on, mut lo, mut hi, mut flips, mut last) = (0, f32::MAX, f32::MIN, 0, true);
    for k in 0..120 {
        let o = step(c, &i, &mut s);
        if k >= 60 {
            let p = o.force > 0.0;
            on += p as i32;
            flips += (p != last) as i32;
            last = p;
            lo = lo.min(s.eng);
            hi = hi.max(s.eng);
        }
    }
    println!("Clio 2nd on the limiter: power on {on}/60 frames, {flips} flips, revs {lo:.3}..{hi:.3}");
    assert!(flips >= 6 && on > 10 && on < 55, "the power pulses ({on} on, {flips} flips)");
    assert!(hi - lo > 0.003 && hi - lo < 0.04 && hi < 1.02, "the needle flutters ({lo:.3}..{hi:.3})");

    let m = &MODELS[5]; // Thunder held in 1
    let force = |r: f32| {
        let mut i = inp(m, 0.0, 2000.0);
        i.v = r * gear_speed(&i) * m.gt_of(1);
        let mut s = new_state(m);
        s.sel = SEL_1;
        s.gear = 1;
        let mut f = 0.0;
        for _ in 0..30 {
            f = step(m, &i, &mut s).force;
        }
        (f, s.gear)
    };
    let (f95, f105, f112, f116) = (force(0.95).0, force(1.05).0, force(1.12).0, force(1.16).0);
    println!("Thunder in 1: {f95:.0} {f105:.0} {f112:.0} {f116:.0}");
    assert!(f105 > 0.5 * f95, "past the redline it still pulls ({f105:.0} vs {f95:.0})");
    assert!(f112 < 0.6 * f95 && f112 > 0.0, "valve float: the power falls away ({f112:.0})");
    assert_eq!(f116, 0.0, "nothing left");
    assert_eq!(force(1.12).1, 1, "held in 1: no upshift");
}

/// Over-revving wears the engine out in real time (player 2026-11-02): the Thunder floating its valves in 1 lasts
/// minutes, not seconds; a money shift 30 % over is gone at once; on the limiter (or in neutral) nothing wears.
/// Blown: no drive, the revs wind down to nothing.
#[test]
fn over_revving_wears_the_engine_out_in_real_time() {
    let m = &MODELS[5];
    let mut i = inp(m, 0.0, 2000.0);
    i.v = 1.12 * gear_speed(&i) * m.gt_of(1);
    let mut s = new_state(m);
    s.sel = SEL_1;
    s.gear = 1;
    let mut t = 0.0;
    while !s.blown && t < 1200.0 {
        step(m, &i, &mut s);
        t += i.dt;
    }
    println!("Thunder floating its valves in 1 (r 1.12 at the wheels): blown after {t:.0} s");
    assert!((60.0..600.0).contains(&t), "minutes, not seconds ({t:.0} s)");
    assert_eq!(step(m, &i, &mut s).force, 0.0, "blown: no drive");
    for _ in 0..180 {
        step(m, &i, &mut s);
    }
    assert!(shown_rpm(&s) < 0.05 && !buzzing(m, &s), "it winds down to nothing ({})", shown_rpm(&s));

    // money shift: 3rd -> 2nd at a speed that is 130 % in 2nd
    let c = &MODELS[4];
    let mut i = inp(c, 0.0, 2000.0);
    i.v = 1.3 * gear_speed(&i) * c.gt_of(2);
    let mut s = new_state(c);
    s.gear = 3;
    step(c, &i, &mut s);
    s.dn = 1;
    for _ in 0..30 {
        step(c, &i, &mut s);
    }
    assert!(s.blown, "money shift 30 % over: gone within half a second (wear {})", s.wear);

    // on the limiter: no wear, a minute in neutral or in gear
    for (idx, gear) in [(2usize, 0), (4, 2), (3, 1), (1, 1)] {
        let m = &MODELS[idx];
        let mut i = inp(m, 0.0, 2000.0);
        let mut s = new_state(m);
        s.gear = gear;
        s.sel = if gear == 0 { SEL_N } else { SEL_1 };
        i.v = if gear == 0 { 0.0 } else { 1.0 * gear_speed(&i) * m.gt_of(gear) };
        for _ in 0..3600 {
            step(m, &i, &mut s);
        }
        assert_eq!(s.wear, 0.0, "{} gear {gear}: the limiter protects it", m.name);
    }
}

/// the rotary's rev warning buzzer (player 2026-11-02): from 90 % of the redline, only the Alpha
#[test]
fn rotary_buzzer() {
    for (idx, m) in MODELS.iter().enumerate() {
        let mut s = new_state(m);
        s.eng = 0.91;
        assert_eq!(buzzing(m, &s), idx == 7, "{}", m.name);
        s.eng = 0.89;
        assert!(!buzzing(m, &s));
    }
}
