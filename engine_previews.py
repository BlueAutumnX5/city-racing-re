"""Engine sound previews (player 2026-10-31: 'pull the engine sounds so I can choose which fits
each car'). Copies E01..E08.wav out of the extracted SD.pak and makes, for each, a preview that
loops the sample the way the game does (engine pitch = the sample played faster: x1.0 idle up to
x1.75 at full revs) - idle, rev up, hold at the top, rev down. Plus one file with all eight in a row."""
import os, shutil, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "extracted", "SD", "files", "Data", "Audio")
OUT = os.path.join(HERE, "Engine sounds")
RATE = 22050


def load(path):
    with wave.open(path) as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)


def save(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())


def preview(s):
    """pitch curve (seconds, multiplier): idle 1.5 s, rev up 3 s, hold 0.7 s, rev down 1.5 s"""
    pts = [(0.0, 1.0), (1.5, 1.0), (4.5, 1.75), (5.2, 1.75), (6.7, 1.1), (7.2, 1.1)]
    t = np.arange(int(pts[-1][0] * RATE)) / RATE
    pitch = np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
    pos = np.cumsum(pitch) % len(s)                  # read position through the looping sample
    i = pos.astype(int)
    frac = pos - i
    y = s[i] * (1 - frac) + s[(i + 1) % len(s)] * frac
    fade = np.minimum(1, np.minimum(t / 0.05, (t[-1] - t) / 0.2))
    return y * fade


def main():
    os.makedirs(OUT, exist_ok=True)
    row = []
    for k in range(1, 9):
        name = f"E{k:02d}"
        src = os.path.join(SRC, name + ".wav")
        shutil.copyfile(src, os.path.join(OUT, f"{name} - original sample.wav"))
        p = preview(load(src))
        save(os.path.join(OUT, f"{name} - preview (idle, rev up, rev down).wav"), p)
        row += [p, np.zeros(int(0.6 * RATE))]
        print(f"{name}: sample {len(load(src)) / RATE:.2f} s, preview {len(p) / RATE:.1f} s")
    save(os.path.join(OUT, "ALL 8 in a row (E01 first).wav"), np.concatenate(row))
    print("written to", OUT)


if __name__ == "__main__":
    main()
