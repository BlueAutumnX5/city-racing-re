"""The race-setup function around the walker call, and the walker's start section."""
import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import sys
sys.path.insert(0, crpaths.RETOOLS)
from crdis import *

print("=== race setup 0x00440570 .. walker call ===")
print(dis(0x00440570, 150))
print("\n=== after the walker call: failure path 0x00440778 ===")
print(dis(0x00440778, 30))
print("\n=== walker start section 0x00432b99 .. 0x00432c24 ===")
print(dis(0x00432b99, 40))
