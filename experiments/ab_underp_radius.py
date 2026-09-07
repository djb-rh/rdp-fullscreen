#!/usr/bin/env python3
"""A/B experiment: shrink the UNDERP's catalogue bounding radius.

render_log.csv showed the renderer drops a placement from the sorted draw list
once the camera is inside its bounding sphere (key = 0) and draws it by another
path - which works for the DOTLINE the car is on elsewhere (177) but not for
the one carrying the crossing (193).  The difference is overlap: at the
crossing the camera is inside 193's sphere, the UNDERP's (radius 10155, origin
1314 from the crossing) and the XOVER's at once.  If that path has a small
capacity, 193 loses to the UNDERP.  Shrinking the UNDERP's radius to RADIUS
keeps the camera out of its sphere except right at the crossing; if the road
either side of the bridge renders, the theory holds.  The UNDERP itself may
clip oddly at close range during the test - that is expected.

Catalogue entries are in the object ROM (obj10h/10k pair, offset OBJCAT + 18*i;
radius is the first word).  Writes roms_loop/racedriv/136077-2021.10h and
-2023.10k with Atari's byte-sum.  build_all.py re-stages stock and undoes it.
"""
import os, struct, sys, world
RADIUS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
w = world.World(); o = {w.name(i): i for i in range(390)}["UNDERP"]
obj = bytearray(w.obj)
r = o * 18                      # 18-byte catalogue records at the head of the object ROM
old = struct.unpack_from(">H", obj, r)[0]
struct.pack_into(">H", obj, r, RADIUS)
print("UNDERP (obj %d) catalogue at 0x%05X: radius %d -> %d" % (o, r, old, RADIUS))
OUT = "roms_loop/racedriv"
for name, suffix, phase, base in (("136077-2021.10h", 0x21, 0, 0), ("136077-2023.10k", 0x23, 1, 0)):
    half = bytearray(obj[base + phase: base + 0x20000: 2])
    pad = len(half) - 1
    while pad > 0 and half[pad] == 0: pad -= 1
    pad += 1
    assert pad < len(half)
    half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
    open(os.path.join(OUT, name), "wb").write(bytes(half))
    print("  %-18s byte-sum low 0x%02X (want 0x%02X) %s" % (name, sum(half) & 0xFF, suffix, "OK" if (sum(half)&0xFF)==suffix else "MISMATCH"))
