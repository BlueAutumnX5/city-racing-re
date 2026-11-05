r"""newaudio.py - build the player's new music + ambience for racemod `newaudio` (player 2026-11-01:
"add new ambient/music", files in D:\My Downloads\Music).

  race music.mp3       -> Data/Audio/MusTrks/TrR09.wav     a 9th race track (racemod: rand() % 9)
  city sounds.mp3      -> Data/Audio/AmbTrks/AmbCityX01.wav city ambience, day AND night
  dirt roads night.mp3 -> Data/Audio/AmbTrks/AmbFrstN04.wav forest (= countryside / dirt roads) at night

Each MP3 is wrapped unchanged into the game's MP3-in-WAV form and decode-checked (mp3wav.py). The ambience
list is the original AmbientData.obj (Objects.pak, XOR 0x80) with the new tracks added, written as the PLAIN
loose file AmbientDat2.obj (racemod points the exe there; loose files are read by plain fgets, no XOR; LF line
ends because the loose reader strips only '\n'). Lists hold up to 32 names each (0x0046d8c2..: 32 x 0xff).

    newaudio.py            -> "New audio\" (the 4 files, laid out like the game's Data folder)
"""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mp3wav  # noqa: E402

SRC = crpaths.MUSIC
OUT = os.path.join(HERE, "New audio")
ORIG_LIST = os.path.join(HERE, "extracted", "Objects", "files", "Data", "Audio", "AmbTrks", "AmbientData.obj")
TRACKS = [("race music.mp3", r"Data\Audio\MusTrks\TrR09.wav"),
          ("city sounds.mp3", r"Data\Audio\AmbTrks\AmbCityX01.wav"),
          ("dirt roads night.mp3", r"Data\Audio\AmbTrks\AmbFrstN04.wav")]
LIST = r"Data\Audio\AmbTrks\AmbientDat2.obj"
# (section title, DAY/NIGHT) -> extra tracks appended to that list
ADD = {("city", "DAY"): ["Data/Audio/AmbTrks/AmbCityX01.wav"],
       ("city", "NIGHT"): ["Data/Audio/AmbTrks/AmbCityX01.wav"],
       ("forest", "NIGHT"): ["Data/Audio/AmbTrks/AmbFrstN04.wav"]}
FILES = [dst for _, dst in TRACKS] + [LIST]


def ambient_list():
    """the original list with the additions: same lines and columns, counts raised, LF line ends"""
    text = bytes(b ^ 0x80 for b in open(ORIG_LIST, "rb").read()).decode("latin-1")
    lines = text.replace("\r\n", "\n").split("\n")
    out, section, i = [], None, 0
    while i < len(lines):
        line = lines[i]
        if "(city)" in line:
            section = "city"
        elif "(forest)" in line:
            section = "forest"
        if line.startswith("Tracks ") and ":" in line:
            when = line.split()[1].rstrip(":")
            n = int(line.split()[-1])
            names = lines[i + 1:i + 1 + n]
            names += ADD.get((section, when), [])
            label = line[:line.rindex(" ") + 1]
            assert len(names) <= 32, "the game keeps 32 names per list"
            out.append(f"{label}{len(names)}")
            out += names
            i += 1 + n
            continue
        out.append(line)
        i += 1
    return "\n".join(out).encode("latin-1")


def main():
    ok = True
    for src, dst in TRACKS:
        path = os.path.join(OUT, dst)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        w, (sr, ch, br, secs) = mp3wav.wav(open(os.path.join(SRC, src), "rb").read())
        good, pcm, peak = mp3wav.acm_check(w)
        open(path, "wb").write(w)
        ok &= good
        print(f"{dst}: {len(w):,} B, {sr} Hz {ch}ch {br // 1000} kbps, {secs / 60:.1f} min, decode "
              f"{'OK' if good else 'FAILED'} (peak {peak})")
    data = ambient_list()
    path = os.path.join(OUT, LIST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    print(f"{LIST}:\n" + data.decode("latin-1"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
