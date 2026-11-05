r"""City Racing race-course / RNG patcher - "how chaotic should the races be?"

WHAT GENERATES A RACE
---------------------
There is no race file anywhere in the game. A course is built at runtime by a RANDOM WALK
over the yellow driving-line network (route kind 3), in game.exe at 0x00432b40:

    start  = nearest kind-3 cell to the billboard      (0x00432b78, the literal `push 3`)
    step   = rand() % (number of neighbours not recently visited)
    record = the cell's (column,row) into an output array, max 0x800 = 2048 points
    stop   = when the step budget runs out, at a dead end, or at 2048 points
    reject = if fewer than 0x1e = 30 points were collected

Two consequences worth knowing:

  * Races ONLY follow kind 3 (yellow). Not kind 4, not kind 2, not plain road. So the way
    to send a race off the tarmac is to DRAW NEW YELLOW LINE with mapeditor.py - the
    generator will then walk onto it like any other road.
  * The step budget is computed from a distance ratio at the call site (0x004406c1), so
    race length normally scales with how far away the destination is.

THE PATCHES
-----------
Every one is byte-for-byte reversible and is verified against the expected original bytes
before it is written, so a patch can never land on the wrong instruction.

  reshuffle   swap the RNG's two constants for a different full-period generator.
              Every random decision in the game changes - all 215 rand() call sites.
  nostep      make the step budget decrement by 0 instead of 1, so it never runs down.
              The course then grows until the 2048-point cap or a dead end.

              THIS ONE NEEDS `wander`. Normally the walk ends when the budget hits zero,
              and that counts as SUCCESS. With nostep the only two endings left are the
              2048-point cap (success) and a dead end (FAILURE - the generator returns 0
              and no billboard is placed). `wander` lets the walk step back onto cells it
              has already used, which is what stops it painting itself into a cul-de-sac.
              Every level below that includes nostep therefore includes wander too.

  wander      NOP the three "don't revisit the last 3 cells" tests (0x00432c7f/85/8b).
              The walk may cross its own path, so courses knot back on themselves.
              The immediate-reverse test is DELIBERATELY LEFT IN - without it the walk
              would bounce between two cells forever.
  junction    lower the "cells since the last junction" threshold at 0x00432c2e from 4.
              Below that the generator throws the whole course away and restarts, so a
              lower number lets it keep courses that cross junctions in quick succession.
  noseed      turn srand() (0x0054ab91) into a bare `ret`. Reseeding stops happening, so
              anything the game reseeds deterministically stops being reproducible.
              This also affects landscape scatter, which reseeds per terrain sector - so
              scenery will differ every time a sector loads. Loud, and the riskiest one.

LEVELS
------
  Every level includes `astarfix`. Measured in racesim, 1,200 courses each, 0 overflows:

  1 mild     reshuffle                        stock feel, different routes
  2 twisty   + wander + spread                length is a lottery (0.7..8 km), ~6 U-turns
  3 wild     + nostep + wander + junction     always ~7.5 km, ~10 U-turns
  4 insane   level 3 + noseed                 + scenery can reshuffle as you drive
  5 anarchy  level 4 + reverse                ~20 U-turns, frantic zig-zag on a few
                                              streets near the billboard

If race billboards ever disappear from the map, the course generator is failing for every
billboard - `restore` and report which level it was on.

USAGE
-----
  racemod.py show                 what is patched right now
  racemod.py level 2              apply a level
  racemod.py apply nostep wander  apply named patches
  racemod.py restore              byte-for-byte back to the original game.exe
"""

import crpaths  # noqa: E402  (machine paths: crpaths.py / local.ini)
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys

GAME = crpaths.GAME_EXE
STOCK = crpaths.STOCK_EXE
BACKUP = crpaths.RACEMOD_BACKUP

# A different full-period LCG. Hull-Dobell: increment odd, (multiplier-1) divisible by 4.
NEW_MUL, NEW_ADD = 1664525, 1013904223

# name -> (virtual address, original bytes, patched bytes, one-line description)
PATCHES = {
    "reshuffle": [
        (0x0054abad, struct.pack("<I", 214013), struct.pack("<I", NEW_MUL),
         "RNG multiplier"),
        (0x0054abb3, struct.pack("<I", 2531011), struct.pack("<I", NEW_ADD),
         "RNG increment"),
    ],
    # Change the IMMEDIATE from 1 to 0, so the instruction still runs and still sets the
    # flags - it just subtracts nothing.
    #
    # DO NOT go back to NOPping the whole instruction. That was the first attempt and it
    # removed every race billboard from the game:
    #
    #   00432cc1  sub dword [esp+0x64], 1     <- sets ZF
    #   00432cc6  mov edi, [0x12d0cd4]        |
    #   00432ccc  mov ecx, [esp+edx*4+0x2c]   |  none of these touch flags
    #   00432cd0  mov esi, [esi+ecx*4+0x10]   |
    #   00432cd4  jne 0x432c24                <- consumes the SUB's ZF
    #
    # The compiler reused the decrement as the loop condition. NOP it out and the `jne`
    # reads flags left by `div edi` two instructions earlier, which x86 leaves
    # ARCHITECTURALLY UNDEFINED. The walk then exits after ~1 step, collects fewer than
    # the 0x1e = 30 points the generator demands (0x00432cda), returns 0, and the caller
    # at 0x0044070c takes `je` and never places the billboard. Reported from play
    # 2026-09-22: "I can't find any yellow or blue race billboard anymore."
    "nostep": [
        (0x00432cc5, b"\x01", b"\x00",
         "step budget decrements by 0 instead of 1 (flags preserved)"),
    ],
    "wander": [
        (0x00432c7f, bytes.fromhex("7411"), b"\x90\x90", "allow revisiting cell -2"),
        (0x00432c85, bytes.fromhex("740b"), b"\x90\x90", "allow revisiting cell -3"),
        (0x00432c8b, bytes.fromhex("7405"), b"\x90\x90", "allow revisiting cell -4"),
    ],
    "junction": [
        (0x00432c2e, b"\x04", b"\x01", "junction spacing 4 -> 1"),
    ],
    "noseed": [
        (0x0054ab91, b"\x8b", b"\xc3", "srand() becomes a no-op"),
    ],
    # The walker refuses to step back onto the cell it just left (0x00432c77/79). With
    # that also gone every neighbour is fair game, including straight back - so the
    # course can reverse ANYWHERE, not only at dead ends and staircase corners.
    "reverse": [
        (0x00432c79, bytes.fromhex("7417"), b"\x90\x90",
         "allow an immediate U-turn anywhere"),
    ],
    # RISK REDUCTION - NOT A GUARANTEE. The finished route lives in a 2048-entry buffer
    # at 0x012cc418, followed by other globals and then the map object's own header
    # (world size, grid size, cell size). With `wander`, the two A* passes can stretch
    # a route to 2.8x its walk (racesim, 2026-09-23), so NO walk cap bounds it:
    #     cap 1536 -> 17/150 courses overflowed      cap 1024 -> 5/400
    #     cap  896 ->  0/400                         cap  768 -> 1/400 (!)
    # 896 is the best measured value, but the tail is random. A real fix has to bound
    # the second A* pass itself. Only the compare's immediate changes here.
    "cap": [
        (0x00432c60, bytes.fromhex("00080000"), struct.pack("<I", 896),
         "walk capped at 896 points (overflow rare, not impossible)"),
    ],
    # Race distance is  rand() % 1001 + 2500*progress + 800  (0x004405c3), then /4 for
    # the step budget. Widening the random part makes race LENGTH chaotic too - from
    # stock-short to as long as `cap` allows - instead of every course maxing out.
    "spread": [
        (0x004405c4, bytes.fromhex("e9030000"), struct.pack("<I", 6001),
         "race length random part 0..1000 -> 0..6000"),
    ],
}

# ---- astarfix: a real bug in the 2005 game, and the actual cause of the overflow ----
#
# The A* pathfinder (0x0042d260) writes its point count in exactly one place,
# `mov [eax], esi` at 0x0042d7ed, reached only after it finds the goal. A search whose
# start equals its end, or whose goal is unreachable, returns 0 WITHOUT WRITING THE
# COUNT. Its callers (the two smoothing passes) never check - they add whatever the
# previous search left there. That skips over buffer slots nobody wrote this time, which
# still hold points from an OLDER race, and the next search then drives the route to
# that ghost location across the city and back.
#
# Proven in racesim by poisoning the count before every call: all 40,838 start==end
# searches left the poison untouched. Stock almost never has start==end. `wander`'s
# U-turns cause it constantly (6 steps out, 6 back = the same cell 12 steps later),
# which is why routes inflated to 2.8x their walk and overflowed.
#
# Fix: jump from A*'s entry to a stub in int3 padding that
#   1. zeroes the count, so a search that fails reports 0 instead of stale garbage;
#   2. returns at once if start == end. The original searches the ENTIRE road network
#      before giving up on those, which made level 3 generate races ~7x slower than
#      stock - a hitch in-game every time a billboard spawns. A failed search returns
#      eax = 0, so returning 0 early gives the callers exactly what they got before.
#   3. otherwise replays the 5 displaced bytes and jumps back into the real A*.
# Arguments at entry: [esp+4] start col, +8 start row, +0xc end col, +0x10 end row,
# +0x18 &count. thiscall, 9 stack args, A*'s only exit is `ret 0x24` (0x0042d836).
# eax and edx are dead at entry (A* overwrites both before reading them); ecx is
# `this` and is left alone.
ASTAR_ENTRY = 0x0042d260
ASTAR_CAVE = 0x004dba55     # 43 bytes of int3 between `ret 0x18` and the next function


def _astarfix():
    displaced = bytes.fromhex("83ec3c5355")          # sub esp,0x3c / push ebx / push ebp
    stub = (bytes.fromhex("8b442418")                # mov eax, [esp+0x18]    &count
            + bytes.fromhex("c70000000000")          # mov dword [eax], 0     count = 0
            + bytes.fromhex("8b442404")              # mov eax, [esp+4]       start col
            + bytes.fromhex("3344240c")              # xor eax, [esp+0xc]     ^ end col
            + bytes.fromhex("8b542408")              # mov edx, [esp+8]       start row
            + bytes.fromhex("33542410")              # xor edx, [esp+0x10]    ^ end row
            + bytes.fromhex("0bc2")                  # or eax, edx
            + bytes.fromhex("7503")                  # jnz go
            + bytes.fromhex("c22400")                # ret 0x24               eax is 0 here
            + displaced                              # go:
            + b"\xe9")
    stub += struct.pack("<i", (ASTAR_ENTRY + 5) - (ASTAR_CAVE + len(stub) + 4))
    jmp = b"\xe9" + struct.pack("<i", ASTAR_CAVE - (ASTAR_ENTRY + 5))
    return [(ASTAR_ENTRY, displaced, jmp, "A* entry jumps to the fix stub"),
            (ASTAR_CAVE, b"\xcc" * len(stub), stub,
             "stub: count = 0; start == end -> return; else run A*")]


PATCHES["astarfix"] = _astarfix()


# ---- leap: the race line sometimes cuts a STRAIGHT line from one road to another ------
#
# Designed with the player 2026-09-24, for "Level Chaos Leap". Two hooks:
#
#   walker, 0x00432cd0   after the normal step picks the next cell, roll the dice. With
#                        probability LEAP_CHANCE/32768 pick a random yellow cell anywhere
#                        (random index, scan forward to the next kind-3 record) and, if it
#                        is LEAP_MIN..LEAP_MAX cells away, continue the walk from THERE.
#   gate, walker's two   the smoothing passes' `call A*` (0x00432d3a, 0x00432dca) go to a
#   A* calls             gate instead: endpoints more than LEAP_GAP cells apart -> count = 0,
#                        return 0, do NOT fill the gap. That gap is what the player sees as a
#                        straight line. Anything else -> jump into the normal A* entry, which
#                        carries astarfix.
#
# Why the thresholds cannot catch a normal race: a smoothing search spans at most 12 walk
# steps, so a normal gap is <= 12 cells, and LEAP_GAP is 16. A leap is >= 60 cells, and
# even after the 12 + 12 walk steps either side are sampled away it stays > 16 in both
# passes. Both ends of every straight line are yellow cells, so every checkpoint stays on
# a road.
#
# v2, 2026-09-24. v1 put the gap rule at A*'s ENTRY, so it hit every caller of A*: the
# path builder 0x00431350 serves traffic spawns (0x004315e0), pedestrians (0x00421f70),
# the camera (0x00402e80), AI re-routing (0x0043cda0) and 0x0044aba0. Stock traffic hops
# are 48 units = 12 cells and slipped under 16, but `view` doubles them to 24 cells, and
# every traffic route was refused: in-game "Vehicles on area: 1(30)", reproduced in
# trafficsim.py (level 7 + view: 0.3% traffic / 0% police routes built). The gate now sits
# on the walker's two call sites only, so no other caller can ever see the leap rule.
# v1 is kept in leap_v1.pickle; racesim proves v2 builds identical race courses.
#
# The code lives in the 469 zero bytes after .text's VirtualSize (0x0056722b..0x00567400).
# VirtualSize is raised to cover them (`slack`), so Windows maps them as code. `leap`
# REQUIRES astarfix: the gate jumps into A*'s entry, and U-turns cause start == end calls.
LEAP_CHANCE = 128                  # per walker step, out of 32768
LEAP_MIN, LEAP_MAX = 60, 200       # leap length in cells (x4 = world units)
LEAP_GAP = 16                      # A* refuses gaps wider than this (normal max is 12)
LEAP_ASTAR = 0x00567230            # A* gate (walker's calls only)
LEAP_WALK = 0x00567280             # walker stub
TEXT_VSIZE_FIELD = 0x00400218      # .text VirtualSize, in the PE section header
RAND_FN = 0x0054aba3
# The walker's two smoothing-pass calls to A* (5-byte `call rel32`), verified 2026-09-24:
# A* has exactly three callers - these two, and 0x004314cd in the path builder.
WALKER_ASTAR_CALLS = (0x00432d3a, 0x00432dca)


def _leap():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(src, at):
        b, _ = ks.asm(src, at)
        return bytes(b)

    # Same stack frame as A*'s entry: [esp] return into the walker, +4 start col,
    # +8 start row, +0xc end col, +0x10 end row, +0x18 &count; thiscall, `ret 0x24`.
    # |d| > GAP  <=>  (d + GAP) >u 2*GAP  (one unsigned compare instead of abs()).
    # Only eax is used: eax/edx are dead at A*'s entry, ecx is `this`.
    astar = asm(f"""
        mov eax, dword ptr [esp+4]
        sub eax, dword ptr [esp+0xc]
        add eax, {LEAP_GAP}
        cmp eax, {2 * LEAP_GAP}
        ja skip
        mov eax, dword ptr [esp+8]
        sub eax, dword ptr [esp+0x10]
        add eax, {LEAP_GAP}
        cmp eax, {2 * LEAP_GAP}
        ja skip
        jmp {ASTAR_ENTRY}
    skip:
        mov eax, dword ptr [esp+0x18]
        mov dword ptr [eax], 0
        xor eax, eax
        ret 0x24
    """, LEAP_ASTAR)
    walk = asm(f"""
        mov esi, dword ptr [esi+ecx*4+0x10]
        pushfd
        call {RAND_FN}
        cmp eax, {LEAP_CHANCE}
        jae done
        call {RAND_FN}
        mov ecx, eax
        shl ecx, 15
        push ecx
        call {RAND_FN}
        pop ecx
        or eax, ecx
        xor edx, edx
        mov ecx, 360000
        div ecx
        lea eax, [edx+edx*2]
        shl eax, 4
        lea eax, [eax+ebp+0x1b98a0]
        lea edx, [ebp+0x12344a0]
    scan:
        cmp byte ptr [eax], 3
        je found
        add eax, 48
        cmp eax, edx
        jb scan
        lea eax, [ebp+0x1b98a0]
        jmp scan
    found:
        movzx ecx, word ptr [eax+0x24]
        movzx edx, word ptr [esi+0x24]
        sub ecx, edx
        mov edx, ecx
        sar edx, 31
        xor ecx, edx
        sub ecx, edx
        push ecx
        movzx ecx, word ptr [eax+0x26]
        movzx edx, word ptr [esi+0x26]
        sub ecx, edx
        mov edx, ecx
        sar edx, 31
        xor ecx, edx
        sub ecx, edx
        pop edx
        cmp ecx, edx
        jae havemax
        mov ecx, edx
    havemax:
        cmp ecx, {LEAP_MIN}
        jb done
        cmp ecx, {LEAP_MAX}
        ja done
        mov esi, eax
    done:
        popfd
        jne 0x00432c24
        jmp 0x00432cda
    """, LEAP_WALK)
    assert LEAP_ASTAR + len(astar) <= LEAP_WALK, "A* gate overruns the walker stub"
    assert LEAP_WALK + len(walk) <= 0x00567400, "leap code overruns the .text slack"
    calls = []
    for site in WALKER_ASTAR_CALLS:
        calls.append((site, b"\xe8" + struct.pack("<i", ASTAR_ENTRY - (site + 5)),
                      b"\xe8" + struct.pack("<i", LEAP_ASTAR - (site + 5)),
                      "walker smoothing pass: call A* -> call leap gate"))
    return calls + [
        (LEAP_ASTAR, bytes(len(astar)), astar,
         f"leap gate: gap > {LEAP_GAP} cells -> count=0, no search; else normal A*"),
        (0x00432cd0, bytes.fromhex("8b748e100f854affffff"),
         b"\xe9" + struct.pack("<i", LEAP_WALK - (0x00432cd0 + 5)) + b"\xcc" * 5,
         "walker step -> leap stub"),
        (LEAP_WALK, bytes(len(walk)), walk,
         f"walker: {LEAP_CHANCE}/32768 per step, leap {LEAP_MIN}..{LEAP_MAX} cells"),
    ]


# The .text VirtualSize bump that makes the 469 zero bytes at 0x0056722b..0x00567400 load
# as code. Its own patch because BOTH `leap` (code) and `view` (constants) live there -
# if each carried the header edit, applying both would fail the original-bytes check.
PATCHES["slack"] = [
    (TEXT_VSIZE_FIELD, struct.pack("<I", 0x16622B), struct.pack("<I", 0x166400),
     ".text VirtualSize covers the slack the leap code and view constants live in"),
]

try:
    PATCHES["leap"] = _leap()
except ImportError:
    pass    # keystone missing: the leap levels are simply unavailable


# ---- view: everything further (designed with the player 2026-09-24) -------------------
#
# Mapped in full before a byte was changed - see memory city-racing-view-distances. The
# rule throughout: a distance and the capacity it fills move TOGETHER, capacity first.
#
# NEVER edit a shared constant in place. 60.0, 20.0, 90.0, 400.0, 100.0 and 500.0 are each
# read by 15-80 instructions across unrelated systems (60.0 is also the race setup's
# billboard radius). Instead each relevant instruction's 4-byte address operand is
# repointed at a PRIVATE constant in the .text slack (after the leap code). Constants
# with exactly one reading function are changed in place.
# Constants live in .rdata's file-backed tail (0x0058f642..0x0058f800: 446 zero bytes, nothing
# references them); `rdataslack` raises .rdata's VirtualSize over them. They used to sit in
# the .text slack, which is now needed for code (the pedestrian and racer-count hooks). They
# cannot go in the .data tail: that part of .data is BSS, zero-filled, not in the file.
VIEW_CONSTS = 0x0058f650
RDATA_VSIZE_FIELD = 0x00400240                   # .rdata VirtualSize, PE section header #2
PATCHES["rdataslack"] = [
    (RDATA_VSIZE_FIELD, struct.pack("<I", 0x27642), struct.pack("<I", 0x27800),
     ".rdata VirtualSize covers its whole raw tail (constants + code) to 0x0058f800"),
]

# ---- rdataexec: the .rdata tail as extra CODE space (2026-09-25) --------------------------
# The .text slack is full (leap, racerfree, fadein, spawnreach end at 0x005673fc of 0x00567400).
# .rdata's raw data runs to 0x0058f800 and its tail 0x0058f642.. was zero; RDATA_CODE onwards
# holds code caves. Its section header's Characteristics (0x0040025c) 0x40000040 (initialized
# data, read) gains IMAGE_SCN_MEM_EXECUTE (0x20000000), so those pages are mapped executable.
# Same-size edit, no new section, no file growth.
RDATA_CODE = 0x0058f700                          # caves: 0x0058f700..0x0058f800 (256 bytes)
RDATA_CODE_END = 0x0058f800
PATCHES["rdataexec"] = [
    (0x0040025c, struct.pack("<I", 0x40000040), struct.pack("<I", 0x60000040),
     ".rdata section executable (code caves in its tail from 0x0058f700)"),
]

# The ONE view-distance number (2026-09-25: 1000 -> 1600, player: "distant buildings
# disappear"). Everything that scales with the view derives from it: the master distance
# 0x00590414 (far plane, fog 0.5*M -> M, chunk streaming, trees 0.7*M, list-2 props 0.2*M, sky),
# the Distance cap and Game.ini Distance = M/200 - 1 (the game computes (v+1)*200), the chunk
# clamp, the object/light caps (stock ratios 400/600 and 100/600), grass (x M/1000 of our 1000
# values) and the ad screens. Must be a multiple of 200 so Game.ini can express it.
VIEW_DISTANCE = 1600.0
assert VIEW_DISTANCE % 200 == 0 and VIEW_DISTANCE >= 600
# Traffic / non-chasing police are removed beyond this (from the camera's ground point /
# the player's car). Module-level because `spawnreach` derives its limit from it.
TRAFFIC_DESPAWN = 160.0
# Which object classes get the lamp view distance (fade 800 -> 1000 m instead of 200 -> 250).
# GTYPE values are single bits (0x200 DECORS, 0x400 LAMPPOST), so one `test` covers both.
# 0x600 = lamps + loose objects/race billboards (player 2026-09-26); 0x400 = lamps only.
LOOSE_LIKE_LAMPS = True
LAMP_CLASS_MASK = 0x600 if LOOSE_LIKE_LAMPS else 0x400
# Collision radius around the CAMERA (2026-09-26, player: "traffic or opponents still go through
# buildings if it was like 40 meters or more" + ramps, loose objects, rocks, trees "until 180").
# Both sides of a collision need a body: cars (traffic + racers; police always have one) and the
# static things they hit. See the `view` constants carphys / bldphys / decorphys / objphys.
# Player's choice (2026-09-26, after "infinite?" - not possible: traffic is gone at 160, trees/rocks
# only exist within ~450/320, and the broadphase holds 32766 bodies at most): cars, buildings,
# trees and rocks 250 (= the chunk buildings; police chase to 200); loose objects, ramps, race
# billboards and lamps only as far as traffic exists.
PHYS_RADIUS = 250.0
LOOSE_PHYS = TRAFFIC_DESPAWN                      # 160


def _view():
    # The fade band, in game distance (= camera distance - the car's radius, [car+0xa24],
    # written by the per-car step 0x0043fbe0 for EVERY car type: traffic, police, racers).
    # Solid to FADE_START, gone at FADE_START + FADE_WIDTH. Used by the in-place fade edits
    # AND by `cardraw` below, so the body is always drawn exactly as far as the fade reaches.
    FADE_START, FADE_WIDTH = 140.0, 10.0
    MASTER = VIEW_DISTANCE          # master view distance (in place at 0x00590414, below)
    STOCK = 600.0                   # stock master distance: scale for the stock-ratio caps
    GRASS = MASTER / 1000.0         # grass was tuned at view 1000 (x2 stock); scale from there
    # Decorations and lamp posts (GTYPE_DECORS 0x200 / GTYPE_LAMPPOST 0x400: benches, cafes,
    # signs, the RACE BILLBOARDS, lamps) had a FIXED 64 -> 80 fade regardless of the Distance
    # setting (player 2026-09-25: race billboards "still fading at close range").
    DECOR_NEAR, DECOR_FAR = 200.0, 250.0
    # Lamp posts only: seen from far away (player 2026-09-25, "as if photographing a distant
    # cityscape from a canyon"). Their distance is scaled by DECOR_FAR / LAMP_FAR before the shared
    # decor fade, so lamps fade LAMP_NEAR -> LAMP_FAR while benches/cafes keep 200 -> 250.
    LAMP_FAR = 1000.0
    LAMP_SCALE = DECOR_FAR / LAMP_FAR
    # 2026-09-26, player: "make the loose objects the same as streetlights ... in the past is one
    # group". LOOSE_LIKE_LAMPS puts decor (0x200: chairs, tables, ramps, cafe sets, race
    # billboards) back in the lamp group: both classes fade LAMP_FAR * 0.8 -> LAMP_FAR
    # (the class test in _view_caves uses the module constant LAMP_CLASS_MASK).
    # Lamp/vehicle coronas grow with distance to keep a constant SCREEN size (0x00414203:
    # size = 1 + (d - 8) / 14.4). Stock hid it (lamps gone by 80 m = 6x, cars by 60 m); at our
    # ranges a straight road stacks 18x-70x additive flares into a wall of light (player
    # screenshot 2026-09-25). Cap the growth at the stock maximum: beyond CORONA_GROW_END a
    # lamp corona keeps its world size and shrinks on screen like a real light. Vehicles are
    # deliberately NOT capped (the player likes the car glare as it is).
    CORONA_GROW_END = 80.0
    CORONA_CAP = (CORONA_GROW_END - 8.0) / 14.4
    # Fog (player 2026-09-25: "fade starts at 1200 instead"). Set every frame by 0x00428800 (start =
    # V*0.5, end = V, V = Distance setting) and at device init by 0x0040f4b0 (master*0.5 / master);
    # both multiply by the SHARED 0.5 (0x005682f8) -> repointed to FOG_START / MASTER. The water
    # fog (0x0042a750, 0.2V -> 0.8V) is separate and unchanged.
    FOG_START = 1200.0
    # Big BUILDING/BRIDGE objects faded V-125 -> V-75 (branch B of 0x00410bd0, shared 125/75 at
    # 0x00568eb8/0x00568ebc, rate 0.02 = 1/50), hidden while fog began at V/2. With fog starting
    # at 1200 they would visibly dissolve before the fog, so the fade moves to V-50 -> V: they
    # disappear exactly as the fog becomes total (and as the chunks end).
    BUILDING_FADE = 50.0                         # = 1/0.02, the unchanged fade width
    consts = [                      # key, value, what it replaces
        ("chunk",    MASTER, "chunk generation clamp (was 500)"),
        ("vdraw",    round(400.0 * MASTER / STOCK), "object/light draw cap (was 400 = 2/3 of 600)"),
        ("vdetail",  round(100.0 * MASTER / STOCK), "direct-light / car-glow cap (was 100 = 1/6)"),
        # Traffic is CENTRED ON THE CAMERA (player's request 2026-09-24: "spawn everywhere
        # equally in the player's proximity, no matter where the camera faces"). Stock put the
        # spawn/despawn centre 60*0.4 = 24 ahead of the camera, the first build 48 ahead, so
        # spawns were 48 behind .. 144 ahead. The anchor offset is now 0: spawns on a ring of
        # 150 around the camera (in-place 0x00569a58), despawn beyond 155 from it, visible
        # only inside 150 (solid to 140), so every car spawns invisible and fades in only
        # as it drives toward the player. Police are centred on the player's car already:
        # ring 150 (0x00569a54), despawn 155, 200 while chasing (player's numbers).
        # 2026-09-25: despawn 155 -> 160 and rings 150 -> 140 (player's choice). spawnlife.py
        # showed 33% of spawns dying within 0.5 s: the ring is centred on the nearest road
        # cell, so many cars landed 155-160 away, past the old despawn line. `fadein` makes
        # spawns inside the fade band (140 -> 150) appear smoothly.
        ("despawn",   TRAFFIC_DESPAWN, "traffic despawn (was 60)"),
        ("pdespawn",  TRAFFIC_DESPAWN, "police despawn (was 60)"),
        ("ppursuit",  200.0, "police despawn while chasing (was 90)"),
        ("anchor",      0.0, "spawn centre offset (was 60; x0.4 = 24 ahead of camera)"),
        # A building exists physically only while its chunk's edge is within this of the
        # camera. At 120 a police car 120-190 away still drove INTO buildings, and when the
        # player closed in the collision appeared around it and Bullet launched it skyward
        # (player report 2026-09-24). Police live to ~190 from the camera, traffic to ~170,
        # so 250 means collision never appears around a car already inside a building.
        ("chunkcol",  250.0, "chunk building-collision radius (was 20)"),
        ("objphys",   PHYS_RADIUS, "tree / rock physics radius (was 20; 60 until 2026-09-26)"),
        ("grass",     140.0 * GRASS, "grass fields drawn within (was 70, a shared constant)"),
        # CAR BODIES STOPPED AT 60 (found 2026-09-25 from the player's night screenshot + a
        # live read: cars 82-139 away with fade 1.00 and the visible flag set showed ONLY
        # their lights). The per-car draw passes run by the traffic manager (0x00442080,
        # 0x00442520, 0x004429f0) skip a car whose [car+0xa24] > the SHARED 60.0: the body
        # itself (0x004355b0: the car's own VB/IB, fade as texture-factor alpha), its other
        # layers (0x00435870, 0x00435a00, 0x00435bc0, 0x00435eb0) and wheels (0x0043bd50,
        # 0x0043c130). Stock despawned every car at 60, so the limit never showed. The
        # lights (0x00415700) have their own cap (vdetail) and only need fade > 0, hence
        # "lights with no body" from 60 out. Bodies now draw to the fade's end.
        # Appended LAST so the other constants keep their addresses.
        ("cardraw", FADE_START + FADE_WIDTH, "car body/layers/wheels drawn within (was 60)"),
        # Static objects (found 2026-09-25). The object draw 0x00410bd0 picks a branch by
        # class [obj+0x9d0] (GTYPE_* from the .obj, table 0x00456360): DECORS/LAMPPOST fade
        # over the SHARED 64/80/0.0625 (0x00568eac/eb0/ea8, read by menus, HUD, D3DX...).
        # Their sub-parts (lamp heads, cafe chairs; list [obj+0xc64]) use the same fade in
        # the static-manager draw 0x00452570, and a building's parts are LOADED within 80
        # and unloaded beyond it (update 0x00453450 -> 0x00453290 / 0x004521c0).
        ("decorfar",  DECOR_FAR,  "decor/lamp fully faded at (was 80)"),
        ("decornear", DECOR_NEAR, "decor/lamp fade starts at (was 64)"),
        ("decorrate", 1.0 / (DECOR_FAR - DECOR_NEAR), "decor/lamp fade 1/width (was 1/16)"),
        # Ad screens on buildings (Data/Static/InfoScreen/02, GTYPE_BUILDING, self-illum
        # texture INFOSCREENn = a 512x256 render target the game draws the adverts into).
        # 0x0046adb0 RELEASES a screen's render target once it is > 200 (shared 0x005685a0)
        # away, but the building keeps drawing the screen, and D3D9 samples an unbound
        # texture as WHITE: the "white billboard far away" bug, in stock too. Keep the
        # target for as long as the building can be seen.
        ("adscreen",  MASTER, "ad-screen render target kept within (was 200)"),
        # Decorations/lamps are switched on and off PER CHUNK (player: "in chunks, like
        # Minecraft"): the chunk step 0x0042f0e0 activates every 0x600-class object of a chunk
        # ([obj+0xa34] via 0x00429420 -> 0x00453180) when the chunk's edge distance
        # [part+0x10c] < 40 (SHARED 0x00569100, 16 readers) and deactivates beyond. That put
        # the switch at ~50..200 per object; with the fade now ending at DECOR_FAR it cut
        # visible objects. Activate while any of them can still be inside the fade:
        # object distance >= chunk edge distance - its radius, so + 10 of margin.
        ("decoract",  max(DECOR_FAR, LAMP_FAR) + 10.0, "decor/lamp chunk activation distance (was 40)"),
        # Spawner 0x00442c90 (mapped 2026-09-25): below target, one attempt per timer tick
        # ([mgr+0x9d78], reloaded at 0x00442e12 from the SHARED 0.1 at 0x00568548). An attempt
        # fails without retry if there is no kind-3 road cell within 10 cells (0x0042c5d0), the
        # route to the ring fails (0x004315e0) or a car is within 10 of it (0x00441aa0). Fill was
        # 65% of target at ~2 spawns/s. 4x the attempts; none happen once the target is met.
        ("spawnint",  0.025, "traffic spawn attempt interval (was 0.1 s)"),
        ("lampscale", LAMP_SCALE, "lamp distance scale for the decor fade (lamps to LAMP_FAR)"),
        ("coronacap", CORONA_CAP, "corona growth cap: (d-8)/14.4 at CORONA_GROW_END"),
        ("fogfrac",   FOG_START / MASTER, "fog start as a fraction of the view (was 0.5)"),
        ("bldnear",   BUILDING_FADE, "building fade starts at V - this (was 125)"),
        ("bldfar",    0.0, "building gone at V - this (was 75)"),
        # COLLISION (2026-09-26). Found by listing every add/remove of a Bullet body:
        # - CARS: the per-car step 0x0043fbe0 -> 0x0043dbb0 gives a traffic car or racer its
        #   collision body ([car+0x8040], add/remove in 0x0043da20) only while [car+0xa24] (its
        #   camera distance) < the SHARED 20 (60 in states [car+0x1e74] 3/4), or while it touches
        #   a bridge (0x00453fc0 class 0x80) or another car (0x00441fb0). Police ([+0xc8c]==2)
        #   always have one. Beyond that a car runs without a body = through EVERYTHING static.
        # - STATIC MANAGER 0x00453450 per object, distance to the camera minus its radius:
        #   BUILDING 0x100 on/off at 20; BRIDGE 0x80 at 20 or any car touching; DECORS/LAMPPOST
        #   at 20 or a car with a body touching (0x00442010). Trees and rocks (the field lists,
        #   0x0044e6b0 / 0x0044eb60 - list 2 IS the stones, Data/Static/Nature/Stones) use objphys.
        ("carphys",   PHYS_RADIUS, "traffic/racer collision body within (was 20, 60 in states 3/4)"),
        ("bldphys",   PHYS_RADIUS, "standalone building collision body within (was 20)"),
        ("decorphys", LOOSE_PHYS,  "loose object/ramp/billboard/lamp collision within (was 20)"),
    ]
    addr, block = {}, b""
    for i, (k, v, _) in enumerate(consts):
        addr[k] = VIEW_CONSTS + 4 * i
        block += struct.pack("<f", v)
    assert VIEW_CONSTS + len(block) <= 0x0058f700, "view constants overrun the .rdata slack"

    repoint = [   # address of the 4-byte operand inside the instruction, old constant, key
        (0x00432fc0, 0x00568588, "chunk",    "landscape loader: min(Distance, 500) clamp"),
        (0x00411e5c, 0x00568edc, "vdraw",    "vehicle render cutoff #1 (min(view, 400))"),
        (0x004140fa, 0x00568edc, "vdraw",    "vehicle render cutoff #2"),
        (0x00417c75, 0x00568edc, "vdraw",    "vehicle render cutoff #3"),
        (0x004152c6, 0x005682e8, "vdetail",  "vehicle detail cutoff #1 (min(view, 100))"),
        (0x00415732, 0x005682e8, "vdetail",  "vehicle detail cutoff #2"),
        (0x0043fc8e, 0x00568ec4, "despawn",  "traffic despawn distance"),
        (0x0043fce2, 0x00568ec4, "pdespawn", "police despawn distance"),
        (0x0043fcf7, 0x00569830, "ppursuit", "police despawn distance while chasing"),
        (0x00442ce8, 0x00568ec4, "anchor",   "traffic spawn anchor (x 0.4 ahead of camera)"),
        (0x0042f1fb, 0x00568eb4, "chunkcol", "chunk collision body: add when closer than"),
        (0x0042f239, 0x00568eb4, "chunkcol", "chunk collision body: remove when further"),
        (0x0044e777, 0x00568eb4, "objphys",  "tree physics: add when closer than"),
        (0x0044e7b0, 0x00568eb4, "objphys",  "tree physics: remove when further"),
        (0x0044ec17, 0x00568eb4, "objphys",  "rock (list-2) physics: add"),
        (0x0044ec50, 0x00568eb4, "objphys",  "rock (list-2) physics: remove"),
        (0x0043dbb4, 0x00568eb4, "carphys",  "car collision body: on within (traffic/racers)"),
        (0x0043dbbc, 0x00568ec4, "carphys",  "car collision body in states 3/4 (was 60)"),
        (0x004534ed, 0x00568eb4, "bldphys",  "standalone building physics: on within"),
        (0x00453515, 0x00568eb4, "bldphys",  "standalone building physics: off beyond"),
        (0x00453646, 0x00568eb4, "decorphys", "decor/lamp physics: on within (or a car touching)"),
        (0x00453674, 0x00568eb4, "decorphys", "decor/lamp physics: off beyond (and no car touching)"),
        # Grass draw 0x0044f000: a field is drawn only when [field+0x10c] < 70 (0x0044f17c).
        (0x0044f180, 0x0056832c, "grass",    "grass field draw cutoff"),
        # All seven are `comiss xmm0, [0x568ec4]` (0f 2f 05 + disp32), operand at +3.
        (0x004355e8, 0x00568ec4, "cardraw",  "car body draw (pass 1)"),
        (0x004358a8, 0x00568ec4, "cardraw",  "car layer draw (pass 1)"),
        (0x0043bda2, 0x00568ec4, "cardraw",  "car wheels draw (pass 1)"),
        (0x00435a38, 0x00568ec4, "cardraw",  "car layer draw (pass 2)"),
        (0x00435bf8, 0x00568ec4, "cardraw",  "car layer draw (pass 2, second)"),
        (0x0043c180, 0x00568ec4, "cardraw",  "car wheels draw (pass 2)"),
        (0x00435ee8, 0x00568ec4, "cardraw",  "car layer draw (pass 3)"),
        # decor/lamp class fade in 0x00410bd0 (branch for 0x200/0x400)
        (0x00410f49, 0x00568eb0, "decorfar",  "decor/lamp: beyond this alpha 0"),
        (0x00410f70, 0x00568eac, "decornear", "decor/lamp: fade start"),
        (0x00410f81, 0x00568ea8, "decorrate", "decor/lamp: fade rate"),
        # sub-parts in the static-manager draw 0x00452570
        # (0x004526a3 "object parts: skipped beyond" is now inside the lamp hook below)
        (0x004526f5, 0x00568eb0, "decorfar",  "object parts: alpha 0 beyond"),
        (0x00452733, 0x00568eac, "decornear", "object parts: fade start"),
        (0x0045274d, 0x00568ea8, "decorrate", "object parts: fade rate"),
        # building parts load / unload in the static-manager update 0x00453450
        (0x0045353e, 0x00568eb0, "decorfar",  "building parts: load when closer than"),
        (0x0045356a, 0x00568eb0, "decorfar",  "building parts: unload when further than"),
        # ad screens 0x0046adb0
        (0x0046adc4, 0x005685a0, "adscreen",  "ad screen render target: release beyond"),
        # per-chunk decor/lamp activation in 0x0042f0e0
        (0x0042f28e, 0x00569100, "decoract",  "chunk decor/lamps: switch off beyond"),
        (0x0042f2b3, 0x00569100, "decoract",  "chunk decor/lamps: switch on within"),
        # spawner timer reload (movss xmm1, [0x568548] at 0x00442e12)
        (0x00442e16, 0x00568548, "spawnint",  "traffic spawn attempt interval"),
        # fog start: per-frame setter 0x00428800 and device-init 0x0040f4b0 (mulss [0.5])
        (0x00428829, 0x005682f8, "fogfrac",   "fog start fraction (per frame)"),
        (0x0040f70c, 0x005682f8, "fogfrac",   "fog start fraction (device init)"),
        # building/bridge fade in 0x00410bd0 branch B
        (0x00410db6, 0x00568ebc, "bldfar",    "building/bridge: invisible beyond V - this"),
        (0x00410dcd, 0x00568eb8, "bldnear",   "building/bridge: fade starts at V - this"),
    ]
    inplace = [   # private constants: exactly one reading function each (verified)
        # Fade band (camera distance). Stock 39 -> 60. First build scaled it x2 to 78 -> 120;
        # the player found the see-through cars "a bit too obvious", so 100 -> 120; then saw
        # far cars as "only their lights" (an additive glow at 30% still shows, a body at 30%
        # does not) and chose: the body stays solid until its lights disappear, uniformly.
        # The fade value is a GENERIC per-object field read by ~20 render paths (trees,
        # pedestrians, lamps, wheels, bodies...), so rather than special-casing bodies the
        # band is narrowed to its far edge: solid to 116, body AND lights dissolve together
        # over the last 4 units, gone at 120 (lights are gated on fade > 0, 0x0041577f).
        # Geometry: spawns inside the camera's ~45 deg view land ~124+ away, beyond 120, so
        # they still fade in; the extra solid spawns are off to the sides.
        # Camera-centred spawning (player's numbers, 2026-09-24): solid to 140, fully faded
        # at 150, spawns at 150 (invisible), despawn 180.
        (0x00569838, 39.0, FADE_START, "traffic fade start (fade now 140 -> 150)"),
        (0x00569834, 1 / 21, 1 / FADE_WIDTH, "traffic fade 1/width (21 -> 10)"),
        (0x00569a58, 48.0, 140.0, "traffic spawn ring around the camera"),
        (0x00569a54, 54.0, 140.0, "police spawn ring around the player's car"),
        # Pedestrians follow the camera-centred anchor (see the pedestrians note below).
        # NB the shipped value is 30.000002 (0x41f00001), not 30.0 - the byte check caught it.
        (0x00569c9c, struct.unpack("<f", bytes.fromhex("0100f041"))[0], 55.0,
         "pedestrian spawn ring 30 -> 55 (outside their 50 fade end)"),
        (0x00569ad0, 62.5, 70.0, "pedestrian despawn 62.5 -> 70"),
        (0x00590414, 600.0, MASTER, f"MASTER distance: far plane, fog {MASTER / 2:g}->{MASTER:g}, chunks"),
        # Grass shader `AlphaFactor` = (fade start, fade end, 0, 0), set at 0x0044f067/7a.
        # The player saw grass still ending close by (2026-09-24): overlay grass fields
        # "143/3" = loaded / drawn, unchanged from stock. x2, with the draw cutoff above.
        (0x00569d08, 52.5, 105.0 * GRASS, f"grass fade start 52.5 -> {105.0 * GRASS:g}"),
        (0x00569d04, 105.0, 210.0 * GRASS, f"grass fade end 105 -> {210.0 * GRASS:g}"),
    ]
    p = [(VIEW_CONSTS, bytes(len(block)), block, "view constants block")]
    for disp, old, key, why in repoint:
        p.append((disp, struct.pack("<I", old), struct.pack("<I", addr[key]),
                  f"{why} -> {consts[[c[0] for c in consts].index(key)][1]:g}"))
    for va, old, new, why in inplace:
        p.append((va, struct.pack("<f", old), struct.pack("<f", new), why))
    p += [
        (0x0059041c, struct.pack("<I", 600), struct.pack("<I", int(MASTER)),
         f"Distance setting cap 600 -> {MASTER:g} (Game.ini Distance={int(MASTER) // 200 - 1})"),
        # `lea eax, [edx*4 + 3]` -> [edx*4 + 48]: target = density*56 + 4, max 60. The count
        # includes slot 0 = the player's own car (so does the overlay's "Vehicles on area").
        # History: 30 (x2), 31 tried, 30, then 60 asked for 2026-09-24 together with
        # `racerfree` (opponents on top, clamped to the 64-slot list). Stock max 15.
        (0x00442dab, struct.pack("<I", 3), struct.pack("<I", 48),
         "traffic target: density*(Traffic*4+48)+4 -> max 60 (incl. your car)"),
        # btAxisSweep3 maxHandles. Raised BEFORE any physics radius; release-build Bullet
        # corrupts itself when full instead of refusing.
        # 8192 until 2026-09-26; the collision radii (PHYS_RADIUS 250 for trees/rocks) can put
        # thousands of static bodies in, so the btAxisSweep3<unsigned short> maximum: its
        # constructor asserts maxHandles < 32767. ~3 MB of handles + edge arrays.
        (0x004253af, struct.pack("<I", 0x400), struct.pack("<I", 0x7FFE),
         "physics world capacity 1024 -> 32766 bodies (the 16-bit broadphase maximum)"),
        # "Grass/Trees objects too much!" -> MessageBoxA. The add is skipped either way;
        # only the modal popup goes. Stack stays balanced (caller does add esp,0xc) and
        # both callers ignore the return value (verified 2026-09-24).
        (0x004508c2, bytes.fromhex("e8194f0000"), b"\x90" * 5, "silence 'Grass objects too much!'"),
        (0x0045093b, bytes.fromhex("e8a04e0000"), b"\x90" * 5, "silence 'Trees objects too much!'"),
    ]
    p += _view_caves(addr)
    return p


# Code caves owned by `view` (in the executable .rdata tail, see `rdataexec`).
CORONA_CAVE = RDATA_CODE                         # 0x0058f700
LAMPA_CAVE = RDATA_CODE + 0x20                   # 0x0058f720
LAMPB_CAVE = RDATA_CODE + 0x50                   # 0x0058f750
VIEW_CAVES_END = RDATA_CODE + 0x80               # 0x0058f780.. free for other patches


def _view_caves(addr):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(src, at, limit):
        code = bytes(ks.asm(src, at)[0])
        assert at + len(code) <= limit, f"cave at {at:#x} is {len(code)} bytes, past {limit:#x}"
        return code

    def jmp(frm, to, size):
        return b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (size - 5)

    # 1. corona growth cap, LAMP POSTS ONLY (player 2026-09-25: keep the car head/tail light glare
    #    exactly as it is). Hook 0x00414224 `addss xmm1,xmm3; movaps xmm0,xmm1` (7 bytes);
    #    xmm1 = (d-8)/14.4 and eax = the object's class (loaded at 0x004141e1, unchanged since).
    corona = asm(f"""
        cmp eax, 0x400
        jne grow
        minss xmm1, dword ptr [{addr['coronacap']:#x}]
    grow:
        addss xmm1, xmm3
        movaps xmm0, xmm1
        jmp 0x0041422b
    """, CORONA_CAVE, LAMPA_CAVE)
    # 2a. lamp class fade in 0x00410bd0 (branch for 0x200/0x400). Hook 0x00410f3e
    #     `movss xmm0,[esi+0xa24]` (8 bytes): xmm0 = distance, scaled for lamps only; the fade
    #     code that follows (0x00410f46..0x00410f94) uses xmm0 only as that distance.
    lampa = asm(f"""
        movss xmm0, dword ptr [esi+0xa24]
        test dword ptr [esi+0x9d0], {LAMP_CLASS_MASK:#x}
        je done
        mulss xmm0, dword ptr [{addr['lampscale']:#x}]
    done:
        jmp 0x00410f46
    """, LAMPA_CAVE, LAMPB_CAVE)
    # 2b. lamp PARTS (the lamp head) in the static-manager draw 0x00452570. Hook 0x004526a1
    #     `fld [0x568eb0]` (6 bytes; was the view repoint to decorfar): st0 = part distance,
    #     just stored to [esp+0x14] (read again at 0x004526de for the fade). ebx = the parent.
    lampb = asm(f"""
        test dword ptr [ebx+0x9d0], {LAMP_CLASS_MASK:#x}
        je done
        fmul dword ptr [{addr['lampscale']:#x}]
        fst dword ptr [esp+0x14]
    done:
        fld dword ptr [{addr['decorfar']:#x}]
        jmp 0x004526a7
    """, LAMPB_CAVE, VIEW_CAVES_END)
    return [
        (0x00414224, bytes.fromhex("f30f58cb0f28c1"), jmp(0x00414224, CORONA_CAVE, 7),
         "lamp corona size: growth capped (cave; vehicles unchanged)"),
        (CORONA_CAVE, bytes(len(corona)), corona, "lamp corona growth cap: min((d-8)/14.4, cap)"),
        (0x00410f3e, bytes.fromhex("f30f1086240a0000"), jmp(0x00410f3e, LAMPA_CAVE, 8),
         "decor/lamp fade: lamp distance scaled (cave)"),
        (LAMPA_CAVE, bytes(len(lampa)), lampa, "lamp posts: distance x DECOR_FAR/LAMP_FAR"),
        (0x004526a1, bytes.fromhex("d905b08e5600"), jmp(0x004526a1, LAMPB_CAVE, 6),
         "object parts fade: lamp head distance scaled (cave)"),
        (LAMPB_CAVE, bytes(len(lampb)), lampb, "lamp heads: distance x DECOR_FAR/LAMP_FAR"),
    ]


PATCHES["view"] = _view()


# ---- glow: light-glow batches big enough for `view` (and a 2005 overflow fixed) -------
#
# Found 2026-09-24 after the player reported coronas / headlight "god rays" flickering on
# EVERYTHING at certain angles, rare in stock and frequent with `view`. The renderer
# sub-object 0x0255d7f0 has two per-pass batches in D3D9 managed buffers, locked with
# DISCARD at pass start (0x0040b780), unlocked at the end (0x0040b830), drawn by
# 0x0040ba30 / 0x0040bc40 from the live counts only (nothing else hardcodes the sizes):
#
#   A  light glows   add 0x0040b890: `if (verts + n >= 5000) return;`  - a glow set that
#      does not fit is silently DROPPED for that frame. Draw order changes as things move,
#      so different glows drop each frame = the flicker. Users: vehicle glows 0x00415700
#      (2 x 40 verts / 60 indices per car), 0x00414080 and 0x00436010 (quads 4/6),
#      0x00417770 (triangles 1/1). Max ratio 1.5 indices per vertex; stock IB is 1.5 x cap.
#   B  ground light pools   add 0x0040b960: `if (verts + n >= 2500) return;`, ONE user
#      0x0041330d (night only): 7x7 grid = 49 verts / 216 indices per pool. It checks
#      vertices only, and its index buffer holds 3750 indices = 17 pools while the vertex
#      cap allows 51: pools 18..51 write up to ~22 KB PAST THE INDEX BUFFER. A real 2005
#      bug; `view` draws more lamps, so it would hit it far more often.
#
# Limits and sizes move together. Index values stay < 65536 (16-bit indices).
GLOW_A = 20000                                  # vertices (stock 5000)
GLOW_B = 9800                                   # vertices = 200 pools (stock 2500 = 51)
GLOW_B_IB = 200 * 216 * 2                       # bytes: every pool the cap admits (199)
assert (GLOW_B - 50) // 49 + 1 <= 200 and GLOW_A < 65536 - 40 and GLOW_B < 65536 - 49
PATCHES["glow"] = [
    (0x0040b8a3, struct.pack("<I", 5000), struct.pack("<I", GLOW_A),
     f"glow batch A vertex cap 5000 -> {GLOW_A}"),
    (0x0040b664, struct.pack("<I", 5000 * 48), struct.pack("<I", GLOW_A * 48),
     f"glow batch A vertex buffer 5000 -> {GLOW_A} vertices (48 B)"),
    (0x0040b6ab, struct.pack("<I", 7500 * 2), struct.pack("<I", GLOW_A * 3 // 2 * 2),
     f"glow batch A index buffer 7500 -> {GLOW_A * 3 // 2} indices (ratio 1.5 kept)"),
    (0x0040b973, struct.pack("<I", 2500), struct.pack("<I", GLOW_B),
     f"light-pool batch B vertex cap 2500 -> {GLOW_B} (51 -> 199 pools)"),
    (0x0040b689, struct.pack("<I", 2500 * 24), struct.pack("<I", GLOW_B * 24),
     f"light-pool batch B vertex buffer 2500 -> {GLOW_B} vertices (24 B)"),
    (0x0040b6d0, struct.pack("<I", 3750 * 2), struct.pack("<I", GLOW_B_IB),
     "light-pool batch B index buffer 3750 -> 43200 indices: fixes the 2005 overflow"),
]


# ---- racerfree: race opponents do not count against the traffic target -------------------
#
# Asked for 2026-09-24 ("racers use the traffic pool; the dirt track is empty with 8
# players"). Race start (0x00443490) removes every car but the player and creates the racers
# in the SAME 64-slot list, and the spawner compares its target with the whole count
# (`cmp eax,[edi+0x128]; jbe skip` at 0x00442de2). Vehicle type [car+0xc8c]: 0 = the player,
# 1 = race opponent, 2 = police, 3 = traffic (a finished racer is switched to 3, 0x004411a0).
# The hook counts the type-1 cars and compares count against target + opponents, CLAMPED TO
# 64: the create function 0x004400d0 returns 0 once the list holds 64 and the spawner never
# checks that (0x00442fc9 calls a method on the result), so the spawner must never ask for
# car 65. It also stores the effective target in [edi+0x12c], which only the overlay reads
# ("Vehicles on area X(Y)" stays truthful in races).
RACERFREE_CAVE = 0x00567330


def _racerfree():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm("""
        push eax
        push ecx
        push edx
        mov ecx, dword ptr [edi+0x128]
        xor edx, edx
    count:
        dec ecx
        js counted
        mov eax, dword ptr [edi+ecx*4+0x28]
        test eax, eax
        je count
        cmp dword ptr [eax+0xc8c], 1
        jne count
        inc edx
        jmp count
    counted:
        mov eax, dword ptr [esp+8]
        add eax, edx
        cmp eax, 64
        jbe clamped
        mov eax, 64
    clamped:
        mov dword ptr [edi+0x12c], eax
        pop edx
        pop ecx
        add esp, 4
        cmp eax, dword ptr [edi+0x128]
        jbe 0x004431b3
        jmp 0x00442dee
    """, RACERFREE_CAVE)
    code = bytes(code)
    assert RACERFREE_CAVE > LEAP_WALK + 0xa1, "racerfree code overlaps the leap walker stub"
    jmp = b"\xe9" + struct.pack("<i", RACERFREE_CAVE - (0x00442de2 + 5)) + b"\x90" * 7
    return code, [
        (0x00442de2, bytes.fromhex("3b87280100000f86c5030000"), jmp,
         "traffic spawner: compare the count against target + race opponents (max 64)"),
        (RACERFREE_CAVE, bytes(len(code)), code,
         "count type-1 cars; effective target = min(target + opponents, 64)"),
    ]


try:
    _rf_code, PATCHES["racerfree"] = _racerfree()
    RACERFREE_CAVE_END = RACERFREE_CAVE + len(_rf_code)
except ImportError:
    RACERFREE_CAVE_END = RACERFREE_CAVE


# ---- fadein: traffic and police always FADE IN, however close they appear ----------------
#
# Measured 2026-09-25 (livewatch_232056.csv, 4191 traffic spawns): only 28% of new cars
# started invisible. 60% appeared part-faded and 12% fully solid, because the spawn ring (150)
# is centred on the road cell nearest the camera, not the camera, and the fade runs to 150.
# Cars driving at you also cross the 10-unit band in a fraction of a second. The player saw
# it as lights that "fade in on some cars, not others".
# The per-car step 0x0043fbe0 computes alpha from distance and stores it at 0x0043fc55
# (`movss [ebx+0xd00], xmm0`, then copied to the render field +0x86c). The hook limits how
# fast that value may RISE: alpha = min(distance alpha, previous alpha + frame time * RATE).
# It FALLS with distance exactly as before, so despawns (beyond the fade) are unchanged. New
# cars start at 0 (the car init 0x00436620 zeroes +0xd00 and +0x86c). Only traffic (type 3)
# and police (type 2) are limited: race opponents appear at the start line and must not
# fade in there, and the player's car (slot 0) is never stepped here. The step runs every
# frame from the main update 0x00425040. The frame time is [0x012d04a8] (game clock object
# 0x012d04a0 +8, seconds; 0.008 read live at ~130 fps).
# Free registers at the rejoin point 0x0043fc5d: eax (0x0043fa90 writes it before reading),
# xmm1 and xmm2 (not read again before the next call).
FADEIN_CAVE = 0x00567380                         # after racerfree, inside the .text slack
FADEIN_RATE = 0x0058f6c0                         # .rdata tail, clear of VIEW_CONSTS
FADEIN_SECONDS = 1.0                             # 0 -> fully visible takes at least this long
TEXT_SLACK_END = 0x00567400                      # .text VirtualSize 0x166400 with `slack`


def _fadein():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(f"""
        mov eax, dword ptr [ebx+0xc8c]
        cmp eax, 2
        je limit
        cmp eax, 3
        jne store
    limit:
        movss xmm1, dword ptr [ebx+0xd00]
        movss xmm2, dword ptr [0x012d04a8]
        mulss xmm2, dword ptr [{FADEIN_RATE:#x}]
        addss xmm1, xmm2
        minss xmm0, xmm1
    store:
        movss dword ptr [ebx+0xd00], xmm0
        jmp 0x0043fc5d
    """, FADEIN_CAVE)
    code = bytes(code)
    assert FADEIN_CAVE >= RACERFREE_CAVE_END, "fadein code overlaps racerfree"
    assert FADEIN_CAVE + len(code) <= TEXT_SLACK_END, "fadein code runs past the .text slack"
    jmp = b"\xe9" + struct.pack("<i", FADEIN_CAVE - (0x0043fc55 + 5)) + b"\x90" * 3
    return [
        (0x0043fc55, bytes.fromhex("f30f1183000d0000"), jmp,
         "per-car step: store the fade through the fade-in limiter"),
        (FADEIN_CAVE, bytes(len(code)), code,
         f"traffic/police alpha may rise at most 1/{FADEIN_SECONDS:g} per second"),
        (FADEIN_RATE, bytes(4), struct.pack("<f", 1.0 / FADEIN_SECONDS),
         f"fade-in rate (1/{FADEIN_SECONDS:g} s)"),
    ]


# ---- spawnreach: never create a car that the despawn check deletes on its first frame ----
# Measured 2026-09-25 (spawnlife_221525.csv, view 1600, ring 140, despawn 160, 4x attempts):
# fill 98% of target, but 27% of new traffic vanished within 0.05 s. They were created 160-180
# (median 167) from the camera: the 140 ring is measured from the road cell nearest the anchor,
# which 0x0042c5d0 may find up to 10 cells (40 units) away. Hook the spawner after its own
# rejection test (0x00442f8f `test eax,eax / jne 0x004431b2`) and also fail the attempt when the
# route's first point [0x02641980] is further than SPAWN_REACH from the anchor, horizontally
# (ESI = &anchor = mgr+0x9d7c throughout the spawner; set once at 0x00442cf5). The next attempt
# follows 0.025 s later. Clobbers xmm0/xmm1: dead at 0x00442f97 (written before read, and calls
# follow). Police use the player's car as centre; the same anchor test is within ~8 units.
SPAWNREACH_CAVE = 0x005673c0                     # after fadein (ends 0x005673bd), slack ends 0x567400
SPAWN_REACH = TRAFFIC_DESPAWN - 8.0              # margin for the camera/car offset and a first step
SPAWNREACH_SQ = 0x0058f6c4                       # .rdata tail, right after FADEIN_RATE


def _spawnreach():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(f"""
        test eax, eax
        jne fail
        movss xmm0, dword ptr [0x02641980]
        subss xmm0, dword ptr [esi]
        mulss xmm0, xmm0
        movss xmm1, dword ptr [0x02641988]
        subss xmm1, dword ptr [esi+8]
        mulss xmm1, xmm1
        addss xmm0, xmm1
        comiss xmm0, dword ptr [{SPAWNREACH_SQ:#x}]
        ja fail
        jmp 0x00442f97
    fail:
        jmp 0x004431b2
    """, SPAWNREACH_CAVE)
    code = bytes(code)
    assert SPAWNREACH_CAVE >= FADEIN_CAVE + 0x3d, "spawnreach overlaps the fadein cave"
    assert SPAWNREACH_CAVE + len(code) <= TEXT_SLACK_END, f"spawnreach is {len(code)} bytes, past the slack"
    jmp = b"\xe9" + struct.pack("<i", SPAWNREACH_CAVE - (0x00442f8f + 5)) + b"\x90" * 3
    return [
        (0x00442f8f, bytes.fromhex("85c00f851b020000"), jmp,
         "traffic spawner: also refuse spawn points beyond the despawn reach"),
        (SPAWNREACH_CAVE, bytes(len(code)), code,
         f"fail the attempt if route start is > {SPAWN_REACH:g} from the anchor"),
        (SPAWNREACH_SQ, bytes(4), struct.pack("<f", SPAWN_REACH * SPAWN_REACH),
         f"spawn reach squared ({SPAWN_REACH:g}^2)"),
    ]


try:
    PATCHES["spawnreach"] = _spawnreach()
except ImportError:
    pass


try:
    PATCHES["fadein"] = _fadein()
except ImportError:
    pass


# ---- racers: 4, 6, 8, 10 or 12 racers, equally likely ------------------------------------
#
# Stock: racers = (rand() % 300)/100*2 + 4 = 4/6/8 (0x00440816, `mov ecx, 300`). With 500:
# 4/6/8/10/12, odds 20.1/20.1/20.0/19.8/19.8% (32768 is not a multiple of 500).
# The ONLY 8-slot structure is the racer list, traffic manager +0x13da0 (8 dwords; then
# +0x13dc0 finish counter, +0x13dc4 police count...). Audited 2026-09-24: every reader of
# the racer count 0x02668944 (setup 0x00440520, standings 0x00441020, finish 0x00441150,
# race start 0x00443490, offer screen 0x00462830, HUD 0x00467eb0) loops over the list with
# the count as its length; the position [car+0xc80] only feeds comparisons, a sprintf and
# arithmetic (no position-indexed table); names (RacersName.obj) are menu-only; the start
# grid uses route points 0..2*ceil(n/2)-1 of a >= 100-point route. So: the list moves to a
# 16-slot array in the .data tail and all 19 references are repointed. 16 are
# manager-relative - the manager is a singleton (0x02649368; every path to those four
# functions proven to pass it) - so their displacement becomes RACER_LIST - manager; 3
# (HUD) are absolute. The constructor's eight unrolled clears now clear the new slots 0-7;
# slots 8-15 start at 0 (BSS).
RACER_LIST = 0x026fc5a0                          # 16 x 4 bytes, ends 0x026fc5e0
TRAFFIC_MGR = 0x02649368
_RACER_SITES = [(0x43fece, 0x13da0), (0x43fed4, 0x13da4), (0x43feda, 0x13da8),
                (0x43fee0, 0x13dac), (0x43fee6, 0x13db0), (0x43feec, 0x13db4),
                (0x43fef2, 0x13db8), (0x43fef8, 0x13dbc), (0x441040, 0x13da0),
                (0x4410e7, 0x13da0), (0x441103, 0x13da0), (0x441123, 0x13da0),
                (0x441136, 0x13da0), (0x44116d, 0x13da0), (0x4411b9, 0x13da0),
                (0x443518, 0x13da0), (0x468f2c, 0x0265d108), (0x468f62, 0x0265d108),
                (0x468ff7, 0x0265d108)]


def _racers():
    p = [(0x00440817, struct.pack("<I", 300), struct.pack("<I", 500),
          "racers = (rand()%500)/100*2+4 -> 4/6/8/10/12, equally likely")]
    for va, old in _RACER_SITES:
        if old >= 0x02000000:                    # absolute: [esi*4 + list]
            new = RACER_LIST + (old - (TRAFFIC_MGR + 0x13da0))
        else:                                    # manager-relative: [mgr_reg + off]
            new = RACER_LIST - TRAFFIC_MGR + (old - 0x13da0)
        p.append((va, struct.pack("<I", old), struct.pack("<I", new),
                  "racer list moved to a 16-slot array"))
    return p


PATCHES["racers"] = _racers()


# ---- pedestrians: centred on the camera, like traffic ------------------------------------
#
# Pedestrians are placed around the TRAFFIC spawn anchor [0x026530e4] (= traffic manager
# +0x9d7c): spawner 0x0044d2d0 puts them on a ring around it (0x0044d36e/74/79, ring
# 0x00569c9c), the per-pedestrian step 0x0044b9a0 despawns them beyond 0x00569ad0 from it
# (0x0044ba2e), and fades them by CAMERA distance 32.5 -> 50 (0x00569ad8 / 0x00569ad4).
# History: `view` first moved that anchor 48 ahead and pedestrians popped in centre screen;
# a `pedanchor` hook (2026-09-24, pedcheck.py 3/3) rebuilt the stock 24-ahead point for them.
# Since the traffic anchor became the camera itself, pedestrians simply follow it (the
# player's choice, "follow the traffic cars too"), so that hook was removed: ring 30 -> 55
# (outside the 50 fade end, so they spawn invisible) and despawn 62.5 -> 70 (about the stock
# area, so the same density). Both constants have one reading function each (verified).
#
# The .data tail (0x026fc57c..0x026fd000, BSS, referenced by nothing) holds the racer list;
# `dataslack` raises .data's VirtualSize over it, as `slack` does for .text.
DATA_VSIZE_FIELD = 0x00400268                    # .data VirtualSize, PE section header #3
PATCHES["dataslack"] = [
    (DATA_VSIZE_FIELD, struct.pack("<I", 0x216C57C), struct.pack("<I", 0x216C600),
     ".data VirtualSize covers the racer list at 0x026fc5a0"),
]

# The developer overlay WITHOUT the `Debug out` flag (which also makes Esc quit instantly
# and disables the camera's terrain check). One gate, 6 bytes; it uses the normal HUD
# font and renderer. Shows FPS, polys/frame, chunks, trees/grass fields, collision
# objects, vehicles now(target).
PATCHES["overlay"] = [
    (0x00402655, bytes.fromhex("0f8402080000"), b"\x90" * 6,
     "developer overlay always on (no Debug-out side effects)"),
]

# ---- shadows: the shadow maps could not hold a shadow (stock bug on modern GPUs) -----------
# Found 2026-09-25 (player: "no shadow anywhere", Shadows=3 = the menu max, on BOTH the Intel
# and the RTX GPU). The shadow pass 0x00420320 renders into CD3DRender(0x0255d7f0)+0x44090
# (global 0x025a1880), 1024x1024 with its own D16 depth surface (+0x4409c), after
# Clear(DEPTH only): the ground is drawn with TEXTUREFACTOR 0xFF000000 (black = no shadow) and
# the casters with 0xFF9F9F9F (grey = 62% shadow); `techSmoothSurface` blurs it into +0x44094 /
# +0x44098 (0x025a1884 / 0x025a1888). Receivers read the COLOUR: terrain 0x0042b190 blends
# SRC=ZERO, DEST=INVSRCCOLOR (screen * (1 - shadow)); stones/bridges use stage 1 in 0x00410bd0.
# But all three targets are created (0x0040c7e0) as D3DFMT_A8 (0x1c): alpha only, sampled as
# RGB = 0, so every receiver multiplies by 1 = no shadow. 2005 GPUs could not render to A8, so
# D3DX silently substituted a format WITH colour and shadows worked; today's GPUs support A8
# render targets and get exactly what was asked for. Fix: A8R8G8B8 (0x15), 3 x 4 MB of VRAM.
PATCHES["shadows"] = [
    (va + 1, b"\x1c", b"\x15", f"shadow render target #{i} format A8 -> A8R8G8B8")
    for i, va in enumerate((0x0040c89a, 0x0040c8bf, 0x0040c8e4), 1)
]

# ---- nodamage: the PLAYER's car takes no damage (toggleable extra, 2026-09-25) --------------
# Player request: "only the player car doesn't get damage ... make sure this is toggleable" (they
# test a lot and do not want to pay for repairs to get clean screenshots).
# Damage model (found 2026-09-25, workshop repair code 0x00464fd0 + live probes): damage % =
# (body + mean(4 corners) + engine) / 3 (0x004353b0), where body = mean of +0x18 over the car's
# vertex-zone array [car+0xc98] (0x28-byte entries, count [+0xcb4]+[+0xcc8]; the visible dents),
# corners = per-WHEEL damage +0x818c..+0x8198 (a hit on a rear corner makes that tyre slide),
# engine = +0x7fd8; 0x004353f0 then derives the performance loss (engine force +0x7f84 ...).
# All of it is added in ONE place, the collision handler 0x0043a420 (thiscall car, 4 args,
# `ret 0x10`, called for each car of a contact pair by 0x00420d20 and by 0x0043b4c0). Before
# 0x0043aa4e it does the non-damage work (sparks 0x0041d5f0, wanted level [0x012d044c], bonus
# messages 0x0045f6f0); the damage block runs 0x0043ab15..0x0043b43f (lock VB, dents, tyres,
# engine, performance); 0x0043b444.. plays the crash sound (volume from the force) and returns.
# Hook 0x0043ab0d (`addss xmm1,[0.5]`, force final, stack balanced, esi = car, ebx = other):
# the player's car jumps to 0x0043b444 - no dents, tyre or engine damage, sound kept; every
# other car is untouched. Existing damage stays until one repair.
NODAMAGE_CAVE = 0x0058f780                       # after the view caves, .rdata code space
PLAYER_CAR = 0x012d0c88                          # [this] = the player's car


def _nodamage():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(f"""
        cmp esi, dword ptr [{PLAYER_CAR:#x}]
        jne damage
        jmp 0x0043b444
    damage:
        addss xmm1, dword ptr [0x005682f8]
        jmp 0x0043ab15
    """, NODAMAGE_CAVE)
    code = bytes(code)
    assert NODAMAGE_CAVE >= VIEW_CAVES_END, "nodamage overlaps the view caves"
    assert NODAMAGE_CAVE + len(code) <= RDATA_CODE_END, "nodamage runs past the .rdata tail"
    jmp = b"\xe9" + struct.pack("<i", NODAMAGE_CAVE - (0x0043ab0d + 5)) + b"\x90" * 3
    return [
        (0x0043ab0d, bytes.fromhex("f30f580df8825600"), jmp,
         "collision damage: the player's car skips dents/tyres/engine (sound kept)"),
        (NODAMAGE_CAVE, bytes(len(code)), code, "if car == player: jump to the crash-sound tail"),
    ]


try:
    PATCHES["nodamage"] = _nodamage()
except ImportError:
    pass

# ---- modsect: a NEW executable section for new code (2026-09-25) ---------------------------
# The .text slack (0x567400) and the .rdata tail (0x0058f800) are full, so new features get a
# fifth PE section, `.crmod`, right after .rsrc: VA 0x02701000, 64 KB mapped RWX, the first
# 16 KB stored in the file (code, constants, text) and the rest zero-filled at load (BSS for
# pointers and buffers). The section header goes in the free space after the 4th header (the
# headers end at 0x2b0 of 0x400). Its raw data is APPENDED to the file at 0x1b6600 - after the
# GameTop Authenticode blob (0x1b3c00 + 0x28d8), which our patches invalidated long ago and which
# the loader never reads. The exe has no relocations, so the image must fit at 0x00400000..
# 0x02711000 - the loader reserves it before any heap or stack exists.
# Patch entries in the section read as zero past the end of an unpatched file (see `read_at`),
# so `state` sees them as "off", and `put` grows the file when it writes them.
MOD_VA = 0x02701000
MOD_VSIZE = 0x10000
MOD_RSIZE = 0x6000                               # 2026-10-04: 16 -> 24 KB stored (the S2 area was full);
                                                 # the BSS keeps 40 KB (Panini's effect buffer needs 36 KB)
MOD_RAW = 0x001B6600
MOD_BSS = MOD_VA + MOD_RSIZE                     # zero-filled at load, writable
PATCHES["modsect"] = [
    (0x0040011E, struct.pack("<H", 4), struct.pack("<H", 5), "NumberOfSections 4 -> 5"),
    (0x00400168, struct.pack("<I", 0x02301000), struct.pack("<I", 0x02301000 + MOD_VSIZE),
     "SizeOfImage + 64 KB"),
    (0x004002B0, bytes(40),
     struct.pack("<8sIIIIIIHHI", b".crmod", MOD_VSIZE, MOD_VA - 0x00400000, MOD_RSIZE, MOD_RAW,
                 0, 0, 0, 0, 0xE0000060),
     "section header #5 .crmod: code | data | execute | read | write"),
    (MOD_VA, bytes(0x40), b"racemod .crmod section: new code for City Racing RE\0".ljust(0x40, b"\0"),
     "section signature"),
    (MOD_VA + MOD_RSIZE - 0x10, bytes(0x10), b"end of .crmod\0\0\0",
     "section end marker (the file grows to the full raw size)"),
]


# ---- panini: Panini projection, PANINI_FOV (panini.py) horizontal (player request 2026-09-25) --
# "make the FOV to be Panini projection, and set it to 120 degree". Stock: ONE projection for
# all three views (0x00401070, built once by 0x00425620): 90 deg VERTICAL, aspect = w/h x 0.85
# (0x00568300, shared by 4 car/AI readers) -> 113 deg horizontal and a 17.6% sideways stretch.
# Frustum culling extracts its planes from view x projection (0x00401190), so a wider camera
# culls correctly by itself.
#  1. camera (0x00425700, main camera only): aspect = w/h (no 0.85), vertical FOV = 2 atan(tan(
#     PANINI_FOV/2) / aspect) = a rectilinear view PANINI_FOV wide. That view with the same
#     aspect covers the Panini image's corners exactly - no overscan needed.
#  2. shader: the game compiles Data/Misc/RenderTechniques_20.dat (World.pak) with its static
#     2004 D3DX (0x00487a94, D3DXCreateEffect). The call at 0x0040ab1b now goes through a cave that
#     copies the text into a buffer and appends `techPanini` (panini.technique_text) - the game's
#     own effect then owns it, including the lost/reset device cycle (0x0040c6a0 releases it).
#     Proven on the GPU by paninitest.py (every pixel within 0.003 px of panini.model).
#  3. supersampling (2026-09-26, player: "jagged lines very clear, as if I play in 1366x768" and
#     "upsample it to 1440p first"): the renderer makes its glow/blur targets at the end of
#     0x0040c7e0 (restore) and frees them in 0x0040c6a0 (invalidate, also on device reset). Ours
#     go there too: a render-target TEXTURE of backbuffer x panini.RENDER_SCALE (2560x1440 on a
#     1080p screen, the game's RT format) + a depth-stencil of that size in the format of the
#     device's own depth buffer (GetDepthStencilSurface / GetDesc), no multisampling (it must
#     match the texture). D3DPOOL_DEFAULT: they must go before a Reset.
#  4. redirect: 0x00421710 draws the reflection (0x0041fa20, 0x0041ff40) and shadow (0x00420320)
#     targets first - each saves and restores the current target through the renderer's helpers
#     (0x0040b3f0/0x0040b410 save, 0x0040b430/0x0040b470 restore) - then resets vertex pools
#     (0x0040b780) and clears (0x00428850). Right before that clear (0x0042173c) the world is
#     pointed at the big texture + depth: the backbuffer and the device's depth surface are saved
#     (with a reference). Glow (0x0040fbd0) and motion blur (0x0040c080) read and restore the
#     CURRENT target, so they follow. The backbuffer-size globals are read only by the camera
#     setup 0x00425620; viewport code scales the current viewport (0x004015f0).
#  5. the 3D arrow (HUD object 0x025d79b8, DirectArrow model at [+0xfea4], drawn by 0x0045ea60 at
#     a fixed camera-space spot 0.5 ahead / 0.375 up) was drawn in the HUD phase (0x0046b330)
#     after the warp, through the wide flat lens: tiny and near the middle (player, 160 deg). The
#     HUD's call (0x0046b333) is removed; the pass draws it INTO the world image before the warp,
#     so Panini's centre magnification puts it back at about its stock size and place.
#  6. pass: the 3D world ends with glow and a tail-jump into motion blur at 0x00421873; the HUD
#     comes after. The jump now calls blur, draws the arrow, and then:
#     - redirected: back to the saved backbuffer + depth surface (references dropped);
#     - not redirected (no depth surface, a failure): StretchRect(backbuffer -> big texture);
#     then SetTechnique - ALWAYS, not via the renderer's name cache at +0x44070, because the game
#     never clears that cache when a device reset recreates the effect (0x0040c6a0 / 0x0040fb00
#     release it, 0x0040aa40 rebuilds it) - then the cache is set to us so the game's own users
#     (0x0040af20 and friends, all inside the 3D world) switch back; VS c0 = (-1/W, 1/H) of the
#     SCREEN (half-pixel shift + the pixel width the edge filter needs); the renderer's full-screen
#     quad (+0x440a4); effect Begin / Pass(0) / Draw / End (2004 D3DX: End restores every state
#     the pass set); stage 0's texture restored. If the world went to the big texture but cannot
#     be warped (technique missing, Begin failing), it is StretchRect'ed onto the screen as is -
#     the player never gets a black frame.
PAN_CODE = MOD_VA + 0x40
PAN_FOV_CAVE = PAN_CODE                          # 0x02701040
PAN_FX_CAVE = PAN_CODE + 0x40                    # 0x02701080
PAN_CREATE_CAVE = PAN_CODE + 0xA0                # 0x027010e0
PAN_RELEASE_CAVE = PAN_CODE + 0x1C0              # 0x02701200
PAN_REL_ALL = PAN_CODE + 0x1E0                   # 0x02701220 helper: release everything
PAN_REL_SAVES = PAN_CODE + 0x200                 # 0x02701240 helper: release the saved targets
PAN_REDIR_CAVE = PAN_CODE + 0x240                # 0x02701280
PAN_PASS_CAVE = PAN_CODE + 0x340                 # 0x02701380
PAN_CODE_END = MOD_VA + 0x800
PAN_TANE = MOD_VA + 0x800                        # float tan(PANINI_FOV / 2)
PAN_M1 = MOD_VA + 0x804                          # -1.0f
PAN_P1 = MOD_VA + 0x808                          # +1.0f
PAN_SS = MOD_VA + 0x80C                          # float panini.RENDER_SCALE
PAN_NAME = MOD_VA + 0x810                        # "techPanini" (a D3DXHANDLE by name)
PAN_TECH = MOD_VA + 0x1000                       # the technique text
PAN_TECH_MAX = 0x2000
PAN_TEX = MOD_BSS                                # IDirect3DTexture9*: the big world image
PAN_DS = MOD_BSS + 0x4                           # IDirect3DSurface9*: its depth-stencil
PAN_SAVE_RT = MOD_BSS + 0x8                      # the backbuffer, while the world is redirected
PAN_SAVE_DS = MOD_BSS + 0xC                      # the device's depth surface, idem
PAN_ACTIVE = MOD_BSS + 0x10                      # 1 between the redirect and the pass
PAN_FXBUF = MOD_BSS + 0x1000                     # effect text + technique -> D3DXCreateEffect
PAN_FXBUF_SIZE = 0x8000
assert PAN_FXBUF + PAN_FXBUF_SIZE <= MOD_VA + MOD_VSIZE, "Panini's effect buffer runs past the .crmod mapping"
RENDERER = 0x0255D7F0
BB_W, BB_H = 0x025A180C, 0x025A1810              # backbuffer width / height (ints)
HUD_OBJ = 0x025D79B8                             # `this` of the HUD draw 0x0046b330
ARROW_DRAW = 0x0045EA60                          # draws the 3D direction arrow (thiscall, no args)
# 7. sky (2026-09-26, player: "the sea and sky has a cutoff to the right"): the sky dome
#    Data/Sky/Main.msh is a UNIT sphere (radius 1.0, horizon band Horizon.dds) that 0x004276e0
#    re-centres on the camera every frame (identity matrix + camera position, Z off). At a wide
#    view its sides come nearer than the 0.2 near plane: view depth = cos(az) cos(elev) < 0.2
#    beyond ~78 deg at the horizon, ~76.6 at 30 deg up - exactly the strip seen at 160 deg (stock
#    never looks past 56). The dome is drawn SKY_SCALE times bigger (still Z off, still far inside
#    fog start and far plane): clipped only past 88.9 deg. Also used by the reflection passes.
PAN_SKY_CAVE = MOD_VA + 0x900                    # 0x02701900
SKY_SCALE = 10.0
# 8. chase camera distance (2026-09-26, player: at 100 deg tall "my car is now a bit far"). 0x004018c0
#    (every frame from the camera update 0x00402e80, and from its reset 0x00401c40): dist = camera
#    mode [cam+0x9ed0] x car[+0x8b4] x 0.85 (fmul [0x00568300] at 0x004018fb, one of five SHARED
#    readers) x (1 + 0.5 min(speed x 0.005, 1)). Eye = -forward dist + up 0.5 dist, and the aim uses
#    dist/3, so scaling dist slides the camera along the same line: same framing, car 1/k bigger.
#    The operand is repointed to 0.85 x panini.CHASE_DISTANCE.
PAN_CHASE = MOD_VA + 0x820                       # float 0.85 x CHASE_DISTANCE


def _panini():
    import math
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    import panini
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    tech = panini.technique_text().encode("latin-1")
    tl = len(tech)
    assert tl <= PAN_TECH_MAX, "techPanini text too long"
    asm = lambda src, at: bytes(ks.asm(src, at)[0])
    fov = asm(f"""
        fst dword ptr [esp+4]
        fdivr dword ptr [{PAN_TANE:#x}]
        fld1
        fpatan
        fadd st(0), st(0)
        fstp dword ptr [esp]
        jmp 0x00425713
    """, PAN_FOV_CAVE)
    fx = asm(f"""
        push esi
        push edi
        push ecx
        mov ecx, dword ptr [esp+0x18]
        cmp ecx, {PAN_FXBUF_SIZE - tl:#x}
        ja done
        mov esi, dword ptr [esp+0x14]
        mov edi, {PAN_FXBUF:#x}
        cld
        rep movsb
        mov esi, {PAN_TECH:#x}
        mov ecx, {tl:#x}
        rep movsb
        mov dword ptr [esp+0x14], {PAN_FXBUF:#x}
        add dword ptr [esp+0x18], {tl:#x}
    done:
        pop ecx
        pop edi
        pop esi
        jmp 0x00487a94
    """, PAN_FX_CAVE)
    # release helpers: every register preserved. REL_ALL = texture, depth, both saves;
    # REL_SAVES = the two saved screen targets. Both clear PAN_ACTIVE.
    rel_all = asm(f"""
        pushad
        mov esi, {PAN_TEX:#x}
        mov ebx, 4
        jmp {PAN_REL_SAVES + 11:#x}
    """, PAN_REL_ALL)
    rel_saves = asm(f"""
        pushad
        mov esi, {PAN_SAVE_RT:#x}
        mov ebx, 2
    loop:
        mov eax, dword ptr [esi]
        test eax, eax
        je next
        mov dword ptr [esi], 0
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    next:
        add esi, 4
        dec ebx
        jne loop
        mov dword ptr [{PAN_ACTIVE:#x}], 0
        popad
        ret
    """, PAN_REL_SAVES)
    assert asm(f"pushad; mov esi, {PAN_SAVE_RT:#x}; mov ebx, 2", PAN_REL_SAVES).__len__() == 11
    # end of the renderer's restore 0x0040c7e0: ebp = renderer; ebx/esi/edi belong to ITS caller
    create = asm(f"""
        pushad
        call {PAN_REL_ALL:#x}
        mov edi, dword ptr [ebp+0x44034]
        test edi, edi
        je done
        cvtsi2ss xmm0, dword ptr [{BB_W:#x}]
        mulss xmm0, dword ptr [{PAN_SS:#x}]
        cvtss2si ebx, xmm0
        cvtsi2ss xmm0, dword ptr [{BB_H:#x}]
        mulss xmm0, dword ptr [{PAN_SS:#x}]
        cvtss2si esi, xmm0
        push 0
        push {PAN_TEX:#x}
        push 0
        push dword ptr [ebp+0x41e84]
        push 1
        push 1
        push esi
        push ebx
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x5c]
        test eax, eax
        jge texok
        mov dword ptr [{PAN_TEX:#x}], 0
        jmp done
    texok:
        sub esp, 0x28
        lea eax, [esp]
        push eax
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0xa0]
        test eax, eax
        jl nods
        mov eax, dword ptr [esp]
        lea ecx, [esp+4]
        push ecx
        push eax
        mov edx, dword ptr [eax]
        call dword ptr [edx+0x30]
        mov dword ptr [esp+0x24], eax
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        cmp dword ptr [esp+0x24], 0
        jl nods
        push 0
        push {PAN_DS:#x}
        push 0
        push 0
        push 0
        push dword ptr [esp+0x18]
        push esi
        push ebx
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x74]
        test eax, eax
        jge nods
        mov dword ptr [{PAN_DS:#x}], 0
    nods:
        add esp, 0x28
    done:
        popad
        pop ebp
        add esp, 0x68
        ret
    """, PAN_CREATE_CAVE)
    release = asm(f"""
        call {PAN_REL_ALL:#x}
        mov eax, dword ptr [esi+0x440a4]
        jmp 0x0040c7c8
    """, PAN_RELEASE_CAVE)
    redir = asm(f"""
        pushad
        call {PAN_REL_SAVES:#x}
        mov ebx, dword ptr [{PAN_TEX:#x}]
        test ebx, ebx
        je out
        cmp dword ptr [{PAN_DS:#x}], 0
        je out
        mov edi, dword ptr [{RENDERER + 0x44034:#x}]
        test edi, edi
        je out
        push {PAN_SAVE_RT:#x}
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl undo
        push {PAN_SAVE_DS:#x}
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0xa0]
        test eax, eax
        jl undo
        sub esp, 4
        lea eax, [esp]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl undopop
        mov eax, dword ptr [esp]
        push eax
        push 0
        push edi
        mov ecx, dword ptr [edi]
        call dword ptr [ecx+0x94]
        mov ebp, eax
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        add esp, 4
        test ebp, ebp
        jl undo
        push dword ptr [{PAN_DS:#x}]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x9c]
        test eax, eax
        jl undort
        mov dword ptr [{PAN_ACTIVE:#x}], 1
        jmp out
    undopop:
        add esp, 4
        jmp undo
    undort:
        push dword ptr [{PAN_SAVE_RT:#x}]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x94]
    undo:
        call {PAN_REL_SAVES:#x}
    out:
        popad
        mov ecx, 0x02648150
        jmp 0x00421741
    """, PAN_REDIR_CAVE)
    # locals after `sub esp, 0x28`: [0] backbuffer, [4] big surface, [8] pass count,
    # [0xc] stage-0 texture before the pass, [0x10..0x1f] VS c0, [0x20] redirected this frame,
    # [0x24] "warp failed after the texture was bound". `push dword ptr [esp+X]` reads its
    # operand before esp moves.
    pas = asm(f"""
        call 0x0040c080
        pushad
        mov ecx, {HUD_OBJ:#x}
        call {ARROW_DRAW:#x}
        mov esi, {RENDERER:#x}
        mov edi, dword ptr [esi+0x44034]
        mov ebx, dword ptr [{PAN_TEX:#x}]
        test ebx, ebx
        je out
        sub esp, 0x28
        xor eax, eax
        mov dword ptr [esp+0xc], eax
        mov dword ptr [esp+0x24], eax
        mov eax, dword ptr [{PAN_ACTIVE:#x}]
        mov dword ptr [esp+0x20], eax
        test eax, eax
        je copy
        push dword ptr [{PAN_SAVE_RT:#x}]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x94]
        push dword ptr [{PAN_SAVE_DS:#x}]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x9c]
        call {PAN_REL_SAVES:#x}
        jmp draw
    copy:
        mov ebp, -1
        lea eax, [esp]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl free
        lea eax, [esp+4]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl relbb
        push 2
        push 0
        push dword ptr [esp+0xc]
        push 0
        push dword ptr [esp+0x10]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x88]
        mov ebp, eax
        mov eax, dword ptr [esp+4]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    relbb:
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        test ebp, ebp
        jl free
    draw:
        mov ecx, dword ptr [esi+0x4406c]
        test ecx, ecx
        je fallback
        push {PAN_NAME:#x}
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0xec]
        test eax, eax
        jl fallback
        mov dword ptr [esi+0x44070], {PAN_NAME:#x}
        cvtsi2ss xmm0, dword ptr [{BB_W:#x}]
        movss xmm1, dword ptr [{PAN_M1:#x}]
        divss xmm1, xmm0
        movss dword ptr [esp+0x10], xmm1
        cvtsi2ss xmm0, dword ptr [{BB_H:#x}]
        movss xmm1, dword ptr [{PAN_P1:#x}]
        divss xmm1, xmm0
        movss dword ptr [esp+0x14], xmm1
        xor eax, eax
        mov dword ptr [esp+0x18], eax
        mov dword ptr [esp+0x1c], eax
        push 1
        lea eax, [esp+0x14]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x178]
        lea eax, [esp+0xc]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x100]
        test eax, eax
        jge gotold
        mov dword ptr [esp+0xc], 0
    gotold:
        push ebx
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x104]
        push 0x102
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x164]
        push 20
        push 0
        push dword ptr [esi+0x440a4]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x190]
        mov ecx, dword ptr [esi+0x4406c]
        push 0
        lea eax, [esp+0xc]
        push eax
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x100]
        test eax, eax
        jl beginfail
        mov ecx, dword ptr [esi+0x4406c]
        push 0
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x104]
        push 2
        push 0
        push 5
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x144]
        mov ecx, dword ptr [esi+0x4406c]
        push ecx
        mov edx, dword ptr [ecx]
        call dword ptr [edx+0x108]
        jmp restex
    beginfail:
        mov dword ptr [esp+0x24], 1
    restex:
        push dword ptr [esp+0xc]
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x104]
        mov eax, dword ptr [esp+0xc]
        test eax, eax
        je texdone
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    texdone:
        cmp dword ptr [esp+0x24], 0
        je free
    fallback:
        cmp dword ptr [esp+0x20], 0
        je free
        lea eax, [esp]
        push eax
        push 0
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x98]
        test eax, eax
        jl free
        lea eax, [esp+4]
        push eax
        push 0
        push ebx
        mov eax, dword ptr [ebx]
        call dword ptr [eax+0x48]
        test eax, eax
        jl fbrelbb
        push 2
        push 0
        push dword ptr [esp+8]
        push 0
        push dword ptr [esp+0x14]
        push edi
        mov eax, dword ptr [edi]
        call dword ptr [eax+0x88]
        mov eax, dword ptr [esp+4]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    fbrelbb:
        mov eax, dword ptr [esp]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    free:
        add esp, 0x28
    out:
        popad
        ret
    """, PAN_PASS_CAVE)
    k = struct.unpack("<I", struct.pack("<f", SKY_SCALE))[0]
    sky = asm(f"""
        mov edx, dword ptr [ebx]
        mov dword ptr [edx], {k:#x}
        mov dword ptr [edx+0x14], {k:#x}
        mov dword ptr [edx+0x28], {k:#x}
        push 0x44
        add edx, 0x860
        jmp 0x0042772d
    """, PAN_SKY_CAVE)
    assert PAN_SKY_CAVE + len(sky) <= PAN_SKY_CAVE + 0x40
    caves = [(PAN_FOV_CAVE, fov, PAN_FX_CAVE), (PAN_FX_CAVE, fx, PAN_CREATE_CAVE),
             (PAN_CREATE_CAVE, create, PAN_RELEASE_CAVE), (PAN_RELEASE_CAVE, release, PAN_REL_ALL),
             (PAN_REL_ALL, rel_all, PAN_REL_SAVES), (PAN_REL_SAVES, rel_saves, PAN_REDIR_CAVE),
             (PAN_REDIR_CAVE, redir, PAN_PASS_CAVE), (PAN_PASS_CAVE, pas, PAN_CODE_END)]
    for at, code, limit in caves:
        assert at + len(code) <= limit, f"panini cave at {at:#x} is {len(code)} bytes, overruns {limit:#x}"
    jmp = lambda frm, to, n: b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (n - 5)
    call = lambda frm, to: b"\xe8" + struct.pack("<i", to - (frm + 5))
    tan_e = math.tan(math.radians(panini.PANINI_FOV / 2))
    data = struct.pack("<4f", tan_e, -1.0, 1.0, panini.RENDER_SCALE) + panini.TECH_NAME.encode() + b"\0"
    out = [
        (0x00425700, bytes.fromhex("d80d00835600d95c2404d905a8855600d91c24"), jmp(0x00425700, PAN_FOV_CAVE, 19),
         f"main camera: true aspect, vertical FOV for {panini.PANINI_FOV:g} deg horizontal"),
        (0x0040AB1B, bytes.fromhex("e874cf0700"), call(0x0040AB1B, PAN_FX_CAVE),
         "D3DXCreateEffect gets RenderTechniques + techPanini"),
        (0x0040CB87, bytes.fromhex("5d83c468c3"), jmp(0x0040CB87, PAN_CREATE_CAVE, 5),
         f"renderer restore: also the {panini.RENDER_SCALE:.4g}x world texture + depth"),
        (0x0040C7C2, bytes.fromhex("8b86a4400400"), jmp(0x0040C7C2, PAN_RELEASE_CAVE, 6),
         "renderer invalidate: also release ours"),
        (0x0042173C, bytes.fromhex("b950816402"), jmp(0x0042173C, PAN_REDIR_CAVE, 5),
         "before the world's clear: render the world into the big texture"),
        (0x0046B333, call(0x0046B333, ARROW_DRAW), b"\x90" * 5,
         "HUD no longer draws the 3D arrow (the pass does, before the warp)"),
        (0x00421873, bytes.fromhex("e908a8feff"), jmp(0x00421873, PAN_PASS_CAVE, 5),
         "after the 3D world (motion blur), before the HUD: arrow + the Panini pass"),
    ]
    out += [(at, bytes(len(code)), code, f"panini cave {i}") for i, (at, code, _) in enumerate(caves, 1)]
    out += [(0x00427723, bytes.fromhex("8b136a4481c260080000"), jmp(0x00427723, PAN_SKY_CAVE, 10),
             f"sky dome drawn {SKY_SCALE:g}x bigger (a unit sphere near-clips at wide views)"),
            (PAN_SKY_CAVE, bytes(len(sky)), sky, "sky dome scale"),
            (0x004018FB, bytes.fromhex("d80d00835600"), b"\xd8\x0d" + struct.pack("<I", PAN_CHASE),
             f"chase camera distance x {panini.CHASE_DISTANCE:g} (own constant, 0.85 is shared)"),
            (PAN_CHASE, bytes(4), struct.pack("<f", 0.85 * panini.CHASE_DISTANCE),
             "0.85 x chase distance"),
            (PAN_TANE, bytes(len(data)), data, "tan(fov/2), -1, +1, render scale, \"techPanini\""),
            (PAN_TECH, bytes(tl), tech, f"techPanini effect text ({tl} bytes)")]
    return out


try:
    PATCHES["panini"] = _panini()
except ImportError:
    pass

# ---- fixedstep: physics at a fixed 144 Hz, whatever the framerate (player request 2026-09-26) --
# "physics behave differently across FPS, we can go through a car, and then the physics triggers
# it and fly our cars opposite way on low framerate. I want it to be fixed on 144 Hz first."
# Stock: the world update 0x00421ee0 calls Bullet 2.6x btDiscreteDynamicsWorld::stepSimulation
# (0x0053bfc0, vtable +0x14) as stepSimulation(frame dt [0x012d04a8], maxSubSteps 0, 1/60).
# maxSubSteps 0 is Bullet's VARIABLE-step mode: ONE step of the whole frame time (the clock
# 0x004214b0 clamps a frame to 50 ms), so at 20-30 FPS a car moves 1-2 m per step, sinks deep into
# another before the solver sees the contact, and the penetration fix-up launches it.
# Now stepSimulation(dt, FIXED_MAX_SUBSTEPS, 1/FIXED_HZ): Bullet accumulates dt ([world+0x74]) and
# runs whole 1/144 s steps, 0..8 per frame (8 x 6.9 ms covers the 50 ms clamp, so no time is lost
# down to 20 FPS). Smoothness: every body has a game motion state (vtable 0x00568f68), and
# synchronizeMotionStates (0x0053bee0) gives it the state extrapolated by the leftover time; the
# renderer AND the car logic and camera read that (0x00449c80 & co. -> car+0xa18), so car and
# camera stay locked together. Forces: gravity is applied and forces cleared once per CALL
# (0x0053be30), so the game's per-frame forces act on every substep of that frame (correct for
# continuous forces); the raycast vehicles update inside each substep (0x0053c170). The other
# readers of 1/60 (0x0045ee67/0x0045efb6 lap-time minutes, 0x0053f594 solver info) are untouched.
# THE RATE IS A SETTING (2026-09-26, same day): 144 Hz spiralled in the city centre - 17 FPS, GPU at
# 7 W. With the 250 m collision bodies one step there costs ~6-7 ms, i.e. MORE than its own 6.9 ms
# slice, so each slow frame needed more steps, which made it slower, down to the substep cap (the
# classic fixed-timestep "spiral of death"). The player picked 60 Hz: `extras on fixedstep 60`
# (any 10..288, the player's range; remembered in the state file as fixedstep_hz). The cap follows the rate: enough
# steps to cover the 50 ms clamp, plus one spare (144 Hz -> 8, 60 Hz -> 4), so the physics can
# never ask for more than ~4 steps' worth of CPU per frame at 60.
FIXED_HZ_DEFAULT = 60.0                          # the tested sweet spot (144 was the first try)
FIXED_HZ_RANGE = (10, 288)                      # the player: "make it from 10 to 288"
FIXED_STEP = MOD_VA + 0x830                      # float 1 / FIXED_HZ


def fixed_hz_saved():
    """The physics rate the state file asks for (default 144)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "racemod_state.json")) as f:
            return float(json.load(f).get("fixedstep_hz", FIXED_HZ_DEFAULT))
    except Exception:
        return FIXED_HZ_DEFAULT


def set_fixed_hz(hz):
    """(Re)build PATCHES['fixedstep'] for a physics rate."""
    global FIXED_HZ, FIXED_MAX_SUBSTEPS
    lo, hi = FIXED_HZ_RANGE
    if not lo <= float(hz) <= hi:
        raise ValueError(f"physics rate {hz} Hz is outside {lo}..{hi}")
    FIXED_HZ = float(hz)
    FIXED_MAX_SUBSTEPS = int(0.05 * FIXED_HZ + 1e-6) + 1
    assert FIXED_MAX_SUBSTEPS / FIXED_HZ >= 0.05, "substeps must cover the game's 50 ms frame clamp"
    PATCHES["fixedstep"] = [
        (0x00421EFB, bytes.fromhex("d905b4915600"), b"\xd9\x05" + struct.pack("<I", FIXED_STEP),
         f"physics fixedTimeStep: 1/60 -> own constant 1/{FIXED_HZ:g}"),
        (0x00421F0A, bytes.fromhex("6a00"), bytes([0x6A, FIXED_MAX_SUBSTEPS]),
         f"physics maxSubSteps 0 (one variable step per frame) -> up to {FIXED_MAX_SUBSTEPS} fixed steps"),
        (FIXED_STEP, bytes(4), struct.pack("<f", 1.0 / FIXED_HZ), f"1/{FIXED_HZ:g} s"),
    ]


set_fixed_hz(fixed_hz_saved())

# ---- engineloop: gapless engine sound at any pitch (player request 2026-09-26) ------------------
# "it run on loop that increase pitch, but everytime it looped, it doesn't loop smoothly, so there
# is a 1 second or more/less silent". The sound system is DirectMusic (CAudioManager 0x026b70b8:
# +0 IDirectSound8, +4 listener, +0x1c performance). Each engine voice (8 files E01..E08.wav x 10
# voices, table +0x4204, built by 0x0046c980) is a WAV segment on its own 3D audiopath; the car's
# pitch goes to the audiopath's DirectSound buffer (SetFrequency 0x0046b7b0). Play(loop)
# 0x0046b410 sets repeats INFINITE and the wave track plays in CLOCK time, so DirectMusic restarts
# the wave every ORIGINAL wave length - but a raised pitch plays it faster: the audio ends early and
# the rest of each period is silence (dmtest.cs against the real DirectMusic: E01 1.341 s -> 310 ms
# gaps at x1.5, 445 ms at x1.75; up to seconds on the long E04 7.7 s).
# Fix: when the voice table is built (the store at 0x0046cbe4), each engine voice gets a plain
# DirectSound 3D buffer holding the same PCM, and its buffer interfaces (+0x138 IDirectSoundBuffer8,
# +0x13c IDirectSound3DBuffer) are swapped for ours - so the game's own pitch, volume, 3D position/
# velocity and min/max distance calls drive it unchanged, and the listener's per-frame commit
# (0x0046e6f9) moves it. DirectSound loops it sample-exactly (DSBPLAY_LOOPING), whatever the pitch.
# The voice is marked at +0xfc (the unused tail of its 256-byte name) and, for marked voices only,
# Play / IsPlaying / Stop / Pause / Resume use the buffer. Buffer flags as DirectMusic's own
# (measured 0x682b0): 3D | frequency | volume | global focus | mute at max distance. The PCM is
# copied at -4 dB: DirectMusic's synth played the same data 3.8-4.0 dB quieter (measured at pitch
# 1), so the level is unchanged. Anything unexpected (not RIFF/PCM/mono/16-bit, a failed create)
# leaves that voice on DirectMusic, as stock.
ENG_MAGIC = 0x504C5344                           # "DSLP" at voice+0xfc
ENG_GAIN = 20675                                 # / 32768 = -4.0 dB
ENG_DSB_FLAGS = 0x000380B0
ENG_CODE = MOD_VA + 0xA00                        # 0x02701a00
ENG_CODE_END = MOD_VA + 0x1000
AUDIO_MGR = 0x026B70B8
IID_DSB8_VA = 0x005805BC                         # the game's own GUIDs
IID_DS3DB_VA = 0x0058059C


def _engineloop():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    src = f"""
    convert:                                ; stdcall convert(voice) -> eax = voice
        push ebp
        mov ebp, esp
        sub esp, 0x80
        push ebx
        push esi
        push edi
        mov esi, dword ptr [ebp+8]
        test esi, esi
        je done
        mov eax, dword ptr [esi+0x124]      ; shared WAV {{bytes, size, refs}}
        test eax, eax
        je done
        mov ebx, dword ptr [eax]
        test ebx, ebx
        je done
        mov ecx, dword ptr [eax+4]
        cmp ecx, 44
        jb done
        cmp dword ptr [ebx], 0x46464952     ; RIFF
        jne done
        cmp dword ptr [ebx+8], 0x45564157   ; WAVE
        jne done
        lea edx, [ebx+ecx]                  ; end of file
        lea edi, [ebx+12]
        mov dword ptr [ebp-4], 0            ; fmt
        mov dword ptr [ebp-8], 0            ; data
        mov dword ptr [ebp-0xc], 0          ; data length
    walk:
        lea eax, [edi+8]
        cmp eax, edx
        ja walked
        cmp dword ptr [edi], 0x20746d66     ; 'fmt '
        jne not_fmt
        lea eax, [edi+8]
        mov dword ptr [ebp-4], eax
    not_fmt:
        cmp dword ptr [edi], 0x61746164     ; 'data'
        jne not_data
        lea eax, [edi+8]
        mov dword ptr [ebp-8], eax
        mov eax, dword ptr [edi+4]
        mov dword ptr [ebp-0xc], eax
    not_data:
        mov eax, dword ptr [edi+4]
        mov ecx, edx
        sub ecx, edi
        cmp eax, ecx
        jae walked                          ; chunk runs past the file: stop walking
        inc eax
        and eax, 0xfffffffe
        lea edi, [edi+eax+8]
        jmp walk
    walked:
        mov eax, dword ptr [ebp-4]
        test eax, eax
        je done
        cmp word ptr [eax], 1               ; PCM
        jne done
        cmp word ptr [eax+2], 1             ; mono (3D buffers must be)
        jne done
        cmp word ptr [eax+14], 16           ; 16-bit
        jne done
        mov ecx, dword ptr [ebp-8]
        test ecx, ecx
        je done
        mov eax, edx
        sub eax, ecx
        cmp dword ptr [ebp-0xc], eax
        jbe len_ok
        mov dword ptr [ebp-0xc], eax
    len_ok:
        and dword ptr [ebp-0xc], 0xfffffffe
        cmp dword ptr [ebp-0xc], 64
        jb done
        mov eax, dword ptr [ebp-4]          ; WAVEFORMATEX at ebp-0x40
        mov ecx, dword ptr [eax]
        mov dword ptr [ebp-0x40], ecx
        mov ecx, dword ptr [eax+4]
        mov dword ptr [ebp-0x3c], ecx
        mov ecx, dword ptr [eax+8]
        mov dword ptr [ebp-0x38], ecx
        mov ecx, dword ptr [eax+12]
        mov dword ptr [ebp-0x34], ecx
        mov dword ptr [ebp-0x30], 0         ; cbSize 0
        mov dword ptr [ebp-0x68], 36        ; DSBUFFERDESC at ebp-0x68
        mov dword ptr [ebp-0x64], {ENG_DSB_FLAGS:#x}
        mov eax, dword ptr [ebp-0xc]
        mov dword ptr [ebp-0x60], eax
        mov dword ptr [ebp-0x5c], 0
        lea eax, [ebp-0x40]
        mov dword ptr [ebp-0x58], eax
        mov dword ptr [ebp-0x54], 0         ; guid3DAlgorithm = DS3DALG_DEFAULT
        mov dword ptr [ebp-0x50], 0
        mov dword ptr [ebp-0x4c], 0
        mov dword ptr [ebp-0x48], 0
        mov eax, dword ptr [{AUDIO_MGR:#x}] ; IDirectSound8
        test eax, eax
        je done
        mov dword ptr [ebp-0x10], 0
        push 0
        lea ecx, [ebp-0x10]
        push ecx
        lea ecx, [ebp-0x68]
        push ecx
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+0xc]            ; CreateSoundBuffer
        test eax, eax
        jl done
        mov eax, dword ptr [ebp-0x10]
        test eax, eax
        je done
        mov dword ptr [ebp-0x1c], 0
        mov dword ptr [ebp-0x20], 0
        mov dword ptr [ebp-0x24], 0
        mov dword ptr [ebp-0x28], 0
        push 0
        lea ecx, [ebp-0x28]
        push ecx
        lea ecx, [ebp-0x24]
        push ecx
        lea ecx, [ebp-0x20]
        push ecx
        lea ecx, [ebp-0x1c]
        push ecx
        push dword ptr [ebp-0xc]
        push 0
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+0x2c]           ; Lock
        test eax, eax
        jl drop_buffer
        mov esi, dword ptr [ebp-8]          ; copy the PCM at ENG_GAIN
        mov edi, dword ptr [ebp-0x1c]
        mov ecx, dword ptr [ebp-0x20]
        shr ecx, 1
        test edi, edi
        je copied
    copy:
        test ecx, ecx
        je copied
        movsx eax, word ptr [esi]
        imul eax, eax, {ENG_GAIN}
        sar eax, 15
        mov word ptr [edi], ax
        add esi, 2
        add edi, 2
        dec ecx
        jmp copy
    copied:
        mov eax, dword ptr [ebp-0x10]
        push dword ptr [ebp-0x28]
        push dword ptr [ebp-0x24]
        push dword ptr [ebp-0x20]
        push dword ptr [ebp-0x1c]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+0x4c]           ; Unlock
        mov esi, dword ptr [ebp+8]
        mov dword ptr [ebp-0x14], 0
        mov dword ptr [ebp-0x18], 0
        mov eax, dword ptr [ebp-0x10]
        lea ecx, [ebp-0x14]
        push ecx
        push {IID_DSB8_VA:#x}
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx]                ; QI IDirectSoundBuffer8
        mov eax, dword ptr [ebp-0x10]
        lea ecx, [ebp-0x18]
        push ecx
        push {IID_DS3DB_VA:#x}
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx]                ; QI IDirectSound3DBuffer
        mov eax, dword ptr [ebp-0x10]       ; drop the creation reference
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        cmp dword ptr [ebp-0x14], 0
        je qi_fail
        cmp dword ptr [ebp-0x18], 0
        je qi_fail
        mov eax, dword ptr [esi+0x138]      ; let go of DirectMusic's audiopath buffer interfaces
        test eax, eax
        je rel1
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    rel1:
        mov eax, dword ptr [esi+0x13c]
        test eax, eax
        je rel2
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    rel2:
        mov eax, dword ptr [ebp-0x14]
        mov dword ptr [esi+0x138], eax
        mov eax, dword ptr [ebp-0x18]
        mov dword ptr [esi+0x13c], eax
        lea ecx, [esi+0x114]                ; base frequency, as the game's setup reads it
        mov eax, dword ptr [esi+0x138]
        push ecx
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+0x20]           ; GetFrequency
        mov eax, dword ptr [esi+0x13c]      ; parked far away, as the game's setup (deferred)
        push 1
        push 0xc9742400
        push 0xc9742400
        push 0xc9742400
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+0x4c]           ; SetPosition(-1e6, -1e6, -1e6)
        mov ecx, esi
        push dword ptr [esi+0x120]
        push dword ptr [esi+0x11c]
        call 0x0046b850                     ; min/max distance (the game's setter)
        mov ecx, esi
        push 0x42c80000
        call 0x0046b6e0                     ; volume 100 (the game's setter)
        mov dword ptr [esi+0xfc], {ENG_MAGIC:#x}
        jmp done
    qi_fail:
        mov eax, dword ptr [ebp-0x14]
        test eax, eax
        je qi_fail2
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    qi_fail2:
        mov eax, dword ptr [ebp-0x18]
        test eax, eax
        je done
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
        jmp done
    drop_buffer:
        mov eax, dword ptr [ebp-0x10]
        push eax
        mov ecx, dword ptr [eax]
        call dword ptr [ecx+8]
    done:
        mov eax, dword ptr [ebp+8]
        pop edi
        pop esi
        pop ebx
        mov esp, ebp
        pop ebp
        ret 4

    store:                                  ; replaces `mov [edi],eax / add edi,8` at 0x0046cbe4
        push eax
        call convert
        mov dword ptr [edi], eax
        add edi, 8
        ret

    play:                                   ; 0x0046b410 Play(loop), thiscall, ret 4
        cmp dword ptr [ecx+0xfc], {ENG_MAGIC:#x}
        je play_ds
        sub esp, 8
        push esi
        mov esi, ecx
        jmp 0x0046b416
    play_ds:
        mov eax, dword ptr [ecx+0x138]
        test eax, eax
        je play_out
        mov edx, dword ptr [esp+4]
        neg edx
        sbb edx, edx
        and edx, 1                          ; DSBPLAY_LOOPING when asked to loop
        push edx
        push 0
        push 0
        push eax
        mov edx, dword ptr [eax]
        call dword ptr [edx+0x30]           ; IDirectSoundBuffer::Play
    play_out:
        ret 4

    isplay:                                 ; 0x0046b690 IsPlaying -> eax 0/1
        cmp dword ptr [ecx+0xfc], {ENG_MAGIC:#x}
        je isp_ds
        push esi
        mov esi, ecx
        mov eax, dword ptr [esi+0x10c]
        jmp 0x0046b699
    isp_ds:
        mov eax, dword ptr [ecx+0x138]
        test eax, eax
        je isp_no
        push 0
        mov edx, esp
        push edx
        push eax
        mov edx, dword ptr [eax]
        call dword ptr [edx+0x24]           ; GetStatus
        test eax, eax
        pop eax
        jl isp_no
        and eax, 1                          ; DSBSTATUS_PLAYING
        ret
    isp_no:
        xor eax, eax
        ret

    stop:                                   ; 0x0046b530 Stop
        cmp dword ptr [ecx+0xfc], {ENG_MAGIC:#x}
        je stop_ds
        mov eax, dword ptr [0x026b70d4]
        jmp 0x0046b535
    stop_ds:
        mov eax, dword ptr [ecx+0x138]
        test eax, eax
        je stop_out
        push eax
        mov edx, dword ptr [eax]
        call dword ptr [edx+0x48]           ; IDirectSoundBuffer::Stop
    stop_out:
        ret

    resume:                                 ; 0x0046b5a0 Resume (after a pause)
        cmp dword ptr [ecx+0xfc], {ENG_MAGIC:#x}
        je res_ds
        sub esp, 0xc
        push esi
        mov esi, ecx
        jmp 0x0046b5a6
    res_ds:
        cmp dword ptr [ecx+0x108], 0
        je res_out
        mov dword ptr [ecx+0x108], 0
        push 1
        call 0x0046b410                     ; Play(loop) -> play_ds
    res_out:
        ret

    pause:                                  ; 0x0046bd30 Pause
        cmp dword ptr [ecx+0xfc], {ENG_MAGIC:#x}
        je pau_ds
        push esi
        mov esi, ecx
        cmp dword ptr [esi+0x108], 0
        jmp 0x0046bd3a
    pau_ds:
        cmp dword ptr [ecx+0x108], 0
        jne pau_out
        push ecx
        call 0x0046b690                     ; IsPlaying -> isp_ds
        pop ecx
        test eax, eax
        je pau_out
        push ecx
        call 0x0046b530                     ; Stop -> stop_ds
        pop ecx
        mov dword ptr [ecx+0x108], 1
    pau_out:
        ret

    """
    src = chr(10).join(line.split(";")[0].rstrip() for line in src.splitlines())   # keystone: ';' separates
    code, _ = ks.asm(src, ENG_CODE)
    code = bytes(code)
    assert ENG_CODE + len(code) <= ENG_CODE_END, f"engineloop code is {len(code)} bytes, overruns"
    labels = {}
    for name in ("convert", "store", "play", "isplay", "stop", "resume", "pause"):
        # find each label by assembling the prefix up to it
        pre = src.split(f"\n    {name}:")[0]
        labels[name] = ENG_CODE + len(bytes(ks.asm(pre, ENG_CODE)[0])) if pre.strip() else ENG_CODE
    jmp = lambda frm, to, n: b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (n - 5)
    call = lambda frm, to: b"\xe8" + struct.pack("<i", to - (frm + 5))
    return [
        (0x0046CBE4, bytes.fromhex("890783c708"), call(0x0046CBE4, labels["store"]),
         "engine voice table: each E0x voice gets its own looping DirectSound 3D buffer"),
        (0x0046B410, bytes.fromhex("83ec08568bf1"), jmp(0x0046B410, labels["play"], 6),
         "sound Play: engine voices -> IDirectSoundBuffer::Play(LOOPING)"),
        (0x0046B690, bytes.fromhex("568bf18b860c010000"), jmp(0x0046B690, labels["isplay"], 9),
         "sound IsPlaying: engine voices -> GetStatus"),
        (0x0046B530, bytes.fromhex("a1d4706b02"), jmp(0x0046B530, labels["stop"], 5),
         "sound Stop: engine voices -> IDirectSoundBuffer::Stop"),
        (0x0046B5A0, bytes.fromhex("83ec0c568bf1"), jmp(0x0046B5A0, labels["resume"], 6),
         "sound Resume: engine voices restart their loop"),
        (0x0046BD30, bytes.fromhex("568bf183be0801000000"), jmp(0x0046BD30, labels["pause"], 10),
         "sound Pause: engine voices stop and remember it"),
        (ENG_CODE, bytes(len(code)), code, f"engineloop code ({len(code)} bytes)"),
    ], labels


try:
    PATCHES["engineloop"], ENG_LABELS = _engineloop()
except ImportError:
    pass

# ==== STAGE 2 (2026-10-04 overnight, the player asleep: every one is a switch, OFF by default) ====
# New caves live in .crmod 0x3000..0x3FF0 (the effect text ends at PAN_TECH + PAN_TECH_MAX = 0x3000,
# the section end marker sits at 0x3FF0). Each patch owns a fixed 0x40-byte-aligned slot.
S2_CODE = MOD_VA + 0x3000
S2_CODE_END = MOD_VA + MOD_RSIZE - 0x10
assert PAN_TECH + PAN_TECH_MAX <= S2_CODE


def _s2asm(src, at, limit):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, at)[0])
    assert at + len(code) <= limit, f"cave at {at:#x} is {len(code)} bytes, past {limit:#x}"
    return code


def _s2jmp(frm, to, size):
    return b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (size - 5)


# ---- awdfix: AWD no longer doubles the engine push (Stage 2 #16, player 2026-09-27) ------------
# The drive code 0x004345e0 (every car, thiscall esi = car) ends with
#   if [car+0x7fb0] (Front Tyre Driving): applyEngineForce(F, 0); applyEngineForce(F, 1)
#   if [car+0x7fb4] (Rear  Tyre Driving): applyEngineForce(F, 2); applyEngineForce(F, 3)
# with the SAME F (= [esp+4], the car's whole engine force) for every driven wheel (0x00539d20 is
# Bullet's btRaycastVehicle::applyEngineForce: wheel[i].m_engineForce = F; nothing else calls it).
# So FWD/RWD push with 2F and AWD with 4F - twice the car. Every stock car is RWD (all ten .obj),
# which is why the developers never saw it; the Car Tuner's AWD (and the player's police/03/05
# tunes) doubled them. Fix: AWD gives each wheel F/2, so the car pushes 2F in total like any 2-wheel
# drive car, now spread over four tyres (better traction, same power). FWD/RWD are untouched, so the
# stock game is byte-for-byte the same in behaviour. Reverse (negative F) is halved alike.
# Hook 0x0043491d `cmp [esi+0x7fb0],0; je 0x43495f` (9 bytes). xmm0 is dead here (reloaded at
# 0x004349a1); xmm1 (the zero the code relies on) is not touched.
AWD_CAVE = S2_CODE                               # 0x02704000
AWD_HALF = S2_CODE + 0x38                        # float 0.5


def _awdfix():
    code = _s2asm(f"""
        cmp dword ptr [esi+0x7fb0], 0
        je nofront
        cmp dword ptr [esi+0x7fb4], 0
        je front
        movss xmm0, dword ptr [esp+4]
        mulss xmm0, dword ptr [{AWD_HALF:#x}]
        movss dword ptr [esp+4], xmm0
    front:
        jmp 0x00434926
    nofront:
        jmp 0x0043495f
    """, AWD_CAVE, AWD_HALF)
    return [
        (0x0043491D, bytes.fromhex("83beb07f0000007439"), _s2jmp(0x0043491D, AWD_CAVE, 9),
         "drive: AWD cars give each wheel half the engine force (2 wheels' worth in total)"),
        (AWD_CAVE, bytes(len(code)), code, f"awdfix cave ({len(code)} bytes)"),
        (AWD_HALF, bytes(4), struct.pack("<f", 0.5), "0.5"),
    ]


try:
    PATCHES["awdfix"] = _awdfix()
except ImportError:
    pass


def _saved(key, default):
    """A setting from the state file (the default when absent or unreadable)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "racemod_state.json")) as f:
            return float(json.load(f).get(key, default))
    except Exception:
        return default


# ---- gravity: Moon (or any) gravity (Stage 2 #6, player 2026-09-26) ------------------------------
# The game makes ONE physics world (0x00425490: btDiscreteDynamicsWorld ctor 0x0053f530, which
# sets m_gravity = (0, [0x005692c0] = -10, 0) at world+0x64) and then calls world->setGravity
# (vtable +0x2c = 0x0053c110) with (0, [0x005692c0], 0) at 0x004254ca. Every rigid body - cars,
# traffic, police, loose objects, ramps, billboards - takes its gravity from the world when it is
# added (addRigidBody 0x0053b210/0x0053b240 -> btRigidBody::setGravity 0x00536960), and nothing
# else ever calls setGravity. So repointing that one load at our own constant changes gravity for
# the whole world and only for it (0x005692c0 is also read by Bullet itself at 0x0052007f, and by
# the ctor, so the shared constant is left alone). The game's world is in metres with g = 10
# (Earth-ish); the Moon is 1.62 m/s2. Not physics: particles/sparks and the pedestrians' own
# animation are unaffected. Setting: `extras on gravity <m/s2>`, saved as gravity_ms2.
GRAVITY_DEFAULT = 1.62                           # the Moon
GRAVITY_RANGE = (0.5, 30.0)                      # Pluto-ish .. beyond Jupiter (24.8)
GRAVITY_CONST = S2_CODE + 0x40                   # float -g
GRAVITY = GRAVITY_DEFAULT


def set_gravity(g):
    """(Re)build PATCHES['gravity'] for a gravity in m/s2 (positive = down, like the game's 10)."""
    global GRAVITY
    lo, hi = GRAVITY_RANGE
    if not lo <= float(g) <= hi:
        raise ValueError(f"gravity {g} m/s2 is outside {lo:g}..{hi:g}")
    GRAVITY = float(g)
    PATCHES["gravity"] = [
        (0x004254CA, bytes.fromhex("f30f100dc0925600"),
         bytes.fromhex("f30f100d") + struct.pack("<I", GRAVITY_CONST),
         f"world->setGravity: y from the shared -10 -> own constant -{GRAVITY:g}"),
        (GRAVITY_CONST, bytes(4), struct.pack("<f", -GRAVITY), f"gravity -{GRAVITY:g} m/s2"),
    ]


set_gravity(_saved("gravity_ms2", GRAVITY_DEFAULT))

# ---- revboost: reverse as strong as first gear (Stage 2 #8, player 2026-09-26) ------------------
# "reversing is weak; a slow car can't reverse up a 25 deg incline". The drive code 0x004345e0
# (every car; car+0x7f70 speed km/h, +0x7f78 acceleration, +0x7f80 force F, +0x7f84 max force,
# +0x7f8c throttle, +0x7f94 brake/reverse pedal, +0x7f98 handbrake):
#  - throttle: F ramps to +max, and the force APPLIED is F x (1 + max(0, 50 - v) x accel / 40)
#    (0x00434863..0x004348d4: 50 = [0x00568f58], accel x 0.5 = [0x005682f8], 20 = [0x00568eb4]) -
#    a launch boost: 3.5x at a standstill for accel 2, fading to 1x at 50 km/h;
#  - reverse pedal held: F ramps to -max (and fades to 0 at 80 km/h backwards), and is applied
#    AS IS (0x004348d6: only positive F is zeroed). No boost at all.
# So a car reverses with 1/3.5 of its launch push: car 01 (1000 kg, force 2000, RWD) pushes 4000 N
# backwards, while a 25 deg slope pulls it down with 1000 x 10 x sin 25 = 4226 N - it cannot climb.
# Fix: while the reverse pedal is held and F < 0, apply the same launch boost with |v|. Real cars'
# reverse gear is about as short as first, so reverse now launches like first gear. Everything else
# (forward, coasting, braking, the handbrake, the 80 km/h reverse fade) is unchanged. AI cars use the
# same code, so traffic/police/racers that back out of a crash recover faster too.
# Hook 0x004348d6 `comiss xmm4,xmm1; jbe 0x4348e1; movss [esp+4],xmm1` (11 bytes): xmm4 = F, xmm1 = 0,
# xmm6 = 1.0 (kept), [esp+4] = the force to apply (already F). xmm0/xmm2/xmm3 are dead here.
REV_CAVE = S2_CODE + 0x80                        # 0x02704080


def _revboost():
    code = _s2asm(f"""
        comiss xmm4, xmm1
        jbe notpos
        movss dword ptr [esp+4], xmm1
        jmp 0x004348e1
    notpos:
        movss xmm0, dword ptr [esi+0x7f94]
        comiss xmm0, xmm1
        jbe done
        movss xmm2, dword ptr [esi+0x7f70]
        xorps xmm3, xmm3
        subss xmm3, xmm2
        maxss xmm2, xmm3
        movss xmm0, dword ptr [0x00568f58]
        subss xmm0, xmm2
        maxss xmm0, xmm1
        movss xmm2, dword ptr [esi+0x7f78]
        mulss xmm2, dword ptr [0x005682f8]
        movss xmm3, dword ptr [0x00568eb4]
        divss xmm3, xmm2
        divss xmm0, xmm3
        addss xmm0, dword ptr [0x005682c4]
        mulss xmm0, xmm4
        movss dword ptr [esp+4], xmm0
    done:
        jmp 0x004348e1
    """, REV_CAVE, REV_CAVE + 0x80)
    return [
        (0x004348D6, bytes.fromhex("0f2fe17606f30f114c2404"), _s2jmp(0x004348D6, REV_CAVE, 11),
         "drive: reverse gets the same launch boost as first gear (1 + (50-|v|) x accel/40)"),
        (REV_CAVE, bytes(len(code)), code, f"revboost cave ({len(code)} bytes)"),
    ]


try:
    PATCHES["revboost"] = _revboost()
except ImportError:
    pass

# ---- policeeyes / morepolice: Stage 2 #2 (player 2026-09-26: "police awareness farther + more police")
# EYES. A police car (vehicle type [car+0xc8c] == 2) starts a chase in its AI update at 0x0043cc6b
# when the wanted meter [0x012d044c] > 0.25, the player's car has [+0x1e70] == 2, and the distance
# (0x00454d50, car+0xa18 to the player's car+0xa18) is under 40 m: `fld [0x00569100]` at 0x0043ccb3,
# a 40.0 shared with 15 other readers - so only that load is repointed, to POLICE_SEE. A patrol car
# exists out to ~160 m (TRAFFIC_DESPAWN; 200 once chasing), so 160 is the useful maximum.
# EVADE (own extra since 2026-10-04; first it shared the policeeyes slider and the player "can never
# evade" at 160). The WANTED METER's reach ("it will inactive and reduce the level if it was too far"):
# every frame the police manager (0x0043f82d) looks for the nearest car
# in the chase state (0x00441b70: [car+0x1e74] or [+0x1e78] == 4) within `fld [0x00568ec4]` = 60 m
# (0x0043f848, a 60.0 with 30+ other readers). None found -> wanted -= 0.025/s and the pursuit flag
# [0x012d0448] (police radio, HUD) drops. So a chase started at 160 m drained from the first second.
# MORE. The spawner (0x00442c90) makes a new car police when [mgr+0x13dc4] < 4 and rand() % 101 >= 90
# (11 in 101 = 10.9%); pursuit police (model 2) if wanted > 0.8. But [mgr+0x13dc4] is a SPAWN counter:
# +1 per police spawn (0x004431ac), back to 0 only when every car is cleared (0x00442c40, 0x00440520,
# 0x0043ff10 - race/world resets). Removing a car (0x00440190) never decrements it. So the 2005 game
# spawns at most 4 police between resets and then none, however long you drive - a quiet original
# bug. Fix: count the police that are ALIVE (type 2 in the manager's list) against POLICE_MAX, and
# raise the chance to 20 in 101. Police still come out of the normal traffic target (no extra cars;
# the 64-slot list is untouched). Hook 0x00442e3c `push ebp; xor ebp,ebp; cmp [edi+0x13dc4],eax; jae`
# (11 bytes); eax/ecx/edx are dead there (rand() follows), xmm0 (= 0, stored by both paths) is kept.
POLICE_SEE_DEFAULT = 100.0
POLICE_SEE_RANGE = (40.0, 160.0)
POLICE_SEE_CONST = S2_CODE + 0x44                # float metres
POLICE_MAX_DEFAULT = 8
POLICE_MAX_RANGE = (1, 20)
POLICE_CHANCE_THRESH = 81                        # rand() % 101 >= 81 -> 20 of 101 = 19.8% (stock 90)
POLICE_CAVE = S2_CODE + 0x100                    # 0x02704100
POLICE_SEE = POLICE_SEE_DEFAULT
POLICE_MAX = POLICE_MAX_DEFAULT
EVADE_DEFAULT = 80.0
EVADE_RANGE = (20.0, 160.0)
EVADE_CONST = S2_CODE + 0x58                     # float metres
EVADE = EVADE_DEFAULT


def set_evade(m):
    global EVADE
    lo, hi = EVADE_RANGE
    if not lo <= float(m) <= hi:
        raise ValueError(f"evade distance {m} m is outside {lo:g}..{hi:g}")
    EVADE = float(m)
    PATCHES["evade"] = [
        (0x0043F848, bytes.fromhex("d905c48e5600"), b"\xd9\x05" + struct.pack("<I", EVADE_CONST),
         f"wanted meter: holds while a chasing police car is within {EVADE:g} m (stock 60)"),
        (EVADE_CONST, bytes(4), struct.pack("<f", EVADE), f"{EVADE:g} m"),
    ]


def set_police_see(m):
    global POLICE_SEE
    lo, hi = POLICE_SEE_RANGE
    if not lo <= float(m) <= hi:
        raise ValueError(f"police sight {m} m is outside {lo:g}..{hi:g}")
    POLICE_SEE = float(m)
    PATCHES["policeeyes"] = [
        (0x0043CCB3, bytes.fromhex("d90500915600"), b"\xd9\x05" + struct.pack("<I", POLICE_SEE_CONST),
         f"police AI: start a chase within {POLICE_SEE:g} m of you (stock 40)"),
        (POLICE_SEE_CONST, bytes(4), struct.pack("<f", POLICE_SEE), f"{POLICE_SEE:g} m"),
    ]


def set_police_max(n):
    global POLICE_MAX
    lo, hi = POLICE_MAX_RANGE
    if float(n) != int(float(n)) or not lo <= int(float(n)) <= hi:
        raise ValueError(f"police count {n} is not a whole number in {lo}..{hi}")
    POLICE_MAX = int(float(n))
    code = _s2asm(f"""
        push ebp
        xor ebp, ebp
        xor eax, eax
        xor ecx, ecx
    count:
        cmp ecx, dword ptr [edi+0x128]
        jae counted
        mov edx, dword ptr [edi+ecx*4+0x28]
        inc ecx
        test edx, edx
        je count
        cmp dword ptr [edx+0xc8c], 2
        jne count
        inc eax
        jmp count
    counted:
        cmp eax, {POLICE_MAX}
        jae full
        jmp 0x00442e47
    full:
        jmp 0x00442e7c
    """, POLICE_CAVE, POLICE_CAVE + 0x80)
    PATCHES["morepolice"] = [
        (0x00442E3C, bytes.fromhex("5533ed3987c43d01007335"), _s2jmp(0x00442E3C, POLICE_CAVE, 11),
         f"spawner: police cap counts ALIVE police (max {POLICE_MAX}), not police spawned since the last reset"),
        (POLICE_CAVE, bytes(len(code)), code, f"morepolice cave ({len(code)} bytes)"),
        (0x00442E56, bytes([0x5A]), bytes([POLICE_CHANCE_THRESH]),
         f"spawner: police chance 11/101 -> {101 - POLICE_CHANCE_THRESH}/101 per spawn"),
    ]


try:
    set_police_see(_saved("police_see_m", POLICE_SEE_DEFAULT))
    set_police_max(_saved("police_max", POLICE_MAX_DEFAULT))
    set_evade(_saved("police_evade_m", EVADE_DEFAULT))
except ImportError:
    pass

# ---- boardkeep: race billboards are not deleted at 175 m (player 2026-10-04) ----------------------
# "after we accept a race, then we go and leave the billboard behind ... when we look back the billboard's
# gone. It will stay if we are pretty much closer." One race billboard at a time ([0x02649368+0x13d98],
# made by 0x00440e30 from Data/Static/InfoScreen/01/Main1.obj, removed by 0x00440e90). The race manager's
# step checks, once per interval, the camera's distance to the board's spot [+0xdd88] (0x004432f3,
# distance 0x00454d50) and DELETES the board beyond [0x00569a3c] = 175 m (the free-roam "despawn and
# respawn elsewhere"); decor itself draws to 1000 m, so the board just vanishes in plain view. 175 is
# SHARED with the spawn placement (0x00440675: new boards 100..175 m away) and the minimap marker
# (0x00462a29) - those stay. Repoint only the despawn `fld` at 0x004432fe to our own distance. Trade-off:
# a bigger distance keeps boards in view longer but new race offers appear less often (a new board
# spawns only after the old one is gone).
# 2nd deleter (found live with re-tools/boardwatch.py: board gone 56 m away, ~6 s into a race): the race
# step 0x004411f0 at 0x004419a5 deletes the board as soon as the camera cannot SEE it (0x00401e40 =
# 30 m sphere in the view frustum) - "it disappears when I am not looking at it, only when starting a
# race". Skip that (jne -> jmp at 0x004419cc): no new board can spawn during a race, and the game
# deletes the board at the race end (0x00443aee) and on quit (0x00421d07) anyway.
BOARD_KEEP_DEFAULT = 175.0                       # = stock (player 2026-10-05: 400 made new race offers too rare)
BOARD_KEEP_RANGE = (175.0, 1000.0)
BOARD_KEEP_CONST = S2_CODE + 0x1100              # float metres
BOARD_KEEP = BOARD_KEEP_DEFAULT


def set_board_keep(m):
    global BOARD_KEEP
    lo, hi = BOARD_KEEP_RANGE
    if not lo <= float(m) <= hi:
        raise ValueError(f"billboard keep distance {m} m is outside {lo:g}..{hi:g}")
    BOARD_KEEP = float(m)
    PATCHES["boardkeep"] = [
        (0x004432FE, bytes.fromhex("d9053c9a5600"), bytes.fromhex("d905") + struct.pack("<I", BOARD_KEEP_CONST),
         f"race billboard: deleted only beyond {BOARD_KEEP:g} m from the camera (stock 175)"),
        (BOARD_KEEP_CONST, bytes(4), struct.pack("<f", BOARD_KEEP), f"{BOARD_KEEP:g} m"),
        (0x004419CC, bytes.fromhex("751b"), bytes.fromhex("eb1b"),
         "race: do not delete the start billboard the moment it is out of view (it goes at the race end)"),
    ]


try:
    set_board_keep(_saved("board_keep_m", BOARD_KEEP_DEFAULT))
except ImportError:
    pass

# ---- racereset: the player is not put back on the racing line at 24 m (player 2026-10-04) ------------
# "in races, the game respawned me if I go too far from the race line ... the opponents have this
# disabled". The racer progress step 0x0043f4f0 (every racer; called from 0x0043f81e): progress
# [car+0x7f48] advances when the car passes its route point within 16 m sideways; then, ONLY for the
# player ([0x012d0c88]) during a race ([0x0265d104]), if the car is farther than [0x0056982c] = 24 m
# from that point it calls 0x00438e70 + 0x0043df30 = teleport back onto the point (2.5 m up). AI racers
# never get this. Repoint the fld at 0x0043f650 (the constant's only reader) to our own distance.
# NOTE: progress still needs every route point passed in order (16 m), so skipping one leaves progress
# stuck until you return to it - the reset is what rescued that; a large distance = practically off.
RACE_RESET_DEFAULT = 150.0
RACE_RESET_RANGE = (24.0, 2000.0)
RACE_RESET_CONST = S2_CODE + 0x1104              # float metres
RACE_RESET = RACE_RESET_DEFAULT


def set_race_reset(m):
    global RACE_RESET
    lo, hi = RACE_RESET_RANGE
    if not lo <= float(m) <= hi:
        raise ValueError(f"race reset distance {m} m is outside {lo:g}..{hi:g}")
    RACE_RESET = float(m)
    PATCHES["racereset"] = [
        (0x0043F650, bytes.fromhex("d9052c985600"), bytes.fromhex("d905") + struct.pack("<I", RACE_RESET_CONST),
         f"race: put back on the racing line only beyond {RACE_RESET:g} m from the route point (stock 24)"),
        (RACE_RESET_CONST, bytes(4), struct.pack("<f", RACE_RESET), f"{RACE_RESET:g} m"),
    ]


try:
    set_race_reset(_saved("race_reset_m", RACE_RESET_DEFAULT))
except ImportError:
    pass

# ---- wantedhits: harsher wanted meter on hits (play test 2026-10-04: "it adds 2 wanted level when I
# crash onto pedestrian, and 3 into the police cars. Can you change it to 4, and 5?")
# The HUD shows trunc(wanted * 10.5) bars, max 10 (0x004698c9). In the player-collision handler:
#   pedestrian ([obj+0x9d0] == 0x2000, alive [+0x6de4] == 0): wanted += 0.2 ([0x00568bb0], shared with
#     the chase speed formula) at 0x0043a97b, then min 1.0, max 0.26 -> repointed to WANTED_PED = 0.4.
#   police car (type 2, impact > 0.3): wanted = max(wanted, 0.3) at 0x0043a891..0x0043a8ab (xmm4 = 0.3
#     is reused afterwards, so it stays) -> rewritten in place as maxss with WANTED_COP = 0.5. A floor, as
#     stock: contacts repeat every physics step, a true "+0.5" would max the meter on one scrape.
#     (Every car crash also adds impact * 0.0125, untouched.)
WANTED_PED_CONST = S2_CODE + 0x50                # float
WANTED_COP_CONST = S2_CODE + 0x54                # float
WANTED_PED = 0.4                                 # 4 bars (stock 0.2 = 2)
WANTED_COP = 0.5                                 # 5 bars (stock 0.3 = 3)
PATCHES["wantedhits"] = [
    (0x0043A97B, bytes.fromhex("f30f581db08b5600"), bytes.fromhex("f30f581d") + struct.pack("<I", WANTED_PED_CONST),
     f"hitting a pedestrian: wanted +{WANTED_PED * 10.5:.0f} bars (stock +2)"),
    (0x0043A891, bytes.fromhex("f30f101d4c042d010f2fe376150f28dcf30f111d4c042d01eb08"),
     bytes.fromhex("f30f101d4c042d01") + bytes.fromhex("f30f5f1d") + struct.pack("<I", WANTED_COP_CONST)
     + bytes.fromhex("f30f111d4c042d01") + bytes.fromhex("eb08"),
     f"hitting a police car: wanted at least {int(WANTED_COP * 10.5)} bars (stock 3)"),
    (WANTED_PED_CONST, bytes(8), struct.pack("<ff", WANTED_PED, WANTED_COP), "0.4 / 0.5"),
]

# ---- smartpolice: chasing police follow the road and brake for corners (Stage 2, 2026-10-04) -------
# Player: "the Police behind doesn't follow the road, and just crash into a building to the side I turn
# into ... sometimes overshoot the turn too". The chase state (4) handler 0x0043cda0, per police car:
#  - every 0.5 s (timer +0x1ea4 vs [0x005682f8]) the route count +0x7f44 = 0 and, when you are more than
#    22 m away ([0x00569824]), the route is rebuilt by the shared path builder 0x00431350 (A* on the road
#    grid) into [car+0x1ecc] (12-byte points, 4 m apart). Within 22 m: no route, it aims at points
#    around YOU (local space) = straight across the corner block.
#  - THE BUG: the builder stores the route REVERSED - point [0] is at YOUR end, the last point at the
#    police car (re-tools/chaseprobe.py, real map). The follow code (0x0043d28a) aims at point [1]
#    anyway = 4 m from you. So with a perfect road route in hand, the police drove straight at you.
#  - target speed (0x0043d2f7..0x0043d3de, km/h) depends on your speed, the wanted level and distance,
#    never on the road ahead = no braking for corners.
# Fix (4 parts, every chasing police car; patrols and traffic untouched):
#  1. re-route every SMART_INTERVAL s (0x0043cde2 repointed), 2. use the route down to SMART_MINROUTE m
#  (0x0043ce1f repointed; < 8 m the stock ram aim still takes over), 3. cave A at 0x0043d28a: find the
#  route point nearest the car, walk toward you until one is >= L ahead (L = |speed| x SMART_LOOK_K,
#  clamped SMART_LOOK_MIN..MAX) and aim there; 4. same cave: for every route point within SMART_DMAX
#  m, the ROAD's own bend there (12 m in vs 12 m out; t = |u_in - u_out| = 2 sin(angle/2)) gives a
#  radius ~ arc / t and a corner speed sqrt(SMART_GRIP x radius) (>= SMART_VMIN); allowed now =
#  sqrt(corner^2 + braking at SMART_DECEL over the distance). The minimum goes to SMART_CAP for this
#  car and cave B at 0x0043d3de caps the target speed. Where the route has fewer than SMART_BEND points
#  behind a point (the car's end), the incoming direction is the car's HEADING x one chord - not
#  "car position -> point": the car has usually driven past the nearest point (lane snapping, routes
#  0.25 s old), which made a fake U-turn under the car and a 33-38 km/h cap (copwatch 2026-10-04: far
#  police piled up at 35-44 km/h while you drove 62). Points closer than SMART_BEND points to YOUR end
#  use point 0 as the outgoing end, so a corner just before you is braked for too (the first version
#  skipped them: chasesim, police arriving at 60 km/h when you stood 20 m round a corner). 5. ram mode (< 8 m, 0x0043cf0b): stock aims at
#  you + your heading x min(speed x 0.2, 20 m) - 20 m ahead of you at 100 km/h, so when you turn the
#  aim swings across the corner (play test: "sometimes I can still see them going off road"). The lead
#  is capped at SMART_RAM_LEAD (0x0043cf20 `movss xmm3,[0x568eb4]` repointed; 20.0 is shared). (A first version compared the road direction
#  with the car's CURRENT heading: half-way round a corner the corner looked done and the cap rose
#  again - chasesim measured 99 km/h at the apex.)
SMART_CAVE_A = S2_CODE + 0x300                   # 0x02704300 .. 0x02704600
SMART_CAVE_B = S2_CODE + 0x600                   # 0x02704600 .. 0x02704640
SMART_DATA = S2_CODE + 0x640                     # floats/dwords
SMART_INTERVAL = 0.25                            # s between re-routes (stock 0.5)
SMART_MINROUTE = 8.0                             # m: route used beyond this (stock 22)
SMART_LOOK_K = 0.5 / 3.6                         # look-ahead = 0.5 s of travel (speed is km/h)
SMART_LOOK_MIN, SMART_LOOK_MAX = 8.0, 30.0       # m
SMART_DMAX = 70.0                                # m of road checked for corners
SMART_VMIN = 25.0                                # km/h: never plan slower than this
SMART_GRIP = 5.5                                 # m/s2 planned sideways grip (low on purpose: the chord estimate
                                                 # reads a 90-deg junction as R 14 m, the real line is ~8 m)
SMART_DECEL = 7.0                                # m/s2 planned braking
SMART_BEND = 5                                   # points (x 4 m) before/after each point for its bend
SMART_STRAIGHT = 0.2                             # t = 2 sin(angle/2): bends under ~11.5 deg are ignored
# (2026-10-04 play test: "when it is far from me, and follows the road, it is just slower" - the first
# tuning (12 m chord, grip 8, every kink over 3 deg) braked for the wobble of the lane lines on straight
# roads. chasesim: mean speed 42 -> 49 km/h, caught 56 -> 55 of 60.)
SMART_RAM_LEAD = 5.0                             # m ahead of you a ramming police car aims (stock <= 20)
_SMART_CONSTS = [  # name, value (float) - laid out from SMART_DATA in this order
    ("INTERVAL", SMART_INTERVAL), ("MINROUTE", SMART_MINROUTE), ("LOOK_K", SMART_LOOK_K),
    ("LOOK_MIN", SMART_LOOK_MIN), ("LOOK_MAX", SMART_LOOK_MAX), ("DMAX2", SMART_DMAX ** 2),
    ("VMIN2", SMART_VMIN ** 2), ("GRIP", SMART_GRIP * 3.6 ** 2), ("A2", 2 * SMART_DECEL * 3.6 ** 2),
    ("BIG", 1e30), ("ONE", 1.0), ("CAP", 0.0), ("STRAIGHT", SMART_STRAIGHT), ("HALF", 0.5),
    ("L1", 0.0), ("L2", 0.0), ("D", 0.0), ("RAM_LEAD", SMART_RAM_LEAD), ("CHORD", 4.0 * SMART_BEND)]
SM = {n: SMART_DATA + 4 * i for i, (n, _) in enumerate(_SMART_CONSTS)}
SM["ABS"] = SMART_DATA + 4 * len(_SMART_CONSTS)
SM["CAR"] = SM["ABS"] + 4


def _smart_dist2(dst):
    """xmm<dst> = squared 2D distance car (xmm4 x, xmm5 z) to point eax*4 in edi (eax = 3*index)."""
    return f"""
    movss xmm{dst}, dword ptr [edi+eax*4]
    subss xmm{dst}, xmm4
    mulss xmm{dst}, xmm{dst}
    movss xmm1, dword ptr [edi+eax*4+8]
    subss xmm1, xmm5
    mulss xmm1, xmm1
    addss xmm{dst}, xmm1
    """


def _smartpolice():
    a = _s2asm(f"""
        push ebx
        push edi
        push ebp
        lea edi, [esi+0x1ecc]
        mov ecx, eax
        mov ebp, eax
        movss xmm4, dword ptr [esi+0xa18]
        movss xmm5, dword ptr [esi+0xa20]
        xor edx, edx
        xor ebx, ebx
        movss xmm3, dword ptr [{SM['BIG']}]
    near_loop:
        cmp edx, ecx
        jae near_done
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, xmm3
        jae near_next
        movaps xmm3, xmm0
        mov ebx, edx
    near_next:
        inc edx
        jmp near_loop
    near_done:
        movss xmm2, dword ptr [esi+0x7f70]
        movss xmm1, dword ptr [{SM['ABS']}]
        andps xmm2, xmm1
        mulss xmm2, dword ptr [{SM['LOOK_K']}]
        maxss xmm2, dword ptr [{SM['LOOK_MIN']}]
        minss xmm2, dword ptr [{SM['LOOK_MAX']}]
        mulss xmm2, xmm2
        mov edx, ebx
    look_loop:
        test edx, edx
        je look_done
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, xmm2
        jae look_done
        dec edx
        jmp look_loop
    look_done:
        lea eax, [edx+edx*2]
        lea eax, [edi+eax*4]
        mov ecx, dword ptr [eax]
        mov dword ptr [esi+0x1e90], ecx
        mov ecx, dword ptr [eax+4]
        mov dword ptr [esi+0x1e94], ecx
        mov ecx, dword ptr [eax+8]
        mov dword ptr [esi+0x1e98], ecx
        movss xmm3, dword ptr [{SM['BIG']}]
        mov edx, ebx
    cap_loop:
        cmp edx, 1
        jb cap_done
        lea eax, [edx+edx*2]
        {_smart_dist2(0)}
        comiss xmm0, dword ptr [{SM['DMAX2']}]
        ja cap_done
        sqrtss xmm0, xmm0
        movss dword ptr [{SM['D']}], xmm0
        lea ecx, [edx+{SMART_BEND}]
        cmp ecx, ebp
        jb in_pt
        movss xmm6, dword ptr [esi+0x20]
        mulss xmm6, dword ptr [{SM['CHORD']}]
        movss xmm7, dword ptr [esi+0x28]
        mulss xmm7, dword ptr [{SM['CHORD']}]
        jmp in_vec
    in_pt:
        lea ecx, [ecx+ecx*2]
        movss xmm1, dword ptr [edi+ecx*4]
        movss xmm2, dword ptr [edi+ecx*4+8]
        movss xmm6, dword ptr [edi+eax*4]
        subss xmm6, xmm1
        movss xmm7, dword ptr [edi+eax*4+8]
        subss xmm7, xmm2
    in_vec:
        movaps xmm1, xmm6
        mulss xmm1, xmm1
        movaps xmm2, xmm7
        mulss xmm2, xmm2
        addss xmm1, xmm2
        sqrtss xmm1, xmm1
        comiss xmm1, dword ptr [{SM['ONE']}]
        jb cap_next
        movss dword ptr [{SM['L1']}], xmm1
        divss xmm6, xmm1
        divss xmm7, xmm1
        lea ecx, [edx-{SMART_BEND}]
        test ecx, ecx
        jge out_ok
        xor ecx, ecx
    out_ok:
        lea ecx, [ecx+ecx*2]
        movss xmm1, dword ptr [edi+ecx*4]
        subss xmm1, dword ptr [edi+eax*4]
        movss xmm2, dword ptr [edi+ecx*4+8]
        subss xmm2, dword ptr [edi+eax*4+8]
        movaps xmm0, xmm1
        mulss xmm0, xmm0
        movss dword ptr [{SM['L2']}], xmm2
        mulss xmm2, xmm2
        addss xmm0, xmm2
        movss xmm2, dword ptr [{SM['L2']}]
        sqrtss xmm0, xmm0
        comiss xmm0, dword ptr [{SM['ONE']}]
        jb cap_next
        divss xmm1, xmm0
        divss xmm2, xmm0
        addss xmm0, dword ptr [{SM['L1']}]
        mulss xmm0, dword ptr [{SM['HALF']}]
        subss xmm6, xmm1
        subss xmm7, xmm2
        mulss xmm6, xmm6
        mulss xmm7, xmm7
        addss xmm6, xmm7
        sqrtss xmm6, xmm6
        comiss xmm6, dword ptr [{SM['STRAIGHT']}]
        jb cap_next
        divss xmm0, xmm6
        mulss xmm0, dword ptr [{SM['GRIP']}]
        maxss xmm0, dword ptr [{SM['VMIN2']}]
        movss xmm1, dword ptr [{SM['D']}]
        mulss xmm1, dword ptr [{SM['A2']}]
        addss xmm0, xmm1
        minss xmm3, xmm0
    cap_next:
        dec edx
        jmp cap_loop
    cap_done:
        sqrtss xmm3, xmm3
        movss dword ptr [{SM['CAP']}], xmm3
        mov dword ptr [{SM['CAR']}], esi
        pop ebp
        pop edi
        pop ebx
        jmp 0x0043d2c7
    """, SMART_CAVE_A, SMART_CAVE_B)
    b = _s2asm(f"""
        cmp dword ptr [{SM['CAR']}], esi
        jne keep
        minss xmm0, dword ptr [{SM['CAP']}]
        mov dword ptr [{SM['CAR']}], 0
    keep:
        movss xmm5, dword ptr [0x00568594]
        jmp 0x0043d3e6
    """, SMART_CAVE_B, SMART_DATA)
    data = b"".join(struct.pack("<f", v) for _, v in _SMART_CONSTS) + struct.pack("<II", 0x7FFFFFFF, 0)
    return [
        (0x0043CDE2, bytes.fromhex("0f2f05f8825600"), bytes.fromhex("0f2f05") + struct.pack("<I", SM["INTERVAL"]),
         f"chase: re-route every {SMART_INTERVAL:g} s (stock 0.5)"),
        (0x0043CE1F, bytes.fromhex("0f2f0524985600"), bytes.fromhex("0f2f05") + struct.pack("<I", SM["MINROUTE"]),
         f"chase: follow the road route down to {SMART_MINROUTE:g} m (stock 22, then straight at you)"),
        (0x0043D28A, bytes.fromhex("8bcd3bc572028bc8493bcd76048bc5eb073bc573028bc548"), _s2jmp(0x0043D28A, SMART_CAVE_A, 24),
         "chase: aim along the route from the police car's end (stock: 4 m from YOU - the route is stored reversed)"),
        (SMART_CAVE_A, bytes(len(a)), a, f"smartpolice cave A: look-ahead target + corner speed ({len(a)} bytes)"),
        (0x0043D3DE, bytes.fromhex("f30f102d94855600"), _s2jmp(0x0043D3DE, SMART_CAVE_B, 8),
         "chase: target speed capped for the corners ahead"),
        (SMART_CAVE_B, bytes(len(b)), b, f"smartpolice cave B ({len(b)} bytes)"),
        (0x0043CF20, bytes.fromhex("f30f101db48e5600"), bytes.fromhex("f30f101d") + struct.pack("<I", SM["RAM_LEAD"]),
         f"chase, ramming (< 8 m): aim at most {SMART_RAM_LEAD:g} m ahead of you (stock up to 20 - cut corners)"),
        (SMART_DATA, bytes(len(data)), data, "smartpolice constants"),
    ]


try:
    PATCHES["smartpolice"] = _smartpolice()
except ImportError:
    pass

# ---- policefix: the ORIGINAL chase AI, only the backwards route fixed (2026-10-04) ------------------
# Player, after smartpolice: "revert the police code so it is using the original dumb one ... just switch
# the logic so it isn't backward". Everything stock (0.5 s re-route, straight at you within 22 m, stock
# target speed, stock 20 m ram lead) EXCEPT the aim in route mode (0x0043d28a): stock aims at route point
# [1] = 4 m from YOU (the route is stored reversed). Simply taking the point 2nd from the police end is
# not enough: the route is up to 0.5 s old, so a fast car passes that point at once and the stock "aim
# behind" branch crawls at 33.75 km/h. So: nearest route point to the car, then toward you until one is
# >= L ahead (L = |speed| x 0.5 s, 8..30 m) - the same aim as smartpolice, nothing else of it.
PFIX_CAVE = S2_CODE + 0xA40                      # .. 0xB40
PFIX_DATA = S2_CODE + 0xB40                      # BIG, LOOK_K, LOOK_MIN, LOOK_MAX, ABS mask


def _policefix():
    d = {n: PFIX_DATA + 4 * i for i, n in enumerate(("BIG", "LOOK_K", "LOOK_MIN", "LOOK_MAX", "ABS"))}
    dist2 = """
        movss xmm0, dword ptr [edi+eax*4]
        subss xmm0, xmm4
        mulss xmm0, xmm0
        movss xmm1, dword ptr [edi+eax*4+8]
        subss xmm1, xmm5
        mulss xmm1, xmm1
        addss xmm0, xmm1
    """
    code = _s2asm(f"""
        push ebx
        push edi
        lea edi, [esi+0x1ecc]
        mov ecx, eax
        movss xmm4, dword ptr [esi+0xa18]
        movss xmm5, dword ptr [esi+0xa20]
        xor edx, edx
        xor ebx, ebx
        movss xmm3, dword ptr [{d['BIG']}]
    near_loop:
        cmp edx, ecx
        jae near_done
        lea eax, [edx+edx*2]
        {dist2}
        comiss xmm0, xmm3
        jae near_next
        movaps xmm3, xmm0
        mov ebx, edx
    near_next:
        inc edx
        jmp near_loop
    near_done:
        movss xmm2, dword ptr [esi+0x7f70]
        movss xmm1, dword ptr [{d['ABS']}]
        andps xmm2, xmm1
        mulss xmm2, dword ptr [{d['LOOK_K']}]
        maxss xmm2, dword ptr [{d['LOOK_MIN']}]
        minss xmm2, dword ptr [{d['LOOK_MAX']}]
        mulss xmm2, xmm2
        mov edx, ebx
    look_loop:
        test edx, edx
        je look_done
        lea eax, [edx+edx*2]
        {dist2}
        comiss xmm0, xmm2
        jae look_done
        dec edx
        jmp look_loop
    look_done:
        lea eax, [edx+edx*2]
        lea eax, [edi+eax*4]
        mov ecx, dword ptr [eax]
        mov dword ptr [esi+0x1e90], ecx
        mov ecx, dword ptr [eax+4]
        mov dword ptr [esi+0x1e94], ecx
        mov ecx, dword ptr [eax+8]
        mov dword ptr [esi+0x1e98], ecx
        pop edi
        pop ebx
        jmp 0x0043d2c7
    """, PFIX_CAVE, PFIX_DATA)
    data = struct.pack("<4fI", 1e30, SMART_LOOK_K, SMART_LOOK_MIN, SMART_LOOK_MAX, 0x7FFFFFFF)
    return [
        (0x0043D28A, bytes.fromhex("8bcd3bc572028bc8493bcd76048bc5eb073bc573028bc548"), _s2jmp(0x0043D28A, PFIX_CAVE, 24),
         "chase: aim along the route from the police car's end (stock aims 4 m from YOU); nothing else changed"),
        (PFIX_CAVE, bytes(len(code)), code, f"policefix cave ({len(code)} bytes)"),
        (PFIX_DATA, bytes(len(data)), data, "policefix constants"),
    ]


try:
    PATCHES["policefix"] = _policefix()
except ImportError:
    pass

# ---- milkyway: a real Milky Way in the night sky (Stage 2 #13, 2026-10-04) ----------------------
# Stock night sky = 100 copies of a 32x32 sparkle (built 0x004259b0, drawn 0x00425eb0 from 0x00428898):
# world = translate to the camera, FVF XYZ|TEX1, additive (ONE/ONE), lit by a material whose EMISSIVE is
# -(0.5..1 twinkle) x [0x02648270] (the sun direction's y: negative at night - drawn only then).
# Added (2026-10-04 v2 - v1 drew with the stars and the sky DOME 0x004271a0, drawn after them, painted
# over it): between the dome and the moon (hook 0x004288ab `mov ecx,esi; call 0x427880`), a sphere of radius MW_RADIUS around the camera with the ESO/S. Brunier
# panorama (CC BY 4.0; skyprep.py -> Data/Sky/MilkyWay.jpg in Textures.pak, asked for as .bmp like
# every texture), drawn with the stars' states set by the cave itself through the game's cached setters
# (fog off 0x0040b0f0, z off 0x0040b000, z-write off 0x0040afd0, lighting on 0x0040b030, ONE/ONE
# 0x0040b060), world = camera translation (SetTransform +0xb0), FVF XYZ|TEX1 (+0x164), and its own steady
# material: emissive = clamp(-y x MW_RAMP - 1, 0, 1) x brightness (the slider; computed once per frame,
# kept in TMPI - free after the sphere is built - for the material). First use: texture through
# the game's loader 0x0040ad00 (its cache), a 65x33 sphere built into VirtualAlloc'd memory (galactic
# -> world rotation MW_R, so the band arcs across the sky), both windings (cull state untouched). Draw:
# material via 0x0040ac90 and texture via 0x0040adc0 (the game's own state cache), then
# DrawIndexedPrimitiveUP (device vtable +0x150). The moon/cloud passes after it set their own states and
# streams. If the texture or memory is missing, nothing is drawn.
MW_CAVE = S2_CODE + 0xB60                        # .. 0xEE0
MW_DATA = S2_CODE + 0xEE0                        # .. 0xFF0 (270 bytes)
MW_LON, MW_LAT = 64, 32
MW_NV = (MW_LON + 1) * (MW_LAT + 1)              # 2145 vertices, 20 bytes
MW_NT = MW_LON * MW_LAT * 4                      # both windings
MW_RADIUS = 590.0                                # just inside the stock stars (600)
MW_FADE_START, MW_FADE_FULL = 0.08, 0.30         # 2026-10-04 (3rd): sun y -0.08 (4.6 deg below) .. -0.30 (17.5):
                                                 # the 8.6..17.5 deg window "just vanished" at dawn (the sun is quick)
MW_RAMP = 1 / (MW_FADE_FULL - MW_FADE_START)     # b = clamp(-y x RAMP - FADE_C) = (-y - START) / (FULL - START)
MW_FADE_C = S2_CODE + 0x10F4                     # float START x RAMP
# (2nd) b = clamp(-y x RAMP - 1) with RAMP 1/0.15: starts at sun y -0.15 (8.6 deg below),
                                                 # full at -0.30 (17.5 deg). History 2026-10-04: clamp(-y x 4) (full
                                                 # from 14.5 deg) sat over the red dawn sky; RAMP 5 (-0.2 / -0.4)
                                                 # faded 'a bit too early' - this is the safe middle
MW_BRIGHT_DEFAULT = 1.0
MW_BRIGHT_RANGE = (0.1, 1.0)                     # D3D clamps lit colour at 1: above 1 would do nothing
MW_BRIGHT = MW_BRIGHT_DEFAULT
MW_TEXNAME = b"Data/Sky/MilkyWay.dds\0"                # uncompressed DDS: the 4096 JPEG did not load (v1/v2)
MW_GC_ALT = 20.0                                 # galactic centre this high over the horizon (deg)
# Cloud shadow (2026-10-04, the player: "the clouds ... like rendering the stars in front of it"): the
# clouds (0x00428590: Data/Sky/Clouds.msh + Clouds.jpg, sky +0x1f0/+0x1f4) are drawn ADDITIVELY (ONE/ONE),
# so nothing behind them is ever hidden - the stock stars shine through them too. Hook 0x004287b1 (after
# the clouds' material, texture, ONE/ONE and FVF, before their DrawSubset): at night draw the cloud mesh
# once more with SRC=ZERO, DEST=INVSRCCOLOR and the material emissive s = ramp x MW_CLOUD_SHADE, i.e.
# sky = sky x (1 - cloud x s): thick cloud blocks the Milky Way and stars; then the clouds' own material
# and ONE/ONE go back and the stock pass adds their glow. s = 0 by day: the stock clouds are untouched.
MW_SHADE_CAVE = S2_CODE + 0x1000                 # .. 0x10F0 (the area .crmod grew by)
MW_SHADE_K = S2_CODE + 0x10F0                    # float MW_CLOUD_SHADE
MW_CLOUD_SHADE = 1.0
MW_TILT = 60.0                                   # galactic plane this steep (deg from horizontal)


def _mw_rotation():
    """Columns = where galactic x (to the centre), y (l = 90) and z (north pole) point in the game's
    left-handed world (y up). y = x cross z keeps the sky unmirrored when seen from inside."""
    import math
    a = math.radians(MW_GC_ALT)
    gx = (0.0, math.sin(a), math.cos(a))
    e = math.radians(90.0 - MW_TILT)
    nr = (math.cos(e), math.sin(e), 0.0)
    d = sum(p * q for p, q in zip(nr, gx))
    gz = tuple(p - d * q for p, q in zip(nr, gx))
    ln = math.sqrt(sum(p * p for p in gz))
    gz = tuple(p / ln for p in gz)
    gy = (gx[1] * gz[2] - gx[2] * gz[1], gx[2] * gz[0] - gx[0] * gz[2], gx[0] * gz[1] - gx[1] * gz[0])
    return gx, gy, gz


def _mw_shade_src(k_addr):
    """The cloud-shadow cave (hook 0x004287b1) as assembly text; k_addr = where the strength float
    lives (MW_SHADE_K in the build, fresh memory for re-tools/mwlive_shade.py)."""
    d = MW_D
    return f"""
        pushad
        movss xmm0, dword ptr [0x02648270]
        mulss xmm0, dword ptr [{d['NEGK']}]
        subss xmm0, dword ptr [{MW_FADE_C}]
        maxss xmm0, dword ptr [{d['ZERO']}]
        minss xmm0, dword ptr [{d['ONE']}]
        mulss xmm0, dword ptr [{k_addr}]
        comiss xmm0, dword ptr [{d['EPS']}]
        jbe skip
        movss dword ptr [{d['MAT'] + 0x30}], xmm0
        movss dword ptr [{d['MAT'] + 0x34}], xmm0
        movss dword ptr [{d['MAT'] + 0x38}], xmm0
        push {d['MAT']}
        mov ecx, 0x0255d7f0
        call 0x0040ac90
        push 4
        push 1
        mov ecx, 0x0255d7f0
        call 0x0040b060
        mov ecx, dword ptr [ebx+0x1f0]
        mov edx, dword ptr [ecx+0x18c]
        mov eax, dword ptr [edx]
        mov ecx, dword ptr [eax]
        push 0
        push eax
        call dword ptr [ecx+0xc]
        lea eax, [esp+0x40]
        push eax
        mov ecx, 0x0255d7f0
        call 0x0040ac90
        push 2
        push 2
        mov ecx, 0x0255d7f0
        call 0x0040b060
    skip:
        popad
        mov ecx, dword ptr [ebx+0x1f0]
        jmp 0x004287b7
    """


def set_milkyway(v):
    global MW_BRIGHT
    import math
    lo, hi = MW_BRIGHT_RANGE
    if not lo <= float(v) <= hi:
        raise ValueError(f"Milky Way brightness {v} is outside {lo:g}..{hi:g}")
    MW_BRIGHT = float(v)
    names = ["STATE", "TEX", "VTX", "IDX", "TMPI", "CB", "SB", "CL", "SL", "DB", "DL", "HALFPI", "PI",
             "INVLON", "INVLAT", "NEGK", "ZERO", "ONE", "GAIN", "EPS"] + [f"R{i}" for i in range(9)]
    d = {n: MW_DATA + 4 * i for i, n in enumerate(names)}
    d["MAT"] = MW_DATA + 4 * len(names)                    # D3DMATERIAL9, 0x44 bytes
    d["NAME"] = d["MAT"] + 0x44
    d["WORLD"] = d["NAME"] + 24                            # 4x4 world matrix, translation filled per frame
    gx, gy, gz = _mw_rotation()
    R = [gx[r] * MW_RADIUS for r in range(3)], [gy[r] * MW_RADIUS for r in range(3)], [gz[r] * MW_RADIUS for r in range(3)]
    rvals = [R[c][r] for r in range(3) for c in range(3)]  # R{3r+c}: world axis r from galactic axis c
    floats = {"DB": math.pi / MW_LAT, "DL": 2 * math.pi / MW_LON, "HALFPI": math.pi / 2, "PI": math.pi,
              "INVLON": 1.0 / MW_LON, "INVLAT": 1.0 / MW_LAT, "NEGK": -MW_RAMP, "ZERO": 0.0, "ONE": 1.0,
              "GAIN": MW_BRIGHT, "EPS": 0.002}
    data = bytearray()
    for n in names:
        if n in floats:
            data += struct.pack("<f", floats[n])
        elif n.startswith("R"):
            data += struct.pack("<f", rvals[int(n[1:])])
        else:
            data += bytes(4)
    mat = bytearray(0x44)
    struct.pack_into("<f", mat, 0x0C, 1.0)                 # diffuse alpha 1; emissive rgb set per frame
    struct.pack_into("<f", mat, 0x3C, 1.0)
    data += mat + MW_TEXNAME.ljust(24, b"\0")
    data += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    assert MW_DATA + len(data) <= S2_CODE_END, "milkyway data past the .crmod area"
    rows = ""
    for r in range(3):
        rows += f"""
        movaps xmm3, xmm0
        mulss xmm3, dword ptr [{d[f'R{3 * r}']}]
        movaps xmm4, xmm1
        mulss xmm4, dword ptr [{d[f'R{3 * r + 1}']}]
        addss xmm3, xmm4
        movaps xmm4, xmm2
        mulss xmm4, dword ptr [{d[f'R{3 * r + 2}']}]
        addss xmm3, xmm4
        movss dword ptr [edi+{4 * r}], xmm3
        """
    code = _s2asm(f"""
        pushad
        cmp dword ptr [{d['STATE']}], 0
        jne ready
        mov dword ptr [{d['STATE']}], 2
        push 1
        push 1
        push {d['NAME']}
        mov ecx, 0x0255d7f0
        call 0x0040ad00
        cmp eax, -1
        je out
        mov dword ptr [{d['TEX']}], eax
        push 4
        push 0x3000
        push {MW_NV * 20 + MW_NT * 6}
        push 0
        call dword ptr [0x00568170]
        test eax, eax
        je out
        mov dword ptr [{d['VTX']}], eax
        lea ecx, [eax+{MW_NV * 20}]
        mov dword ptr [{d['IDX']}], ecx
        mov edi, eax
        xor ebp, ebp
    row:
        mov dword ptr [{d['TMPI']}], ebp
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['DB']}]
        fsubr dword ptr [{d['HALFPI']}]
        fsincos
        fstp dword ptr [{d['CB']}]
        fstp dword ptr [{d['SB']}]
        xor esi, esi
    col:
        mov dword ptr [{d['TMPI']}], esi
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['DL']}]
        fsubr dword ptr [{d['PI']}]
        fsincos
        fstp dword ptr [{d['CL']}]
        fstp dword ptr [{d['SL']}]
        movss xmm0, dword ptr [{d['CB']}]
        mulss xmm0, dword ptr [{d['CL']}]
        movss xmm1, dword ptr [{d['CB']}]
        mulss xmm1, dword ptr [{d['SL']}]
        movss xmm2, dword ptr [{d['SB']}]
        {rows}
        mov dword ptr [{d['TMPI']}], esi
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['INVLON']}]
        fstp dword ptr [edi+12]
        mov dword ptr [{d['TMPI']}], ebp
        fild dword ptr [{d['TMPI']}]
        fmul dword ptr [{d['INVLAT']}]
        fstp dword ptr [edi+16]
        add edi, 20
        inc esi
        cmp esi, {MW_LON + 1}
        jb col
        inc ebp
        cmp ebp, {MW_LAT + 1}
        jb row
        mov edi, dword ptr [{d['IDX']}]
        xor ebp, ebp
    irow:
        xor esi, esi
    icol:
        mov eax, ebp
        imul eax, eax, {MW_LON + 1}
        add eax, esi
        lea ecx, [eax+{MW_LON + 1}]
        lea edx, [eax+1]
        mov word ptr [edi], ax
        mov word ptr [edi+2], cx
        mov word ptr [edi+4], dx
        mov word ptr [edi+6], ax
        mov word ptr [edi+8], dx
        mov word ptr [edi+10], cx
        mov word ptr [edi+12], dx
        mov word ptr [edi+14], cx
        lea edx, [ecx+1]
        mov word ptr [edi+16], dx
        mov word ptr [edi+18], dx
        mov word ptr [edi+20], cx
        lea edx, [eax+1]
        mov word ptr [edi+22], dx
        add edi, 24
        inc esi
        cmp esi, {MW_LON}
        jb icol
        inc ebp
        cmp ebp, {MW_LAT}
        jb irow
        mov dword ptr [{d['STATE']}], 1
    ready:
        cmp dword ptr [{d['STATE']}], 1
        jne out
        movss xmm0, dword ptr [0x02648270]
        mulss xmm0, dword ptr [{d['NEGK']}]
        subss xmm0, dword ptr [{MW_FADE_C}]
        maxss xmm0, dword ptr [{d['ZERO']}]
        minss xmm0, dword ptr [{d['ONE']}]
        mulss xmm0, dword ptr [{d['GAIN']}]
        comiss xmm0, dword ptr [{d['EPS']}]
        jbe out
        movss dword ptr [{d['TMPI']}], xmm0
        push 0
        mov ecx, 0x0255d7f0
        call 0x0040b0f0
        push 0
        mov ecx, 0x0255d7f0
        call 0x0040b000
        push 0
        mov ecx, 0x0255d7f0
        call 0x0040afd0
        push 1
        mov ecx, 0x0255d7f0
        call 0x0040b030
        push 2
        push 2
        mov ecx, 0x0255d7f0
        call 0x0040b060
        mov eax, dword ptr [0x02610010]
        mov ecx, dword ptr [eax+0x70]
        mov dword ptr [{d['WORLD'] + 0x30}], ecx
        mov ecx, dword ptr [eax+0x74]
        mov dword ptr [{d['WORLD'] + 0x34}], ecx
        mov ecx, dword ptr [eax+0x78]
        mov dword ptr [{d['WORLD'] + 0x38}], ecx
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push {d['WORLD']}
        push 0x100
        push eax
        call dword ptr [ecx+0xb0]
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push 0x102
        push eax
        call dword ptr [ecx+0x164]
        movss xmm0, dword ptr [{d['TMPI']}]
        movss dword ptr [{d['MAT'] + 0x30}], xmm0
        movss dword ptr [{d['MAT'] + 0x34}], xmm0
        movss dword ptr [{d['MAT'] + 0x38}], xmm0
        push {d['MAT']}
        mov ecx, 0x0255d7f0
        call 0x0040ac90
        push 0
        push 0
        push 1
        push dword ptr [{d['TEX']}]
        mov ecx, 0x0255d7f0
        call 0x0040adc0
        mov eax, dword ptr [0x025a1824]
        mov ecx, dword ptr [eax]
        push 20
        push dword ptr [{d['VTX']}]
        push 101
        push dword ptr [{d['IDX']}]
        push {MW_NT}
        push {MW_NV}
        push 0
        push 4
        push eax
        call dword ptr [ecx+0x150]
    out:
        popad
        mov ecx, esi
        call 0x00427880
        jmp 0x004288b2
    """, MW_CAVE, MW_DATA)
    global MW_D
    MW_D = d
    shade = _s2asm(_mw_shade_src(MW_SHADE_K), MW_SHADE_CAVE, MW_SHADE_K)
    PATCHES["milkyway"] = [
        (0x004288AB, bytes.fromhex("8bcee8ceefffff"), _s2jmp(0x004288AB, MW_CAVE, 7),
         "night sky: after the sky dome (before moon/clouds), draw the Milky Way sphere"),
        (MW_CAVE, bytes(len(code)), code, f"milkyway cave ({len(code)} bytes)"),
        (MW_DATA, bytes(len(data)), bytes(data), f"milkyway data (brightness {MW_BRIGHT:g})"),
        (0x004287B1, bytes.fromhex("8b8bf0010000"), _s2jmp(0x004287B1, MW_SHADE_CAVE, 6),
         "clouds: at night first darken the sky behind them (they only add light: stars showed through)"),
        (MW_SHADE_CAVE, bytes(len(shade)), shade, f"cloud shadow cave ({len(shade)} bytes)"),
        (MW_SHADE_K, bytes(4), struct.pack("<f", MW_CLOUD_SHADE), f"cloud shadow strength {MW_CLOUD_SHADE:g}"),
        (MW_FADE_C, bytes(4), struct.pack("<f", MW_FADE_START * MW_RAMP),
         f"night fade: starts at sun y -{MW_FADE_START:g}, full at -{MW_FADE_FULL:g}"),
    ]


try:
    set_milkyway(min(max(_saved("milkyway_bright", MW_BRIGHT_DEFAULT), MW_BRIGHT_RANGE[0]), MW_BRIGHT_RANGE[1]))
except ImportError:
    pass

# ---- rayfast: the wheel rays stop testing every object in the world (Stage 2 #15, 2026-10-04) -----
# The player's 5 CPU profiles (city, 2026-10-04 11:25-11:31): physics = 70-84% of the main thread,
# almost all of it in btCollisionWorld::rayTest 0x0051e8f0 (~40% in its own loop) and the two shape
# getAabb's it calls (0x0051bbb0 ~13%, 0x005271e0 ~11%). Who casts the rays: btDefaultVehicleRaycaster::
# castRay 0x00538400 - one per WHEEL per physics step for every car (traffic, police, racers, you).
# This Bullet (2.6x/2.7x, btAxisSweep3) answers each ray by looping over EVERY collision object,
# recomputing its AABB through a virtual call and slab-testing the ray against it; later Bullet versions
# (2.76+) ask the broadphase instead. Cost = cars x 4 x steps/s x objects.
# Fix, exact by construction:
#  H1 updateAabbs 0x0051d930 (once per step, before the rays) already computes every awake object's
#     AABB (getAabb into [esp+0x20] min / [esp+0x10] max) - cave H1 at 0x0051d9a9 copies it, with the
#     object, its shape and its origin, into a table (VirtualAlloc'd on first use, index = the object's
#     slot in m_collisionObjects).
#  H2 rayTest's loop 0x0051ea6c (after the filter test): if the table entry is this object AND shape,
#     shift the cached box by how far the object has moved since (origin now - origin then), widen it
#     by RAYFAST_MARGIN for rotation, and skip the object when the ray's own box misses it. Anything not
#     clearly missed - and every object without a valid entry - goes through the ORIGINAL getAabb +
#     btRayAabb + rayTestSingle, so hits are found exactly as before.
#  H3 right after that original getAabb (0x0051ea8a: min [esp+0xe4], max [esp+0x34]) the box is stored
#     in the table too, so objects updateAabbs never refreshes (asleep: state 2/5 - statics too) get
#     cached on their first ray and stay cheap afterwards.
RAYFAST_H1 = S2_CODE + 0x700                     # .. 0x7C0
RAYFAST_H2 = S2_CODE + 0x7C0                     # .. 0x940
RAYFAST_H3 = S2_CODE + 0x940                     # .. 0xA00
RAYFAST_DATA = S2_CODE + 0xA00                   # table pointer, margin
RAYFAST_TABLE = RAYFAST_DATA                     # dword: 0 until the first step allocates it
RAYFAST_MARGIN_C = RAYFAST_DATA + 4              # float
RAYFAST_MARGIN = 0.5                             # m: rotation within one step (a car spinning 2 rev/s
                                                 # at 90 Hz moves its corners ~0.35 m)
RAYFAST_CAP = 16384                              # objects (entries of 48 bytes = 768 KB)
RAYFAST_ENTRY = 48                               # obj, shape, origin xyz, min xyz, max xyz, pad


def _rayfast():
    E, CAP = RAYFAST_ENTRY, RAYFAST_CAP
    h1 = _s2asm(f"""
        push eax
        push ecx
        push edx
        mov eax, dword ptr [{RAYFAST_TABLE}]
        test eax, eax
        jne have
        push 4
        push 0x3000
        push {CAP * E}
        push 0
        call dword ptr [0x00568170]
        mov dword ptr [{RAYFAST_TABLE}], eax
        test eax, eax
        je done
    have:
        cmp ebp, {CAP}
        jae done
        imul ecx, ebp, {E}
        add eax, ecx
        mov dword ptr [eax], edi
        mov ecx, dword ptr [edi+0xa8]
        mov dword ptr [eax+4], ecx
        mov ecx, dword ptr [edi+0x34]
        mov dword ptr [eax+8], ecx
        mov ecx, dword ptr [edi+0x38]
        mov dword ptr [eax+0xc], ecx
        mov ecx, dword ptr [edi+0x3c]
        mov dword ptr [eax+0x10], ecx
        mov ecx, dword ptr [esp+0x2c]
        mov dword ptr [eax+0x14], ecx
        mov ecx, dword ptr [esp+0x30]
        mov dword ptr [eax+0x18], ecx
        mov ecx, dword ptr [esp+0x34]
        mov dword ptr [eax+0x1c], ecx
        mov ecx, dword ptr [esp+0x1c]
        mov dword ptr [eax+0x20], ecx
        mov ecx, dword ptr [esp+0x20]
        mov dword ptr [eax+0x24], ecx
        mov ecx, dword ptr [esp+0x24]
        mov dword ptr [eax+0x28], ecx
    done:
        pop edx
        pop ecx
        pop eax
        test byte ptr [edi+0xac], 1
        jmp 0x0051d9b0
    """, RAYFAST_H1, RAYFAST_H2)
    axes = ""
    for a in (0, 4, 8):
        axes += f"""
        movss xmm1, dword ptr [eax+{0x34 + a}]
        subss xmm1, dword ptr [edx+{0x8 + a}]
        movss xmm2, dword ptr [edx+{0x14 + a}]
        addss xmm2, xmm1
        subss xmm2, dword ptr [{RAYFAST_MARGIN_C}]
        movss xmm3, dword ptr [edx+{0x20 + a}]
        addss xmm3, xmm1
        addss xmm3, dword ptr [{RAYFAST_MARGIN_C}]
        movss xmm4, dword ptr [esi+{a}]
        minss xmm4, dword ptr [edi+{a}]
        comiss xmm4, xmm3
        ja skip
        movss xmm4, dword ptr [esi+{a}]
        maxss xmm4, dword ptr [edi+{a}]
        comiss xmm4, xmm2
        jb skip
        """
    h2 = _s2asm(f"""
        mov edx, dword ptr [{RAYFAST_TABLE}]
        test edx, edx
        je slow
        mov ecx, dword ptr [esp+0x10]
        cmp ecx, {CAP}
        jae slow
        imul ecx, ecx, {E}
        add edx, ecx
        cmp dword ptr [edx], eax
        jne slow
        mov ecx, dword ptr [eax+0xa8]
        cmp dword ptr [edx+4], ecx
        jne slow
        {axes}
    slow:
        mov ecx, dword ptr [eax+0xa8]
        mov edx, dword ptr [ecx]
        jmp 0x0051ea74
    skip:
        jmp 0x0051ed7a
    """, RAYFAST_H2, RAYFAST_H3)
    h3 = _s2asm(f"""
        push eax
        push ecx
        push edx
        mov eax, dword ptr [{RAYFAST_TABLE}]
        test eax, eax
        je done
        mov ecx, dword ptr [esp+0x1c]
        cmp ecx, {CAP}
        jae done
        imul ecx, ecx, {E}
        add eax, ecx
        mov edx, dword ptr [esp+0x20]
        mov dword ptr [eax], edx
        mov ecx, dword ptr [edx+0xa8]
        mov dword ptr [eax+4], ecx
        mov ecx, dword ptr [edx+0x34]
        mov dword ptr [eax+8], ecx
        mov ecx, dword ptr [edx+0x38]
        mov dword ptr [eax+0xc], ecx
        mov ecx, dword ptr [edx+0x3c]
        mov dword ptr [eax+0x10], ecx
        mov ecx, dword ptr [esp+0xf0]
        mov dword ptr [eax+0x14], ecx
        mov ecx, dword ptr [esp+0xf4]
        mov dword ptr [eax+0x18], ecx
        mov ecx, dword ptr [esp+0xf8]
        mov dword ptr [eax+0x1c], ecx
        mov ecx, dword ptr [esp+0x40]
        mov dword ptr [eax+0x20], ecx
        mov ecx, dword ptr [esp+0x44]
        mov dword ptr [eax+0x24], ecx
        mov ecx, dword ptr [esp+0x48]
        mov dword ptr [eax+0x28], ecx
    done:
        pop edx
        pop ecx
        pop eax
        movss xmm3, dword ptr [0x005682f8]
        jmp 0x0051ea92
    """, RAYFAST_H3, RAYFAST_DATA)
    return [
        (0x0051D9A9, bytes.fromhex("f687ac00000001"), _s2jmp(0x0051D9A9, RAYFAST_H1, 7),
         "updateAabbs: remember every object's AABB + position for this step's rays"),
        (RAYFAST_H1, bytes(len(h1)), h1, f"rayfast cave H1 ({len(h1)} bytes)"),
        (0x0051EA6C, bytes.fromhex("8b88a80000008b11"), _s2jmp(0x0051EA6C, RAYFAST_H2, 8),
         "rayTest: skip objects whose remembered box the ray clearly misses (the rest: exact test as before)"),
        (RAYFAST_H2, bytes(len(h2)), h2, f"rayfast cave H2 ({len(h2)} bytes)"),
        (0x0051EA8A, bytes.fromhex("f30f101df8825600"), _s2jmp(0x0051EA8A, RAYFAST_H3, 8),
         "rayTest: also remember a box computed the slow way (objects asleep in updateAabbs)"),
        (RAYFAST_H3, bytes(len(h3)), h3, f"rayfast cave H3 ({len(h3)} bytes)"),
        (RAYFAST_MARGIN_C, bytes(4), struct.pack("<f", RAYFAST_MARGIN), f"rotation margin {RAYFAST_MARGIN:g} m"),
    ]


try:
    PATCHES["rayfast"] = _rayfast()
except ImportError:
    pass

# ---- adaptive: the physics rate as a FLOOR that follows the FPS above it (Stage 2 #14) ---------
# The player's idea (2026-09-26): "if we set 60 and the FPS is 20, it still runs at 60 ... if the FPS
# is at 72, ours at 60 Hz, it automatically follows 72 Hz" - physics rate = max(FPS, floor).
# With `fixedstep` alone, Bullet takes steps of exactly 1/Hz and carries the remainder in its
# accumulator (m_localTime, world+0x74): above Hz the steps don't line up with frames (some frames
# take 0 steps, some 2) and the drawn positions are extrapolated by the leftover time - the classic
# fixed-step judder - while a 144 FPS screen still only sees 90 physics updates a second.
# `adaptive` (needs fixedstep, whose 1/Hz constant it reads at run time):
#   - FPS at or above the floor (dt <= 1/Hz): T = dt + the accumulator's leftover (non-zero only on
#     the first frame after dropping below the floor), n = ceil(T x Hz) (1 in steady state, 2 at a
#     crossing; rounded with a 0.1% tolerance so the ~1e-6 leftover at FPS == Hz does not make
#     it 2), accumulator = 0, stepSimulation(T, n, T/n x (1 - 2^-20)): n equal steps that end
#     exactly at the frame (the 2^-20 makes Bullet's int(localTime / step) come out as n despite
#     float rounding; ~T/10^6 is left over, nothing to extrapolate). 72 FPS -> 72 Hz, 144 -> 144.
#   - FPS below the floor, or paused (dt 0): exactly fixedstep's call, stepSimulation(dt, 64, 1/Hz)
#     (Bullet's own clamp never bites: dt <= 50 ms gives at most int(0.05 Hz) + 1 steps).
# Every step is <= 1/Hz and the cost is max(FPS, Hz) steps a second - never more than either stock
# (one per frame) or fixedstep (Hz a second). The first try, n = ceil(dt x Hz) at every FPS, was
# rejected in s2check: just below the floor it doubles the steps (90 Hz at 55 FPS = 110 steps/s),
# which is exactly the city-centre case.
# Hook 0x00421ef5 (the `mov ecx, [esi+0x28288]` that starts the call sequence) -> cave -> back at
# 0x00421f18; the old sequence (where fixedstep's own edits live) becomes unreachable, so the two
# patches never fight over bytes. esi (the game object) is kept; eax/ecx/edx/x87/xmm were already
# clobbered by the original call.
ADAPT_CAVE = S2_CODE + 0x180                     # 0x02704180
ADAPT_EPS = S2_CODE + 0x48                       # float 1 - 2^-20
ADAPT_TOL = S2_CODE + 0x4C                       # float 1 - 2^-10: a step may be 0.1% over 1/Hz
ADAPT_MAXN = 64


def _adaptive():
    code = _s2asm(f"""
        mov ecx, dword ptr [esi+0x28288]
        mov eax, dword ptr [ecx]
        mov edx, dword ptr [eax+0x14]
        movss xmm0, dword ptr [0x012d04a8]
        xorps xmm1, xmm1
        comiss xmm0, xmm1
        jbe fixed
        comiss xmm0, dword ptr [{FIXED_STEP:#x}]
        ja fixed
        addss xmm0, dword ptr [ecx+0x74]
        movaps xmm1, xmm0
        divss xmm1, dword ptr [{FIXED_STEP:#x}]
        mulss xmm1, dword ptr [{ADAPT_TOL:#x}]
        cvttss2si eax, xmm1
        cvtsi2ss xmm2, eax
        comiss xmm1, xmm2
        jbe floor_ok
        inc eax
    floor_ok:
        cmp eax, 1
        jge lo_ok
        mov eax, 1
    lo_ok:
        cmp eax, {ADAPT_MAXN}
        jle hi_ok
        mov eax, {ADAPT_MAXN}
    hi_ok:
        cvtsi2ss xmm2, eax
        movaps xmm1, xmm0
        divss xmm1, xmm2
        mulss xmm1, dword ptr [{ADAPT_EPS:#x}]
        mov dword ptr [ecx+0x74], 0
        sub esp, 4
        movss dword ptr [esp], xmm1
        push eax
        sub esp, 4
        movss dword ptr [esp], xmm0
        call edx
        jmp 0x00421f18
    fixed:
        sub esp, 4
        movss xmm1, dword ptr [{FIXED_STEP:#x}]
        movss dword ptr [esp], xmm1
        push {ADAPT_MAXN}
        sub esp, 4
        movss xmm0, dword ptr [0x012d04a8]
        movss dword ptr [esp], xmm0
        call edx
        jmp 0x00421f18
    """, ADAPT_CAVE, ADAPT_CAVE + 0x100)
    return [
        (0x00421EF5, bytes.fromhex("8b8e88820200"), _s2jmp(0x00421EF5, ADAPT_CAVE, 6),
         "physics: rate = max(FPS, floor) - one frame-aligned step above the floor, 1/Hz steps below"),
        (ADAPT_CAVE, bytes(len(code)), code, f"adaptive cave ({len(code)} bytes)"),
        (ADAPT_EPS, bytes(4), struct.pack("<f", 1.0 - 2.0 ** -20), "1 - 2^-20"),
        (ADAPT_TOL, bytes(4), struct.pack("<f", 1.0 - 2.0 ** -10), "1 - 2^-10"),
    ]


try:
    PATCHES["adaptive"] = _adaptive()
except ImportError:
    pass


# ---- nightlock / darknight / headlights / hlcars: Stage 2 #9 (player 2026-10-05 .. 10-31) ----------
# Ported 1:1 from the LIVE prototypes the player tuned in game (re-tools/nightlock.py, nightlive.py,
# moonlive.py, hllive.py = headlights v15c, 2026-10-10; player 2026-10-31: "lets complete the lights
# first with the panel"). Same cave sources, same constants, same hook sites - only the addresses are
# fixed instead of VirtualAllocEx'ed, so they survive a game restart without Night Mode (live).bat.
#
# nightlock (eternal night, "make the game night only"): the time-of-day step 0x00426c90 computes
# phase = (timer ms + 500000) mod 2000000 (a day = 33.3 min) and loads it at 0x00426d00
# `mov [esp+8],edx; fild dword [esp+8]` (8 bytes). The cave loads a fixed phase instead; sun, moon,
# sky colours, stars and the night factor +0x1dc all follow from it. Value: the locked hour (0 =
# midnight, 12 = noon - phase = hour / 24 x 2,000,000).
NL_CAVE = S2_CODE + 0x1200                       # 0x02705200 .. 0x1230
NL_PHASE = S2_CODE + 0x1230                      # int phase + NL_DAY
NL_DAY = 2000000
NIGHTLOCK_DEFAULT = 0.0
NIGHTLOCK_RANGE = (0.0, 23.5)
NIGHTLOCK = NIGHTLOCK_DEFAULT


def set_nightlock(hour):
    global NIGHTLOCK
    lo, hi = NIGHTLOCK_RANGE
    if not lo <= float(hour) <= hi:
        raise ValueError(f"locked hour {hour} is outside {lo:g}..{hi:g}")
    NIGHTLOCK = float(hour)
    code = _s2asm(f"""
        mov edx, dword ptr [{NL_PHASE:#x}]
        sub edx, {NL_DAY}
        mov dword ptr [esp+8], edx
        fild dword ptr [esp+8]
        jmp 0x00426d08
    """, NL_CAVE, NL_PHASE)
    PATCHES["nightlock"] = [
        (0x00426D00, bytes.fromhex("89542408db442408"), _s2jmp(0x00426D00, NL_CAVE, 8),
         "time of day: a fixed phase instead of the clock"),
        (NL_CAVE, bytes(len(code)), code, f"nightlock cave ({len(code)} bytes)"),
        (NL_PHASE, bytes(4), struct.pack("<i", round(NIGHTLOCK / 24.0 * NL_DAY) % NL_DAY + NL_DAY),
         f"locked at {NIGHTLOCK:g} h (phase + one day, so midnight never reads as 'not installed')"),
    ]


# darknight (realistic dark full-moon night, player 2026-10-10: "make the night realistic dark with
# full moon" / "switch to the realistic moonlight color"): two hooks, both scaled by the game's own
# smooth night factor (sky +0x1dc = 0x0264832c), so the day is untouched.
#  - ambient: the time-of-day step ends by storing the ambient RGB (sky +0x1b8.., read only by the
#    light manager: D3D ambient, moonlight = ambient x moon intensity, fog colour). Hook its last store
#    0x00427190 `movss [esi+0x1c4],xmm6` (8 bytes): channel c *= 1 - night x (1 - K x tint_c).
#    tint (1.05, 1.0, 0.48) cancels the game's blue x2 night table -> warm grey, physical moonlight.
#  - moon: the light manager loads the moon intensity (+0x1c8) at 0x00405f9d `movss xmm0,[0x2648318]`
#    (8 bytes; the other read at 0x00406122 only enables the light): x (1 - night x (1 - DN_MOON)).
# Lamps, windows, glows and the headlights are emissive/separate and keep their brightness.
# Value: K = night brightness (live 0.22; 1 = stock brightness).
DN_AMB_CAVE = S2_CODE + 0x1240                   # 0x02705240 .. 0x12E0
DN_MOON_CAVE = S2_CODE + 0x12E0                  # .. 0x1320
DN_DATA = S2_CODE + 0x1320                       # 4f (1 - K tint_rgb, 1.0), 2f (1 - MOON, 1.0)
DN_TINT = (1.05, 1.0, 0.48)
DN_MOON = 2.2
DARKNIGHT_DEFAULT = 0.22
DARKNIGHT_RANGE = (0.05, 0.9)                    # 0.9 x 1.05 keeps red positive
DARKNIGHT = DARKNIGHT_DEFAULT


def set_darknight(k):
    global DARKNIGHT
    lo, hi = DARKNIGHT_RANGE
    if not lo <= float(k) <= hi:
        raise ValueError(f"night brightness {k} is outside {lo:g}..{hi:g}")
    DARKNIGHT = float(k)
    ch = ""
    for n, off in enumerate((0x1b8, 0x1bc, 0x1c0)):
        ch += f"""
        movss xmm0, dword ptr [esi+0x1dc]
        mulss xmm0, dword ptr [{DN_DATA + 4 * n:#x}]
        movss xmm1, dword ptr [{DN_DATA + 12:#x}]
        subss xmm1, xmm0
        movss xmm0, dword ptr [esi+{off:#x}]
        mulss xmm0, xmm1
        movss dword ptr [esi+{off:#x}], xmm0"""
    amb = _s2asm(f"""
        movss dword ptr [esi+0x1c4], xmm6{ch}
        jmp 0x00427198
    """, DN_AMB_CAVE, DN_MOON_CAVE)
    moon = _s2asm(f"""
        movss xmm1, dword ptr [0x0264832c]
        mulss xmm1, dword ptr [{DN_DATA + 16:#x}]
        movss xmm0, dword ptr [{DN_DATA + 20:#x}]
        subss xmm0, xmm1
        mulss xmm0, dword ptr [0x02648318]
        jmp 0x00405fa5
    """, DN_MOON_CAVE, DN_DATA)
    data = struct.pack("<4f", *(1.0 - DARKNIGHT * t for t in DN_TINT), 1.0) + struct.pack("<2f", 1.0 - DN_MOON, 1.0)
    PATCHES["darknight"] = [
        (0x00427190, bytes.fromhex("f30f11b6c4010000"), _s2jmp(0x00427190, DN_AMB_CAVE, 8),
         "time of day: night ambient scaled per channel (warm-grey moonlight)"),
        (0x00405F9D, bytes.fromhex("f30f100518836402"), _s2jmp(0x00405F9D, DN_MOON_CAVE, 8),
         f"light manager: moon intensity x{DN_MOON:g} at full night"),
        (DN_AMB_CAVE, bytes(len(amb)), amb, f"darknight ambient cave ({len(amb)} bytes)"),
        (DN_MOON_CAVE, bytes(len(moon)), moon, f"darknight moon cave ({len(moon)} bytes)"),
        (DN_DATA, bytes(len(data)), data, f"night brightness K {DARKNIGHT:g} x tint {DN_TINT}"),
    ]


# headlights (#9, "all cars' headlights light the world like street lamps do", v15c): see headlights.py
# for the design. Everything lives in a 6th PE section `.crhl` right after .crmod (1.1 MB: the effect
# text is 86 KB and the reflector cookie a 1 MB A8R8G8B8 DDS - .crmod's 64 KB cannot hold them), laid
# out exactly like hllive.py's VirtualAllocEx block:
#   +0x0000 main cave (hook 0x0043124c, end of the terrain draw: land, bridges, buildings)
#   +0x1000 reset cave (hook 0x0040c6a4 in the renderer's invalidate: release the effect before Reset)
#   +0x1800 car-body cave (hook 0x004217aa, between the body and the glass passes)
#   +0x2000 data block (headlights.DATA_LAYOUT; writable - the section is RWX)
#   +0x3000 late cave (hook 0x004217f0: lamp posts, loose objects, trees, rocks)
#   +0x4000 techHeadlights effect text (compiled by the game's 2004 D3DX on the first night frame, as a
#           SEPARATE effect - Panini's 32 KB buffer and the game's effect are not touched)
#   +0x20000 the cookie DDS (D3DXCreateTextureFromFileInMemoryEx, D3DPOOL_MANAGED)
# `hlsect` adds the section header (NumberOfSections 5 -> 6, SizeOfImage + HL_VSIZE): it edits the
# fields modsect wrote, so it is applied after it (apply's ORDER_FIRST) and `state` follows the stack.
# Value: brightness = the live gain slider (40). hlcars: how many nearest cars light the world (FPS).
HL_VA = MOD_VA + MOD_VSIZE                       # 0x02711000
HL_RAW = MOD_RAW + MOD_RSIZE                     # 0x001BC600: right after .crmod's stored bytes
HL_LOST, HL_BODY, HL_DATA, HL_LATE, HL_TEXT, HL_DDS = (HL_VA + o for o in (0x1000, 0x1800, 0x2000, 0x3000,
                                                                          0x4000, 0x20000))
HL_RSIZE = 0x120200                              # + the 1,048,704-byte cookie, file-aligned (asserted)
HL_VSIZE = 0x121000
IMG_SIZE_MOD = 0x02301000 + MOD_VSIZE            # SizeOfImage with .crmod
PATCHES["hlsect"] = [
    (0x0040011E, struct.pack("<H", 5), struct.pack("<H", 6), "NumberOfSections 5 -> 6"),
    (0x00400168, struct.pack("<I", IMG_SIZE_MOD), struct.pack("<I", IMG_SIZE_MOD + HL_VSIZE),
     "SizeOfImage + the headlights section"),
    (0x004002D8, bytes(40),
     struct.pack("<8sIIIIIIHHI", b".crhl", HL_VSIZE, HL_VA - 0x00400000, HL_RSIZE, HL_RAW,
                 0, 0, 0, 0, 0xE0000060),
     "section header #6 .crhl: code | data | execute | read | write"),
    (HL_VA + HL_RSIZE - 0x10, bytes(0x10), b"end of .crhl\0\0\0\0",
     "section end marker (the file grows to the full raw size)"),
]
HL_GAIN_DEFAULT = 40.0
HL_GAIN_RANGE = (5.0, 80.0)
HL_GAIN = HL_GAIN_DEFAULT
HL_CARS_DEFAULT = 8
HL_CARS_RANGE = (1, 16)
HL_CARS = HL_CARS_DEFAULT
_HL_CACHE = {}


def _hl_cookie():
    """The cookie DDS (1.3 s of numpy), cached on disk keyed by headlights.py's bytes."""
    import hashlib
    import headlights
    here = os.path.dirname(os.path.abspath(__file__))
    key = hashlib.sha256(open(os.path.join(here, "headlights.py"), "rb").read()).hexdigest()
    path = os.path.join(here, "hl_cookie_cache.dds")
    try:
        with open(path + ".key") as f:
            if f.read().strip() == key:
                return open(path, "rb").read()
    except OSError:
        pass
    dds = headlights.cookie_dds()
    with open(path, "wb") as f:
        f.write(dds)
    with open(path + ".key", "w") as f:
        f.write(key)
    return dds


def set_headlights(gain):
    global HL_GAIN
    import headlights as hl
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    lo, hi = HL_GAIN_RANGE
    if not lo <= float(gain) <= hi:
        raise ValueError(f"headlight brightness {gain} is outside {lo:g}..{hi:g}")
    HL_GAIN = float(gain)
    if "code" not in _HL_CACHE:
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        asm = lambda src, at: bytes(ks.asm(src, at)[0])
        text = hl.technique_text().encode("latin-1") + b"\0"
        dds = _hl_cookie()
        assert HL_TEXT + len(text) <= HL_DDS and HL_DDS + len(dds) <= HL_VA + HL_RSIZE - 0x10, "headlights payload"
        c = dict(main=asm(hl.cave_src(HL_DATA, "own", HL_TEXT, len(text) - 1, HL_DDS, len(dds)), HL_VA),
                 lost=asm(hl.lost_cave_src(HL_DATA), HL_LOST), body=asm(hl.body_cave_src(HL_DATA), HL_BODY),
                 late=asm(hl.late_cave_src(HL_DATA), HL_LATE), text=text, dds=dds)
        assert HL_VA + len(c["main"]) <= HL_LOST and HL_LOST + len(c["lost"]) <= HL_BODY
        assert HL_BODY + len(c["body"]) <= HL_DATA and HL_DATA + hl.DATA_LAYOUT["DATA_END"] <= HL_LATE
        assert HL_LATE + len(c["late"]) <= HL_TEXT
        _HL_CACHE["code"] = c
    c = _HL_CACHE["code"]
    data = hl.data_init(gain=HL_GAIN)                # MAXCARS = N_CARS (16); hlcars stacks on it
    mc = hl.DATA_LAYOUT["MAXCARS"]
    jmp = lambda frm, to, size: b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (size - 5)
    PATCHES["headlights"] = [
        (hl.HOOK, hl.HOOK_ORIG, jmp(hl.HOOK, HL_VA, 7),
         "terrain end: redraw land/bridges/buildings near lit cars with techHeadlights"),
        (hl.LOST_HOOK, hl.LOST_ORIG, jmp(hl.LOST_HOOK, HL_LOST, 5),
         "renderer invalidate: release the headlight effect before a device reset"),
        (hl.BODY_HOOK, hl.BODY_ORIG, jmp(hl.BODY_HOOK, HL_BODY, 5), "car bodies lit by other cars' headlights"),
        (hl.LATE_HOOK, hl.LATE_ORIG, jmp(hl.LATE_HOOK, HL_LATE, 5),
         "late draws: lamp posts, loose objects, trees, rocks lit"),
        (HL_VA, bytes(len(c["main"])), c["main"], f"headlights main cave ({len(c['main'])} bytes)"),
        (HL_LOST, bytes(len(c["lost"])), c["lost"], f"reset cave ({len(c['lost'])} bytes)"),
        (HL_BODY, bytes(len(c["body"])), c["body"], f"car-body cave ({len(c['body'])} bytes)"),
        (HL_DATA, bytes(mc), data[:mc], f"headlight data (brightness {HL_GAIN:g})"),
        (HL_DATA + mc, bytes(4), data[mc:mc + 4], f"lit cars {hl.N_CARS}"),
        (HL_DATA + mc + 4, bytes(len(data) - mc - 4), data[mc + 4:], "headlight data (rest)"),
        (HL_LATE, bytes(len(c["late"])), c["late"], f"late cave ({len(c['late'])} bytes)"),
        (HL_TEXT, bytes(len(c["text"])), c["text"], f"techHeadlights effect text ({len(c['text'])} bytes)"),
        (HL_DDS, bytes(len(c["dds"])), c["dds"], f"reflector beam cookie DDS ({len(c['dds'])} bytes)"),
    ]


def set_hlcars(n):
    global HL_CARS
    import headlights as hl
    lo, hi = HL_CARS_RANGE
    if not (lo <= float(n) <= hi and float(n) == int(float(n))):
        raise ValueError(f"lit cars {n} must be a whole number {lo}..{hi}")
    HL_CARS = int(float(n))
    PATCHES["hlcars"] = [
        (HL_DATA + hl.DATA_LAYOUT["MAXCARS"], struct.pack("<I", hl.N_CARS), struct.pack("<I", HL_CARS),
         f"headlights: only the {HL_CARS} nearest cars light the world"),
    ]


set_nightlock(_saved("nightlock_hour", NIGHTLOCK_DEFAULT))
set_darknight(_saved("darknight_k", DARKNIGHT_DEFAULT))
try:
    set_headlights(_saved("headlight_gain", HL_GAIN_DEFAULT))
    set_hlcars(_saved("headlight_cars", HL_CARS_DEFAULT))
except ImportError:
    pass


# ---- manual: a real manual gearbox for YOUR car (Stage 2 #11, player 2026-10-31: "research and do the
# real drivetrain thing, starts with manual. Use the simulator") ---------------------------------------
# Stock drivetrain (0x004345e0, every car, every physics step): ONE engine force F (+0x7f80) ramps towards
# the max force (+0x7f84) while the throttle (+0x7f8c, the player's Up key = 2000) is held, and the force
# APPLIED to the driven wheels is F x (1 + max(0, 50 - v) x accel/40) - a launch boost of 3.5x at 0 km/h
# fading to 1x at 50 km/h. That is an automatic/CVT in disguise. The engine SOUND fakes gears too: a new
# "gear" every 20 km/h (0x00434bfc). Nothing models RPM.
# With this, for the player's car only ([0x012d0c88]; traffic/police/racers stay stock):
#  - gears N, 1..MANUAL_GEARS, shifted with X (up) and Z (down). Both keys reach the window procedure
#    0x00456610 but do nothing in normal play (Z only lowers the editor fly-camera, view 0, which the C key
#    skips unless [Misc] Editor mode=1; X is handled nowhere); a hook on its keydown path (the binding call at
#    0x0045677e) counts presses (auto-repeat skipped via lParam bit 30, only while the game runs:
#    [0x00590448]). The drive cave consumes one up/down per step. Starts in 1st.
#  - RPM r = |v| / (Vd x GT[g]), r = 1 at the redline; Vd = the car's design speed = (base force +0x7f88 +
#    200 x upgrade level +0x7fdc) x 0.06 - the same 0.06 the game uses for the engine sound's "max speed"
#    (+0x7f74), so it ignores damage (gears do not get shorter when the car is hurt).
#  - drive force = F x m_g x tc(r) / tc(r_top): m_g = 1 + accel x 1.25 (GT_top/GT_g - 1)/(GT_top/GT_1 - 1)
#    (1st gear = exactly the stock launch boost 1 + 50 accel/40, top gear = 1), torque curve tc = 1 -
#    k (r - 0.62)^2, k 1.42 below the peak (0.69 at idle) and 0.6 above (0.91 at the redline), normalised so
#    TOP gear at the design speed pushes exactly like stock (r_top = 1/1.5, right at the peak) -> same top
#    speed; top gear stays within 3% of stock up to 1.3x the design speed. Engine POWER limit on top:
#    force <= F x max(1, Vd / |v|) - constant power below the design speed (the gears' mid-range pull),
#    never more than stock at or above it (no gear can beat the stock top speed). 1st gear launches on a slipping clutch with the engine at 40% revs (MAN_SLIP: near
#    peak torque, ~4% above the stock launch); 2nd+ bog down below idle (x max(0.25, r/0.15)). Rev limiter: no force at r >= 1. Shifting: no force for MAN_SHIFT_TIME.
#  - off the throttle in gear above 3 km/h: engine braking -EB x Fmax x m_g x (r - idle).
#  - clutch: hold Shift (the game's own Shift-held flag 0x012d0c0c, set/cleared by the window procedure
#    0x0045690c / 0x00456b32; it only does something in Editor mode) = engine disconnected, like neutral: no
#    drive force, no engine braking, and the engine free-revs - RPM eases toward the limiter (NREV) with the
#    throttle, toward idle without, at FREERATE /s. Let go and the wheels set the RPM again.
#  - clutch dump: the engine RPM ENG is kept apart from the wheel RPM. Let the clutch go with ENG above the
#    wheels and the clutch slips: ENG falls to the wheel RPM at DUMPRATE /s (flywheel inertia) and the
#    stored spin adds drive force x (1 + KICK x (ENG - RPM)) on top of the power limit (~2x for a dump
#    from the limiter at a standstill) - enough to break traction (no wheel-speed model in the game, so it
#    shows as sliding, not spinning wheels). The needle and the sound show max(RPM, ENG). A gear change
#    resets ENG, so only the Shift clutch builds a kick - plain shifts are unchanged.
#  - power: the engine-power cap is blended between the stock force at that speed (F x (1 + max(0, 50 - v) x
#    accel/40), the game's own launch boost, 0x004348a6) and the realistic constant-power cap F x max(1, Vd/v):
#    cap = stock + POWER x (realistic - stock). POWER = 1 (100 %, realistic) unless the `manpower` extra sets
#    it; at 0 % the best gear matches the stock car at every speed and the others are weaker.
#  - wheels off the ground: c = driven wheels touching / driven wheels, from Bullet's
#    btWheelInfo.m_raycastInfo.m_isInContact = byte +0x54 of each 0x118-byte wheel in the array at
#    [vehicle +0xa4] (rayCast 0x00538760 clears it, sets it on a hit at 0x00538b4b; front wheels 0/1 driven if
#    car +0x7fb0, rear 2/3 if +0x7fb4). c < 1 (airborne, or on two wheels): no load on the engine, so ENG
#    eases (FREERATE) toward c x wheel RPM + (1 - c) x free revs (limiter with the gas, idle without) and no
#    clutch kick; touch down with ENG above the wheels and the landing gets the clutch-dump kick.
#  - reverse is a GEAR: R below N (Z from N, only below REV_OK km/h; X from R back to N). In R the throttle
#    drives backwards through 1st gear's ratio/torque/clutch/limiter (GT/MM index -1 = the slots just below
#    the tables). The Down arrow is a BRAKE only: your car's F is clamped >= 0 at the top of the cave (the
#    stock pedal code at 0x00434747/0x0043479b runs F negative = the automatic reverse below 1 km/h at
#    0x004348e1), and with the pedal down the applied force is 0 -> the stock brake (setBrake 0x00538dd0,
#    ramp +0x7f90) keeps working, never switched off for "reversing". Neutral: no drive force.
#  - HUD: the gear (N, 1-6, R) under the speedometer's speed number, drawn with
#    the speedometer's own font calls (0x004702a0 width, 0x00470260 draw; hook 0x00468265 right after the
#    speed number).
#  - engine sound: the pitch load comes from r (idle = stock idle pitch, redline = 1.9x), on and off the
#    throttle, so upshifts drop the pitch and engine braking keeps it up (hook 0x00434d5a).
#  - instant throttle: the stock engine force F (+0x7f80) creeps up over ~2.5 s while the throttle is held
#    (0x00434648: dF = accel x throttle x dt / (1 + 0.004 F)). In gear with the throttle down, your car's F is
#    set straight to the max force +0x7f84 (the gearbox, torque curve and clutch now shape the pull).
#  - tachometer: the speedometer's small needle drew 0.8 x F / max force (0x00468036..0x00468072, 270 deg x
#    that) - the creeping throttle. It now shows the RPM: idle 0.15 .. redline 1.0 at 0.8 x 270 deg (where
#    the old needle stopped at full throttle), smoothed (TACH_RATE /s), and BLINKS red from TACH_SHIFT up
#    (the shift light; hook 0x00468119 = the needle's colour push).
MAN_CAVE = S2_CODE + 0x1D00                      # 0x02705D00 .. 0x2100 drive (+0x1600..0x1900: its old home,
                                                 # outgrown 10-31, now unused) (S2 +0x1400..0x1600 left free:
MAN_SND = S2_CODE + 0x1900                       # .. 0x1980 sound           the live night tools write there
MAN_KEY = S2_CODE + 0x1980                       # .. 0x1A00 keys            if run on a build with darknight)
MAN_DATA = S2_CODE + 0x1A00                      # .. 0x1B00
MAN_HUD = S2_CODE + 0x1B00                       # .. 0x1C00 gear readout
MAN_HUD_X, MAN_HUD_Y = 711.0, 582.0              # virtual 800x600: the speedometer dial is (621,431)-(801,601), its
MAN_HUD_SCALE = 0.5                              # needle pivots at (711,516) and sweeps 270 deg; the speed number is
MAN_HUD_COLOR = 0xFFFFFFFF                       # centred at (711,565) - the gear goes under it, in the free sector
MAN_KEY_UP, MAN_KEY_DOWN = 0x58, 0x5A            # X, Z
MAN_CLUTCH_FLAG = 0x012D0C0C                     # the game's "Shift held" dword
MAN_GEARS_DEFAULT = 5
MAN_GEARS_RANGE = (4, 6)
MAN_GEARS = MAN_GEARS_DEFAULT
MAN_TABLES = {4: (0.40, 0.68, 1.02, 1.50), 5: (0.33, 0.55, 0.80, 1.10, 1.50),
              6: (0.30, 0.47, 0.66, 0.88, 1.15, 1.50)}     # redline speed / design speed per gear; top gear
                                                            # redline 1.5x: the limiter never caps a car below
                                                            # stock even if its real top speed beats the design
MAN_IDLE = 0.15
MAN_SLIP = 0.40                                  # 1st gear launch: the clutch slips with the engine at 40% revs
MAN_TCK, MAN_TCKHI, MAN_TCP = 1.42, 0.6, 0.62    # torque 1 - k (r - peak)^2: steep below the peak, gentle above
MAN_EB = 0.06
MAN_SHIFT_TIME = 0.25
MAN_KICK = 1.7                                   # clutch dump: force x (1 + KICK x rev surplus)
MAN_DUMPRATE = 4.0                               # the slipping clutch pulls the engine to the wheels at 4 /s
MAN_PITCH_TOP = 1.2                              # load at the redline (pitch 1 + 0.75 x load = 1.9x)
MAN_TACH = S2_CODE + 0x1C00                      # .. 0x1CC0 tachometer needle angle
MAN_TACH_COL = S2_CODE + 0x1CC0                  # .. 0x1CD0 its colour push
MAN_TACH_DATA = S2_CODE + 0x1CD0                 # .. 0x1D00
TACH_RATE = 15.0                                 # needle follows the RPM with a ~70 ms lag (no jitter, quick drops)
TACH_SHIFT = 0.88                                # shift light from 88% revs
TACH_BLINK = 0.125                               # 8 blinks a second
TACH_COLOR, TACH_COLOR_SHIFT = 0xFF808000, 0xFFFF2020   # stock olive / shift-light red
TD = {n: MAN_TACH_DATA + 4 * i for i, n in enumerate(
    ["TACH", "BLINKT", "COL", "RATE", "SHIFTR", "BLINKP", "BLINKH", "TACHMAX", "TACHANG", "COLN", "COLR"])}
_MAN_FIELDS = ["GEAR", "UP", "DN", "SHIFT_T", "RPM", "NGEARS", "R0", "TCK", "TCP", "TCN", "EB", "SHIFT_TIME",
               "K006", "K200", "TCKHI", "ONE", "VMIN_EB", "LOADK", "ZERO", "RLIM_EB", "ABSMASK", "NREV", "LOADMAX",
               "BOGMIN", "INVR0", "RSLIP", "FREERATE", "ENG", "KICK", "DUMPRATE", "SIGNMASK"]
assert 4 * len(_MAN_FIELDS) <= 0x7C              # +0x7C = GT[-1] (R), +0x9C = MM[-1]
MAN_REV_OK = 5.0                                 # km/h: N -> R only this slow
MAN_AIR = S2_CODE + 0x2100                       # .. 0x2240 wheel-contact / engine-load subroutine
MAN_KICKSUB = S2_CODE + 0x2240                   # .. 0x2280 clutch-kick multiplier subroutine
MAN_POWER = S2_CODE + 0x2280                     # float: its own edit, so `manpower` can stack on it
MAN_POWER_DEFAULT = 100
MAN_POWER_RANGE = (0, 100)
MAN_POWER_PCT = MAN_POWER_DEFAULT
BT_WHEELS, BT_WHEEL_SIZE, BT_IN_CONTACT = 0xA4, 0x118, 0x54   # btRaycastVehicle / btWheelInfo
MD = {n: MAN_DATA + 4 * i for i, n in enumerate(_MAN_FIELDS)}
MD["GT"] = MAN_DATA + 0x80                       # GT[g], g = 1..6 at +4g
MD["MM"] = MAN_DATA + 0xA0                       # m_g = 1 + accel x MM_g, g = 1..6 at +4g
MD.update(HUD_X=MAN_DATA + 0xC0, HUD_Y=MAN_DATA + 0xC4, HUD_SCALE=MAN_DATA + 0xC8, HUD_COLOR=MAN_DATA + 0xCC,
          REVSPD=MAN_DATA + 0xD0, HALFH=MAN_DATA + 0xD4, GEARCHARS=MAN_DATA + 0xD8, GEARTXT=MAN_DATA + 0xE0,
          REVOK=MAN_DATA + 0xE4, KC=MAN_DATA + 0xE8, K50=MAN_DATA + 0xEC, INV40=MAN_DATA + 0xF0)


def set_manual(gears):
    global MAN_GEARS
    lo, hi = MAN_GEARS_RANGE
    if not (lo <= float(gears) <= hi and float(gears) == int(float(gears))):
        raise ValueError(f"gears {gears} must be a whole number {lo}..{hi}")
    MAN_GEARS = int(float(gears))
    gt = MAN_TABLES[MAN_GEARS]
    tc = lambda r: 1.0 - (MAN_TCK if r < MAN_TCP else MAN_TCKHI) * (r - MAN_TCP) ** 2
    vals = dict(GEAR=("<i", 1), UP=("<i", 0), DN=("<i", 0), SHIFT_T=("<f", 0.0), RPM=("<f", MAN_IDLE),
                NGEARS=("<i", MAN_GEARS), R0=("<f", MAN_IDLE), TCK=("<f", MAN_TCK), TCP=("<f", MAN_TCP),
                TCN=("<f", 1.0 / tc(1.0 / gt[-1])), EB=("<f", MAN_EB), SHIFT_TIME=("<f", MAN_SHIFT_TIME),
                K006=("<f", 0.06), K200=("<f", 200.0), TCKHI=("<f", MAN_TCKHI), ONE=("<f", 1.0), VMIN_EB=("<f", 3.0),
                LOADK=("<f", MAN_PITCH_TOP / (1.0 - MAN_IDLE)), ZERO=("<f", 0.0), RLIM_EB=("<f", 1.15),
                ABSMASK=("<I", 0x7FFFFFFF), NREV=("<f", 1.0), LOADMAX=("<f", MAN_PITCH_TOP), BOGMIN=("<f", 0.25),
                INVR0=("<f", 1.0 / MAN_IDLE), RSLIP=("<f", MAN_SLIP), FREERATE=("<f", 2.5),
                ENG=("<f", MAN_IDLE), KICK=("<f", MAN_KICK), DUMPRATE=("<f", MAN_DUMPRATE),
                SIGNMASK=("<I", 0x80000000), REVOK=("<f", MAN_REV_OK), KC=("<f", 1.0), K50=("<f", 50.0),
                INV40=("<f", 1.0 / 40.0))
    data = bytearray(0x100)
    for n, (fmt, v) in vals.items():
        struct.pack_into(fmt, data, MD[n] - MAN_DATA, v)
    struct.pack_into("<ffffff8s", data, MD["HUD_X"] - MAN_DATA, MAN_HUD_X, MAN_HUD_Y, MAN_HUD_SCALE, 0.0,
                     -1.0, 0.5, b"N123456R")
    struct.pack_into("<I", data, MD["HUD_COLOR"] - MAN_DATA, MAN_HUD_COLOR)
    for g, f in enumerate(gt, 1):
        struct.pack_into("<f", data, MD["GT"] - MAN_DATA + 4 * g, f)
        # m_g = 1 + accel x MM_g: 1st = the stock launch boost 1 + 50 accel/40, top = 1, between by ratio
        struct.pack_into("<f", data, MD["MM"] - MAN_DATA + 4 * g, 1.25 * (gt[-1] / f - 1.0) / (gt[-1] / gt[0] - 1.0))
    struct.pack_into("<f", data, MD["GT"] - MAN_DATA - 4, gt[0])       # R = 1st gear's ratio, backwards
    struct.pack_into("<f", data, MD["MM"] - MAN_DATA - 4, 1.25)
    M = {k: f"{v:#x}" for k, v in MD.items()}
    force_m = f"""
        movss xmm2, dword ptr [esi+0x7f78]
        mulss xmm2, dword ptr [eax*4+{M['MM']}]
        addss xmm2, xmm6"""
    drive = _s2asm(f"""
        movss xmm4, dword ptr [esi+0x7f80]
        cmp esi, dword ptr [0x012d0c88]
        jne stock
        maxss xmm4, xmm1
        movss dword ptr [esi+0x7f80], xmm4
        mov eax, dword ptr [{M['GEAR']}]
        cmp dword ptr [{M['UP']}], 0
        je noup
        dec dword ptr [{M['UP']}]
        cmp eax, dword ptr [{M['NGEARS']}]
        jge noup
        inc eax
        mov dword ptr [{M['ENG']}], 0
        movss xmm0, dword ptr [{M['SHIFT_TIME']}]
        movss dword ptr [{M['SHIFT_T']}], xmm0
    noup:
        cmp dword ptr [{M['DN']}], 0
        je nodn
        dec dword ptr [{M['DN']}]
        test eax, eax
        jg dnok
        jl nodn
        movss xmm0, dword ptr [esi+0x7f70]
        comiss xmm0, dword ptr [{M['REVOK']}]
        ja nodn
    dnok:
        dec eax
        mov dword ptr [{M['ENG']}], 0
        movss xmm0, dword ptr [{M['SHIFT_TIME']}]
        movss dword ptr [{M['SHIFT_T']}], xmm0
    nodn:
        mov dword ptr [{M['GEAR']}], eax
        movss xmm0, dword ptr [{M['SHIFT_T']}]
        subss xmm0, dword ptr [0x012d04a8]
        maxss xmm0, xmm1
        movss dword ptr [{M['SHIFT_T']}], xmm0
        cmp dword ptr [{MAN_CLUTCH_FLAG:#x}], 0
        jne neutral
        test eax, eax
        je neutral
        cvtsi2ss xmm2, dword ptr [esi+0x7fdc]
        mulss xmm2, dword ptr [{M['K200']}]
        addss xmm2, dword ptr [esi+0x7f88]
        mulss xmm2, dword ptr [{M['K006']}]
        mulss xmm2, dword ptr [eax*4+{M['GT']}]
        movss xmm3, dword ptr [esi+0x7f70]
        movss xmm7, dword ptr [{M['ABSMASK']}]
        andps xmm3, xmm7
        divss xmm3, xmm2
        movss dword ptr [{M['RPM']}], xmm3
        call {MAN_AIR:#x}
        movss xmm0, dword ptr [esi+0x7f94]
        comiss xmm0, xmm1
        ja zero
        comiss xmm5, xmm1
        jbe coast
        movss xmm4, dword ptr [esi+0x7f84]
        movss dword ptr [esi+0x7f80], xmm4
        movss xmm0, dword ptr [{M['SHIFT_T']}]
        comiss xmm0, xmm1
        ja zero
        comiss xmm3, xmm6
        jae zero
        movaps xmm7, xmm6
        cmp eax, 1
        je slip1
        cmp eax, -1
        jne bogchk
    slip1:
        maxss xmm3, dword ptr [{M['RSLIP']}]
        movss dword ptr [{M['RPM']}], xmm3
        jmp nobog
    bogchk:
        movss xmm0, dword ptr [{M['R0']}]
        comiss xmm3, xmm0
        jae nobog
        movaps xmm7, xmm3
        mulss xmm7, dword ptr [{M['INVR0']}]
        maxss xmm7, dword ptr [{M['BOGMIN']}]
    nobog:
        maxss xmm3, dword ptr [{M['R0']}]
        subss xmm3, dword ptr [{M['TCP']}]
        movss xmm2, dword ptr [{M['TCKHI']}]
        comiss xmm3, xmm1
        jae khi
        movss xmm2, dword ptr [{M['TCK']}]
    khi:
        mulss xmm3, xmm3
        mulss xmm3, xmm2
        movaps xmm0, xmm6
        subss xmm0, xmm3
        mulss xmm0, dword ptr [{M['TCN']}]
        mulss xmm0, xmm7{force_m}
        mulss xmm0, xmm2
        mulss xmm0, xmm4
        cvtsi2ss xmm2, dword ptr [esi+0x7fdc]
        mulss xmm2, dword ptr [{M['K200']}]
        addss xmm2, dword ptr [esi+0x7f88]
        mulss xmm2, dword ptr [{M['K006']}]
        movss xmm3, dword ptr [esi+0x7f70]
        movss xmm7, dword ptr [{M['ABSMASK']}]
        andps xmm3, xmm7
        maxss xmm3, xmm6
        divss xmm2, xmm3
        maxss xmm2, xmm6
        mulss xmm2, xmm4
        movss xmm7, dword ptr [{M['K50']}]
        subss xmm7, xmm3
        maxss xmm7, xmm1
        mulss xmm7, dword ptr [esi+0x7f78]
        mulss xmm7, dword ptr [{M['INV40']}]
        addss xmm7, xmm6
        mulss xmm7, xmm4
        subss xmm2, xmm7
        mulss xmm2, dword ptr [{MAN_POWER:#x}]
        addss xmm2, xmm7
        minss xmm0, xmm2
        call {MAN_KICKSUB:#x}
        mulss xmm0, xmm2
        test eax, eax
        jns dpos
        movss xmm7, dword ptr [{M['SIGNMASK']}]
        xorps xmm0, xmm7
    dpos:
        movss dword ptr [esp+4], xmm0
        jmp 0x004348e1
    coast:
        movss xmm0, dword ptr [{M['SHIFT_T']}]
        comiss xmm0, xmm1
        ja zero
        movss xmm0, dword ptr [esi+0x7f70]
        movss xmm7, dword ptr [{M['SIGNMASK']}]
        test eax, eax
        jns cdir
        xorps xmm0, xmm7
    cdir:
        comiss xmm0, dword ptr [{M['VMIN_EB']}]
        jbe zero
        minss xmm3, dword ptr [{M['RLIM_EB']}]
        subss xmm3, dword ptr [{M['R0']}]
        maxss xmm3, xmm1
        mulss xmm3, dword ptr [esi+0x7f84]
        mulss xmm3, dword ptr [{M['EB']}]{force_m}
        mulss xmm3, xmm2
        movaps xmm0, xmm1
        subss xmm0, xmm3
        test eax, eax
        jns cpos
        xorps xmm0, xmm7
    cpos:
        movss dword ptr [esp+4], xmm0
        jmp 0x004348e1
    neutral:
        movss xmm3, dword ptr [{M['R0']}]
        comiss xmm5, xmm1
        jbe nrev
        movss xmm3, dword ptr [{M['NREV']}]
    nrev:
        movss xmm0, dword ptr [{M['RPM']}]
        maxss xmm0, dword ptr [{M['ENG']}]
        subss xmm3, xmm0
        movss xmm2, dword ptr [0x012d04a8]
        mulss xmm2, dword ptr [{M['FREERATE']}]
        minss xmm2, dword ptr [{M['ONE']}]
        mulss xmm3, xmm2
        addss xmm3, xmm0
        movss dword ptr [{M['RPM']}], xmm3
        movss dword ptr [{M['ENG']}], xmm3
    zero:
        movss dword ptr [esp+4], xmm1
        jmp 0x004348e1
    stock:
        jmp 0x0043484c
    """, MAN_CAVE, MAN_CAVE + 0x400)
    snd = _s2asm(f"""
        cmp esi, dword ptr [0x012d0c88]
        jne sstock
        movss xmm0, dword ptr [{M['RPM']}]
        maxss xmm0, dword ptr [{M['ENG']}]
        subss xmm0, dword ptr [{M['R0']}]
        maxss xmm0, dword ptr [{M['ZERO']}]
        mulss xmm0, dword ptr [{M['LOADK']}]
        minss xmm0, dword ptr [{M['LOADMAX']}]
        movss dword ptr [esp+4], xmm0
        movaps xmm2, xmm0
        minss xmm2, dword ptr [{M['ONE']}]
    sstock:
        fld dword ptr [esp+4]
        mov edx, dword ptr [ecx+0x114]
        jmp 0x00434d64
    """, MAN_SND, MAN_KEY)
    key = _s2asm(f"""
        call 0x00454a80
        cmp dword ptr [0x00590448], 0
        je kout
        test dword ptr [esp+0x28], 0x40000000
        jne kout
        cmp ebx, {MAN_KEY_UP:#x}
        jne kdn
        inc dword ptr [{M['UP']}]
        jmp kout
    kdn:
        cmp ebx, {MAN_KEY_DOWN:#x}
        jne kout
        inc dword ptr [{M['DN']}]
    kout:
        jmp 0x00456783
    """, MAN_KEY, MAN_DATA)
    hud = _s2asm(f"""
        pushad
        mov eax, dword ptr [{M['GEAR']}]
        test eax, eax
        jns fwd
        mov eax, 7
    fwd:
        movzx ecx, byte ptr [eax+{M['GEARCHARS']}]
        mov dword ptr [{M['GEARTXT']}], ecx
        push 1
        push dword ptr [{M['HUD_SCALE']}]
        push {M['GEARTXT']}
        mov ecx, ebx
        call 0x004702a0
        fmul dword ptr [{M['HALFH']}]
        fsubr dword ptr [{M['HUD_X']}]
        push 1
        push dword ptr [{M['HUD_SCALE']}]
        push dword ptr [{M['HUD_COLOR']}]
        push {M['GEARTXT']}
        push dword ptr [{M['HUD_Y']}]
        sub esp, 4
        fstp dword ptr [esp]
        mov ecx, ebx
        call 0x00470260
        fstp st(0)
        popad
        mov eax, dword ptr [0x012d0c88]
        jmp 0x0046826a
    """, MAN_HUD, MAN_HUD + 0x100)
    air = _s2asm(f"""
        push eax
        push ebx
        push ecx
        push edx
        mov ebx, dword ptr [esi+0x8024]
        mov ebx, dword ptr [ebx+{BT_WHEELS:#x}]
        xor ecx, ecx
        xor edx, edx
        cmp dword ptr [esi+0x7fb0], 0
        je anofront
        add ecx, 2
        movzx eax, byte ptr [ebx+{BT_IN_CONTACT:#x}]
        add edx, eax
        movzx eax, byte ptr [ebx+{BT_WHEEL_SIZE + BT_IN_CONTACT:#x}]
        add edx, eax
    anofront:
        cmp dword ptr [esi+0x7fb4], 0
        je anorear
        add ecx, 2
        movzx eax, byte ptr [ebx+{2 * BT_WHEEL_SIZE + BT_IN_CONTACT:#x}]
        add edx, eax
        movzx eax, byte ptr [ebx+{3 * BT_WHEEL_SIZE + BT_IN_CONTACT:#x}]
        add edx, eax
    anorear:
        movaps xmm7, xmm6
        test ecx, ecx
        je akc
        cvtsi2ss xmm7, edx
        cvtsi2ss xmm0, ecx
        divss xmm7, xmm0
    akc:
        movss dword ptr [{M['KC']}], xmm7
        pop edx
        pop ecx
        pop ebx
        pop eax
        comiss xmm7, xmm6
        jae aground
        movss xmm0, dword ptr [{M['R0']}]
        comiss xmm5, xmm1
        jbe afree
        movss xmm0, dword ptr [{M['NREV']}]
    afree:
        movaps xmm2, xmm6
        subss xmm2, xmm7
        mulss xmm0, xmm2
        movaps xmm2, xmm3
        mulss xmm2, xmm7
        addss xmm0, xmm2
        movss xmm2, dword ptr [{M['ENG']}]
        subss xmm0, xmm2
        movss xmm7, dword ptr [0x012d04a8]
        mulss xmm7, dword ptr [{M['FREERATE']}]
        minss xmm7, dword ptr [{M['ONE']}]
        mulss xmm0, xmm7
        addss xmm0, xmm2
        movss dword ptr [{M['ENG']}], xmm0
        ret
    aground:
        movss xmm0, dword ptr [{M['ENG']}]
        comiss xmm0, xmm3
        jbe esync
        movaps xmm2, xmm0
        subss xmm2, xmm3
        movss xmm7, dword ptr [0x012d04a8]
        mulss xmm7, dword ptr [{M['DUMPRATE']}]
        minss xmm7, dword ptr [{M['ONE']}]
        mulss xmm2, xmm7
        subss xmm0, xmm2
        movss dword ptr [{M['ENG']}], xmm0
        ret
    esync:
        movss dword ptr [{M['ENG']}], xmm3
        ret
    """, MAN_AIR, MAN_KICKSUB)
    kicksub = _s2asm(f"""
        movaps xmm2, xmm6
        movss xmm7, dword ptr [{M['KC']}]
        comiss xmm7, xmm6
        jb kret
        movss xmm2, dword ptr [{M['ENG']}]
        subss xmm2, dword ptr [{M['RPM']}]
        maxss xmm2, xmm1
        mulss xmm2, dword ptr [{M['KICK']}]
        addss xmm2, xmm6
    kret:
        ret
    """, MAN_KICKSUB, MAN_KICKSUB + 0x40)
    T = {k: f"{v:#x}" for k, v in TD.items()}
    tach = _s2asm(f"""
        movss xmm0, dword ptr [{M['RPM']}]
        maxss xmm0, dword ptr [{M['ENG']}]
        maxss xmm0, dword ptr [{M['R0']}]
        movss xmm1, dword ptr [{T['TACH']}]
        subss xmm0, xmm1
        movss xmm2, dword ptr [0x012d04a8]
        mulss xmm2, dword ptr [{T['RATE']}]
        minss xmm2, dword ptr [{M['ONE']}]
        mulss xmm0, xmm2
        addss xmm0, xmm1
        movss dword ptr [{T['TACH']}], xmm0
        mov ecx, dword ptr [{T['COLN']}]
        xorps xmm1, xmm1
        comiss xmm0, dword ptr [{T['SHIFTR']}]
        jb tset
        movss xmm1, dword ptr [{T['BLINKT']}]
        addss xmm1, dword ptr [0x012d04a8]
        comiss xmm1, dword ptr [{T['BLINKP']}]
        jb tph
        subss xmm1, dword ptr [{T['BLINKP']}]
    tph:
        comiss xmm1, dword ptr [{T['BLINKH']}]
        jae tset
        mov ecx, dword ptr [{T['COLR']}]
    tset:
        movss dword ptr [{T['BLINKT']}], xmm1
        mov dword ptr [{T['COL']}], ecx
        minss xmm0, dword ptr [{T['TACHMAX']}]
        maxss xmm0, dword ptr [{M['ZERO']}]
        mulss xmm0, dword ptr [{T['TACHANG']}]
        push ecx
        jmp 0x0046807a
    """, MAN_TACH, MAN_TACH_COL)
    tcol = _s2asm(f"""
        push dword ptr [{T['COL']}]
        jmp 0x0046811e
    """, MAN_TACH_COL, MAN_TACH_DATA)
    tdata = bytearray(len(TD) * 4)
    struct.pack_into("<ffIffffffII", tdata, 0, MAN_IDLE, 0.0, TACH_COLOR, TACH_RATE, TACH_SHIFT, TACH_BLINK,
                     TACH_BLINK / 2, 1.1, 0.8 * 4.71238898, TACH_COLOR, TACH_COLOR_SHIFT)
    PATCHES["manual"] = [
        (0x00434844, bytes.fromhex("f30f10a6807f0000"), _s2jmp(0x00434844, MAN_CAVE, 8),
         f"drive: your car through a {MAN_GEARS}-speed manual gearbox (RPM, torque curve, limiter, engine braking)"),
        (0x00434D5A, bytes.fromhex("d94424048b9114010000"), _s2jmp(0x00434D5A, MAN_SND, 10),
         "engine sound: your car's pitch follows the real RPM"),
        (0x0045677E, bytes.fromhex("e8fde2ffff"), _s2jmp(0x0045677E, MAN_KEY, 5),
         "keys: X shifts up, Z shifts down (hold Shift = clutch)"),
        (MAN_CAVE, bytes(len(drive)), drive, f"manual drive cave ({len(drive)} bytes)"),
        (MAN_SND, bytes(len(snd)), snd, f"manual sound cave ({len(snd)} bytes)"),
        (MAN_KEY, bytes(len(key)), key, f"manual key cave ({len(key)} bytes)"),
        (0x00468265, bytes.fromhex("a1880c2d01"), _s2jmp(0x00468265, MAN_HUD, 5),
         "speedometer: the gear (N, 1..6, R) under the speed number"),
        (MAN_HUD, bytes(len(hud)), hud, f"manual HUD cave ({len(hud)} bytes)"),
        (0x00468036, bytes.fromhex("f30f1080807f0000"), _s2jmp(0x00468036, MAN_TACH, 8),
         "speedometer: the small needle is a tachometer (RPM, not the creeping throttle)"),
        (0x00468119, bytes.fromhex("68008080ff"), _s2jmp(0x00468119, MAN_TACH_COL, 5),
         f"speedometer: the small needle blinks red from {TACH_SHIFT:.0%} revs (shift light)"),
        (MAN_TACH, bytes(len(tach)), tach, f"tachometer cave ({len(tach)} bytes)"),
        (MAN_TACH_COL, bytes(len(tcol)), tcol, f"shift-light colour cave ({len(tcol)} bytes)"),
        (MAN_TACH_DATA, bytes(len(tdata)), bytes(tdata), "tachometer data"),
        (MAN_AIR, bytes(len(air)), air, f"wheel-contact / engine-load subroutine ({len(air)} bytes)"),
        (MAN_KICKSUB, bytes(len(kicksub)), kicksub, f"clutch-kick subroutine ({len(kicksub)} bytes)"),
        (MAN_POWER, bytes(4), struct.pack("<f", 1.0), "engine power 100 % (realistic)"),
        (MAN_DATA, bytes(len(data)), bytes(data), f"gearbox: {MAN_GEARS} gears {gt}, idle {MAN_IDLE}"),
    ]


set_manual(_saved("manual_gears", MAN_GEARS_DEFAULT))


def set_manpower(pct):
    global MAN_POWER_PCT
    lo, hi = MAN_POWER_RANGE
    if not lo <= float(pct) <= hi:
        raise ValueError(f"power {pct} must be {lo}..{hi} %")
    MAN_POWER_PCT = float(pct)
    PATCHES["manpower"] = [
        (MAN_POWER, struct.pack("<f", 1.0), struct.pack("<f", MAN_POWER_PCT / 100.0),
         f"manual gearbox: engine power {MAN_POWER_PCT:g} % (0 = stock car, 100 = realistic)"),
    ]


set_manpower(_saved("manual_power", MAN_POWER_DEFAULT))

# ---- drivetrain: per-car gearboxes in Rust (crdrive.dll), Stage 2 #11 v2 (player 2026-10-31) ------------
# The player's spec (memory city-racing-car-gearbox-spec): every model its own box - Galant 4AT (4th = OD),
# Clio 5MT, Rover 6AT quick-shift, Cosmo 6MT close-ratio, Thunder 3AT, Accord 5MT, Alpha 6MT ROTARY, Uber
# 6-speed F1 (paddle-style, clutch button kept); automatics shift themselves on a P R N D 2 1 lever (Z/X)
# and show "D 3". The logic lives in rust/crdrive (no_std 32-bit DLL, no imports, 8 native unit tests);
# here only tiny asm DOORS at the hook sites of the old asm `manual` extra (which this REPLACES):
#   0x00436620 car loader (thiscall car, arg path "Data/Vehicles/0X/Main|Police.obj") -> cr_car_init:
#              the model comes from the path, so Car Tuner stat edits cannot confuse it
#   0x00434844 drive (every car)  -> cr_drive(car, &force): 1 = force set (-> 0x004348e1), 0 = stock
#   0x00434d5a engine sound (player only) -> cr_sound(car, load) -> load
#   0x0045677e window-procedure keydown -> cr_key(vk, lparam)   (X / Z)
#   0x00468265 speedometer -> cr_hud_text() -> "N" / "4" / "D 3" ... drawn with the game's font calls
#   0x00468036 + 0x00468119 small needle -> cr_tach() angle, cr_tach_color() colour (shift light)
# The DLL is loaded once (LoadLibraryA/GetProcAddress, already in the import table: IAT 0x0056805c /
# 0x00568060) by DT_LOADER on the first door; missing DLL or wrong version -> every door runs stock code.
# Value: engine power % (= the old `manpower`: 0 = never above the stock car, 100 = realistic).
DT_BASE = S2_CODE + 0x2400                       # .. 0x2A00
DT_LOADED, DT_FN = DT_BASE, DT_BASE + 4          # dword state (0 untried, 1 ok, -1 failed), 8 fn pointers
DT_FUNCS = ["cr_car_init", "cr_drive", "cr_sound", "cr_key", "cr_hud_text", "cr_tach", "cr_tach_color",
            "cr_version"]
DT_F = {n: DT_FN + 4 * i for i, n in enumerate(DT_FUNCS)}
DT_TCOL, DT_TANG = DT_BASE + 0x28, DT_BASE + 0x2C
DT_HUD = DT_BASE + 0x30                          # HUD_X, HUD_Y, scale, half, colour
DT_STR = DT_BASE + 0x50                          # dll name + export names
DT_LOADER = DT_BASE + 0x100
DT_DOORS = DT_BASE + 0x200
DT_SETTINGS = S2_CODE + 0x2300                   # b"CRDV" + power: read by crdrive.dll (lib.rs SETTINGS)
DT_DLL_NAME = "crdrive.dll"
DT_DLL_VERSION = 1
DT_DLL_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rust", "crdrive", "target",
                          "i686-pc-windows-msvc", "release", DT_DLL_NAME)
if not os.path.exists(DT_DLL_SRC):                 # no local cargo build: the committed one (build.bat refreshes it)
    DT_DLL_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", DT_DLL_NAME)
DT_POWER_DEFAULT = 100
DT_POWER_RANGE = (0, 100)
DT_POWER = DT_POWER_DEFAULT
IAT_LOADLIBRARYA, IAT_GETPROCADDRESS = 0x0056805C, 0x00568060
DT_XMM_SAVE = "\n".join(f"        movups xmmword ptr [esp+{4 + 16 * k:#x}], xmm{k}" for k in range(8))
DT_XMM_LOAD = "\n".join(f"        movups xmm{k}, xmmword ptr [esp+{4 + 16 * k:#x}]" for k in range(8))


def set_drivetrain(pct):
    global DT_POWER
    lo, hi = DT_POWER_RANGE
    if not lo <= float(pct) <= hi:
        raise ValueError(f"power {pct} must be {lo}..{hi} %")
    DT_POWER = float(pct)
    F = {n: f"{a:#x}" for n, a in DT_F.items()}
    strs = bytearray()
    names = {}
    for n in [DT_DLL_NAME] + DT_FUNCS:
        names[n] = DT_STR + len(strs)
        strs += n.encode() + b"\0"
    assert DT_STR + len(strs) <= DT_LOADER
    resolve = "\n".join(f"""
        push {names[n]:#x}
        push ebx
        call dword ptr [{IAT_GETPROCADDRESS:#x}]
        mov dword ptr [{F[n]}], eax""" for n in DT_FUNCS)
    loader = _s2asm(f"""
        cmp dword ptr [{DT_LOADED:#x}], 0
        jne ldone
        pushad
        pushfd
        mov dword ptr [{DT_LOADED:#x}], -1
        push {names[DT_DLL_NAME]:#x}
        call dword ptr [{IAT_LOADLIBRARYA:#x}]
        test eax, eax
        jz lout
        mov ebx, eax
        {resolve}
        mov eax, dword ptr [{F['cr_version']}]
        test eax, eax
        jz lclear
        call eax
        cmp eax, {DT_DLL_VERSION}
        jne lclear
        mov dword ptr [{DT_LOADED:#x}], 1
        jmp lout
    lclear:
        mov edi, {DT_FN:#x}
        mov ecx, {len(DT_FUNCS)}
        xor eax, eax
        rep stosd
    lout:
        popfd
        popad
    ldone:
        ret
    """, DT_LOADER, DT_DOORS)
    doors, at = [], DT_DOORS

    def door(src, size):
        nonlocal at
        code = _s2asm(src, at, at + size)
        doors.append((at, code))
        at += size
        return at - size
    d_init = door(f"""
        call {DT_LOADER:#x}
        mov eax, dword ptr [{F['cr_car_init']}]
        test eax, eax
        jz cskip
        push ecx
        push edx
        push dword ptr [esp+0xc]
        push ecx
        call eax
        add esp, 8
        pop edx
        pop ecx
    cskip:
        push -1
        push 0x565cec
        jmp 0x00436627
    """, 0x40)
    d_drive = door(f"""
        call {DT_LOADER:#x}
        mov eax, dword ptr [{F['cr_drive']}]
        test eax, eax
        jz dplain
        sub esp, 0x84
{DT_XMM_SAVE}
        mov ecx, esp
        push ecx
        push esi
        call eax
        add esp, 8
{DT_XMM_LOAD}
        test eax, eax
        jz dstock
        movss xmm0, dword ptr [esp]
        add esp, 0x84
        movss dword ptr [esp+4], xmm0
        movss xmm4, dword ptr [esi+0x7f80]
        jmp 0x004348e1
    dstock:
        add esp, 0x84
    dplain:
        movss xmm4, dword ptr [esi+0x7f80]
        jmp 0x0043484c
    """, 0xC0)
    d_sound = door(f"""
        mov eax, dword ptr [{F['cr_sound']}]
        test eax, eax
        jz sorig
        push ecx
        push edx
        sub esp, 0x84
{DT_XMM_SAVE}
        push dword ptr [esp+0x90]
        push esi
        call eax
        add esp, 8
        fstp dword ptr [esp]
        mov eax, dword ptr [esp]
{DT_XMM_LOAD}
        add esp, 0x84
        pop edx
        pop ecx
        cmp eax, dword ptr [esp+4]
        je sorig
        mov dword ptr [esp+4], eax
        movss xmm2, dword ptr [esp+4]
        minss xmm2, dword ptr [{DT_HUD + 0x14:#x}]
    sorig:
        fld dword ptr [esp+4]
        mov edx, dword ptr [ecx+0x114]
        jmp 0x00434d64
    """, 0xC0)
    d_key = door(f"""
        call 0x00454a80
        mov eax, dword ptr [{F['cr_key']}]
        test eax, eax
        jz kout
        push ecx
        push edx
        push dword ptr [esp+0x30]
        push ebx
        call eax
        add esp, 8
        pop edx
        pop ecx
    kout:
        jmp 0x00456783
    """, 0x30)
    d_hud = door(f"""
        fstp dword ptr [{DT_HUD + 0x18:#x}]
        pushad
        mov eax, dword ptr [{F['cr_hud_text']}]
        test eax, eax
        jz hout
        call eax
        test eax, eax
        jz hout
        mov edi, eax
        push 1
        push dword ptr [{DT_HUD + 8:#x}]
        push edi
        mov ecx, ebx
        call 0x004702a0
        fmul dword ptr [{DT_HUD + 0xC:#x}]
        fsubr dword ptr [{DT_HUD:#x}]
        push 1
        push dword ptr [{DT_HUD + 8:#x}]
        push dword ptr [{DT_HUD + 0x10:#x}]
        push edi
        push dword ptr [{DT_HUD + 4:#x}]
        sub esp, 4
        fstp dword ptr [esp]
        mov ecx, ebx
        call 0x00470260
        fstp st(0)
    hout:
        popad
        fld dword ptr [{DT_HUD + 0x18:#x}]
        mov eax, dword ptr [0x012d0c88]
        jmp 0x0046826a
    """, 0x80)
    d_tach = door(f"""
        mov edx, dword ptr [{F['cr_tach']}]
        test edx, edx
        jz tstock
        call edx
        fstp dword ptr [{DT_TANG:#x}]
        mov edx, dword ptr [{F['cr_tach_color']}]
        test edx, edx
        jz tnocol
        call edx
        mov dword ptr [{DT_TCOL:#x}], eax
    tnocol:
        movss xmm0, dword ptr [{DT_TANG:#x}]
        push ecx
        jmp 0x0046807a
    tstock:
        movss xmm0, dword ptr [eax+0x7f80]
        jmp 0x0046803e
    """, 0x40)
    d_tcol = door(f"""
        push dword ptr [{DT_TCOL:#x}]
        jmp 0x0046811e
    """, 0x10)
    assert at <= DT_BASE + 0x600
    data = bytearray(0x50)
    struct.pack_into("<I", data, DT_TCOL - DT_BASE, 0xFF808000)
    struct.pack_into("<ffffIf", data, DT_HUD - DT_BASE, MAN_HUD_X, MAN_HUD_Y, MAN_HUD_SCALE, 0.5, MAN_HUD_COLOR,
                     1.0)                          # +0x14 = 1.0, +0x18 = the HUD door's x87 stash
    settings = b"CRDV" + struct.pack("<f", DT_POWER / 100.0)
    PATCHES["drivetrain"] = [
        (0x00436620, bytes.fromhex("6aff68ec5c5600"), _s2jmp(0x00436620, d_init, 7),
         "car loader: tell crdrive.dll which model each car is (from its Data/Vehicles path)"),
        (0x00434844, bytes.fromhex("f30f10a6807f0000"), _s2jmp(0x00434844, d_drive, 8),
         "drive: your car through its own gearbox (crdrive.dll)"),
        (0x00434D5A, bytes.fromhex("d94424048b9114010000"), _s2jmp(0x00434D5A, d_sound, 10),
         "engine sound: your car's pitch follows its real revs"),
        (0x0045677E, bytes.fromhex("e8fde2ffff"), _s2jmp(0x0045677E, d_key, 5),
         "keys: X / Z shift (or move an automatic's lever), Shift = clutch"),
        (0x00468265, bytes.fromhex("a1880c2d01"), _s2jmp(0x00468265, d_hud, 5),
         "speedometer: the gear (N 1..6 R, or P R N D 2 1 with the gear)"),
        (0x00468036, bytes.fromhex("f30f1080807f0000"), _s2jmp(0x00468036, d_tach, 8),
         "speedometer: the small needle is a tachometer"),
        (0x00468119, bytes.fromhex("68008080ff"), _s2jmp(0x00468119, d_tcol, 5),
         "speedometer: the needle blinks red at the shift point (manual / F1)"),
        (DT_BASE, bytes(len(data)), bytes(data), "drivetrain data (fn table, HUD layout)"),
        (DT_STR, bytes(len(strs)), bytes(strs), f"drivetrain: {DT_DLL_NAME} and its export names"),
        (DT_LOADER, bytes(len(loader)), loader, f"drivetrain DLL loader ({len(loader)} bytes)"),
    ] + [(a, bytes(len(c)), c, f"drivetrain door ({len(c)} bytes)") for a, c in doors] + [
        (DT_SETTINGS, bytes(len(settings)), settings, f"drivetrain: engine power {DT_POWER:g} %"),
        (DT_SETTINGS + 8, bytes(4), bytes(4), "drivetrain: AI gearboxes off (its own edit: `aigears` stacks on it)"),
        (DT_SETTINGS + 12, bytes(4), bytes(4), "drivetrain: rpm dial off (its own edit: `rpmdial` stacks on it)"),
        (DT_SETTINGS + 16, bytes(4), bytes(4),
         "drivetrain: realistic gearing 50/50 (top speed + 0-100 halfway to the real car; `realcar` stacks on it)"),
        (DT_SETTINGS + 20, bytes(4), bytes(4), "drivetrain: no punch override (tools only)"),
    ]


set_drivetrain(_saved("drivetrain_power", DT_POWER_DEFAULT))

# ---- aigears: traffic, police and racers through their model's gearbox too (player 2026-10-31) -----------
# One flag the DLL reads (settings +8). AI cars shift themselves (automatics in D, manual/F1 near the redline),
# keep the stock throttle RAMP (their analog throttle - writes like 0x0043cb46 / 0x0043d428 scale it), and their
# braking and reversing stay 100 % stock (cr_drive hands any car with the pedal down or F < 0 back to the
# stock code: the AI depends on the stock auto-reverse to get unstuck). Their engine sound follows the revs.
PATCHES["aigears"] = [
    (DT_SETTINGS + 8, struct.pack("<I", 0), struct.pack("<I", 1),
     "AI cars (traffic, police, racers) drive through their own gearboxes"),
]

# ---- realcar: realistic gearing at the REAL cars' 0-100 (player 2026-11-01: "50/50 as default, and a Real-car
# version so I can change it depending on my mood"). The game's drag is linear damping (-10 %/s, coast-down
# measured), so stock cars pull ~1 g to a low top speed. crdrive.dll (model.rs REAL, drive.rs drag_back): top
# speed halfway to the real car's (force and every gear x s_top), and every acceleration x k (engine x k, (1-k)
# of the drag given back, top speed held). `drivetrain` alone = 50/50 (0-100 halfway, settings +16 = 0);
# `realcar` = settings +16 = 1: the real 0-100 (Galant 9.0 s, Clio 10.5, Rover 9.5, Cosmo 6.0, Thunder 10.5,
# Accord 16.0, Alpha 5.3, Uber 4.7). k calibrated by realcal.py.
PATCHES["realcar"] = [
    (DT_SETTINGS + 16, struct.pack("<I", 0), struct.pack("<I", 1),
     "realistic gearing: the real cars' 0-100 (instead of 50/50)"),
]


# ---- carsounds + keeplivery (player 2026-10-31: "every time we exit the game and continue, my car
# is back to the default livery and engine sound ... make the livery permanent, and same cars must
# not have randomized engine sounds") ------------------------------------------------------------
# ENGINE SOUND. The car constructor 0x00436620 (thiscall esi = car, ebx = its .obj path until
# 0x00436cc8) reads the file's "Engine Sound ID" into [car+0x7fec] (0x00436aa7), then OVERWRITES it
# with rand() % 8 (0x00436ae2) - every .obj says 0 anyway, the developer never filled them in. The
# placement code 0x0043c280 rolls it again for AI cars ([car+0xc8c] != 0, 0x0043c3a4). The index picks
# Data/Audio/E01..E08.wav (CAudioManager +0x4204, 8 x 10 voices; 0x0046d660 ignores >= 8).
# `carsounds`: 0x00436ae2 takes the value from a 20-byte table instead (index = the "0X" digit of
# Data/Vehicles/0X/..., +10 for Police.obj; 0xFF = keep the stock random pick), and the AI re-roll at
# 0x0043c3a4 is removed so a placed car keeps its model's sound. rand() is still called at both sites,
# so the random number stream (traffic, races) is exactly the stock one.
# LIVERY. A car's look = body colour [car+0xe48] (4 floats, drawn through the 8x8 texture
# [car+0x1e68] baked by 0x004101c0), decal colour [car+0xe5c] and the decal texture [car+0xe70]
# (one of the .obj's "Vehicle Decal NN" names at [car+0xe78], 0xFF bytes each, count [car+0xe74],
# picked at random 1..count-1 by the constructor). The save (0x00421980 -> car 0x00436530) stores
# both colours but not the decal, and the load (0x00421b60) rebuilds the car (new random decal and
# colours, texture baked), then reads the saved colours into the fields WITHOUT re-baking the body
# texture - so a loaded car shows random paint and a random decal.
# `keeplivery`: the save appends an 8-byte block "CRLV" + decal index just before it closes the file
# (0x00421b38; the index is found by looking each decal name up in the texture cache 0x00410140 and
# matching [car+0xe70]). The load reads 8 more bytes before it closes (0x00421cf7; an old save has
# none: fread returns nothing, the block stays zero), re-bakes the body texture from the loaded colour,
# and when the block is there swaps in the saved decal (release 0x0040ada0 / acquire 0x0040ad00, the
# constructor's own calls). The stock game reading a new save stops before the block.
CS_CAVE = S2_CODE + 0x2A00                       # .. 0x2A60
CS_TABLE = S2_CODE + 0x2A60                      # 20 bytes: 0..9 Main.obj, 10..19 Police.obj
LV_SAVE = S2_CODE + 0x2A80                       # .. 0x2B20
LV_LOAD = S2_CODE + 0x2B20                       # .. 0x2BE0
LV_BUF = S2_CODE + 0x2BF0                        # 8 bytes, written at run time
LV_MAGIC = 0x564C5243                            # "CRLV"
CAR_SOUND_SLOTS = ("01", "02", "03", "04", "05", "06", "07", "08", "01P", "03P")
# a first guess from measuring the samples (E03/E05 darkest, E06 the fastest firing buzz, E08/E02/E01
# brightest) - the player picks by ear in the panel; -1 = random like the stock game
CARSOUNDS_DEFAULT = {"01": 4, "02": 0, "03": 6, "04": 1, "05": 2, "06": 5, "07": 7, "08": 3,
                     "01P": 4, "03P": 6}


def _saved_carsounds():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "racemod_state.json")) as f:
            got = json.load(f).get("carsounds") or {}
    except Exception:
        got = {}
    return {k: int(got.get(k, d)) for k, d in CARSOUNDS_DEFAULT.items()}


def set_carsounds(table):
    """table: slot ("01".."08", "01P", "03P") -> 0..7 (E01..E08) or -1 (random); missing slots keep
    their current value. Raises ValueError."""
    global CARSOUNDS
    new = dict(CARSOUNDS)
    for k, v in (table or {}).items():
        if k not in CAR_SOUND_SLOTS:
            raise ValueError(f"engine sound slot {k!r} is not one of {', '.join(CAR_SOUND_SLOTS)}")
        if int(v) != v or not -1 <= int(v) <= 7:
            raise ValueError(f"engine sound for {k} must be 0..7 (E01..E08) or -1 (random), not {v}")
        new[k] = int(v)
    CARSOUNDS = new
    tab = bytearray(b"\xff" * 20)
    for k, v in CARSOUNDS.items():
        tab[int(k[:2]) + (10 if k.endswith("P") else 0)] = 0xFF if v < 0 else v
    code = _s2asm(f"""
        push edx
        movzx edx, byte ptr [ebx+15]
        sub edx, 0x30
        cmp edx, 9
        ja keep
        cmp byte ptr [ebx+16], 0x2f
        jne keep
        cmp byte ptr [ebx+17], 0x50
        jne main
        add edx, 10
    main:
        movzx edx, byte ptr [{CS_TABLE:#x}+edx]
        cmp edx, 8
        jae keep
        mov eax, edx
    keep:
        mov dword ptr [esi+0x7fec], eax
        pop edx
        jmp 0x00436ae8
    """, CS_CAVE, CS_TABLE)
    PATCHES["carsounds"] = [
        (0x00436AE2, bytes.fromhex("8986ec7f0000"), _s2jmp(0x00436AE2, CS_CAVE, 6),
         "car constructor: engine sound from the per-model table, not rand() % 8"),
        (0x0043C3A4, bytes.fromhex("8983ec7f0000"), b"\x90" * 6,
         "car placement: no second random engine sound for AI cars"),
        (CS_CAVE, bytes(len(code)), code, f"carsounds cave ({len(code)} bytes)"),
        (CS_TABLE, bytes(20), bytes(tab), "engine sound per model: " + ", ".join(
            f"{k} {'random' if v < 0 else f'E{v + 1:02d}'}" for k, v in CARSOUNDS.items())),
    ]


CARSOUNDS = dict(CARSOUNDS_DEFAULT)
set_carsounds(_saved_carsounds())


def _keeplivery():
    save = _s2asm(f"""
        mov eax, dword ptr [0x012d0c88]
        test eax, eax
        jz close
        push ebx
        push edi
        mov ebx, eax
        xor edi, edi
    find:
        cmp edi, dword ptr [ebx+0xe74]
        jae notfound
        imul eax, edi, 0xff
        lea eax, [eax+ebx+0xe78]
        push eax
        mov ecx, 0x0255da6c
        call 0x00410140
        cmp eax, dword ptr [ebx+0xe70]
        je found
        inc edi
        jmp find
    notfound:
        or edi, -1
    found:
        mov dword ptr [{LV_BUF:#x}], {LV_MAGIC:#x}
        mov dword ptr [{LV_BUF + 4:#x}], edi
        pop edi
        pop ebx
        cmp dword ptr [{LV_BUF + 4:#x}], -1
        je close
        push esi
        push 1
        push 8
        push {LV_BUF:#x}
        mov ecx, 0x012cc128
        call 0x0046ee50
    close:
        push esi
        mov ecx, 0x012cc128
        call 0x0046eb80
        jmp 0x00421b43
    """, LV_SAVE, LV_LOAD)
    load = _s2asm(f"""
        mov dword ptr [{LV_BUF:#x}], 0
        mov dword ptr [{LV_BUF + 4:#x}], 0
        push esi
        push 1
        push 8
        push {LV_BUF:#x}
        mov ecx, 0x012cc128
        call 0x0046edf0
        push ebx
        mov ebx, dword ptr [0x012d0c88]
        test ebx, ebx
        jz done
        push 8
        lea eax, [ebx+0xe48]
        push eax
        lea eax, [ebx+0x1e68]
        push eax
        mov ecx, 0x0255da6c
        call 0x004101c0
        cmp dword ptr [{LV_BUF:#x}], {LV_MAGIC:#x}
        jne done
        mov eax, dword ptr [{LV_BUF + 4:#x}]
        cmp eax, dword ptr [ebx+0xe74]
        jae done
        push eax
        push dword ptr [ebx+0xe70]
        mov ecx, 0x0255d7f0
        call 0x0040ada0
        pop eax
        imul eax, eax, 0xff
        lea eax, [eax+ebx+0xe78]
        push 1
        push 0
        push eax
        mov ecx, 0x0255d7f0
        call 0x0040ad00
        mov dword ptr [ebx+0xe70], eax
    done:
        pop ebx
        push esi
        mov ecx, 0x012cc128
        call 0x0046eb80
        jmp 0x00421d02
    """, LV_LOAD, LV_BUF)
    return [
        (0x00421B38, bytes.fromhex("56b928c12c01e83dd00400"), _s2jmp(0x00421B38, LV_SAVE, 11),
         "save: append \"CRLV\" + your car's decal before closing the file"),
        (0x00421CF7, bytes.fromhex("56b928c12c01e87ece0400"), _s2jmp(0x00421CF7, LV_LOAD, 11),
         "load: re-bake the body paint from the saved colour, put the saved decal back"),
        (LV_SAVE, bytes(len(save)), save, f"keeplivery save cave ({len(save)} bytes)"),
        (LV_LOAD, bytes(len(load)), load, f"keeplivery load cave ({len(load)} bytes)"),
    ]


PATCHES["keeplivery"] = _keeplivery()


# ---- hudfix: the driving HUD is no longer stretched on wide screens (player 2026-11-01) ------------------
# The game lays its 2D interface out on an 800x600 canvas: renderer 0x0255d7f0 keeps x scale = width/800
# (+0x42004 = 0x0259f7f4) and y scale = height/600 (+0x42014 = 0x0259f804), so at 16:9 everything is 33 %
# too wide. The fix lives in crdrive.dll (lib.rs cr_dpup / cr_dipup, hud.rs): while the driving HUD draws,
# every pre-transformed batch is narrowed to the y scale and pinned to its own edge (left / centre / right).
# Here: 1) the HUD call 0x0046b3bc `call 0x467eb0` goes through HF_DOOR = cr_hud_begin, the HUD,
# cr_hud_end; 2) the 9 Direct3D draw sites of the 2D helpers that HUD uses load their method from a slot
# instead of the device vtable: `mov reg,[ecx+0x14c]` (DrawPrimitiveUP) / `[ecx+0x150]`
# (DrawIndexedPrimitiveUP, text) -> `mov reg,[HF_DPUP / HF_DIPUP]`. The slots start on pass-through thunks
# (jump to the device's own method), so menus, shops and a missing DLL draw exactly as stock; the door
# swaps in the DLL's functions once it has them. Outside the HUD window the DLL passes every call through.
HF_BASE = S2_CODE + 0x2C00                       # .. 0x2E00
HF_DPUP, HF_DIPUP, HF_BEGIN, HF_END, HF_STATE = (HF_BASE + 4 * k for k in range(5))
HF_STR = HF_BASE + 0x20
HF_THUNK_UP, HF_THUNK_IUP = HF_BASE + 0x80, HF_BASE + 0x90
HF_DOOR = HF_BASE + 0xA0
HF_END_ADDR = HF_BASE + 0x200
HF_FUNCS = ["cr_hud_begin", "cr_hud_end", "cr_dpup", "cr_dipup"]
# (site, original 6 bytes, register): the draw call of each 2D helper the driving HUD 0x00467eb0 uses
HF_SITES = [
    (0x0040CEA1, "8b814c010000", "eax", "DrawPrimitiveUP in 0x0040cb90 (via 0x0040cec0)"),
    (0x0040DF5D, "8b814c010000", "eax", "DrawPrimitiveUP in 0x0040da90 (via 0x0040e0a0)"),
    (0x0040E55A, "8b814c010000", "eax", "DrawPrimitiveUP in 0x0040e0e0 (via 0x0040e580)"),
    (0x0040EAD8, "8b814c010000", "eax", "DrawPrimitiveUP in 0x0040e850"),
    (0x0045C8E2, "8b914c010000", "edx", "DrawPrimitiveUP in the rect 0x0045c7d0"),
    (0x0045CA21, "8b914c010000", "edx", "DrawPrimitiveUP in the quad 0x0045c910"),
    (0x0045CB64, "8b914c010000", "edx", "DrawPrimitiveUP in the quad 0x0045ca50"),
    (0x004683E9, "8b814c010000", "eax", "DrawPrimitiveUP in the speedometer 0x00467eb0"),
    (0x00470240, "8b8150010000", "eax", "DrawIndexedPrimitiveUP in the text 0x0046ff10"),
]


def _hudfix():
    strs, names = bytearray(), {}
    for n in [DT_DLL_NAME] + HF_FUNCS:
        names[n] = HF_STR + len(strs)
        strs += n.encode() + b"\0"
    assert HF_STR + len(strs) <= HF_THUNK_UP
    thunk_up = _s2asm(f"""
        mov eax, dword ptr [esp+4]
        mov eax, dword ptr [eax]
        jmp dword ptr [eax+0x14c]
    """, HF_THUNK_UP, HF_THUNK_IUP)
    thunk_iup = _s2asm(f"""
        mov eax, dword ptr [esp+4]
        mov eax, dword ptr [eax]
        jmp dword ptr [eax+0x150]
    """, HF_THUNK_IUP, HF_DOOR)
    gpa = lambda n, reg: f"""
        push {names[n]:#x}
        push ebx
        call dword ptr [{IAT_GETPROCADDRESS:#x}]
        test eax, eax
        jz hout
        mov {reg}, eax"""
    door = _s2asm(f"""
        call {DT_LOADER:#x}
        cmp dword ptr [{HF_STATE:#x}], 0
        jne hready
        pushad
        mov dword ptr [{HF_STATE:#x}], -1
        cmp dword ptr [{DT_LOADED:#x}], 1
        jne hout
        push {names[DT_DLL_NAME]:#x}
        call dword ptr [{IAT_LOADLIBRARYA:#x}]
        test eax, eax
        jz hout
        mov ebx, eax
        {gpa("cr_hud_begin", "esi")}
        {gpa("cr_hud_end", "edi")}
        {gpa("cr_dpup", "ebp")}
        {gpa("cr_dipup", "edx")}
        mov dword ptr [{HF_DIPUP:#x}], edx
        mov dword ptr [{HF_DPUP:#x}], ebp
        mov dword ptr [{HF_BEGIN:#x}], esi
        mov dword ptr [{HF_END:#x}], edi
        mov dword ptr [{HF_STATE:#x}], 1
    hout:
        popad
    hready:
        cmp dword ptr [{HF_STATE:#x}], 1
        jne hplain
        push ecx
        call dword ptr [{HF_BEGIN:#x}]
        pop ecx
        call 0x00467eb0
        call dword ptr [{HF_END:#x}]
        ret
    hplain:
        jmp 0x00467eb0
    """, HF_DOOR, HF_END_ADDR)
    slots = struct.pack("<5I", HF_THUNK_UP, HF_THUNK_IUP, 0, 0, 0)
    out = [
        (0x0046B3BC, bytes.fromhex("e8efcaffff"), b"\xe8" + struct.pack("<i", HF_DOOR - (0x0046B3BC + 5)),
         "HUD: the driving HUD 0x00467eb0 runs between cr_hud_begin / cr_hud_end"),
    ]
    for site, orig, reg, what in HF_SITES:
        slot = HF_DIPUP if orig.endswith("50010000") else HF_DPUP
        new = bytes.fromhex({"eax": "8b05", "edx": "8b15"}[reg]) + struct.pack("<I", slot)
        out.append((site, bytes.fromhex(orig), new, what + " -> crdrive.dll (pass-through outside the HUD)"))
    out += [
        (HF_BASE, bytes(len(slots)), slots, "hudfix slots: DrawPrimitiveUP / DrawIndexedPrimitiveUP start on thunks"),
        (HF_STR, bytes(len(strs)), bytes(strs), "hudfix export names"),
        (HF_THUNK_UP, bytes(len(thunk_up)), thunk_up, "pass-through: the device's own DrawPrimitiveUP"),
        (HF_THUNK_IUP, bytes(len(thunk_iup)), thunk_iup, "pass-through: the device's own DrawIndexedPrimitiveUP"),
        (HF_DOOR, bytes(len(door)), door, f"hudfix door ({len(door)} bytes)"),
    ]
    return out


PATCHES["hudfix"] = _hudfix()


# ---- rpmdial: the speedometer gets each car's rpm scale + an honest speed needle (player 2026-11-01) --------
# 1) dial_faces.py paints one face per model (HUD faces/Main_0X.dds: olive arc, red zone redline..dial max,
#    numbers x1000 rpm, "x1000 RPM", "Km/h", a tick every 5 km/h). Apply copies them next to the game as LOOSE
#    files Data/Interface/HUD/SpeedBar/Main_0X.dds (the texture loader falls back to loose files; the archives
#    stay untouched). crdrive.dll (cr_hud_begin, settings +12) points the dial sprite's texture (HUD +0x9d84
#    +0x70) at the player's car's face every frame and turns the small needle to rpm / dial max.
# 2) The stock speed needle turned 0.024802 rad (1.421 deg) per km/h, but the printed scale is 1.5 deg per km/h
#    (0 at 134.8 deg, a 20 every 30 deg, 180 at 404.8 deg; measured on Main.dds), so it read ~5 % low: 95 at
#    a true 100, 170 at 180 (player: "at 100 it shows like 90"). The constant 0x0056c030 has one reader
#    (0x00468160 mulss) -> 4.712389 / 180 = 0.0261799 rad per km/h.
RD_FACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "HUD faces")
RD_FACES = [f"Main_{m:02d}.dds" for m in range(1, 9)]
RD_GAME_DIR = os.path.join("Data", "Interface", "HUD", "SpeedBar")
NEEDLE_MAX = 235.0                                  # km/h: the speed needle's new limit (rpmdial)
PATCHES["rpmdial"] = [
    (DT_SETTINGS + 12, struct.pack("<I", 0), struct.pack("<I", 1),
     "speedometer: each car's own rpm face + the small needle on its scale (crdrive.dll)"),
    (0x0056C030, bytes.fromhex("aa2dcb3c"), struct.pack("<f", 4.712389 / 180),
     "speed needle: 1.5 deg per km/h like the printed scale (was 1.421: read ~5 % low)"),
    # player 2026-11-01: realistic gearing takes the Cosmo/Alpha/Uber past 180 - keep the faces, let the needle
    # go on at the same 1.5 deg/km/h through the blank gap; the stock clamp 0..180 (0x0046813e, 180.0 at
    # 0x00568538, which other code may share) now loads its own 235 (240 would sit on the 0 mark)
    (DT_SETTINGS + 0x40, bytes(4), struct.pack("<f", NEEDLE_MAX), f"speed needle limit {NEEDLE_MAX:g} km/h"),
    (0x0046813E, bytes.fromhex("f30f101538855600"), b"\xf3\x0f\x10\x15" + struct.pack("<I", DT_SETTINGS + 0x40),
     f"speed needle: clamp at {NEEDLE_MAX:g} km/h instead of 180 (same scale past the last number)"),
]


# ---- racergod: race opponents take no damage, traffic and police still do (player 2026-11-01) ----------------
# The crash-damage path (0x0043a420, esi = the damaged car) checks for the player in `nodamage` at 0x0043ab0d and
# rejoins at 0x0043ab15 `push 0x2710` (5 bytes) for every other car. This hooks THAT instruction, so both extras
# stack in any combination: [car+0xc8c] == 1 (vehicle type: 0 player, 1 race opponent, 2 police, 3 traffic) ->
# the crash-sound tail 0x0043b444 like the player's god mode (they still crash and sound, they just do not dent,
# lose tyres or engine); any other car -> the original push and on into the damage block.
#
# ---- policedmg: police cars take 1x / 2x / 3x damage, so they are disabled sooner (player 2026-11-01) --------
# At 0x0043ab15 the hit's STRENGTH is at [esp+0x10] (0x0043ab07: min(impulse x k, cap)) and xmm1 = the dent
# RADIUS (strength + 0.5, stored as [esp+0x18] after the block's pushes): every part within the radius gets
# (1 - dist/radius) x ... x strength x 1.25 (0x0043ac41..0x0043ac67). Only the STRENGTH is scaled, so each
# dent / tyre / engine hit is exactly N x as hard and the damage shape stays the same (scaling xmm1 too would
# widen the radius and hit far more parts). A wrecked police car turns into traffic (type 3) with the +200 bonus
# (0x0043d69d..0x0043d72e).
#
# Both share ONE hook (`crashhook`, pulled in by either): flag CH_RACERS (racergod) and float CH_POLICE
# (policedmg, 1.0 = stock). With neither ticked the cave changes nothing.
RG_CAVE = S2_CODE + 0x2E00                       # .. 0x2E60 crashhook cave
CH_RACERS = S2_CODE + 0x2E60                     # dword: 1 = race opponents take no damage (racergod)
CH_POLICE = S2_CODE + 0x2E64                     # float: police damage x (policedmg)


def _crashhook():
    code = _s2asm(f"""
        cmp dword ptr [esi+0xc8c], 1
        jne notracer
        cmp dword ptr [{CH_RACERS:#x}], 0
        je damage
        jmp 0x0043b444
    notracer:
        cmp dword ptr [esi+0xc8c], 2
        jne damage
        fld dword ptr [esp+0x10]
        fmul dword ptr [{CH_POLICE:#x}]
        fstp dword ptr [esp+0x10]
    damage:
        push 0x2710
        jmp 0x0043ab1a
    """, RG_CAVE, RG_CAVE + 0x60)
    return [
        (0x0043AB15, bytes.fromhex("6810270000"), _s2jmp(0x0043AB15, RG_CAVE, 5),
         "collision damage: through the crash hook (racers immune / police damage x)"),
        (RG_CAVE, bytes(len(code)), code, f"crash hook cave ({len(code)} bytes)"),
        (CH_RACERS, bytes(4), bytes(4), "crash hook: race opponents take damage (racergod flips it)"),
        (CH_POLICE, bytes(4), struct.pack("<f", 1.0), "crash hook: police damage x1 (policedmg changes it)"),
    ]


PATCHES["crashhook"] = _crashhook()
PATCHES["racergod"] = [
    (CH_RACERS, bytes(4), struct.pack("<I", 1),
     "collision damage: race opponents (type 1) skip dents/tyres/engine (sound kept)"),
]
POLICE_DMG_RANGE, POLICE_DMG_DEFAULT = (1, 3), 1


def set_police_dmg(n):
    """(Re)build PATCHES['policedmg'] for police damage x n (1, 2 or 3)."""
    global POLICE_DMG
    lo, hi = POLICE_DMG_RANGE
    if float(n) != int(float(n)) or not lo <= int(float(n)) <= hi:
        raise ValueError(f"police damage {n} is not a whole number in {lo}..{hi}")
    POLICE_DMG = int(float(n))
    PATCHES["policedmg"] = [
        (CH_POLICE, struct.pack("<f", 1.0), struct.pack("<f", float(POLICE_DMG)),
         f"collision damage: police cars take {POLICE_DMG}x (disabled sooner)"),
    ]


set_police_dmg(_saved("police_dmg_x", POLICE_DMG_DEFAULT))


# ---- markskeep: blood splats AND tyre marks stay ~1 hour (player 2026-11-01: "tyre marks ~1 hour", "blood too") 
# The blood manager 0x02610308 keeps a pool of 512 records x 0x178 (add 0x0041af30 <- the pedestrian hit
# 0x0044b974; init 0x0041a730). A record lives T = 10 + 0.1 x rand(0..100) s (+0x3c total, +0x40 remaining,
# 0x0041a90a); its per-frame update 0x0041e400 counts +0x40 down by the frame time and frees it at 0
# ([rec] = 0, +0x174 = 0). With r = remaining / T: r 1 -> 0.75 the pool SPREADS, 0.75 -> 0.25 it is at full
# alpha (min(2r, 0.5) x 0.75 at 0x0041e63f), 0.25 -> 0 it fades. Distance only hides it (0x00401e40), never
# frees it - so with 10-20 s it was always gone by the time you came back.
# 1) 0x0041e414 `movss xmm0,[ebx+0x40]; subss xmm0,xmm3` (9 bytes) -> cave: in the FULL phase the countdown
#    runs at 0.5 T / hold, so that phase lasts `hold` seconds; spreading and fading keep their few seconds.
# 2) a full pool used to DROP new blood (0x0041af48 `xor eax,eax; pop esi; ret 0x18`): it now reuses the record
#    with the least life left, clearing its cached ground mesh (+0x174 = 1 means "mesh built": the old shape
#    would be drawn at the new place).
#
# TYRE MARKS ("it is really there - look at the memory when I skid": found live with re-tools/markscan.py).
# Untextured black strips: the manager (0x0041b970 ctor) holds 64 strips x 0xd0c ([+0] active, +4 age s, +8
# 64 vertex pairs x 2 x 24 bytes (xyz, colour = alpha << 24, uv), +0xd08 count) + 64 small 0x78 records. The car
# code 0x0043930e takes a strip from the allocator 0x0041bad0 and adds points through 0x0041b040 (intensity 1 - 2 x
# Bullet skidInfo wheel+0x114, alpha = intensity x 63.75, 0.1 m above the ground). Every frame 0x0041ba80 ->
# 0x0041b3a0: age += dt; > 10 s (0x0041b3c2, shared 10.0) -> freed; > 6 s (0x0041b3de, 6.0) -> alpha x (1 -
# (age - 6) / 4). So marks lived 6 s dark + 4 s fade, and a full pool (all 64 strips live) left NO mark.
# 3) both compares load our own hold / hold + 4 s; 4) 0x0041bae3 `jb loop; xor eax,eax; ret` (5 bytes) -> cave:
#    the loop goes on, and a full pool takes the OLDEST strip (largest age) into the stock init 0x0041bae8
#    (active 1, age 0, count 0).
#    2026-11-02 (live: all 1024 strips used but the oldest only 32 s old - 431 held ONE point, 150 two; a stuck AI
#    car flickering in and out of a skid starts a strip every few frames, 10 at one spot): a strip with < 2 points
#    draws nothing, so a full pool reuses those JUNK strips first (older than 1 s - a skid just starting keeps its
#    strip), and only then the oldest real mark.
BK_CAVE = S2_CODE + 0x2E80                       # .. 0x2EE0 countdown cave
BK_FULL = S2_CODE + 0x2EE0                       # .. 0x2F20 pool-full cave
BK_K = S2_CODE + 0x2F20                          # float: 0.5 / hold seconds
BK_SAVE = S2_CODE + 0x2F24                       # xmm2 stash (run time)
TM_HOLD = S2_CODE + 0x2F28                       # float: tyre marks dark this long (s)
TM_END = S2_CODE + 0x2F2C                        # float: ... and gone at hold + 4 s
# S2 is full up to its end marker (+0x2FF0): the allocator and the jump guard live in .crhl's free gap between
# the headlights effect text (ends ~+0x19110) and the cookie (+0x20000); `markskeep` needs tmsect -> hlsect anyway
TM_FULL = HL_VA + 0x1E000                        # .. +0x1E080 the strip allocator (replaces 0x0041bad0)
TM_GUARD = HL_VA + 0x1E080                       # .. +0x1E100 jump guard before each point
TM_JUMP2 = HL_VA + 0x1E100                       # float: (8 m)^2
MARKS_KEEP_RANGE, MARKS_KEEP_DEFAULT = (1, 180), 60
# 5) MORE STRIPS (player 2026-11-01: "64 is too small - 3 cars skid in front of me and the marks just go"): the
#    manager (static at 0x025a18b0: 64 strips x 0xd0c, then 64 x 0x78 records at the FIXED offset +0x34300, the
#    next object right behind) moves to `tmsect`'s zero-filled 7th section with TM_N strips. Every user goes
#    through `mov ecx, 0x025a18b0` (9 sites, ctor via the static initialiser 0x00567030) and the 64 / 0x34300
#    constants (14 fields) - all rewritten. Only strips on screen are drawn (bounding box + 0x00401e40).
# 6) JUMP GUARD (player: "skidmark stripes that go straight to anything"): a car that jumps while skidding
#    (race reset to the route, respawn, crash reset) put its next point far away = a long straight stripe -
#    10 s before, an hour now. Before each point (0x0043937f) a point > 8 m from the strip's last one gets a NEW
#    strip for that wheel (wheel record +0x10).
#    2026-11-02: 2048 -> 8192 (player: "can it be 8192"): 26 MB of address space, zero-filled (no file bytes),
#    real RAM only as strips get used.
# 7) MORE BLOOD (player 2026-11-02: "blood splatter to 1024"): the blood manager (static at 0x02610308, 0x2F020
#    bytes: 512 records x 0x178, then +0x2F000 texture id, +0x2F004 / +0x2F008 vertex buffers (48- / 24-byte
#    vertices, 0x800 each = 4 per splat), +0x2F00C index buffer (6 x 16-bit per quad), +0x2F010 / +0x2F014 this
#    frame's vertex counts, +0x2F018 / +0x2F01C the locked vertex pointers; the next object follows at
#    +0x2F020) moves into .crtm behind the tyre marks with BL_N records. Its 9 `mov ecx, 0x02610308` users, the
#    8 trailing fields (47 accesses, all inside its own methods - whole .text scanned) and every size that
#    follows from 512 (count 0x200 / 0x1ff, the buffers 0x18000 / 0xC000 / 0x1800, the index fill 0x801, the
#    per-frame vertex cap 0x800) are rewritten, so all BL_N splats can be drawn in one frame.
TM_N = 8192
TM_STRIPS = TM_N * 0xD0C                         # the records follow the strips
BL_N = 1024
BL_REC = BL_N * 0x178                            # the blood records; the manager's 8 fields follow them
BL_OFF = (TM_STRIPS + 0x1E00 + 4 + 0xFF) & ~0xFF # behind the tyre marks' texture id
TM_VSIZE = (BL_OFF + BL_REC + 0x20 + 0xFFF) & ~0xFFF   # strips, records, the texture id, the blood manager
TM_VA = HL_VA + HL_VSIZE                         # 0x02832000: right after .crhl
BL_VA = TM_VA + BL_OFF
TM_OLD = 0x025A18B0
BL_OLD = 0x02610308
PATCHES["tmsect"] = [
    (0x0040011E, struct.pack("<H", 6), struct.pack("<H", 7), "NumberOfSections 6 -> 7"),
    (0x00400168, struct.pack("<I", IMG_SIZE_MOD + HL_VSIZE), struct.pack("<I", IMG_SIZE_MOD + HL_VSIZE + TM_VSIZE),
     "SizeOfImage + the tyre-mark section"),
    (0x00400300, bytes(40),
     struct.pack("<8sIIIIIIHHI", b".crtm", TM_VSIZE, TM_VA - 0x00400000, 0, 0, 0, 0, 0, 0, 0xC0000080),
     f"section header #7 .crtm: {TM_N} tyre-mark strips + {BL_N} blood splats, zero-filled (uninitialised data | "
     f"read | write)"),
]


def _redisp(orig_hex, old, new):
    """an instruction's bytes with its one 32-bit field `old` (displacement or immediate) set to `new`"""
    b = bytes.fromhex(orig_hex)
    o = struct.pack("<I", old)
    assert b.count(o) == 1, (orig_hex, hex(old))
    return b, b.replace(o, struct.pack("<I", new))


# (site, original bytes, the 512-pool value in it) - racemod-original bytes, re-tools scan 2026-11-02
_BLOOD_SITES = [
    *[(a, "b908036102", BL_OLD) for a in (0x0041E970, 0x0041EDE9, 0x0042176E, 0x004218C1, 0x00424F98, 0x004251E0,
                                         0x0042594D, 0x0044B96F, 0x00567020)],
    (0x0041A992, "c7442410ff010000", 0x1FF), (0x0041AA5A, "6800f00200", 0x2F000),
    (0x0041AA69, "89be08f00200", 0x2F008), (0x0041AA6F, "89be04f00200", 0x2F004),
    (0x0041AA75, "89be0cf00200", 0x2F00C), (0x0041AA7B, "89be14f00200", 0x2F014),
    (0x0041AA81, "89be10f00200", 0x2F010), (0x0041AA87, "89be18f00200", 0x2F018),
    (0x0041AA8D, "89be1cf00200", 0x2F01C),
    (0x0041AABA, "8d9604f00200", 0x2F004), (0x0041AAC8, "898600f00200", 0x2F000),
    (0x0041AAD7, "6800800100", 0x18000), (0x0041AAEB, "8d9608f00200", 0x2F008),
    (0x0041AAFB, "6800c00000", 0xC000), (0x0041AB12, "8dbe0cf00200", 0x2F00C),
    (0x0041AB1F, "6800180000", 0x1800), (0x0041AB27, "6800180000", 0x1800),
    (0x0041AB7B, "ba01080000", 0x801), (0x0041ABAA, "6800180000", 0x1800),
    (0x0041AC40, "899114f00200", 0x2F014), (0x0041AC46, "899110f00200", 0x2F010),
    (0x0041AC56, "83be10f0020000", 0x2F010), (0x0041AC82, "8b8600f00200", 0x2F000),
    (0x0041AD4B, "8b9604f00200", 0x2F004), (0x0041AD6D, "8b960cf00200", 0x2F00C),
    (0x0041ADA8, "8b8610f00200", 0x2F010), (0x0041ADF1, "8b8610f00200", 0x2F010),
    (0x0041AE04, "83be14f0020000", 0x2F014), (0x0041AE2B, "8b8600f00200", 0x2F000),
    (0x0041AEAA, "8b9608f00200", 0x2F008), (0x0041AECC, "8b960cf00200", 0x2F00C),
    (0x0041AEDE, "8b8614f00200", 0x2F014), (0x0041AF17, "8b8e14f00200", 0x2F014),
    (0x0041AF41, "3d00020000", 0x200),
    (0x0041AFA3, "8b8610f00200", 0x2F010), (0x0041AFB1, "81f900080000", 0x800),
    (0x0041AFCA, "039618f00200", 0x2F018), (0x0041AFDA, "01be10f00200", 0x2F010),
    (0x0041AFF3, "8b8614f00200", 0x2F014), (0x0041B001, "81f900080000", 0x800),
    (0x0041B01A, "8b861cf00200", 0x2F01C), (0x0041B02D, "01be14f00200", 0x2F014),
    (0x0041EE03, "8b8600f00200", 0x2F000), (0x0041EE14, "8b8604f00200", 0x2F004),
    (0x0041EE26, "c78604f0020000000000", 0x2F004), (0x0041EE30, "8b8608f00200", 0x2F008),
    (0x0041EE42, "c78608f0020000000000", 0x2F008), (0x0041EE4C, "8b860cf00200", 0x2F00C),
    (0x0041EE5E, "c7860cf0020000000000", 0x2F00C), (0x0041EE75, "8b8604f00200", 0x2F004),
    (0x0041EE82, "8d9618f00200", 0x2F018), (0x0041EE93, "8b8608f00200", 0x2F008),
    (0x0041EEA0, "8d961cf00200", 0x2F01C), (0x0041EEB1, "c78614f0020000000000", 0x2F014),
    (0x0041EEBB, "c78610f0020000000000", 0x2F010), (0x0041EEC7, "bb00020000", 0x200),
    (0x0041EEE7, "8b8604f00200", 0x2F004), (0x0041EEF5, "8bb608f00200", 0x2F008),
]


def _blood_value(old):
    """what a 512-pool value becomes with BL_N records"""
    if old == BL_OLD:
        return BL_VA
    if 0x2F000 <= old <= 0x2F01C:
        return BL_REC + (old - 0x2F000)          # the 8 fields behind the records
    return {0x1FF: BL_N - 1, 0x200: BL_N,         # records (ctor counts down from n - 1)
            0x800: 4 * BL_N, 0x801: 4 * BL_N + 1,  # vertices a frame (4 a splat); the index fill's end
            0x18000: 4 * BL_N * 0x30, 0xC000: 4 * BL_N * 0x18,  # the two vertex buffers
            0x1800: 6 * 2 * BL_N}[old]            # the index buffer (6 x 16-bit a quad)


def _blood_patches():
    out = []
    for a, h, old in _BLOOD_SITES:
        orig, new = _redisp(h, old, _blood_value(old))
        out.append((a, orig, new, f"blood: {BL_N} splats ({old:#x} -> {_blood_value(old):#x})"))
    return out


def set_marks_keep(minutes):
    """(Re)build PATCHES['markskeep']: blood splats and tyre marks held `minutes` at full colour."""
    global MARKS_KEEP
    lo, hi = MARKS_KEEP_RANGE
    if not lo <= float(minutes) <= hi:
        raise ValueError(f"marks keep {minutes} min is outside {lo}..{hi}")
    MARKS_KEEP = float(minutes)
    hold = MARKS_KEEP * 60.0
    count = _s2asm(f"""
        movss dword ptr [{BK_SAVE:#x}], xmm2
        movss xmm0, dword ptr [ebx+0x40]
        movss xmm2, dword ptr [ebx+0x3c]
        mulss xmm2, dword ptr [0x00568544]
        comiss xmm0, xmm2
        ja normal
        movss xmm2, dword ptr [ebx+0x3c]
        mulss xmm2, dword ptr [0x00568d84]
        comiss xmm0, xmm2
        jbe normal
        movss xmm2, dword ptr [ebx+0x3c]
        mulss xmm2, dword ptr [{BK_K:#x}]
        mulss xmm2, xmm3
        subss xmm0, xmm2
        jmp done
    normal:
        subss xmm0, xmm3
    done:
        movss xmm2, dword ptr [{BK_SAVE:#x}]
        jmp 0x0041e41d
    """, BK_CAVE, BK_FULL)
    full = _s2asm(f"""
        push ebx
        push edi
        xor eax, eax
        xor edi, edi
        mov edx, ecx
        mov ebx, 0x7fffffff
    scan:
        cmp dword ptr [edx+0x40], ebx
        jge next
        mov ebx, dword ptr [edx+0x40]
        mov eax, edi
    next:
        add edx, 0x178
        inc edi
        cmp edi, {BL_N}
        jb scan
        imul edx, eax, 0x178
        mov dword ptr [ecx+edx+0x174], 0
        pop edi
        pop ebx
        jmp 0x0041af4e
    """, BK_FULL, BK_K)
    alloc = _s2asm(f"""
        xor eax, eax
        mov edx, ecx
    free:
        cmp dword ptr [edx], 0
        je found
        inc eax
        add edx, 0xd0c
        cmp eax, {TM_N}
        jb free
        push esi
        push edi
        push ebp
        xor eax, eax
        xor edi, edi
        mov edx, ecx
        mov esi, 0xffffffff
    scan:
        mov ebp, dword ptr [edx+4]
        cmp dword ptr [edx+0xd08], 2
        jae keyed
        cmp ebp, 0x3f800000
        jle keyed
        mov ebp, 0x7fffffff
    keyed:
        cmp ebp, esi
        jle next
        mov esi, ebp
        mov eax, edi
    next:
        add edx, 0xd0c
        inc edi
        cmp edi, {TM_N}
        jb scan
        pop ebp
        pop edi
        pop esi
    found:
        jmp 0x0041bae8
    """, TM_FULL, TM_GUARD)
    guard = _s2asm(f"""
        mov eax, dword ptr [ecx+0xd08]
        test eax, eax
        je add
        lea eax, [eax+eax*2]
        shl eax, 4
        lea eax, [ecx+eax-0x28]
        mov edx, dword ptr [esp]
        movss xmm0, dword ptr [edx]
        subss xmm0, dword ptr [eax]
        mulss xmm0, xmm0
        movss xmm1, dword ptr [edx+8]
        subss xmm1, dword ptr [eax+8]
        mulss xmm1, xmm1
        addss xmm0, xmm1
        comiss xmm0, dword ptr [{TM_JUMP2:#x}]
        jbe add
        mov ecx, {TM_VA:#x}
        call 0x0041bad0
        test eax, eax
        jne fresh
        add esp, 8
        jmp 0x00439384
    fresh:
        mov dword ptr [ebx+0x10], eax
        mov ecx, eax
    add:
        call 0x0041b040
        jmp 0x00439384
    """, TM_GUARD, TM_JUMP2)
    size = struct.pack("<I", TM_STRIPS)
    reloc = [(a, bytes.fromhex("b9b0185a02"), b"\xb9" + struct.pack("<I", TM_VA),
              f"tyre-mark manager -> .crtm ({w})")
             for a, w in ((0x00421778, "draw strips"), (0x00421831, "draw records"), (0x004218CB, "clear"),
                          (0x00424FA2, "reset"), (0x004251EA, "per-frame update"), (0x00425960, "reset"),
                          (0x00439309, "car: new strip"), (0x004396D6, "car: record"),
                          (0x00567030, "constructor (static init)"))]
    reloc += [
        (0x0041B97D, bytes.fromhex("bf3f000000"), b"\xbf" + struct.pack("<I", TM_N - 1), f"ctor: {TM_N} strips"),
        (0x0041B9D2, bytes.fromhex("8db300430300"), b"\x8d\xb3" + size, "ctor: records after the strips"),
        (0x0041BA51, bytes.fromhex("6800430300"), b"\x68" + size, "clear: the strips' size"),
        (0x0041BA67, bytes.fromhex("81c600430300"), b"\x81\xc6" + size, "clear: records after the strips"),
        (0x0041BA84, bytes.fromhex("be40000000"), b"\xbe" + struct.pack("<I", TM_N), f"update: {TM_N} strips"),
        (0x0041BAA5, bytes.fromhex("8d8f00430300"), b"\x8d\x8f" + size, "update: records after the strips"),
        (0x0041BB85, bytes.fromhex("bf40000000"), b"\xbf" + struct.pack("<I", TM_N), f"draw: {TM_N} strips"),
        (0x0041BBB2, bytes.fromhex("8d9100430300"), b"\x8d\x91" + size, "record alloc: after the strips"),
        (0x0041BBD7, bytes.fromhex("8db4d100430300"), b"\x8d\xb4\xd1" + size, "record alloc: after the strips"),
        (0x0041BCC8, bytes.fromhex("81c604430300"), b"\x81\xc6" + struct.pack("<I", TM_STRIPS + 4),
         "record draw: after the strips"),
        (0x0041EF11, bytes.fromhex("6800430300"), b"\x68" + size, "reset: the strips' size"),
        (0x0041EF25, bytes.fromhex("8d8600430300"), b"\x8d\x86" + size, "reset: records after the strips"),
        (0x0041EF61, bytes.fromhex("6800430300"), b"\x68" + size, "reset: the strips' size"),
        (0x0041EF75, bytes.fromhex("8d8600430300"), b"\x8d\x86" + size, "reset: records after the strips"),
        # 2026-11-02 CRASH (d3d9.dll AV, dump game.exe.10060.dmp, re-tools/dumpread.py: records draw 0x0041bcba):
        # the manager has ONE more field after the records, the records' texture id at +0x36100 (= old strips
        # 0x34300 + records 0x1E00). Left at +0x36100 it sat inside strip 66 - once the pool filled that far,
        # strip data overwrote it and a garbage texture reached Direct3D. It moves behind the records too.
        (0x0041BCA3, bytes.fromhex("8b8600610300"), b"\x8b\x86" + struct.pack("<I", TM_STRIPS + 0x1E00),
         "record draw: the texture id after the records"),
        (0x0041EF49, bytes.fromhex("898600610300"), b"\x89\x86" + struct.pack("<I", TM_STRIPS + 0x1E00),
         "device restore: the texture id after the records"),
        (0x0041EF83, bytes.fromhex("8b8e00610300"), b"\x8b\x8e" + struct.pack("<I", TM_STRIPS + 0x1E00),
         "device release: the texture id after the records"),
    ]
    PATCHES["markskeep"] = [
        (0x0041E414, bytes.fromhex("f30f104340f30f5cc3"), _s2jmp(0x0041E414, BK_CAVE, 9),
         f"blood splats: the full-colour phase lasts {MARKS_KEEP:g} min"),
        (BK_CAVE, bytes(len(count)), count, f"blood countdown cave ({len(count)} bytes)"),
        (0x0041AF48, bytes.fromhex("33c05ec21800"), _s2jmp(0x0041AF48, BK_FULL, 6),
         "blood splats: a full pool reuses the oldest splat instead of dropping the new one"),
        (BK_FULL, bytes(len(full)), full, f"blood pool-full cave ({len(full)} bytes)"),
        (BK_K, bytes(4), struct.pack("<f", 0.5 / hold), f"0.5 / {hold:g} s"),
        (0x0041B3C2, bytes.fromhex("0f2f0540855600"), b"\x0f\x2f\x05" + struct.pack("<I", TM_END),
         f"tyre marks: gone after {MARKS_KEEP:g} min + 4 s (was 10 s)"),
        (0x0041B3DE, bytes.fromhex("f30f100d14905600"), b"\xf3\x0f\x10\x0d" + struct.pack("<I", TM_HOLD),
         f"tyre marks: dark for {MARKS_KEEP:g} min, then the stock 4 s fade (was 6 s)"),
        (TM_HOLD, bytes(8), struct.pack("<ff", hold, hold + 4.0), f"tyre marks {hold:g} s / {hold + 4:g} s"),
        (0x0041BAD0, bytes.fromhex("33c08bd183"), _s2jmp(0x0041BAD0, TM_FULL, 5),
         f"tyre marks: {TM_N} strips; a full pool reuses the oldest strip instead of leaving no mark"),
        (TM_FULL, bytes(len(alloc)), alloc, f"tyre strip allocator ({len(alloc)} bytes)"),
        (0x0043937F, bytes.fromhex("e8bc1cfeff"), _s2jmp(0x0043937F, TM_GUARD, 5),
         "tyre marks: a wheel that jumped > 8 m (reset/respawn) starts a new strip - no straight stripes"),
        (TM_GUARD, bytes(len(guard)), guard, f"tyre-mark jump guard ({len(guard)} bytes)"),
        (TM_JUMP2, bytes(4), struct.pack("<f", 64.0), "jump guard: (8 m)^2"),
    ] + reloc + _blood_patches()


set_marks_keep(_saved("marks_keep_min", MARKS_KEEP_DEFAULT))

# ---- camfix: chase camera (player 2026-11-02: "close camera is a bit close, make it a bit far, a tiny bit"; "make
# the close and far cams a bit higher - too low, noticeable on the Accord Z8 and Rover, tall roofs"; options modal:
# close +10 %, LIFT ONLY = the same angle, higher).
# 0x004018c0 (see `panini` 8.): d = view [cam+0x9ed0] (1 close, 2 far, 3) x car[+0x8b4] x 0.85 x chase. Outputs,
# relative to the car's point car[+0x1e84] (0x00404605..): EYE = -forward x d x speed stretch + up 0.5 d
# (0x004019bc: d x [0x005682f8] shared 0.5), AIM = forward x d x (...) + up d / 3 (0x00401a9f: d x 0.3333 in xmm3);
# the 3rd output (+3.0 at 0x00401afe) is the camera's UP vector, not a height. "Lift only" adds the same CAM_LIFT x d
# to both heights: the line of sight moves up parallel (same look-down angle, ~4.8 deg standing), the car sits lower
# on screen. The view's integer multiplier becomes a float table so only the close view moves back.
CAM_CAVE = HL_VA + 0x1D000                       # .. +0x1D0C0 three caves (free .crhl gap, see TM_FULL)
CAM_MODES = HL_VA + 0x1D100                      # floats: view 0..3 distance multipliers
CAM_K = HL_VA + 0x1D110                          # floats: eye height 0.5 + lift, aim height 1/3 + lift (x d)
CAM_CLOSE = 1.10                                 # close view x this (far / 3rd unchanged)
CAM_LIFT = 0.10                                  # both heights + this x d
_cam_mode = _s2asm(f"""
    mov edx, dword ptr [ecx+0x9ed0]
    and edx, 3
    fld dword ptr [{CAM_MODES:#x}+edx*4]
    jmp 0x004018d7
""", CAM_CAVE, CAM_CAVE + 0x40)
_cam_eye = _s2asm(f"""
    movaps xmm5, xmm0
    mulss xmm5, dword ptr [{CAM_K:#x}]
    addss xmm5, xmm3
    jmp 0x004019c7
""", CAM_CAVE + 0x40, CAM_CAVE + 0x80)
_cam_aim = _s2asm(f"""
    mulss xmm0, dword ptr [{CAM_K + 4:#x}]
    addss xmm2, xmm5
    jmp 0x00401aa7
""", CAM_CAVE + 0x80, CAM_CAVE + 0xC0)
PATCHES["camfix"] = [
    (0x004018D1, bytes.fromhex("db81d09e0000"), _s2jmp(0x004018D1, CAM_CAVE, 6),
     f"chase camera: the view's distance from a table (close x{CAM_CLOSE:g})"),
    (CAM_CAVE, bytes(len(_cam_mode)), _cam_mode, f"camera view-distance cave ({len(_cam_mode)} bytes)"),
    (0x004019BC, bytes.fromhex("0f28e8f30f59eef30f58eb"), _s2jmp(0x004019BC, CAM_CAVE + 0x40, 11),
     f"chase camera: eye height 0.5 -> {0.5 + CAM_LIFT:g} x distance"),
    (CAM_CAVE + 0x40, bytes(len(_cam_eye)), _cam_eye, f"camera eye-height cave ({len(_cam_eye)} bytes)"),
    (0x00401A9F, bytes.fromhex("f30f59c3f30f58d5"), _s2jmp(0x00401A9F, CAM_CAVE + 0x80, 8),
     f"chase camera: aim height 1/3 -> {1 / 3 + CAM_LIFT:.3f} x distance (same angle, lifted)"),
    (CAM_CAVE + 0x80, bytes(len(_cam_aim)), _cam_aim, f"camera aim-height cave ({len(_cam_aim)} bytes)"),
    (CAM_MODES, bytes(16), struct.pack("<4f", 0.0, CAM_CLOSE, 2.0, 3.0), f"views 0..3: 0 / {CAM_CLOSE:g} / 2 / 3"),
    (CAM_K, bytes(8), struct.pack("<ff", 0.5 + CAM_LIFT, 0.3333 + CAM_LIFT), "eye / aim heights x distance"),
]


# ---- quietexit: quitting the game opens nothing (player 2026-11-01: "not opening the game's root folder") -----
# On exit the game calls ShellExecuteA(0, "open", "http://www.gametop.com/stats/cityracing.html/", 0, 0, 3)
# (0x0045714d..0x00457161). The install's baseline blanks that URL to "" (no phoning home), but ShellExecuteA
# with an EMPTY target opens the current folder = the game folder in Explorer. 0x0045714d `push 3` -> `jmp
# 0x00457162`: the six pushes and the call are skipped together, so the stack is untouched; shutdown goes on.
PATCHES["quietexit"] = [
    (0x0045714D, bytes.fromhex("6a03"), bytes.fromhex("eb13"),
     "exit: skip ShellExecuteA (it opened the game folder in Explorer)"),
]


# ---- newaudio: the player's own music + ambience (player 2026-11-01, newaudio.py builds "New audio\") --------
# Music: 0x0046e226.. srand + rand(): `and eax, 0x80000007 ; jns ; dec ; or eax,-8 ; inc` = rand % 8, then
# `inc eax` -> TrR01..TrR08 (sprintf "Data/Audio/MusTrks/TrR%02d.wav"). -> `cdq ; mov ecx,9 ; idiv ecx ;
# mov eax,edx` (rand() >= 0, so the remainder is 0..8) -> TrR01..TrR09; ecx/edx are dead (the next call clobbers
# them). TrR09.wav is a LOOSE file: the sound loader 0x0046bf60 opens every WAV as a plain file first (open mode
# 1 = fopen "rb", 0x0046c096) and only then from SD.pak (0x1770).
# Ambience: the list Data/Audio/AmbTrks/AmbientData.obj (Objects.pak - rebuilt from pristine by the Car Tuner)
# is redirected by renaming the exe's string to AmbientDat2.obj (same length), AND its open at 0x0046d877 goes
# from mode 0x3e8 (= the Objects archive ONLY - in normal mode 0x0046fb50 has NO loose fallback for archive ids;
# a missing name left every list empty and the ambience pick 0x0046e3e6 `div` crashed, 2026-11-01) to mode 0
# (fopen "rt"): the loose PLAIN file, read by plain fgets (handles < 0x3e8, 0x0046eca0). Must stay installed:
# without the file the lists are empty and the game crashes exactly like that.
NA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "New audio")
NA_FILES = [r"Data\Audio\MusTrks\TrR09.wav", r"Data\Audio\AmbTrks\AmbCityX01.wav",
            r"Data\Audio\AmbTrks\AmbFrstN04.wav", r"Data\Audio\AmbTrks\AmbientDat2.obj"]
PATCHES["newaudio"] = [
    (0x0046E237, bytes.fromhex("250700008079054883c8f840"), bytes.fromhex("99b909000000f7f989d09090"),
     "race music: pick TrR01..TrR09 (rand % 9) instead of TrR01..TrR08"),
    (0x0056C2E7, b"AmbientData.obj", b"AmbientDat2.obj",
     "ambience list -> the loose Data/Audio/AmbTrks/AmbientDat2.obj (with the new tracks)"),
    (0x0046D877, bytes.fromhex("68e8030000"), bytes.fromhex("6800000000"),
     "ambience list: opened as a plain file (mode 0, fopen 'rt') instead of from Objects.pak only"),
]


def install_files(src_dir, files, game_dir, label, dry=False):
    """copy built files (game-relative paths) next to the game; returns a one-line report"""
    missing = [f for f in files if not os.path.exists(os.path.join(src_dir, f))]
    if missing:
        return f"{label} MISSING in {src_dir}: {missing}"
    srcs = {f: open(os.path.join(src_dir, f), "rb").read() for f in files}
    dst = lambda f: os.path.join(game_dir, f)
    stale = [f for f in files if not os.path.exists(dst(f)) or open(dst(f), "rb").read() != srcs[f]]
    if dry:
        return f"{label}: {len(stale)} of {len(files)} would be copied" if stale else f"{label}: installed = built"
    for f in stale:
        os.makedirs(os.path.dirname(dst(f)), exist_ok=True)
        with open(dst(f), "wb") as out:
            out.write(srcs[f])
    ok = all(open(dst(f), "rb").read() == srcs[f] for f in files)
    return f"{label}: copied {len(stale)}, all {len(files)} {'verified' if ok else 'DIFFER'}"


def install_dial_faces(game_dir, dry=False):
    """copy the 8 rpm faces next to the game (loose files); returns a one-line report"""
    dst_dir = os.path.join(game_dir, RD_GAME_DIR)
    missing = [f for f in RD_FACES if not os.path.exists(os.path.join(RD_FACES_DIR, f))]
    if missing:
        return f"rpm faces MISSING in {RD_FACES_DIR}: {missing} - run dial_faces.py"
    srcs = {f: open(os.path.join(RD_FACES_DIR, f), "rb").read() for f in RD_FACES}
    stale = [f for f in RD_FACES if not os.path.exists(os.path.join(dst_dir, f))
             or open(os.path.join(dst_dir, f), "rb").read() != srcs[f]]
    if dry:
        return f"rpm faces: {len(stale)} of 8 would be copied" if stale else "rpm faces: installed = built"
    os.makedirs(dst_dir, exist_ok=True)
    for f in stale:
        with open(os.path.join(dst_dir, f), "wb") as out:
            out.write(srcs[f])
    ok = all(open(os.path.join(dst_dir, f), "rb").read() == srcs[f] for f in RD_FACES)
    return f"rpm faces: copied {len(stale)}, all 8 {'verified' if ok else 'DIFFER'} in {dst_dir}"

# ---- laa: Large Address Aware - 4 GB of address space instead of 2 (parked since 2026-09-25) ----
# A 32-bit exe without IMAGE_FILE_LARGE_ADDRESS_AWARE (0x20) gets 2 GB of user address space even on
# 64-bit Windows; with it, 4 GB. The game's peak was 1664 MB VIRTUAL of the 2048 (81%, view 1600,
# 2026-09-25), before Panini supersampling up to 4x (D3D9 maps part of every render target into the
# process). The flag only lets allocations land above 2 GB; it changes no code. The known risk with
# old games is code that treats pointers as signed numbers - so this is a switch, and memwatch.ps1
# should watch the first long session with it (anything above 2048 MB = it is being used).
# PE file header Characteristics (pe 0x118 + 0x16 = 0x0040012e): 0x0103 -> 0x0123.
PATCHES["laa"] = [
    (0x0040012E, struct.pack("<H", 0x0103), struct.pack("<H", 0x0123),
     "PE Characteristics + LARGE_ADDRESS_AWARE: 4 GB address space instead of 2"),
]

# Patch groups that persist across race-level changes (see the state file).
EXTRAS = ("view", "overlay", "racers", "shadows", "nodamage", "panini", "fixedstep", "engineloop",
          "awdfix", "gravity", "revboost", "policeeyes", "evade", "morepolice", "wantedhits", "smartpolice", "policefix", "rayfast", "milkyway", "boardkeep", "racereset", "adaptive", "laa",
          "nightlock", "darknight", "headlights", "hlcars", "manual", "manpower", "drivetrain", "aigears",
          "realcar", "carsounds", "keeplivery", "hudfix", "rpmdial", "racergod", "policedmg", "markskeep", "camfix", "quietexit", "newaudio")

# Every level carries astarfix: it changes nothing in the stock game (300/300 identical
# routes in racesim) and is what stops U-turn-heavy levels overflowing.
# Designed from the racesim matrix (2026-09-23, 1,200 courses each, 0 overflows):
#   stock    50% of attempts dead-end and silently retry; U-turns 0.3%; ~580 cells
#   twisty   0% fail, U-turns in 98.5% of races (~6 each), length a lottery 171..1967
#   wild     0% fail, U-turns 100% (~10 each), always long ~1880 cells (~7.5 km)
#   anarchy  ~1% fail, ~20 U-turns each, tight zig-zag ~290 cells staying ~40 cells
#            from the billboard - the walk turns into Brownian motion
LEVELS = {
    1: ("mild", ["astarfix", "reshuffle"]),
    2: ("twisty", ["astarfix", "reshuffle", "wander", "spread"]),
    # nostep without wander can dead-end the walk, which fails the course and removes the
    # billboard - so they ship together.
    3: ("wild", ["astarfix", "reshuffle", "nostep", "wander", "junction"]),
    4: ("insane", ["astarfix", "reshuffle", "nostep", "wander", "junction", "noseed"]),
    5: ("anarchy", ["astarfix", "reshuffle", "nostep", "wander", "junction", "noseed",
                    "reverse"]),
    # Designed by the player, 2026-09-23: "Level Chaos". U-turns + lottery lengths, with
    # the A* bug deliberately LIVE so the rare straight-line / ocean jumps come back.
    6: ("chaos", ["-astarfix", "wander", "spread"]),
    # "Level Chaos Leap" (the player's name): Chaos's U-turns and lottery lengths, plus
    # deliberate straight-line leaps between roads. It carries the A* fix, so unlike
    # Chaos this one cannot overflow.
    7: ("chaos leap", ["astarfix", "leap", "wander", "spread"]),
}


def find_level(key):
    """A level by number ('7') or name ('chaos leap', 'chaosleap', 'chaos-leap').
    Returns (number, name, patches), or None."""
    norm = lambda s: str(s).lower().replace(" ", "").replace("-", "").replace("_", "")
    key = norm(key)
    for num, (name, names) in LEVELS.items():
        if key in (str(num), norm(name)):
            return num, name, names
    return None
REQUIRES = {"nostep": ["wander"], "leap": ["slack", "astarfix"],
            "view": ["slack", "rdataslack", "rdataexec", "glow", "racerfree", "fadein",
                     "spawnreach"],
            "racerfree": ["slack"], "fadein": ["slack", "rdataslack"],
            "spawnreach": ["slack", "rdataslack"], "nodamage": ["rdataslack", "rdataexec"],
            "racers": ["dataslack"], "panini": ["modsect"], "fixedstep": ["modsect"],
            "engineloop": ["modsect"], "awdfix": ["modsect"], "gravity": ["modsect"], "revboost": ["modsect"],
            "policeeyes": ["modsect"], "morepolice": ["modsect"], "wantedhits": ["modsect"], "evade": ["modsect"], "smartpolice": ["modsect"], "rayfast": ["modsect"], "policefix": ["modsect"], "milkyway": ["modsect"], "boardkeep": ["modsect"], "racereset": ["modsect"],
            "adaptive": ["modsect", "fixedstep"], "nightlock": ["modsect"], "darknight": ["modsect"],
            "headlights": ["modsect", "hlsect"], "hlcars": ["headlights"], "manual": ["modsect"],
            "manpower": ["manual"], "drivetrain": ["modsect"], "aigears": ["drivetrain"], "realcar": ["drivetrain"],
            "carsounds": ["modsect"], "keeplivery": ["modsect"], "hudfix": ["drivetrain"],
            "rpmdial": ["hudfix"], "racergod": ["crashhook"], "policedmg": ["crashhook"], "markskeep": ["modsect", "tmsect"], "tmsect": ["hlsect"], "camfix": ["hlsect"],
            "crashhook": ["modsect"]}
# a newer extra that does the same job as older ones: ticking it switches them off
SUPERSEDES = {"drivetrain": ["manual", "manpower"]}
# Extras that carry a number (`extras on fixedstep 60`, `extras on gravity 1.62`, the panel's sliders):
# name -> (state-file key, setter (raises ValueError), current value, unit, (lo, hi), default)
VALUED = {
    "fixedstep": ("fixedstep_hz", lambda v: set_fixed_hz(v), lambda: FIXED_HZ, "Hz", FIXED_HZ_RANGE,
                  FIXED_HZ_DEFAULT),
    "gravity": ("gravity_ms2", lambda v: set_gravity(v), lambda: GRAVITY, "m/s2", GRAVITY_RANGE,
                GRAVITY_DEFAULT),
    "policeeyes": ("police_see_m", lambda v: set_police_see(v), lambda: POLICE_SEE, "m", POLICE_SEE_RANGE,
                   POLICE_SEE_DEFAULT),
    "evade": ("police_evade_m", lambda v: set_evade(v), lambda: EVADE, "m", EVADE_RANGE, EVADE_DEFAULT),
    "milkyway": ("milkyway_bright", lambda v: set_milkyway(v), lambda: MW_BRIGHT, "x", MW_BRIGHT_RANGE,
                 MW_BRIGHT_DEFAULT),
    "morepolice": ("police_max", lambda v: set_police_max(v), lambda: POLICE_MAX, "cars", POLICE_MAX_RANGE,
                   POLICE_MAX_DEFAULT),
    "policedmg": ("police_dmg_x", lambda v: set_police_dmg(v), lambda: POLICE_DMG, "x", POLICE_DMG_RANGE,
                  POLICE_DMG_DEFAULT),
    "markskeep": ("marks_keep_min", lambda v: set_marks_keep(v), lambda: MARKS_KEEP, "min", MARKS_KEEP_RANGE,
                  MARKS_KEEP_DEFAULT),
    "boardkeep": ("board_keep_m", lambda v: set_board_keep(v), lambda: BOARD_KEEP, "m", BOARD_KEEP_RANGE,
                  BOARD_KEEP_DEFAULT),
    "racereset": ("race_reset_m", lambda v: set_race_reset(v), lambda: RACE_RESET, "m", RACE_RESET_RANGE,
                  RACE_RESET_DEFAULT),
    "nightlock": ("nightlock_hour", lambda v: set_nightlock(v), lambda: NIGHTLOCK, "h", NIGHTLOCK_RANGE,
                  NIGHTLOCK_DEFAULT),
    "darknight": ("darknight_k", lambda v: set_darknight(v), lambda: DARKNIGHT, "x", DARKNIGHT_RANGE,
                  DARKNIGHT_DEFAULT),
    "headlights": ("headlight_gain", lambda v: set_headlights(v), lambda: HL_GAIN, "x", HL_GAIN_RANGE,
                   HL_GAIN_DEFAULT),
    "hlcars": ("headlight_cars", lambda v: set_hlcars(v), lambda: HL_CARS, "lit cars", HL_CARS_RANGE,
               HL_CARS_DEFAULT),
    "manual": ("manual_gears", lambda v: set_manual(v), lambda: MAN_GEARS, "gears", MAN_GEARS_RANGE,
               MAN_GEARS_DEFAULT),
    "manpower": ("manual_power", lambda v: set_manpower(v), lambda: MAN_POWER_PCT, "%", MAN_POWER_RANGE,
                 MAN_POWER_DEFAULT),
    "drivetrain": ("drivetrain_power", lambda v: set_drivetrain(v), lambda: DT_POWER, "%", DT_POWER_RANGE,
                   DT_POWER_DEFAULT),
}
# Extras that patch the same bytes: never together (apply refuses and says which to untick).
CONFLICTS = {"policefix": ["smartpolice"]}
REQUIRES_WHY = {
    "tmsect": "the bigger tyre-mark pool lives in a 7th exe section right after the headlights' one",
    "crashhook": "God mode for racers and Weaker police cars share one hook in the crash-damage code",
    "wander": "on its own nostep can dead-end the walk, which fails the course and "
              "removes the billboard",
    "slack": "its code/constants live in the .text slack, which needs the VirtualSize bump",
    "astarfix": "the leap gate hands every normal search to A*'s entry, where the fix lives",
    "glow": "more lights in view overflow the light-glow batches (flicker, and a 2005 "
            "index-buffer overrun)",
    "dataslack": "the racer list lives in the .data tail, which needs the VirtualSize bump",
    "rdataslack": "the view constants live in the .rdata tail, which needs the VirtualSize bump",
    "racerfree": "with 60 cars, race opponents must not eat the traffic target, and the "
                 "total must stay within the 64-slot list",
    "fadein": "most new cars appear inside the fade band (the spawn ring is centred on a "
              "road cell, not the camera), so they must fade in over time or they pop in",
    "spawnreach": "the spawn ring's road-cell centre can put new cars past the despawn line, "
                  "where they are deleted on their first frame (27% of spawns)",
    "rdataexec": "the lamp-range, corona-cap and no-damage code caves live in the .rdata "
                 "tail, which must be executable",
    "modsect": "its code and shader text live in the new .crmod section (the old slack is full)",
    "fixedstep": "adaptive reads the physics rate (its floor) from fixedstep's 1/Hz constant",
    "hlsect": "its effect text and 1 MB beam texture live in a 6th exe section (.crhl)",
    "headlights": "it limits how many cars the headlights extra lights",
}
# Applied before everything else, in this order: hlsect edits the header fields modsect wrote,
# and hlcars edits a dword the headlights data block wrote (see `state` for how that reads back).
ORDER_FIRST = ("modsect", "hlsect", "tmsect", "headlights", "manual", "drivetrain", "crashhook")
# Anything that produces U-turns or long walks triggers the A* stale-count bug, so it
# must bring astarfix. `cap` is no longer auto-added: with the fix, a route never grows
# past its walk (worst ratio 0.97 over 1,200 uncapped level-3 courses), and the game's
# own 2048-point check bounds the walk.
NEEDS_FIX = ("wander", "reverse", "nostep", "spread")


# ------------------------------------------------------------------ PE plumbing
def sections(buf):
    pe = struct.unpack_from("<I", buf, 0x3C)[0]
    n = struct.unpack_from("<H", buf, pe + 6)[0]
    opt = struct.unpack_from("<H", buf, pe + 20)[0]
    img = struct.unpack_from("<I", buf, pe + 24 + 28)[0]
    out = []
    for i in range(n):
        o = pe + 24 + opt + i * 40
        vsz, va, rsz, raw = struct.unpack_from("<4I", buf, o + 8)
        out.append((img + va, vsz, raw, rsz))
    return out


def va2raw(buf, va):
    """Virtual address -> file offset. Computed from the headers, never hardcoded,
    so the patcher cannot be fooled by a differently-laid-out build.

    Covers bytes past a section's VirtualSize that are still in the file (the .text
    slack the `leap` code lives in), and the PE headers, which map 1:1 at the base.
    The appended `.crmod` section maps whether or not its header is in `buf` yet, so the
    order `modsect` and its users are applied in does not matter."""
    if MOD_VA <= va < MOD_VA + MOD_RSIZE:
        return MOD_RAW + (va - MOD_VA)
    if HL_VA <= va < HL_VA + HL_RSIZE:
        return HL_RAW + (va - HL_VA)
    for base, vsz, raw, rsz in sections(buf):
        if base <= va < base + max(vsz, rsz):
            return raw + (va - base)
    pe = struct.unpack_from("<I", buf, 0x3C)[0]
    img = struct.unpack_from("<I", buf, pe + 24 + 28)[0]
    if img <= va < img + 0x1000:
        return va - img
    raise ValueError(f"VA 0x{va:08x} is not in any section")


def read_at(buf, va, n):
    """n bytes at `va`. Past the end of the file they read as zero: that is what an
    unpatched exe 'holds' where the appended .crmod section will go."""
    r = va2raw(buf, va)
    cur = bytes(buf[r:r + n])
    return cur + bytes(n - len(cur))


def put(buf, va, orig, new):
    """Write one patch edit into `buf` (a bytearray) if `orig` is what is there; grows the
    file with zeros when the edit lies past its end. Returns None, or the bytes found."""
    cur = read_at(buf, va, len(orig))
    if cur != orig:
        return cur
    r = va2raw(buf, va)
    if r + len(new) > len(buf):
        buf.extend(bytes(r + len(new) - len(buf)))
    buf[r:r + len(new)] = new
    return None


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq game.exe"],
                         capture_output=True, text=True).stdout
    return "game.exe" in out


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def ensure_backup():
    """Snapshot a clean baseline to rebuild from.

    Deliberately prefers the LIVE game.exe over the factory one, as long as the live
    file carries none of our patches. The install has an unrelated local edit - one byte
    at 0x0056aa0c that blanks the 'h' of http://www.gametop.com/stats/cityracing.html so
    the game cannot phone home - and restoring from the factory copy would silently undo
    it. Falling back to the factory file only happens if the live one is already patched,
    in which case it is not a clean baseline at all.
    """
    if os.path.exists(BACKUP):
        return
    live = open(GAME, "rb").read()
    if all(v == "off" for v in state(live).values()):
        shutil.copy2(GAME, BACKUP)
        print(f"baseline taken from the live game.exe -> {BACKUP}")
    elif os.path.exists(STOCK):
        shutil.copy2(STOCK, BACKUP)
        print(f"live game.exe is already patched; baseline taken from the factory copy")
    else:
        raise SystemExit("no clean baseline available - restore game.exe by hand first")


def state(buf):
    """For each patch: 'on', 'off', or 'ALIEN' if the bytes match neither. An edit that another patch
    stacked on top of (its orig = this edit's new: hlsect over modsect's header fields, hlcars over the
    headlights data) reads as 'on' when the top edit is there."""
    out = {}
    above = {(va, orig): new for edits in PATCHES.values() for va, orig, new, _ in edits}
    below = {(va, new): orig for edits in PATCHES.values() for va, orig, new, _ in edits}

    def chain(d, va, x):
        # every value stacked on (or under) x, any depth: modsect -> hlsect -> tmsect edit the same header fields
        out_, x0 = [], x
        while (va, x) in d and d[(va, x)] != x and d[(va, x)] not in out_ and d[(va, x)] != x0:
            x = d[(va, x)]
            out_.append(x)
        return out_
    for name, edits in PATCHES.items():
        seen = set()
        for va, orig, new, _ in edits:
            cur = read_at(buf, va, len(orig))
            seen.add("on" if cur == new or cur in chain(above, va, new)
                     else "off" if cur == orig or cur in chain(below, va, orig)
                     else "ALIEN")
        out[name] = seen.pop() if len(seen) == 1 else "PARTIAL"
    # an extra replaced by a newer one at the same hook sites reads as off, not as half-there
    for new, olds in SUPERSEDES.items():
        if out.get(new) == "on":
            out.update({o: "off" for o in olds})
        elif out.get(new) == "PARTIAL" and any(out.get(o) == "on" for o in olds):
            out[new] = "off"                     # its hook sites are the old extra's
    # two extras that patch the same bytes: while one is on, the other has only its shared bytes
    # "different" - it is off, not half-there (policefix next to smartpolice)
    for a, others in CONFLICTS.items():
        for b in others:
            for x, y in ((a, b), (b, a)):
                if out.get(x) == "on" and out.get(y) == "PARTIAL":
                    out[y] = "off"
    return out


# --------------------------------------------------------------------- commands
def cmd_show():
    buf = open(GAME, "rb").read()
    print(f"game.exe  {len(buf):,} bytes  sha256 {sha(GAME)[:16]}...")
    if os.path.exists(STOCK):
        print(f"  {'MATCHES' if sha(GAME) == sha(STOCK) else 'differs from'} "
              f"the verified original")
    print()
    for name, st in state(buf).items():
        mark = {"on": "[ON ]", "off": "[   ]"}.get(st, f"[{st}]")
        print(f"  {mark} {name}")
        for va, orig, new, why in PATCHES[name]:
            cur = buf[va2raw(buf, va):va2raw(buf, va) + len(orig)]
            print(f"          0x{va:08x}  {cur.hex():<10} {why}")


# ------------------------------------------------------------ state + Game.ini
# The race level and the EXTRAS (view, overlay) are remembered separately, so switching
# race level keeps the extras. Every build still starts from the pristine baseline.
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "racemod_state.json")
INI = os.path.join(os.path.dirname(GAME), "Game.ini")


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".new"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE)


def ini_get(key):
    try:
        text = open(INI, "rb").read().decode("latin-1")
    except OSError:
        return None
    m = re.search(rf"(?m)^{re.escape(key)}=([^\r\n]*)", text)
    return m.group(1) if m else None


def ini_set(key, value):
    """Replace one key's value, byte-preserving everything else (CRLF, no BOM)."""
    raw = open(INI, "rb").read().decode("latin-1")
    new, n = re.subn(rf"(?m)^({re.escape(key)}=)[^\r\n]*", lambda mm: mm.group(1) + value, raw,
                     count=1)
    if n != 1:
        raise RuntimeError(f"{key}= not found in Game.ini")
    tmp = INI + ".new"
    with open(tmp, "wb") as f:
        f.write(new.encode("latin-1"))
    os.replace(tmp, INI)


def sync_ini(view_on, st):
    """view raises the Distance cap to VIEW_DISTANCE, which is Game.ini Distance=M/200-1 (the
    game computes (v+1)*200). The game READS the ini at start and REWRITES [Video] on exit, so
    this only happens while the game is closed (apply() refuses otherwise)."""
    cur = ini_get("Distance")
    want = str(int(VIEW_DISTANCE) // 200 - 1)
    if view_on:
        if "ini_distance_before" not in st:
            st["ini_distance_before"] = cur if cur is not None else "2"
        if cur != want:
            ini_set("Distance", want)
            print(f"  Game.ini: Distance={cur} -> {want}  (view distance {VIEW_DISTANCE:g})")
    elif "ini_distance_before" in st:
        before = st.pop("ini_distance_before")
        if cur != before:
            ini_set("Distance", before)
            print(f"  Game.ini: Distance={cur} -> {before}  (restored)")


def derive_race():
    """Rebuild the race patch list from the live exe when no state file exists yet."""
    live = state(open(GAME, "rb").read())
    race = [n for n, s in live.items()
            if s == "on" and n not in EXTRAS
            and n not in ("slack", "glow", "pedanchor", "dataslack", "rdataslack", "racerfree")]
    if any(n in race for n in NEEDS_FIX) and "astarfix" not in race and "leap" not in race:
        race.insert(0, "-astarfix")            # it can only have been Level Chaos
    return race


def apply(names, restore_first=True, extras=None, record=True, dry=False):
    """dry=True: build the result in memory only and report its sha256 (game.exe is not touched)."""
    if not dry and game_running():
        print("ABORT: game.exe is running - close City Racing first.")
        return 1
    st0 = load_state()
    if extras is None:
        extras = list(st0.get("extras", []))
    requested = [n for n in names if n not in EXTRAS]           # the race part, as asked
    extras = extras + [n for n in names if n in EXTRAS and n not in extras]
    names = requested + extras
    # "-astarfix" = the player deliberately wants the 2005 A* bug live (ocean jumps).
    no_fix = "-astarfix" in names
    names = [n for n in names if n != "-astarfix"]
    bad = [n for n in names if n not in PATCHES]
    if bad:
        print(f"unknown patch(es): {bad}\nknown: {', '.join(PATCHES)}")
        return 2
    if no_fix and "leap" in names:
        print("REFUSED: 'leap' needs the A* fix, so it cannot run with '-astarfix'. "
              "Nothing was written.")
        return 2
    for new, olds in SUPERSEDES.items():
        if new in names and any(o in names for o in olds):
            gone = [o for o in olds if o in names]
            print(f"note: '{new}' replaces {', '.join(repr(o) for o in gone)} - switching "
                  f"{'it' if len(gone) == 1 else 'them'} off.")
            names = [n for n in names if n not in gone]
            extras = [n for n in extras if n not in gone]
    if "drivetrain" in names and not os.path.exists(DT_DLL_SRC):
        print(f"REFUSED: 'drivetrain' needs {DT_DLL_NAME}, which is not built yet ({DT_DLL_SRC}). "
              f"Nothing was written.")
        return 2
    for a, others in CONFLICTS.items():
        clash = [b for b in others if a in names and b in names]
        if clash:
            print(f"REFUSED: '{a}' and '{clash[0]}' change the same police code - tick only one of them. "
                  f"Nothing was written.")
            return 2
    for need, deps in REQUIRES.items():
        for dep in deps:
            if need in names and dep not in names:
                print(f"note: '{need}' needs '{dep}' - {REQUIRES_WHY.get(dep, '')}. "
                      f"Adding it.")
                names.append(dep)
    if no_fix:
        print("WARNING: astarfix deliberately OFF. The game's A* bug is live: routes can "
              "jump in straight lines\n         (over water too), and a long course can "
              "overflow the route buffer - that is\n         a possible crash to desktop, "
              "or billboards stopping until you restart.\n")
    elif any(n in names for n in NEEDS_FIX) and "astarfix" not in names:
        print("note: U-turns and long walks trigger the game's A* stale-count bug, which "
              "overflows the route buffer. Adding 'astarfix'.")
        names.insert(0, "astarfix")
    names = [n for n in ORDER_FIRST if n in names] + [n for n in names if n not in ORDER_FIRST]
    ensure_backup()
    # Always start from the pristine file so patches never stack or half-apply.
    buf = bytearray(open(BACKUP, "rb").read()) if restore_first \
        else bytearray(open(GAME, "rb").read())
    for name in names:
        for va, orig, new, why in PATCHES[name]:
            found = put(buf, va, orig, new)
            if found is not None:
                print(f"REFUSED: 0x{va:08x} holds {found[:32].hex()}, "
                      f"expected {orig[:32].hex()}. Nothing was written.")
                return 3
            show = lambda b: b.hex() if len(b) <= 24 else f"{b[:12].hex()}... ({len(b)} bytes)"
            print(f"  patched 0x{va:08x}  {show(orig)} -> {show(new)}   {why}")
    if dry:
        if os.environ.get("RACEMOD_DRY_OUT"):            # tools only (loadertest.py): keep the built bytes
            with open(os.environ["RACEMOD_DRY_OUT"], "wb") as f:
                f.write(bytes(buf))
        st = state(bytes(buf))
        okall = all(st[n] == "on" for n in names)
        new_sha = hashlib.sha256(bytes(buf)).hexdigest()
        cur_sha = sha(GAME) if os.path.exists(GAME) else ""
        print(f"\nDRY RUN - game.exe not touched. The build would be {len(buf):,} bytes, "
              f"sha256 {new_sha[:16]}, self-check {'OK' if okall else 'FAILED'}; "
              f"{'IDENTICAL to' if new_sha == cur_sha else 'different from'} the installed game.exe "
              f"({cur_sha[:16]}).")
        if "drivetrain" in names:
            dst = os.path.join(os.path.dirname(GAME), DT_DLL_NAME)
            newer = not os.path.exists(dst) or open(DT_DLL_SRC, "rb").read() != open(dst, "rb").read()
            print(f"{DT_DLL_NAME}: {'a NEWER build is waiting - Apply installs it' if newer else 'installed = built'}.")
        if "rpmdial" in names:
            print(install_dial_faces(os.path.dirname(GAME), dry=True))
        if "newaudio" in names:
            print(install_files(NA_DIR, NA_FILES, os.path.dirname(GAME), "new audio", dry=True))
        return 0 if okall else 1
    tmp = GAME + ".new"
    with open(tmp, "wb") as f:
        f.write(buf)
    os.replace(tmp, GAME)
    if "drivetrain" in names:
        dst = os.path.join(os.path.dirname(GAME), DT_DLL_NAME)
        shutil.copy2(DT_DLL_SRC, dst)
        same = open(DT_DLL_SRC, "rb").read() == open(dst, "rb").read()
        print(f"copied {DT_DLL_NAME} ({os.path.getsize(dst):,} bytes) next to game.exe: "
              f"{'verified' if same else 'COPY DIFFERS'}")
    if "rpmdial" in names:
        print(install_dial_faces(os.path.dirname(GAME)))
    if "newaudio" in names:
        print(install_files(NA_DIR, NA_FILES, os.path.dirname(GAME), "new audio"))
    # read back and confirm every patch took
    st = state(open(GAME, "rb").read())
    okall = all(st[n] == "on" for n in names)
    print(f"\nwrote game.exe, {len(buf):,} bytes. "
          f"verification: {'OK' if okall else 'FAILED'}")
    for n, s in st.items():
        if s != "off":
            print(f"   {n}: {s}")
    if okall and record:
        st1 = load_state()
        st1["race"] = requested
        st1["extras"] = extras
        sync_ini("view" in extras, st1)
        save_state(st1)
        if extras:
            print(f"extras kept on: {', '.join(extras)}")
    return 0 if okall else 1


def cmd_restore():
    if game_running():
        print("ABORT: game.exe is running - close City Racing first.")
        return 1
    src = BACKUP if os.path.exists(BACKUP) else STOCK
    if not os.path.exists(src):
        print("no pristine copy to restore from")
        return 2
    shutil.copy2(src, GAME)
    print(f"restored from {src}")
    st = state(open(GAME, "rb").read())
    print(f"  all patches off: {all(v == 'off' for v in st.values())}")
    s = load_state()
    if s.get("extras"):
        print(f"  extras switched off too: {', '.join(s['extras'])}")
    s["race"], s["extras"] = [], []
    sync_ini(False, s)
    save_state(s)
    if os.path.exists(STOCK) and sha(GAME) != sha(STOCK):
        print("  (differs from the factory game.exe by design - the baseline keeps the "
              "local edit at 0x0056aa0c that blanks the gametop.com stats URL)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "show":
        cmd_show()
    elif cmd == "restore":
        sys.exit(cmd_restore())
    elif cmd == "level":
        lv = find_level(" ".join(a[1:])) if len(a) > 1 else None
        if not lv:
            print("levels: " + ", ".join(f"{k}={v[0]}" for k, v in LEVELS.items())
                  + "   (by number or name, e.g.  level 6  or  level chaos)")
            sys.exit(2)
        num, nm, names = lv
        print(f"level {num} ({nm}): {', '.join(names)}\n")
        sys.exit(apply(names))
    elif cmd == "apply":
        if len(a) < 2:
            print("known patches: " + ", ".join(PATCHES))
            sys.exit(2)
        sys.exit(apply(a[1:]))
    elif cmd == "chaos":
        # The race-route switch (player 2026-09-26: "play it as what it was meant to be, but with
        # our Stage 1 modifications ... Off is normal unpatched race lines RNG, On is our cursed
        # chaos one"). Only the RACE patches change; every extra (view, panini, nodamage, ...)
        # stays. `off` remembers the chaos patches in the state file so `on` brings the same back.
        # OFF = NO race patches at all, the 2005 A* bug included (player 2026-09-26: "disable
        # astarfix if I set chaos to off ... you know why"): they saw that bug in the unmodified
        # game, twice in years - a race line into the ocean, one straight across a river - and it
        # is part of the game as it was meant to be. In stock it only fires on a start==end search,
        # which the stock walk almost never makes; the overflows needed our chaos walks. racesim:
        # no race patches + all extras = 200/200 routes identical to the unmodified game.
        # A race list of only `astarfix` (the OFF of the first version) does not count as chaos,
        # so switching off from it never overwrites the remembered chaos level.
        STOCK_RACE = []
        s = load_state()
        race = s.get("race")
        if race is None:
            race = derive_race()
        chaos_on = any(n not in ("astarfix",) for n in race)
        extras = list(s.get("extras", []))
        saved = s.get("chaos_race") or LEVELS[7][1]
        if len(a) == 1:
            print(f"chaos is {'ON: ' + ', '.join(race) if chaos_on else 'OFF: stock race routes' + (' (+ A* fix)' if race else ', pure 2005')}")
            print(f"`chaos on` brings back: {', '.join(race if chaos_on else saved)}")
            print(f"extras (unaffected): {', '.join(extras) or '(none)'}")
            sys.exit(0)
        if a[1] == "off":
            if chaos_on:
                s["chaos_race"] = race
                save_state(s)
            print(f"chaos OFF: stock race routes, pure 2005 - the rare ocean line included "
                  f"(remembered for `chaos on`: {', '.join(race if chaos_on else saved)})\n")
            sys.exit(apply(STOCK_RACE, extras=extras))
        if a[1] == "on":
            print(f"chaos ON: {', '.join(saved)}\n")
            sys.exit(apply(list(saved), extras=extras))
        print("usage: chaos            show\n       chaos off        stock race routes, extras kept\n"
              "       chaos on         your chaos level back")
        sys.exit(2)
    elif cmd == "setup":
        # The control panel (crpanel.py, player 2026-09-27: "a GUI app so I can turn on or turn off
        # every single thing ... so I never open your chat, search for values, and put it on
        # PowerShell every time"). ONE rebuild for a whole configuration, given as a JSON file:
        #   {"extras": [...], "race": "keep" | "stock" | "chaos" | "level:N",
        #    "fixedstep_hz": 60, "panini": {"fov": 160, "vfov": 100, "scale": 2.0, "chase": 0.84},
        #    "dry_run": false}
        # The settings are checked BEFORE anything is built and saved only after a verified write.
        if len(a) < 2:
            print("usage: setup <config.json>   (written by crpanel.py)")
            sys.exit(2)
        try:
            with open(a[1]) as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"cannot read {a[1]}: {e}")
            sys.exit(2)
        s = load_state()
        extras = list(cfg.get("extras", s.get("extras", [])))
        bad = [e for e in extras if e not in EXTRAS]
        if bad:
            print(f"unknown extras {bad}; known: {', '.join(EXTRAS)}")
            sys.exit(2)
        extras = [e for e in EXTRAS if e in extras]                  # canonical order
        try:
            for name, (key, setter, cur, unit, rng, dflt) in VALUED.items():
                if cfg.get(key) is not None:
                    setter(float(cfg[key]))
            if cfg.get("carsounds") is not None:
                set_carsounds(cfg["carsounds"])
            if cfg.get("panini") is not None:
                import panini
                panini.configure(**{k: cfg["panini"].get(k) for k in panini.DEFAULTS})
                PATCHES["panini"] = _panini()
        except ValueError as e:
            print(f"REFUSED: {e}. Nothing was written.")
            sys.exit(2)
        cur_race = s.get("race")
        if cur_race is None:
            cur_race = derive_race()
        chaos_now = any(n not in ("astarfix",) for n in cur_race)
        spec = str(cfg.get("race", "keep"))
        remember = None
        if spec == "keep":
            race = list(cur_race)
        elif spec == "stock":
            race = []
            if chaos_now:
                remember = list(cur_race)
        elif spec == "chaos":
            race = list(s.get("chaos_race") or LEVELS[7][1])
        elif spec.startswith("level:") and spec[6:].isdigit() and int(spec[6:]) in LEVELS:
            race = list(LEVELS[int(spec[6:])][1])
            remember = race
        else:
            print(f"race must be keep / stock / chaos / level:1..{max(LEVELS)}, not {spec!r}")
            sys.exit(2)
        import panini
        print(f"race routes: {', '.join(race) if race else 'stock (pure 2005)'}")
        print(f"extras: {', '.join(extras) or '(none)'}")
        print(f"physics rate: {FIXED_HZ:g} Hz (cap {FIXED_MAX_SUBSTEPS})   gravity: {GRAVITY:g} m/s2   panini: "
              + ", ".join(f"{k} {v:g}" for k, v in panini.settings().items()) + "\n")
        dry = bool(cfg.get("dry_run"))
        rc = apply(race, extras=extras, dry=dry)
        if rc == 0 and not dry:
            s = load_state()
            for name, (key, setter, cur, unit, rng, dflt) in VALUED.items():
                s[key] = cur()
            s["panini"] = panini.settings()
            s["carsounds"] = dict(CARSOUNDS)
            if remember is not None:
                s["chaos_race"] = remember
            save_state(s)
            print("settings saved.")
        sys.exit(rc)
    elif cmd == "extras":
        s = load_state()
        cur = list(s.get("extras", []))
        if len(a) == 1:
            print(f"extras on: {', '.join(cur) or '(none)'}      available: {', '.join(EXTRAS)}")
            print(f"race level patches: {', '.join(s.get('race', [])) or '(stock)'}")
            print(f"physics rate (fixedstep): {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame"
                  f"{'' if 'fixedstep' in cur else '  (fixedstep is off: stock, one step per frame)'}")
            print(f"gravity: {GRAVITY:g} m/s2{'' if 'gravity' in cur else '  (gravity is off: stock 10)'}")
            print(f"Game.ini Distance={ini_get('Distance')}")
            sys.exit(0)
        mode, which = a[1], a[2:]
        # a number after a valued extra is its setting: `extras on fixedstep 60`, `extras on gravity 1.62`
        nums = [w for w in which if re.fullmatch(r"\d+(\.\d+)?", w)]
        which = [w for w in which if w not in nums]
        usage = f"usage: extras on|off {' '.join(EXTRAS)}" + "".join(
            f"\n       extras on {n} <{u}>   {rng[0]:g}..{rng[1]:g} (now {cur():g}, default {d:g})"
            for n, (k, st, cur, u, rng, d) in VALUED.items())
        if mode not in ("on", "off") or not which or any(w not in EXTRAS for w in which):
            print(usage)
            sys.exit(2)
        valued = None
        if nums:
            named = [w for w in which if w in VALUED]
            if mode != "on" or len(named) != 1 or len(nums) != 1:
                print("a number goes with exactly one of: "
                      + ", ".join(f"`extras on {n} <{v[3]}>`" for n, v in VALUED.items()) + "\n" + usage)
                sys.exit(2)
            valued = named[0]
            try:
                VALUED[valued][1](float(nums[0]))
            except ValueError as e:
                print(f"{e}\n{usage}")
                sys.exit(2)
            if valued == "fixedstep":
                print(f"physics rate: {FIXED_HZ:g} Hz, up to {FIXED_MAX_SUBSTEPS} steps a frame")
            else:
                print(f"{valued}: {VALUED[valued][2]():g} {VALUED[valued][3]}")
        new = cur + [w for w in which if w not in cur] if mode == "on" \
            else [e for e in cur if e not in which]
        race = s.get("race")
        if race is None:
            race = derive_race()
            print(f"(no state file yet - keeping the live race patches: {', '.join(race)})")
        rc = apply(race, extras=new)
        if rc == 0 and valued is not None:
            s = load_state()
            s[VALUED[valued][0]] = VALUED[valued][2]()
            save_state(s)
        sys.exit(rc)
    else:
        print(__doc__)
