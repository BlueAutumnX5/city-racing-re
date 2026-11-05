import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys,re; sys.path.insert(0, crpaths.RETOOLS); from crdis import data, va2raw, md; import xmap; m=xmap.load(); S=m['strings']; pend=None
for ins in md.disasm(data[va2raw(0x456480):va2raw(0x456600)], 0x456480):
    t=ins.mnemonic+' '+ins.op_str; mm=re.search(r'push (0x[0-9a-f]+)', t)
    if mm and int(mm.group(1),16) in S: pend=S[int(mm.group(1),16)]
    mv=re.match(r'mov eax, (0x[0-9a-f]+|\d+)$', t)
    if mv and pend: print(f'   {pend:<22} -> {int(mv.group(1),0)}'); pend=None
