r"""mp3wav.py - wrap a constant-bitrate MP3 into a WAV the game can load (player 2026-11-01: new music/ambience).

The game's own tracks (Data/Audio/MusTrks/TrR01.wav ...) are MP3 inside WAV: an MPEGLAYER3WAVEFORMAT 'fmt '
chunk (tag 0x55, avg bytes = bitrate/8, align 1, bits 0, cbSize 12, wID 1, flags 2, block size = one frame,
1 frame per block), a 'fact' chunk (sample count) and the raw MP3 frames as 'data'. DirectMusic hands them to
Windows' ACM MP3 decoder. Here the MP3 frames are copied unchanged (no re-encode, no quality loss); ID3 tags are
dropped. Every output is checked SILENTLY by converting the start of the file to PCM through the same ACM
decoder (acmStreamOpen/acmStreamConvert) - so a format the decoder refuses is caught before it ships.

    mp3wav.py in.mp3 out.wav            convert + decode check
"""
import ctypes
import struct
import sys

BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
            2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def frames(mp3):
    """the MPEG audio frames (no ID3v2 / ID3v1 tags): (bytes, rate, channels, bitrate, samples per frame, count)"""
    i = 0
    if mp3[:3] == b"ID3":
        i = 10 + ((mp3[6] << 21) | (mp3[7] << 14) | (mp3[8] << 7) | mp3[9])
    end = len(mp3) - (128 if mp3[-128:-125] == b"TAG" else 0)
    out, fmt, n = bytearray(), None, 0
    while i + 4 <= end:
        h = int.from_bytes(mp3[i:i + 4], "big")
        ver, layer, bri, sri = (h >> 19) & 3, (h >> 17) & 3, (h >> 12) & 15, (h >> 10) & 3
        if (h >> 21) != 0x7FF or ver == 1 or layer != 1 or bri in (0, 15) or sri == 3:
            i += 1
            continue
        br, sr = BITRATES[1 if ver == 3 else 2][bri] * 1000, RATES[ver][sri]
        size = (144 if ver == 3 else 72) * br // sr + ((h >> 9) & 1)
        this = (sr, 1 if ((h >> 6) & 3) == 3 else 2, br, 1152 if ver == 3 else 576)
        if fmt is None:
            fmt = this
        if this != fmt:
            raise ValueError(f"not constant: frame {n} is {this}, the first was {fmt}")
        out += mp3[i:i + size]
        n += 1
        i += size
    return bytes(out), fmt, n


def wav(mp3):
    data, (sr, ch, br, spf), n = frames(mp3)
    block = (144 if spf == 1152 else 72) * br // sr
    fmt = struct.pack("<HHIIHHH", 0x55, ch, sr, br // 8, 1, 0, 12) + struct.pack("<HIHHH", 1, 2, block, 1, 0)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<II", 4, n * spf)
            + b"data" + struct.pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b""))
    return b"RIFF" + struct.pack("<I", len(body)) + body, (sr, ch, br, n * spf / sr)


class WFX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("tag", ctypes.c_ushort), ("ch", ctypes.c_ushort), ("sr", ctypes.c_uint), ("abps", ctypes.c_uint),
                ("align", ctypes.c_ushort), ("bits", ctypes.c_ushort), ("cb", ctypes.c_ushort),
                ("extra", ctypes.c_ubyte * 12)]


class HDR(ctypes.Structure):
    _fields_ = [("cbStruct", ctypes.c_uint), ("fdwStatus", ctypes.c_uint), ("dwUser", ctypes.c_size_t),
                ("pbSrc", ctypes.c_void_p), ("cbSrcLength", ctypes.c_uint), ("cbSrcLengthUsed", ctypes.c_uint),
                ("dwSrcUser", ctypes.c_size_t), ("pbDst", ctypes.c_void_p), ("cbDstLength", ctypes.c_uint),
                ("cbDstLengthUsed", ctypes.c_uint), ("dwDstUser", ctypes.c_size_t),
                ("dwReservedDriver", ctypes.c_uint * (15 if ctypes.sizeof(ctypes.c_void_p) == 8 else 10))]


def acm_check(w):
    """decode the first ~2 s through Windows' ACM MP3 decoder; returns (ok, PCM bytes, peak sample)"""
    acm = ctypes.WinDLL("msacm32")
    fmt_at = w.index(b"fmt ") + 8
    src = WFX.from_buffer_copy(w[fmt_at:fmt_at + 30])
    dst = WFX(1, src.ch, src.sr, src.sr * src.ch * 2, src.ch * 2, 16, 0)
    has = ctypes.c_void_p()
    if acm.acmStreamOpen(ctypes.byref(has), None, ctypes.byref(src), ctypes.byref(dst), None, None, None, 0):
        return False, 0, 0
    data_at = w.index(b"data") + 8
    chunk = w[data_at:data_at + src.abps * 2]
    sbuf = ctypes.create_string_buffer(chunk, len(chunk))
    dbuf = ctypes.create_string_buffer(src.sr * src.ch * 2 * 3)
    h = HDR(ctypes.sizeof(HDR), 0, 0, ctypes.cast(sbuf, ctypes.c_void_p), len(chunk), 0, 0,
            ctypes.cast(dbuf, ctypes.c_void_p), len(dbuf), 0, 0)
    ok = acm.acmStreamPrepareHeader(has, ctypes.byref(h), 0) == 0 and acm.acmStreamConvert(has, ctypes.byref(h), 0) == 0
    pcm = h.cbDstLengthUsed
    acm.acmStreamUnprepareHeader(has, ctypes.byref(h), 0)
    acm.acmStreamClose(has, 0)
    peak = max(abs(v) for v in struct.unpack(f"<{pcm // 2}h", dbuf.raw[:pcm])) if pcm else 0
    return ok and pcm > 0, pcm, peak


def main():
    w, (sr, ch, br, secs) = wav(open(sys.argv[1], "rb").read())
    open(sys.argv[2], "wb").write(w)
    ok, pcm, peak = acm_check(w)
    print(f"{sys.argv[2]}: {len(w):,} B, {sr} Hz {ch}ch {br // 1000} kbps, {secs / 60:.1f} min; ACM decode "
          f"{'OK' if ok else 'FAILED'} ({pcm:,} B PCM from 2 s, peak {peak})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
