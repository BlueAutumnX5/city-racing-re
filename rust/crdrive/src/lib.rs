//! crdrive.dll - City Racing drivetrain, loaded into game.exe (32-bit) by racemod's `drivetrain` extra.
//! racemod's asm "doors" at the hook sites call these `extern "C"` exports; the DLL links against nothing
//! (no CRT, no imports) and reads/writes the game's memory at fixed addresses (game.exe has no ASLR).
#![cfg_attr(all(not(test), target_arch = "x86"), no_std)]

pub mod buzz;
pub mod drive;
pub mod hud;
pub mod model;

use drive::{Input, State};
use model::{Kind, MODELS};
#[cfg(all(not(test), target_arch = "x86"))]
use core::ffi::c_void;

// ---- game.exe addresses (see memory city-racing-drivetrain / racemod.py) ----
const PLAYER: u32 = 0x012D_0C88; // player's car pointer
const FRAME_DT: u32 = 0x012D_04A8; // frame time, s
const SHIFT_HELD: u32 = 0x012D_0C0C; // the game's own "Shift is down" flag
const RUNNING: u32 = 0x0059_0448; // 1 = playing (not paused)
const SETTINGS: u32 = 0x0270_6300; // written by racemod: b"CRDV", power (f32 0..1), AI gearboxes (u32 1 = on)
const SETTINGS_MAGIC: u32 = u32::from_le_bytes(*b"CRDV");
// car struct
const C_PATH: u32 = 0x8c8; // the car's .obj path, copied in by the constructor (the save writes it)
const C_V: u32 = 0x7f70;
const C_VD: u32 = 0x7f74;
const C_FWD_Y: u32 = 0x24; // the car's forward unit vector (+0x20 x, +0x24 y = sin pitch, +0x28 z), live-checked 11-01 // design speed = Fmax x 0.06: the AI's target speed (and crash damage's scale)
const C_ACCEL: u32 = 0x7f78;
const C_ACCEL_BASE: u32 = 0x7f7c; // the .obj value, before upgrades and damage
const C_F: u32 = 0x7f80;
const C_FMAX: u32 = 0x7f84;
const C_FBASE: u32 = 0x7f88;
const C_THROTTLE: u32 = 0x7f8c;
const C_BRAKE: u32 = 0x7f90;
const C_PEDAL: u32 = 0x7f94;
const C_FRONT_DRIVEN: u32 = 0x7fb0;
const C_REAR_DRIVEN: u32 = 0x7fb4;
const C_ENGINE_DMG: u32 = 0x7fd8; // 0..1: > 0.25 the engine smokes (0x00434a08); crashes add, repairs clear it
const C_UPGRADE: u32 = 0x7fdc;
const C_TRANS: u32 = 0x7fe0;
const C_VEHICLE: u32 = 0x8024;
const C_ROLE: u32 = 0xc8c; // 0 player, 1 racer, 2 police, 3 traffic (drive::ROLE_*)
// Bullet btRaycastVehicle / btWheelInfo
const BT_WHEELS: u32 = 0xa4;
const BT_WHEEL_SIZE: u32 = 0x118;
const BT_IN_CONTACT: u32 = 0x54;

const VK_ESCAPE: u32 = 0x1b;
const VK_X: u32 = 0x58;
const VK_Z: u32 = 0x5a;

pub const VERSION: u32 = 1;

#[inline]
fn rf(a: u32) -> f32 {
    unsafe { core::ptr::read_volatile(a as usize as *const f32) }
}
#[inline]
fn ru(a: u32) -> u32 {
    unsafe { core::ptr::read_volatile(a as usize as *const u32) }
}
#[inline]
fn rb(a: u32) -> u8 {
    unsafe { core::ptr::read_volatile(a as usize as *const u8) }
}
#[inline]
fn wf(a: u32, v: f32) {
    unsafe { core::ptr::write_volatile(a as usize as *mut f32, v) }
}
#[inline]
fn wu(a: u32, v: u32) {
    unsafe { core::ptr::write_volatile(a as usize as *mut u32, v) }
}

#[derive(Clone, Copy)]
struct Slot {
    car: u32,
    model: u8,
    police: bool,
    st: State,
}

const SLOTS: usize = 256;
struct Globals {
    slots: [Slot; SLOTS],
    next: usize,
    up: u32,
    dn: u32,
    tach: f32,
    blink: f32,
    tach_color: u32,
    text: [u8; 8],
}

static mut G: Globals = Globals {
    slots: [Slot { car: 0, model: 0, police: false,
                   st: drive::BLANK };
            SLOTS],
    next: 0,
    up: 0,
    dn: 0,
    tach: 0.15,
    blink: 0.0,
    tach_color: TACH_COLOR,
    text: [0; 8],
};

#[allow(static_mut_refs)]
fn g() -> &'static mut Globals {
    unsafe { &mut *core::ptr::addr_of_mut!(G) }
}

fn find(car: u32) -> Option<usize> {
    g().slots.iter().position(|s| s.car == car && car != 0)
}

fn ai_enabled() -> bool {
    ru(SETTINGS) == SETTINGS_MAGIC && ru(SETTINGS + 8) == 1
}

/// racemod `rpmdial`: per-car speedometer faces + the needle on their rpm scale (settings +12)
fn rpm_dial_enabled() -> bool {
    ru(SETTINGS) == SETTINGS_MAGIC && ru(SETTINGS + 12) == 1
}

/// realistic gearing (settings +16, model::MODE_*): 50/50 unless the panel says otherwise
fn realism_mode() -> u32 {
    if ru(SETTINGS) == SETTINGS_MAGIC { ru(SETTINGS + 16) } else { model::MODE_OFF }
}

/// the player's car model 1..=8 (0 = not known)
fn player_model() -> usize {
    find(ru(PLAYER)).map(|i| g().slots[i].model as usize).unwrap_or(0)
}

fn power() -> f32 {
    if ru(SETTINGS) == SETTINGS_MAGIC { rf(SETTINGS + 4).clamp(0.0, 1.0) } else { 1.0 }
}

/// driven wheels touching the ground / driven wheels (1.0 if unknown)
fn contact(car: u32) -> f32 {
    let veh = ru(car + C_VEHICLE);
    if veh == 0 {
        return 1.0;
    }
    let wheels = ru(veh + BT_WHEELS);
    if wheels == 0 {
        return 1.0;
    }
    let (mut driven, mut touching) = (0u32, 0u32);
    for (axle, flag) in [(0u32, C_FRONT_DRIVEN), (2, C_REAR_DRIVEN)] {
        if ru(car + flag) != 0 {
            for w in axle..axle + 2 {
                driven += 1;
                touching += (rb(wheels + w * BT_WHEEL_SIZE + BT_IN_CONTACT) != 0) as u32;
            }
        }
    }
    if driven == 0 { 1.0 } else { touching as f32 / driven as f32 }
}

// ------------------------------------------------------------------ exports

#[no_mangle]
pub extern "C" fn cr_version() -> u32 {
    VERSION
}

/// door at the car loader 0x00436620: this car is being (re)built from `path`
///
/// # Safety
/// `path` is null or points to a readable string (only its first 64 bytes, up to a 0, are read).
#[no_mangle]
pub unsafe extern "C" fn cr_car_init(car: u32, path: *const u8) {
    let mut len = 0usize;
    if !path.is_null() {
        while len < 64 && unsafe { *path.add(len) } != 0 {
            len += 1;
        }
    }
    let bytes = if path.is_null() { &[][..] } else { unsafe { core::slice::from_raw_parts(path, len) } };
    let (model, police) = model::model_from_path(bytes);
    let gl = g();
    let i = match find(car) {
        Some(i) => i,
        None => match gl.slots.iter().position(|s| s.car == 0) {
            Some(i) => i,
            None => {
                // every slot used (the game never tells us a car is gone): reuse the next one round
                // the table - but never the player's car, or it would fall back to "unknown" mid-drive
                let player = ru(PLAYER);
                loop {
                    gl.next = (gl.next + 1) % SLOTS;
                    if gl.slots[gl.next].car != player || player == 0 {
                        break gl.next;
                    }
                }
            }
        },
    };
    let mut st = drive::new_state(&MODELS[model as usize]);
    // every car its own driver: seed from the car's address and the clock (a respawn at the same address
    // gets someone new)
    st.rng = (car ^ ru(FRAME_DT).rotate_left(16)).wrapping_mul(0x9E37_79B1) | 1;
    gl.slots[i] = Slot { car, model, police, st };
}

/// model of a car (0 = unknown) - for tools/tests
#[no_mangle]
pub extern "C" fn cr_car_model(car: u32) -> u32 {
    find(car).map(|i| g().slots[i].model as u32 | (g().slots[i].police as u32) << 8).unwrap_or(0)
}

/// for tools/tests: out[0..6] = gear, selector, wheel revs, engine revs, shift time left, model (-1 = no car)
///
/// # Safety
/// `out` is null or points to 6 writable floats.
#[no_mangle]
pub unsafe extern "C" fn cr_debug(car: u32, out: *mut f32) {
    let v = match find(car) {
        Some(i) => {
            let s = g().slots[i];
            [s.st.gear as f32, s.st.sel as f32, s.st.rpm, s.st.eng, s.st.shift_t, s.model as f32]
        }
        None => [-1.0; 6],
    };
    if !out.is_null() {
        for (k, x) in v.iter().enumerate() {
            unsafe { *out.add(k) = *x };
        }
    }
}

/// door at 0x00434844 (the drive function, every car, every step). Returns 1 with *out = the applied
/// drive force when this gearbox drives the car, 0 = run the stock code.
///
/// # Safety
/// `car` is 0 or a live car object of the game; `out` is null or points to a writable float.
#[no_mangle]
pub unsafe extern "C" fn cr_drive(car: u32, out: *mut f32) -> i32 {
    if car == 0 {
        return 0;
    }
    let player = car == ru(PLAYER);
    if !player && (!ai_enabled() || rf(car + C_F) < 0.0) {
        return 0; // AI: stock unless AI gearboxes are on; its reversing always stays stock
    }
    // AI braking stays stock too, but its driver keeps working the gears (downshifts, 1st at a stop)
    let stock_brake = !player && rf(car + C_PEDAL) > 0.0;
    let gl = g();
    let i = match find(car) {
        Some(i) => i,
        None => {
            // a car we lost track of: its model from the path the game keeps in the car itself
            unsafe { cr_car_init(car, (car + C_PATH) as *const u8) };
            match find(car) { Some(i) => i, None => return 0 }
        }
    };
    let slot = &mut gl.slots[i];
    let m = &MODELS[slot.model as usize];
    let (s_top, mut punch) = model::real_scale(slot.model as usize, rf(car + C_FBASE), slot.police, realism_mode());
    if ru(SETTINGS) == SETTINGS_MAGIC && rf(SETTINGS + 20) > 0.0 {
        punch = rf(SETTINGS + 20); // tools only (calibration in the simulator); 0 in the game
    }
    let role = if player { 0 } else { ru(car + C_ROLE) as u8 };
    if (role == drive::ROLE_RACER || role == drive::ROLE_POLICE) && s_top != 1.0 {
        // racers and police aim for the new top speed (the AI target 0x0043f113 = Vd x (1 - 0.75 |curve|)),
        // or they would lift at the stock one. Side effect: crash damage scales with max(Vd, 120) of both cars
        // (0x0043a497..), so their crashes hit up to ~1.8x harder. Traffic keeps its stock cruising target.
        wf(car + C_VD, rf(car + C_FMAX) * 0.06 * s_top);
    }
    if player {
        slot.st.up += core::mem::take(&mut gl.up);
        slot.st.dn += core::mem::take(&mut gl.dn);
    }
    let inp = Input {
        v: rf(car + C_V),
        accel: drive::launch_accel(rf(car + C_ACCEL), rf(car + C_ACCEL_BASE),
                                   (ru(car + C_TRANS) as i32).clamp(0, 3)),
        f: rf(car + C_F),
        fmax: rf(car + C_FMAX),
        fbase: rf(car + C_FBASE),
        throttle: rf(car + C_THROTTLE),
        pedal: rf(car + C_PEDAL),
        upgrade: ru(car + C_UPGRADE) as i32,
        trans: (ru(car + C_TRANS) as i32).clamp(0, 3),
        kc: contact(car),
        clutch: player && ru(SHIFT_HELD) != 0,
        dt: rf(FRAME_DT),
        power: power(),
        ai: !player,
        role,
        s_top,
        punch,
        slope: rf(car + C_FWD_Y),
    };
    if stock_brake {
        drive::ai_braking(m, &inp, &mut slot.st);
        return 0;
    }
    let o = drive::step(m, &inp, &mut slot.st);
    blown_engine(car, &mut slot.st);
    if player {
        wf(car + C_F, o.f); // instant throttle; an AI car's F (its throttle ramp) is never touched
        if let Some(b) = o.brake {
            wf(car + C_BRAKE, b);
        }
    }
    if !out.is_null() {
        unsafe { *out = o.force };
    }
    1
}

/// an engine over-revved to death (drive::wear): the game's engine damage goes to full, so it pours smoke like a
/// wrecked one; once the workshop (or anything) repairs it, the engine runs again, as new
fn blown_engine(car: u32, st: &mut State) {
    if !st.blown {
        return;
    }
    if st.dmg_set && rf(car + C_ENGINE_DMG) < 0.999 {
        st.blown = false;
        st.dmg_set = false;
        st.wear = 0.0;
        return;
    }
    wf(car + C_ENGINE_DMG, 1.0);
    st.dmg_set = true;
}

/// door at 0x00434d5a (engine sound, cars near the camera): the pitch load to use
#[no_mangle]
pub extern "C" fn cr_sound(car: u32, load: f32) -> f32 {
    if car != ru(PLAYER) && !ai_enabled() {
        return load;
    }
    match find(car) {
        Some(i) => drive::sound_load(&MODELS[g().slots[i].model as usize], &g().slots[i].st),
        None => load,
    }
}

/// door at 0x0045677e (window procedure keydown): X / Z shift (auto-repeat ignored, not while paused)
#[no_mangle]
pub extern "C" fn cr_key(vk: u32, lparam: u32) {
    if vk == VK_ESCAPE {
        buzz::off(); // the pause menu: no buzzer over it
    }
    if ru(RUNNING) == 0 || lparam & 0x4000_0000 != 0 {
        return;
    }
    match vk {
        VK_X => g().up += 1,
        VK_Z => g().dn += 1,
        _ => {}
    }
}

/// door at 0x00468265 (speedometer): the gear text for the player's car, or null
#[no_mangle]
pub extern "C" fn cr_hud_text() -> *const u8 {
    let car = ru(PLAYER);
    let gl = g();
    match find(car) {
        Some(i) => {
            let s = gl.slots[i];
            drive::gear_text(&MODELS[s.model as usize], &s.st, rf(car + C_V), &mut gl.text);
            gl.text.as_ptr()
        }
        None => core::ptr::null(),
    }
}

// 15 /s smoothed a limiter bounce away; a real needle follows a few hundred rpm at 5-15 Hz (player 2026-11-02)
const TACH_RATE: f32 = 30.0;
const TACH_SHIFT: f32 = 0.88;
const TACH_BLINK: f32 = 0.125;
const TACH_COLOR: u32 = 0xFF80_8000;
const TACH_COLOR_SHIFT: u32 = 0xFFFF_2020;
const TACH_FULL: f32 = 0.8 * 4.712_389; // redline = 0.8 x 270 deg (where the stock needle stopped)

/// door at 0x00468036 (the small needle): its angle; also sets the colour cr_tach_color returns
#[no_mangle]
pub extern "C" fn cr_tach() -> f32 {
    let car = ru(PLAYER);
    let gl = g();
    let (target, idle, manual_light, buzzing) = match find(car) {
        Some(i) => {
            let s = gl.slots[i];
            let m = &MODELS[s.model as usize];
            (drive::shown_rpm(&s.st), m.idle, m.kind != Kind::Auto, drive::buzzing(m, &s.st))
        }
        None => (0.15, 0.15, true, false),
    };
    buzz::update(buzzing && ru(RUNNING) != 0);
    let dt = rf(FRAME_DT);
    let target = if find(car).is_some_and(|i| gl.slots[i].st.blown) { 0.0 } else { target.max(idle) };
    gl.tach += (target - gl.tach) * (dt * TACH_RATE).min(1.0);
    gl.tach_color = TACH_COLOR;
    if manual_light && gl.tach >= TACH_SHIFT {
        gl.blink += dt;
        if gl.blink >= TACH_BLINK {
            gl.blink -= TACH_BLINK;
        }
        if gl.blink < TACH_BLINK / 2.0 {
            gl.tach_color = TACH_COLOR_SHIFT;
        }
    } else {
        gl.blink = 0.0;
    }
    if rpm_dial_enabled() {
        return hud::dial_angle(player_model(), gl.tach); // on the car's own face: rpm / dial max
    }
    gl.tach.clamp(0.0, 1.1) * TACH_FULL
}

/// tools (32-bit test harness): play (1) / stop (0) the buzzer on the harness's own IDirectSound8; returns the
/// playing buffer or 0
#[no_mangle]
pub extern "C" fn cr_buzz_test(ds: u32, on: u32) -> u32 {
    buzz::selftest(ds, on)
}

#[no_mangle]
pub extern "C" fn cr_tach_color() -> u32 {
    g().tach_color
}

// ------------------------------------------------------------------ HUD widescreen fix (racemod `hudfix`)
// racemod points the Direct3D draw calls of the 2D helpers the driving HUD uses (rect 0x0045c7d0, quads
// 0x0045c910 / 0x0045ca50, 0x0040cb90 / 0x0040da90 / 0x0040e0e0 / 0x0040e850, text 0x0046ff10 and the
// speedometer itself) at cr_dpup / cr_dipup, and wraps the HUD call 0x00467eb0 in cr_hud_begin / cr_hud_end.
// Outside that window (menus, shops: mouse-driven) every call goes straight through.
const SCR_W: u32 = 0x0259_F7EC; // renderer +0x41ffc: screen width, px
const SCR_SX: u32 = 0x0259_F7F4; // +0x42004: x scale = width / 800
const SCR_SY: u32 = 0x0259_F804; // +0x42014: y scale = height / 600
const D3D_DRAW_UP: u32 = 0x14c; // IDirect3DDevice9 vtable: DrawPrimitiveUP
const D3D_DRAW_INDEXED_UP: u32 = 0x150; // DrawIndexedPrimitiveUP
const D3D_GET_FVF: u32 = 0x168; // GetFVF
const HUD_BUF_LEN: usize = 0x10000;

static mut HUD_ON: bool = false;
static mut HUD_BUF: [u8; HUD_BUF_LEN] = [0; HUD_BUF_LEN];

type DrawUp = extern "system" fn(u32, u32, u32, *const u8, u32) -> i32;
type DrawIndexedUp = extern "system" fn(u32, u32, u32, u32, u32, *const u8, u32, *const u8, u32) -> i32;
type GetFvf = extern "system" fn(u32, *mut u32) -> i32;

/// the device's own method (vtable slot `off`)
fn d3d_method(dev: u32, off: u32) -> usize {
    ru(ru(dev) + off) as usize
}

/// pre-transformed (XYZRHW) vertices = 2D
fn screen_space(dev: u32) -> bool {
    let get: GetFvf = unsafe { core::mem::transmute(d3d_method(dev, D3D_GET_FVF)) };
    let mut fvf = 0u32;
    get(dev, &mut fvf) >= 0 && fvf & 0x00e == 0x004
}

/// the vertices un-stretched in HUD_BUF, or None = draw them as they are
fn hud_copy(dev: u32, data: *const u8, n: usize, stride: u32) -> Option<*const u8> {
    let len = n * stride as usize;
    if !unsafe { HUD_ON } || data.is_null() || len == 0 || len > HUD_BUF_LEN || !screen_space(dev) {
        return None;
    }
    let buf = unsafe { &mut *core::ptr::addr_of_mut!(HUD_BUF) };
    unsafe { core::ptr::copy_nonoverlapping(data, buf.as_mut_ptr(), len) };
    hud::unstretch(&mut buf[..len], n, stride as usize, rf(SCR_SX), rf(SCR_SY), rf(SCR_W));
    Some(buf.as_ptr())
}

/// door around the driving HUD (0x00467eb0, thiscall: `hud` = its object, which the door passes on)
#[no_mangle]
pub extern "C" fn cr_hud_begin(hud: u32) {
    unsafe { HUD_ON = true };
    if hud != 0 {
        dial_face(hud);
    }
}

// The HUD loads Main.dds through the texture manager into HUD +0x9d7c and copies that slot into the dial
// sprite (HUD +0x9d84) at +0x70 once (0x0045cc3e); the rect helper draws with whatever that field holds.
const HUD_MAIN_TEX: u32 = 0x9d7c;
const HUD_DIAL_TEX: u32 = 0x9d84 + 0x70;

/// the dial shows the player's car's own face (rpm scale + red zone) when `rpmdial` is on, else stock
fn dial_face(hud: u32) {
    let stock = ru(hud + HUD_MAIN_TEX);
    let model = player_model();
    let face = if rpm_dial_enabled() && (1..=8).contains(&model) { face_slot(model) } else { -1 };
    wu(hud + HUD_DIAL_TEX, if face >= 0 { face as u32 } else { stock });
}

static mut FACE_MISSING: [bool; 9] = [false; 9];

/// the face texture's slot, looked up by name every frame (so a level reload can never leave a stale slot)
/// and loaded through the game's own texture manager when missing; -1 = not available (file not there)
#[cfg(all(not(test), target_arch = "x86"))]
fn face_slot(model: usize) -> i32 {
    const TEXMGR: u32 = 0x0255_D7F0;
    // lookup works on the NAME TABLE at +0x27c (0x0040ad15: lea edi,[esi+0x27c]; mov ecx,edi; call 0x00410140);
    // called on TEXMGR itself it searched the wrong memory and never found the face (2026-11-01 bug)
    const TEX_NAMES: u32 = TEXMGR + 0x27c;
    const TEX_LOOKUP: u32 = 0x0041_0140; // thiscall (name) -> slot or -1 (already loaded?)
    const TEX_ACQUIRE: u32 = 0x0040_AD00; // thiscall (name, 1, 1) -> slot (how the HUD loads Main.dds)
    type Lookup = extern "thiscall" fn(u32, *const u8) -> i32;
    type Acquire = extern "thiscall" fn(u32, *const u8, u32, u32) -> i32;
    let missing = unsafe { &mut *core::ptr::addr_of_mut!(FACE_MISSING) };
    if missing[model] {
        return -1;
    }
    let mut name = [0u8; 48];
    hud::face_name(model, &mut name);
    let lookup: Lookup = unsafe { core::mem::transmute(TEX_LOOKUP as usize) };
    let slot = lookup(TEX_NAMES, name.as_ptr());
    if slot >= 0 {
        return slot;
    }
    let acquire: Acquire = unsafe { core::mem::transmute(TEX_ACQUIRE as usize) };
    acquire(TEXMGR, name.as_ptr(), 1, 1);
    let slot = lookup(TEX_NAMES, name.as_ptr());
    if slot < 0 {
        missing[model] = true; // never hit the disk again for a face that is not installed
    }
    slot
}

#[cfg(any(test, not(target_arch = "x86")))]
fn face_slot(_model: usize) -> i32 {
    let _ = unsafe { &*core::ptr::addr_of!(FACE_MISSING) };
    -1
}

#[no_mangle]
pub extern "C" fn cr_hud_end() {
    unsafe { HUD_ON = false };
}

/// IDirect3DDevice9::DrawPrimitiveUP, same stdcall signature (the patched sites call it like the method)
#[no_mangle]
pub extern "system" fn cr_dpup(dev: u32, prim: u32, count: u32, data: *const u8, stride: u32) -> i32 {
    buzz::watchdog(); // the 2D helpers draw menus too: the buzzer stops once the HUD no longer asks for it
    let real: DrawUp = unsafe { core::mem::transmute(d3d_method(dev, D3D_DRAW_UP)) };
    let data = hud_copy(dev, data, hud::prim_verts(prim, count), stride).unwrap_or(data);
    real(dev, prim, count, data, stride)
}

/// IDirect3DDevice9::DrawIndexedPrimitiveUP (the game's text: one call per string)
#[no_mangle]
#[allow(clippy::too_many_arguments)] // the Direct3D method's own signature
pub extern "system" fn cr_dipup(dev: u32, prim: u32, min_index: u32, verts: u32, count: u32, index: *const u8,
                                index_fmt: u32, data: *const u8, stride: u32) -> i32 {
    buzz::watchdog();
    let real: DrawIndexedUp = unsafe { core::mem::transmute(d3d_method(dev, D3D_DRAW_INDEXED_UP)) };
    let n = (min_index + verts) as usize;
    let data = hud_copy(dev, data, n, stride).unwrap_or(data);
    real(dev, prim, min_index, verts, count, index, index_fmt, data, stride)
}

// ------------------------------------------------------------------ no_std DLL plumbing

#[cfg(all(not(test), target_arch = "x86"))]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    loop {}
}

#[cfg(all(not(test), target_os = "windows", target_arch = "x86"))]
#[no_mangle]
pub extern "system" fn _DllMainCRTStartup(_module: *mut u8, _reason: u32, _reserved: *mut u8) -> i32 {
    1
}

#[cfg(all(not(test), target_os = "windows", target_arch = "x86"))]
#[no_mangle]
pub static _fltused: i32 = 0;

#[cfg(test)]
mod tests;

// The C runtime is not linked: the few memory helpers rustc may still emit. Written with volatile
// accesses so the optimiser cannot turn them back into calls to themselves. Same contract as C's:
// the pointers cover `n` bytes (memcpy: not overlapping).
#[cfg(all(not(test), target_arch = "x86"))]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "C" fn memcpy(d: *mut c_void, s: *const c_void, n: usize) -> *mut c_void {
    let (d, s) = (d as *mut u8, s as *const u8);
    for k in 0..n {
        core::ptr::write_volatile(d.add(k), core::ptr::read_volatile(s.add(k)));
    }
    d as *mut c_void
}

#[cfg(all(not(test), target_arch = "x86"))]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "C" fn memmove(d: *mut c_void, s: *const c_void, n: usize) -> *mut c_void {
    let (d, s) = (d as *mut u8, s as *const u8);
    if (d as usize) < (s as usize) {
        for k in 0..n {
            core::ptr::write_volatile(d.add(k), core::ptr::read_volatile(s.add(k)));
        }
    } else {
        for k in (0..n).rev() {
            core::ptr::write_volatile(d.add(k), core::ptr::read_volatile(s.add(k)));
        }
    }
    d as *mut c_void
}

#[cfg(all(not(test), target_arch = "x86"))]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "C" fn memset(d: *mut c_void, c: i32, n: usize) -> *mut c_void {
    let p = d as *mut u8;
    for k in 0..n {
        core::ptr::write_volatile(p.add(k), c as u8);
    }
    d
}

#[cfg(all(not(test), target_arch = "x86"))]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "C" fn memcmp(a: *const c_void, b: *const c_void, n: usize) -> i32 {
    let (a, b) = (a as *const u8, b as *const u8);
    for k in 0..n {
        let (x, y) = (core::ptr::read_volatile(a.add(k)), core::ptr::read_volatile(b.add(k)));
        if x != y {
            return x as i32 - y as i32;
        }
    }
    0
}
