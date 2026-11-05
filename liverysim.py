"""Unicorn proof for the `carsounds` and `keeplivery` extras (player 2026-10-31).

Runs the patched hook sites of a real racemod build. The game functions the caves call (texture cache
lookup/acquire/release, the body-paint baker, the save file's read/write/close) are replaced by
recorders, so each test sees exactly which calls the cave makes, with which arguments, and that the
stack and the callee-saved registers come back intact."""
import struct
import sys

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_PROT_ALL
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                               UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
                               UC_X86_REG_EIP)

import racemod
from drivesim import build, check as _check, OK


def check(cond, label):
    _check(label, cond)

CAR, STR, STACK = 0x07400000, 0x07420000, 0x07500000
PLAYER = 0x012D0C88
FILE = 7
DECALS = ["Data/Vehicles/DecalEmpty.bmp"] + [f"Data/Vehicles/08/Decal{k:02d}A.bmp" for k in range(1, 7)]
HANDLE0 = 100                                    # texture cache index of DECALS[0]; others follow


class Sim:
    def __init__(self, exe):
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_32)
        secs = racemod.sections(exe)
        end = max(b + v for b, v, _, _ in secs)
        mu.mem_map(0x00400000, (end - 0x00400000 + 0xFFF) & ~0xFFF)
        mu.mem_write(0x00400000, exe[:0x1000])
        for b, v, raw, rsz in secs:
            mu.mem_write(b, exe[raw:raw + rsz])
        mu.mem_map(0x07400000, 0x200000, UC_PROT_ALL)
        self.calls = []
        self.read_gives = None                   # bytes the fake fread puts in the buffer (None = EOF)
        self.stubs = {0x00410140: (4, self._lookup), 0x0040AD00: (0xC, self._acquire),
                      0x0040ADA0: (4, self._release), 0x004101C0: (0xC, self._bake),
                      0x0046EE50: (0x10, self._write), 0x0046EDF0: (0x10, self._read),
                      0x0046EB80: (4, self._close)}
        for a, (n, _) in self.stubs.items():
            mu.mem_write(a, b"\xc2" + struct.pack("<H", n))
            mu.hook_add(UC_HOOK_CODE, self._stub, begin=a, end=a)

    # --- memory helpers
    def r32(self, a):
        return struct.unpack("<I", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def cstr(self, a):
        return bytes(self.mu.mem_read(a, 256)).split(b"\0")[0].decode()

    def arg(self, k):
        return self.r32(self.mu.reg_read(UC_X86_REG_ESP) + 4 * k)

    # --- the stubbed game functions
    def _stub(self, mu, addr, size, ud):
        self.stubs[addr][1]()

    def _lookup(self):
        name = self.cstr(self.arg(1))
        self.calls.append(("lookup", name, self.mu.reg_read(UC_X86_REG_ECX)))
        self.mu.reg_write(UC_X86_REG_EAX, HANDLE0 + DECALS.index(name) if name in DECALS else 0xFFFFFFFF)

    def _acquire(self):
        self.calls.append(("acquire", self.cstr(self.arg(1)), self.arg(2), self.arg(3),
                           self.mu.reg_read(UC_X86_REG_ECX)))
        self.mu.reg_write(UC_X86_REG_EAX, 555)

    def _release(self):
        self.calls.append(("release", self.arg(1), self.mu.reg_read(UC_X86_REG_ECX)))

    def _bake(self):
        self.calls.append(("bake", self.arg(1), self.arg(2), self.arg(3), self.mu.reg_read(UC_X86_REG_ECX)))

    def _write(self):
        buf, size, count, f = self.arg(1), self.arg(2), self.arg(3), self.arg(4)
        self.calls.append(("write", bytes(self.mu.mem_read(buf, size * count)), f))

    def _read(self):
        buf, size, count, f = self.arg(1), self.arg(2), self.arg(3), self.arg(4)
        self.calls.append(("read", size * count, f))
        if self.read_gives is not None:
            self.mu.mem_write(buf, self.read_gives)

    def _close(self):
        self.calls.append(("close", self.arg(1)))

    # --- run one hook site
    def run(self, start, stop, regs):
        mu = self.mu
        self.calls = []
        esp = STACK + 0x8000
        base = dict(eax=0x11111111, ebx=0x22222222, ecx=0x33333333, edx=0x44444444, esi=FILE,
                    edi=0x66666666, ebp=0x77777777)
        base.update(regs)
        for n, r in (("eax", UC_X86_REG_EAX), ("ebx", UC_X86_REG_EBX), ("ecx", UC_X86_REG_ECX),
                     ("edx", UC_X86_REG_EDX), ("esi", UC_X86_REG_ESI), ("edi", UC_X86_REG_EDI),
                     ("ebp", UC_X86_REG_EBP)):
            mu.reg_write(r, base[n])
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(start, stop, count=10000)
        out = {n: mu.reg_read(r) for n, r in (("ebx", UC_X86_REG_EBX), ("ecx", UC_X86_REG_ECX),
                                               ("edx", UC_X86_REG_EDX), ("esi", UC_X86_REG_ESI),
                                               ("edi", UC_X86_REG_EDI), ("ebp", UC_X86_REG_EBP))}
        out["esp_ok"] = mu.reg_read(UC_X86_REG_ESP) == esp
        out["eip"] = mu.reg_read(UC_X86_REG_EIP)
        return out, base


def car(sim, decal_index=3, ndecals=len(DECALS)):
    sim.w32(PLAYER, CAR)
    sim.w32(CAR + 0xE74, ndecals)
    for k, name in enumerate(DECALS):
        sim.mu.mem_write(CAR + 0xE78 + k * 0xFF, name.encode() + b"\0")
    sim.w32(CAR + 0xE70, HANDLE0 + decal_index)


def main():
    st = racemod.load_state()
    base = [n for n in st.get("extras", []) if n in racemod.EXTRAS and n not in ("carsounds", "keeplivery")]
    racemod.set_carsounds({"01": 4, "02": 0, "03": 6, "04": 1, "05": 2, "06": -1, "07": 7, "08": 3,
                           "01P": 5, "03P": 6})
    print("extras: saved + carsounds + keeplivery\n")
    exe = build(base + ["carsounds", "keeplivery"])
    sim = Sim(exe)

    print("carsounds - the car constructor at 0x00436ae2 (eax = the stock rand() % 8 = 5)")
    want = {"Data/Vehicles/01/Main.obj": 4, "Data/Vehicles/02/Main.obj": 0, "Data/Vehicles/03/Main.obj": 6,
            "Data/Vehicles/04/Main.obj": 1, "Data/Vehicles/05/Main.obj": 2, "Data/Vehicles/07/Main.obj": 7,
            "Data/Vehicles/08/Main.obj": 3, "Data/Vehicles/01/Police.obj": 5, "Data/Vehicles/03/Police.obj": 6}
    good = True
    for path, w in want.items():
        sim.mu.mem_write(STR, path.encode() + b"\0")
        out, inp = sim.run(0x00436AE2, 0x00436AE8, dict(eax=5, ebx=STR, esi=CAR, ecx=0x012CC128, edx=0xABCD))
        got = sim.r32(CAR + 0x7FEC)
        ok = (got == w and out["eip"] == 0x00436AE8 and out["esp_ok"] and out["ecx"] == 0x012CC128
              and out["edx"] == 0xABCD and out["ebx"] == STR and out["esi"] == CAR)
        good &= ok
        print(f"     {path:<30} -> E{got + 1:02d}{'' if ok else f'   WRONG (want E{w + 1:02d})'}")
    check(good, "every model and both police cars get their own table sound; ecx/edx/stack untouched")
    for path in ("Data/Vehicles/06/Main.obj", "Data/Vehicles/Wheels/01/MainL.obj", "Something/else.obj"):
        sim.mu.mem_write(STR, path.encode() + b"\0")
        sim.run(0x00436AE2, 0x00436AE8, dict(eax=5, ebx=STR, esi=CAR))
        check(sim.r32(CAR + 0x7FEC) == 5, f"{path}: 'random' or not a car -> the stock rand() pick (E06) stays")
    check(bytes(sim.mu.mem_read(0x0043C3A4, 6)) == b"\x90" * 6,
          "AI placement 0x0043c3a4: the second random roll is gone (rand() is still called before it)")
    check(bytes(sim.mu.mem_read(0x0043C393, 5))[0] == 0xE8, "... the rand() call itself is still there")

    print("\nkeeplivery - save (0x00421b38, esi = the open file)")
    car(sim, decal_index=3)
    out, inp = sim.run(0x00421B38, 0x00421B43, {})
    writes = [c for c in sim.calls if c[0] == "write"]
    check(writes == [("write", b"CRLV" + struct.pack("<i", 3), FILE)],
          f"appends 'CRLV' + decal 3 to the save file ({writes})")
    check(sim.calls[-1] == ("close", FILE), "then closes the file, as the stock code does")
    check(all(c[2] == 0x0255DA6C for c in sim.calls if c[0] == "lookup"),
          "decal found by name in the texture cache (this = 0x0255da6c, the cache the constructor fills)")
    check(out["esp_ok"] and out["eip"] == 0x00421B43 and all(out[r] == inp[r] for r in ("ebx", "esi", "edi", "ebp")),
          "stack, ebx, esi, edi, ebp as before; back at 0x00421b43")
    car(sim, decal_index=0)
    sim.run(0x00421B38, 0x00421B43, {})
    check([c for c in sim.calls if c[0] == "write"] == [("write", b"CRLV" + struct.pack("<i", 0), FILE)],
          "decal 0 (DecalEmpty) is saved too")
    car(sim, decal_index=3)
    sim.w32(CAR + 0xE70, 9999)
    sim.run(0x00421B38, 0x00421B43, {})
    check(not [c for c in sim.calls if c[0] == "write"] and sim.calls[-1] == ("close", FILE),
          "decal texture not in the list: nothing appended, file closed")
    sim.w32(PLAYER, 0)
    sim.run(0x00421B38, 0x00421B43, {})
    check(sim.calls == [("close", FILE)], "no player car: only the stock close")

    print("\nkeeplivery - load (0x00421cf7)")
    car(sim, decal_index=5)                      # the rebuilt car rolled decal 5
    sim.read_gives = b"CRLV" + struct.pack("<i", 2)
    out, inp = sim.run(0x00421CF7, 0x00421D02, {})
    check(sim.calls[0] == ("read", 8, FILE), "reads 8 more bytes from the save")
    check(("bake", CAR + 0x1E68, CAR + 0xE48, 8, 0x0255DA6C) in sim.calls,
          "re-bakes the body paint texture from the loaded colour (the stock load never does)")
    check(("release", HANDLE0 + 5, 0x0255D7F0) in sim.calls, "releases the decal the rebuilt car rolled")
    check(("acquire", DECALS[2], 0, 1, 0x0255D7F0) in sim.calls and sim.r32(CAR + 0xE70) == 555,
          f"puts the saved decal back ({DECALS[2]}), acquired like the constructor does")
    check(sim.calls[-1] == ("close", FILE), "then the stock close")
    check(out["esp_ok"] and out["eip"] == 0x00421D02 and all(out[r] == inp[r] for r in ("ebx", "esi", "edi", "ebp")),
          "stack, ebx, esi, edi, ebp as before; back at 0x00421d02")
    car(sim, decal_index=5)
    sim.read_gives = None
    sim.run(0x00421CF7, 0x00421D02, {})
    check([c[0] for c in sim.calls] == ["read", "bake", "close"] and sim.r32(CAR + 0xE70) == HANDLE0 + 5,
          "an OLD save (no block, fread hits the end): paint re-baked, decal left alone")
    car(sim, decal_index=5)
    sim.read_gives = b"CRLV" + struct.pack("<i", 99)
    sim.run(0x00421CF7, 0x00421D02, {})
    check([c[0] for c in sim.calls] == ["read", "bake", "close"], "a decal number past the car's list is ignored")
    sim.read_gives = b"XXXX" + struct.pack("<i", 2)
    sim.run(0x00421CF7, 0x00421D02, {})
    check([c[0] for c in sim.calls] == ["read", "bake", "close"], "no 'CRLV' tag: ignored")
    sim.w32(PLAYER, 0)
    sim.read_gives = b"CRLV" + struct.pack("<i", 2)
    sim.run(0x00421CF7, 0x00421D02, {})
    check([c[0] for c in sim.calls] == ["read", "close"], "no player car: read + close only")

    print("\nwithout the extras")
    stock = Sim(build(base))
    check(all(bytes(stock.mu.mem_read(va, len(orig))) == orig
              for n in ("carsounds", "keeplivery") for va, orig, new, _ in racemod.PATCHES[n][:2]),
          "all four hook sites are the original bytes")

    print(f"\n{sum(OK)}/{len(OK)} checks passed")
    sys.exit(0 if all(OK) else 1)


if __name__ == "__main__":
    main()
