"""Full reference map of game.exe + string fingerprints per function.
Saved as a pickle so later probes load it instantly."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import os, pickle, re, struct, sys, bisect
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *
import rtti
from capstone.x86 import X86_OP_MEM, X86_OP_IMM

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xmap.pkl")

def build():
    md.detail = True
    refs = {}            # target va -> [insn va]
    insns = {}           # insn va -> text (only those with an absolute ref, to keep it small)
    off = TSTART
    while off < TEND:
        last = None
        for ins in md.disasm(data[off:min(TEND, off + 0x4000)], raw2va(off)):
            for op in ins.operands:
                a = None
                if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    a = op.mem.disp & 0xFFFFFFFF
                elif op.type == X86_OP_IMM:
                    a = op.imm & 0xFFFFFFFF
                if a and a >= 0x00400000:
                    refs.setdefault(a, []).append(ins.address)
                    insns[ins.address] = f"{ins.mnemonic} {ins.op_str}"
            last = ins.address + ins.size
        off = va2raw(last) if last and va2raw(last) > off else off + 1
    # strings in .rdata and .data
    strings = {}
    for nm, va, vsz, raw, rsz in SECS:
        if nm not in (".rdata", ".data"):
            continue
        for m in re.finditer(rb"[\x20-\x7e]{4,}", data[raw:raw + rsz]):
            strings[IMG + va + m.start()] = m.group().decode("latin-1")
    # fingerprint: function start -> strings it references
    fp = {}
    for sva, s in strings.items():
        for iva in refs.get(sva, []):
            f = rtti.containing(iva)
            fp.setdefault(f, []).append(s)
    return dict(refs=refs, insns=insns, strings=strings, fp=fp,
                starts=rtti.STARTS, fclass=rtti.func_class)

def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    m = build()
    pickle.dump(m, open(CACHE, "wb"))
    return m

if __name__ == "__main__":
    m = load()
    print(f"{len(m['refs']):,} referenced addresses, {len(m['strings']):,} strings, "
          f"{len(m['fp']):,} functions with string fingerprints")
    # class-ish / path-ish strings, to see what vocabulary we have
    interesting = sorted({s for f, ss in m["fp"].items() for s in ss
                          if re.search(r"C[A-Z][a-z]+[A-Z]?\w*|Data/|[Tt]raffic|[Pp]olice|"
                                       r"[Dd]ist|[Ll]od|LOD|[Ff]og|[Ss]tatic|[Oo]bject", s)})
    print(f"\n{len(interesting)} fingerprint strings of interest:")
    for s in interesting[:220]:
        print("  ", s[:100])
