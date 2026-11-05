//! HUD widescreen fix (player 2026-11-01: "the in-game GUI is still stretched").
//! The game lays its 2D interface out on a virtual 800x600 canvas and scales x by width/800 but y by
//! height/600 (renderer 0x0255d7f0: +0x42004 / +0x42014), so on a 16:9 screen every HUD piece is 33 % too
//! wide and the round speedometer is an oval. While the driving HUD draws (racemod `hudfix` wraps the call
//! to 0x00467eb0), each pre-transformed batch (one quad, one needle, one text string) is narrowed to the
//! height scale and pinned to the edge it was designed against: virtual x < 800/3 -> the left edge, > 1600/3
//! -> the right edge, else the centre. Every piece of one HUD group (dial, needles, digits, gear box) lands
//! in the same zone, so they share one map and stay lined up. Full-width pieces are left alone.

/// virtual canvas width the game designs for
pub const VIRTUAL_W: f32 = 800.0;

/// where a batch is pinned: x' = a + (x - a) * k
pub fn anchor(centre_virtual: f32, w: f32) -> f32 {
    if centre_virtual < VIRTUAL_W / 3.0 {
        0.0
    } else if centre_virtual > 2.0 * VIRTUAL_W / 3.0 {
        w
    } else {
        w * 0.5
    }
}

/// Narrow the x of `n` vertices (`stride` bytes each, x = the first float) in place. sx / sy = the game's
/// x / y scales, w = screen width in pixels. Nothing happens on a 4:3 (or taller) screen or for a batch
/// that spans (almost) the whole width.
pub fn unstretch(v: &mut [u8], n: usize, stride: usize, sx: f32, sy: f32, w: f32) {
    if sx <= 0.0 || sy <= 0.0 || w <= 0.0 || n == 0 || stride < 4 || n * stride > v.len() {
        return;
    }
    let k = sy / sx;
    if k >= 0.999 {
        return;
    }
    let x = |v: &[u8], i: usize| f32::from_le_bytes([v[i * stride], v[i * stride + 1], v[i * stride + 2],
                                                     v[i * stride + 3]]);
    let (mut lo, mut hi) = (f32::MAX, f32::MIN);
    for i in 0..n {
        let xi = x(v, i);
        lo = lo.min(xi);
        hi = hi.max(xi);
    }
    if hi - lo >= 0.9 * w {
        return;
    }
    let a = anchor((lo + hi) * 0.5 / sx, w);
    for i in 0..n {
        let nx = a + (x(v, i) - a) * k;
        v[i * stride..i * stride + 4].copy_from_slice(&nx.to_le_bytes());
    }
}

/// vertices used by a DrawPrimitiveUP call
pub fn prim_verts(prim: u32, count: u32) -> usize {
    let c = count as usize;
    match prim {
        1 => c,     // point list
        2 => 2 * c, // line list
        3 => c + 1, // line strip
        4 => 3 * c, // triangle list
        5 | 6 => c + 2, // strip / fan
        _ => 0,
    }
}

// ---- rpm dial (racemod `rpmdial`, player 2026-11-01): one speedometer face per car (dial_faces.py paints
// Main_0X.dds: olive arc, red zone redline..dial max, numbers x1000 rpm), swapped in by cr_hud_begin, and the
// small needle (the tachometer) turned to rpm / dial max over the arc's 270 degrees.

/// (redline, dial max) rpm per model 1..=8 (index 0 = an unknown car); the same numbers as dial_faces.py and
/// engine_curves.py (player 2026-11-01: Alpha 10000/11000, dial max Rover 6500, Cosmo 8500, Thunder 5500,
/// Uber 9500)
pub const DIAL: [(f32, f32); 9] = [(6000.0, 7000.0), (5000.0, 6000.0), (7000.0, 8000.0), (5500.0, 6500.0),
                                   (7500.0, 8500.0), (4800.0, 5500.0), (8000.0, 9000.0), (10000.0, 11000.0),
                                   (8500.0, 9500.0)];
/// the arc's sweep (radians): 270 degrees from bottom-left over the top
pub const ARC: f32 = 4.712_389;

/// small-needle angle for revs r (1.0 = redline) on model `model`'s face: 0 rpm at the arc's start, the dial
/// max at its end (an over-rev stops there)
pub fn dial_angle(model: usize, r: f32) -> f32 {
    let (red, dial) = DIAL[if model < DIAL.len() { model } else { 0 }];
    (r * red / dial).clamp(0.0, 1.0) * ARC
}

/// the face's file, NUL-terminated: Data/Interface/HUD/SpeedBar/Main_0X.dds
pub fn face_name(model: usize, out: &mut [u8; 48]) {
    let s = b"Data/Interface/HUD/SpeedBar/Main_00.dds";
    out[..s.len()].copy_from_slice(s);
    out[33] = b'0' + (model / 10 % 10) as u8;
    out[34] = b'0' + (model % 10) as u8;
    out[s.len()] = 0;
}
