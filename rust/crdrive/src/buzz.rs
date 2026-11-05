//! The rotary Alpha's rev warning buzzer (player 2026-11-02): a steady piezo tone from 90 % of the redline, like
//! the real rotary sports cars had (the rotor revs so smoothly the driver needs a warning). Played on the game's
//! own DirectSound device (CAudioManager +0, the one the `engineloop` extra already makes buffers on), so it goes
//! quiet with the window's focus like every game sound; one looping 2D buffer, made the first time it is needed.
//! The DLL imports nothing: the device's methods come from its vtable.
#[cfg(all(not(test), target_arch = "x86"))]
use crate::ru;

/// CAudioManager (static): +0 IDirectSound8
#[cfg(all(not(test), target_arch = "x86"))]
const AUDIO: u32 = 0x026B_70B8;
/// the game's sound switch (the engine sounds and ambience only run with it)
#[cfg(all(not(test), target_arch = "x86"))]
const SOUND_ON: u32 = 0x012D_041C;
/// KUSER_SHARED_DATA, mapped read-only into every process: TickCountQuad (low dword) x TickCountMultiplier >> 24
/// = GetTickCount, without importing it
#[cfg(all(not(test), target_arch = "x86"))]
const KUSER_TICK: u32 = 0x7FFE_0320;
#[cfg(all(not(test), target_arch = "x86"))]
const KUSER_MUL: u32 = 0x7FFE_0004;
/// nobody asked for the tone this long (pause menu, a shop, loading: the HUD stopped) = stop it
#[cfg(all(not(test), target_arch = "x86"))]
const QUIET_MS: u32 = 120;

pub const RATE: u32 = 22_050;
/// 2450 Hz = 9 samples a period at 22050 Hz
pub const PERIOD: usize = 9;
/// 0.1 s, a whole number of periods: the loop has no seam
pub const LEN: usize = PERIOD * 245;
/// one period: the fundamental + a third harmonic (a piezo's hard edge), peak 4500 (~ -17 dBFS: heard over the
/// engine without drowning it; buzztest measured 6000 as loud)
pub const WAVE: [i16; PERIOD] = [0, 4500, 3613, 4316, 3000, -3000, -4316, -3613, -4500];

/// the buffer's samples
pub fn pcm(out: &mut [i16]) {
    for (k, x) in out.iter_mut().enumerate() {
        *x = WAVE[k % PERIOD];
    }
}

#[cfg(all(not(test), target_arch = "x86"))]
mod dsound {
    use super::*;

    #[repr(C, packed(2))]
    struct WaveFormat {
        tag: u16,
        channels: u16,
        rate: u32,
        bytes_per_sec: u32,
        align: u16,
        bits: u16,
        extra: u16,
    }

    #[repr(C)]
    struct BufferDesc {
        size: u32,
        flags: u32,
        bytes: u32,
        reserved: u32,
        format: *const WaveFormat,
        algorithm: [u32; 4],
    }

    static FORMAT: WaveFormat = WaveFormat { tag: 1, channels: 1, rate: RATE, bytes_per_sec: RATE * 2, align: 2,
                                             bits: 16, extra: 0 };
    const DSBCAPS_LOCSOFTWARE: u32 = 0x8;
    const DSBCAPS_GLOBALFOCUS: u32 = 0x8000; // tools only: the game's buzzer goes quiet with the window's focus
    const DSBPLAY_LOOPING: u32 = 1;
    const DSBSTATUS_BUFFERLOST: u32 = 2;

    // IDirectSound8 / IDirectSoundBuffer vtable slots
    const DS_CREATE_BUFFER: u32 = 3;
    const B_GET_STATUS: u32 = 9;
    const B_LOCK: u32 = 11;
    const B_PLAY: u32 = 12;
    const B_SET_POSITION: u32 = 13;
    const B_STOP: u32 = 18;
    const B_UNLOCK: u32 = 19;
    const B_RESTORE: u32 = 20;

    type CreateBuffer = extern "system" fn(u32, *const BufferDesc, *mut u32, u32) -> i32;
    type Lock = extern "system" fn(u32, u32, u32, *mut *mut u8, *mut u32, *mut *mut u8, *mut u32, u32) -> i32;
    type Unlock = extern "system" fn(u32, *mut u8, u32, *mut u8, u32) -> i32;
    type Play = extern "system" fn(u32, u32, u32, u32) -> i32;
    type One = extern "system" fn(u32) -> i32;
    type SetPosition = extern "system" fn(u32, u32) -> i32;
    type GetStatus = extern "system" fn(u32, *mut u32) -> i32;

    fn method(obj: u32, slot: u32) -> usize {
        ru(ru(obj) + 4 * slot) as usize
    }

    struct Buzz {
        ds: u32,
        buf: u32,
        playing: bool,
        last: u32,
    }
    static mut B: Buzz = Buzz { ds: 0, buf: 0, playing: false, last: 0 };

    #[allow(static_mut_refs)]
    fn b() -> &'static mut Buzz {
        unsafe { &mut *core::ptr::addr_of_mut!(B) }
    }

    fn now_ms() -> u32 {
        ((ru(KUSER_TICK) as u64 * ru(KUSER_MUL) as u64) >> 24) as u32
    }

    fn fill(buf: u32) -> bool {
        let lock: Lock = unsafe { core::mem::transmute(method(buf, B_LOCK)) };
        let unlock: Unlock = unsafe { core::mem::transmute(method(buf, B_UNLOCK)) };
        let (mut p1, mut n1, mut p2, mut n2) = (core::ptr::null_mut(), 0u32, core::ptr::null_mut(), 0u32);
        if lock(buf, 0, (LEN * 2) as u32, &mut p1, &mut n1, &mut p2, &mut n2, 0) < 0 || p1.is_null() {
            return false;
        }
        let n = (n1 as usize / 2).min(LEN);
        pcm(unsafe { core::slice::from_raw_parts_mut(p1 as *mut i16, n) });
        unlock(buf, p1, n1, p2, n2);
        true
    }

    /// a looping buffer with the tone on device `ds`, 0 = could not
    pub fn create(ds: u32, global: bool) -> u32 {
        let flags = DSBCAPS_LOCSOFTWARE | if global { DSBCAPS_GLOBALFOCUS } else { 0 };
        let desc = BufferDesc { size: core::mem::size_of::<BufferDesc>() as u32, flags,
                                bytes: (LEN * 2) as u32, reserved: 0, format: &FORMAT, algorithm: [0; 4] };
        let make: CreateBuffer = unsafe { core::mem::transmute(method(ds, DS_CREATE_BUFFER)) };
        let mut buf = 0u32;
        if make(ds, &desc, &mut buf, 0) < 0 || buf == 0 || !fill(buf) {
            return 0;
        }
        buf
    }

    pub fn start(buf: u32) -> bool {
        let status: GetStatus = unsafe { core::mem::transmute(method(buf, B_GET_STATUS)) };
        let mut st = 0u32;
        if status(buf, &mut st) >= 0 && st & DSBSTATUS_BUFFERLOST != 0 {
            let restore: One = unsafe { core::mem::transmute(method(buf, B_RESTORE)) };
            if restore(buf) < 0 || !fill(buf) {
                return false;
            }
        }
        let rewind: SetPosition = unsafe { core::mem::transmute(method(buf, B_SET_POSITION)) };
        rewind(buf, 0);
        let play: Play = unsafe { core::mem::transmute(method(buf, B_PLAY)) };
        play(buf, 0, 0, DSBPLAY_LOOPING) >= 0
    }

    pub fn stop(buf: u32) {
        let stop: One = unsafe { core::mem::transmute(method(buf, B_STOP)) };
        stop(buf);
    }

    /// every HUD frame: should the buzzer sound
    pub fn update(want: bool) {
        let s = b();
        // only the Alpha at the redline ever reads the sound globals (the simulators map none of them)
        let ds = if want && ru(SOUND_ON) != 0 { ru(AUDIO) } else { 0 };
        if ds == 0 {
            off();
            return;
        }
        if ds != s.ds {
            // the first time, or the game made a new device: a new buffer (the old one went with the old device)
            s.ds = ds;
            s.buf = create(ds, false);
            s.playing = false;
        }
        if s.buf == 0 {
            return;
        }
        s.last = now_ms();
        if !s.playing {
            s.playing = start(s.buf);
        }
    }

    pub fn off() {
        let s = b();
        if s.playing {
            stop(s.buf);
            s.playing = false;
        }
    }

    /// from every door: the HUD has not asked for a while (pause menu, shop, loading) = quiet
    pub fn watchdog() {
        let s = b();
        if s.playing && now_ms().wrapping_sub(s.last) > QUIET_MS {
            off();
        }
    }

    /// tools: the same buffer on any device (a 32-bit test harness with its own DirectSound): 1 = start,
    /// 2 = start, heard without the window focus (a harness has no window in front), 0 = stop; returns the
    /// playing buffer (0 = failed / stopped)
    pub fn selftest(ds: u32, on: u32) -> u32 {
        let s = b();
        if on != 0 {
            if s.ds != ds {
                s.ds = ds;
                s.buf = create(ds, on == 2);
                s.playing = false;
            }
            if s.buf != 0 && !s.playing {
                s.playing = start(s.buf);
            }
        } else {
            off();
        }
        if s.playing { s.buf } else { 0 }
    }
}

#[cfg(all(not(test), target_arch = "x86"))]
pub use dsound::{off, selftest, update, watchdog};

#[cfg(any(test, not(target_arch = "x86")))]
pub fn update(_want: bool) {}
#[cfg(any(test, not(target_arch = "x86")))]
pub fn off() {}
#[cfg(any(test, not(target_arch = "x86")))]
pub fn watchdog() {}
#[cfg(any(test, not(target_arch = "x86")))]
pub fn selftest(_ds: u32, _on: u32) -> u32 {
    0
}
