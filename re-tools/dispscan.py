"""Find every instruction in the pristine .text using a given displacement.
Usage: dispscan.py 0x7f84 [0x7f88 ...]   (matches [reg + disp] memory operands)"""
import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from pdis import text_insns

want = {int(a, 16) for a in sys.argv[1:]}
pat = re.compile(r"\+ (0x[0-9a-f]+)\]")
for ins in text_insns():
    for m in pat.finditer(ins.op_str):
        if int(m.group(1), 16) in want:
            print(f"  {ins.address:08x}  {ins.mnemonic} {ins.op_str}")
            break
