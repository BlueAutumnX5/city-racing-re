r"""City Racing (GameTop) .hdr/.pak archive tool.

Format, per archive pair <name>.hdr / <name>.pak in Data\:

  .hdr : [record][record]...[uint32 entry count LE]
         record = [filename bytes XOR 0x80][0x00][uint32 size LE][uint32 offset LE]
  .pak : payloads back to back, no padding, no compression, no checksum

The trailing uint32 is the number of entries - it must be RECOMPUTED when files are
added or removed, not copied. Verified: 284/336/822/119 for Objects/Textures/World/SD.

Payloads of .obj files (Objects.pak) are themselves XOR 0x80; everything else is raw
(DDS/JPEG/WAV/mesh). Filenames in the index are always XOR 0x80.
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import hashlib
import json
import os
import struct
import sys

GAME_DATA = crpaths.LIVE_DATA
ARCHIVES = ("Objects", "Textures", "World", "SD")


def xor80(b: bytes) -> bytes:
    """Deobfuscate/obfuscate - XOR 0x80 is its own inverse."""
    return bytes(c ^ 0x80 for c in b)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest().upper()


def read_index(hdr_path):
    """Return (entries, stored_count) where entries is [(name, size, offset), ...]."""
    d = open(hdr_path, "rb").read()
    entries = []
    i = 0
    while True:
        j = d.find(b"\x00", i)
        if j < 0 or j + 9 > len(d):
            break
        name = xor80(d[i:j]).decode("latin-1")
        size, off = struct.unpack_from("<II", d, j + 1)
        entries.append((name, size, off))
        i = j + 9
    rest = d[i:]
    stored = struct.unpack("<I", rest)[0] if len(rest) == 4 else None
    return entries, stored


def build_index(entries) -> bytes:
    """Inverse of read_index. Count is derived, never copied."""
    out = bytearray()
    for name, size, off in entries:
        out += xor80(name.encode("latin-1"))
        out += b"\x00"
        out += struct.pack("<II", size, off)
    out += struct.pack("<I", len(entries))
    return bytes(out)


def load_archive(data_dir, arc):
    """Return (entries, stored_count, [payloads], raw_pak_bytes)."""
    entries, stored = read_index(os.path.join(data_dir, arc + ".hdr"))
    blob = open(os.path.join(data_dir, arc + ".pak"), "rb").read()
    payloads = [blob[o:o + s] for _, s, o in entries]
    return entries, stored, payloads, blob


def build_archive(names, payloads):
    """Recompute offsets sequentially and emit (hdr_bytes, pak_bytes)."""
    entries = []
    off = 0
    pak = bytearray()
    for name, payload in zip(names, payloads):
        entries.append((name, len(payload), off))
        pak += payload
        off += len(payload)
    return build_index(entries), bytes(pak)


# ---------------------------------------------------------------- diagnostics

def cmd_diag():
    for arc in ARCHIVES:
        hdr = os.path.join(GAME_DATA, arc + ".hdr")
        pak = os.path.join(GAME_DATA, arc + ".pak")
        entries, stored = read_index(hdr)
        pak_len = os.path.getsize(pak)
        last_end = entries[-1][1] + entries[-1][2]

        print(f"=== {arc} ===")
        print(f"  entries        : {len(entries)}")
        print(f"  stored count   : {stored}   match={'YES' if stored == len(entries) else 'NO'}")
        print(f"  pak size       : {pak_len}")
        print(f"  last off+size  : {last_end}   match={'YES' if last_end == pak_len else 'NO'}")

        gaps, exp = [], 0
        for name, size, off in entries:
            if off != exp:
                gaps.append((name, exp, off))
            exp = off + size
        print(f"  gaps/overlaps  : {len(gaps)}" + (f"  first={gaps[0]}" if gaps else ""))

        seen, dups = set(), []
        for name, _, _ in entries:
            if name in seen:
                dups.append(name)
            seen.add(name)
        print(f"  duplicate names: {len(dups)}" + (f"  e.g. {dups[:3]}" if dups else ""))

        bad = {ch for name, _, _ in entries for ch in name
               if ch in '<>:"\\|?*' or ord(ch) < 32 or ord(ch) > 126}
        print(f"  odd chars      : {sorted(bad) if bad else 'none (safe for disk)'}")
        zeros = [n for n, s, _ in entries if s == 0]
        print(f"  zero-length    : {len(zeros)}" + (f"  e.g. {zeros[:3]}" if zeros else ""))
        print()


# ------------------------------------------------------- test A: in-memory RT

def cmd_roundtrip_mem():
    allok = True
    for arc in ARCHIVES:
        entries, stored, payloads, blob = load_archive(GAME_DATA, arc)
        hdr_orig = open(os.path.join(GAME_DATA, arc + ".hdr"), "rb").read()
        names = [n for n, _, _ in entries]
        hdr_new, pak_new = build_archive(names, payloads)

        ok_h = sha256(hdr_new) == sha256(hdr_orig)
        ok_p = sha256(pak_new) == sha256(blob)
        allok &= ok_h and ok_p
        print(f"  {arc:9s} hdr {'MATCH ' if ok_h else 'DIFFER'}  pak {'MATCH ' if ok_p else 'DIFFER'}"
              f"   {len(entries)} entries")
        if not ok_h:
            print(f"      orig {sha256(hdr_orig)[:16]} len {len(hdr_orig)}"
                  f" | new {sha256(hdr_new)[:16]} len {len(hdr_new)}")
        if not ok_p:
            print(f"      orig {sha256(blob)[:16]} len {len(blob)}"
                  f" | new {sha256(pak_new)[:16]} len {len(pak_new)}")
    print("\nIN-MEMORY ROUND TRIP:", "PASS" if allok else "FAIL")
    return 0 if allok else 1


# ------------------------------------------------------------ unpack / repack

def cmd_unpack(arc, outdir, quiet=False):
    entries, stored, payloads, _ = load_archive(GAME_DATA, arc)
    os.makedirs(outdir, exist_ok=True)
    names = []
    for (name, size, off), payload in zip(entries, payloads):
        dst = os.path.join(outdir, "files", name.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(payload)
        names.append(name)
    with open(os.path.join(outdir, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"archive": arc, "names": names}, f, indent=1)
    if not quiet:
        print(f"  unpacked {len(names):>4} files from {arc}")


def cmd_pack(indir, out_hdr, out_pak, quiet=False):
    with open(os.path.join(indir, "_index.json"), encoding="utf-8") as f:
        meta = json.load(f)
    payloads = [open(os.path.join(indir, "files", n.replace("/", os.sep)), "rb").read()
                for n in meta["names"]]
    hdr, pak = build_archive(meta["names"], payloads)
    os.makedirs(os.path.dirname(out_hdr) or ".", exist_ok=True)
    open(out_hdr, "wb").write(hdr)
    open(out_pak, "wb").write(pak)
    if not quiet:
        print(f"  packed   {len(payloads):>4} files -> {os.path.basename(out_pak)}"
              f" ({len(pak)} bytes)")


def cmd_roundtrip_disk(workdir):
    allok = True
    for arc in ARCHIVES:
        d = os.path.join(workdir, "extracted", arc)
        cmd_unpack(arc, d)
        oh = os.path.join(workdir, "rebuilt", arc + ".hdr")
        op = os.path.join(workdir, "rebuilt", arc + ".pak")
        cmd_pack(d, oh, op)
        h_orig = sha256(open(os.path.join(GAME_DATA, arc + ".hdr"), "rb").read())
        p_orig = sha256(open(os.path.join(GAME_DATA, arc + ".pak"), "rb").read())
        h_new = sha256(open(oh, "rb").read())
        p_new = sha256(open(op, "rb").read())
        ok = (h_orig == h_new) and (p_orig == p_new)
        allok &= ok
        print(f"  {arc:9s} hdr {'MATCH ' if h_orig==h_new else 'DIFFER'}"
              f"  pak {'MATCH ' if p_orig==p_new else 'DIFFER'}")
    print("\nVIA-DISK ROUND TRIP:", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "diag"
    if cmd == "diag":
        cmd_diag()
    elif cmd == "rt-mem":
        sys.exit(cmd_roundtrip_mem())
    elif cmd == "rt-disk":
        sys.exit(cmd_roundtrip_disk(sys.argv[2]))
    elif cmd == "unpack":
        cmd_unpack(sys.argv[2], sys.argv[3])
    elif cmd == "pack":
        cmd_pack(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
