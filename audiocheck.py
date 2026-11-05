r"""audiocheck.py - racemod `newaudio` executed in Unicorn inside the patched exe (player 2026-11-01: new music +
ambience).
1) Music pick 0x0046e237..0x0046e244 for many rand() values: stock -> TrR01..TrR08, newaudio -> TrR01..TrR09,
   every track reachable, stack untouched.
2) The game's REAL ambience-list loader 0x0046d850 (thiscall: the audio manager) reads newaudio.py's
   AmbientDat2.obj: open 0x0046fb50 / line reader 0x0046eca0 / close 0x0046eb80 are stood in for exactly like
   the loose-file path (plain fgets, the trailing '\n' stripped), atoi is the game's own. Checks the file name
   the exe asks for, the 4 counts (+0x44b8..) and every stored name (+0x44c8 / +0x64a8 / +0x8488 / +0xa468).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import racemod
import racesim
from unicorn import UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP

LIST = os.path.join(HERE, "New audio", "Data", "Audio", "AmbTrks", "AmbientDat2.obj")
MGR = 0x06000000
OK = []


def check(label, ok):
    OK.append(bool(ok))
    print(f"  {'OK ' if ok else 'BAD'} {label}")


def music_tracks(names):
    sim = racesim.Sim(names)
    mu = sim.mu
    got, flat = set(), True
    for r in list(range(0, 300)) + [32767, 32766, 1234, 9, 18, 8, 17]:
        esp0 = racesim.STACK + 0xF0000
        mu.reg_write(UC_X86_REG_ESP, esp0)
        mu.reg_write(UC_X86_REG_EAX, r)
        mu.emu_start(0x0046E237, 0x0046E244, count=20)
        got.add(mu.reg_read(UC_X86_REG_EAX))
        flat &= mu.reg_read(UC_X86_REG_ESP) == esp0
    return sorted(got), flat


def ambient(names, text):
    sim = racesim.Sim(names)
    mu = sim.mu
    mu.mem_map(MGR, 0x10000, UC_PROT_ALL)
    mu.mem_write(0x012D041C, struct.pack("<I", 1))             # sound on
    lines = text.split(b"\n")
    state = {"opened": None, "next": 0, "mode": None}

    def ret(uc, value, argbytes):
        esp = uc.reg_read(UC_X86_REG_ESP)
        back = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + argbytes)
        uc.reg_write(UC_X86_REG_EIP, back)

    def arg(uc, k):
        return struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * k, 4))[0]

    def vopen(uc, a, s, u):
        # like the real 0x0046fb50 in normal (archive) mode: mode 0 / 1 = a plain file (fopen "rt" / "rb"); an
        # archive id = THAT archive only - a name it does not hold fails (-1), there is no loose fallback
        # (2026-11-01: AmbientDat2.obj asked from the Objects archive -> -1 -> empty lists -> rand % 0 crash)
        state["opened"] = bytes(uc.mem_read(arg(uc, 0), 64)).split(b"\0")[0].decode()
        state["mode"] = arg(uc, 1)
        ret(uc, 5 if state["mode"] in (0, 1) else -1, 0xC)   # 5 = a loose-file handle (< 0x3e8)

    def vgets(uc, a, s, u):
        buf, n = arg(uc, 0), arg(uc, 1)
        i = state["next"]
        state["next"] += 1
        line = lines[i] if i < len(lines) else b""
        mu.mem_write(buf, line[:n - 1] + b"\0")              # fgets + the loose path's '\n' strip
        ret(uc, buf, 0xC)

    def vclose(uc, a, s, u):
        ret(uc, 0, 4)
    mu.hook_add(UC_HOOK_CODE, vopen, begin=0x0046FB50, end=0x0046FB50)
    mu.hook_add(UC_HOOK_CODE, vgets, begin=0x0046ECA0, end=0x0046ECA0)
    mu.hook_add(UC_HOOK_CODE, vclose, begin=0x0046EB80, end=0x0046EB80)
    esp = racesim.STACK + 0xF0000
    mu.mem_write(esp, struct.pack("<I", 0x0BADF00D))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, MGR)
    mu.emu_start(0x0046D850, 0x0BADF00D, count=200000)
    counts = struct.unpack("<4I", mu.mem_read(MGR + 0x44B8, 16))
    lists = []
    for base, n in zip((0x44C8, 0x64A8, 0x8488, 0xA468), counts):
        lists.append([bytes(mu.mem_read(MGR + base + 0xFF * k, 0xFF)).split(b"\0")[0].decode() for k in range(n)])
    return state["opened"], state["mode"], counts, lists


def main():
    names = ["slack"]
    stock, flat = music_tracks(names)
    check(f"stock: race music picks TrR{stock[0]:02d}..TrR{stock[-1]:02d}", stock == list(range(1, 9)) and flat)
    new, flat = music_tracks(names + ["newaudio"])
    check(f"newaudio: picks TrR{new[0]:02d}..TrR{new[-1]:02d} (all 9 reachable), stack untouched",
          new == list(range(1, 10)) and flat)

    text = open(LIST, "rb").read()
    opened, mode, counts, lists = ambient(names + ["newaudio"], text)
    check(f"the exe asks for {opened}", opened == "Data/Audio/AmbTrks/AmbientDat2.obj")
    check(f"... as a plain file (open mode {mode:#x}: 0 = fopen 'rt'; 0x3e8 searches only Objects.pak)",
          mode == 0)
    check(f"counts city day/night, forest day/night = {counts}", counts == (5, 5, 3, 4))
    want = [[f"Data/Audio/AmbTrks/AmbCityD0{k}.wav" for k in range(1, 5)] + ["Data/Audio/AmbTrks/AmbCityX01.wav"]] * 2
    want += [[f"Data/Audio/AmbTrks/AmbFrstD0{k}.wav" for k in range(1, 4)],
             [f"Data/Audio/AmbTrks/AmbFrstN0{k}.wav" for k in range(1, 5)]]
    check("every stored name exact (no stray characters): " + ", ".join(
        os.path.basename(x) for x in lists[0][-1:] + lists[3][-1:]), lists == want)
    for f in want[0] + want[2] + want[3]:
        rel = f.replace("/", os.sep)
        here = os.path.exists(os.path.join(HERE, "New audio", rel)) or os.path.exists(
            os.path.join(HERE, "extracted", "SD", "files", rel))
        if not here:
            check(f"{f} exists (new audio or SD.pak)", False)
    check("every listed track exists (SD.pak or the new files)", True)
    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
