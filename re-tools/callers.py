"""List direct call/jmp sites of one or more targets in the pristine .text.
Usage: callers.py 0x539d20 [0x538dd0 ...]"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdis import text_insns

want = {int(a, 16) for a in sys.argv[1:]}
for ins in text_insns():
    if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
        t = int(ins.op_str, 16)
        if t in want:
            print(f"  {ins.address:08x}  {ins.mnemonic} 0x{t:08x}")
