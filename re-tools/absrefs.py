"""Every instruction in the pristine .text that references one of the given absolute addresses
(memory operands or immediates). Usage: absrefs.py 0x5692c0 [...]"""
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdis import text_insns

want = {int(a, 16) for a in sys.argv[1:]}
pat = re.compile(r"0x[0-9a-f]{5,8}")
for ins in text_insns():
    for m in pat.finditer(ins.op_str):
        if int(m.group(0), 16) in want:
            print(f"  {ins.address:08x}  {ins.mnemonic} {ins.op_str}")
            break
