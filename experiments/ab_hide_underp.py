#!/usr/bin/env python3
"""A/B: clear the UNDERP placement's draw-enable bit (+0x22 bit 12).

The ADSP submits the crossing DOTLINE (193) every frame, sorts it nearest and
draws it LAST - and it still is not on screen.  The remaining explanation is a
per-frame polygon budget consumed far-to-near, so the nearest objects are the
ones dropped.  The UNDERP is the heaviest thing in view there (59 faces, and
visible from far off because of its 10155 radius).  With it hidden - physics is
segment-based and unaffected - the road either side of the bridge should draw
if the budget theory is right.  You will see the cutting's road but no walls.

Operates on patched_final/ (the DSK pair) and restages; run build_all.py to undo.
"""
import struct, os, patch_track as pt, patch_segments as ps, world
h=[open(os.path.join("patched_final",n),"rb").read() for n,_,_ in pt.PARTS]
buf=bytearray(len(h[0])*2)
for i in range(len(h[0])): buf[2*i],buf[2*i+1]=h[0][i],h[1][i]
w=world.World(); NAME={i:w.name(i) for i in range(390)}
base=struct.unpack_from(">I",buf,pt.DESC)[0]-0x940000
hidden=[]
for r in range(176,197):
    a=base+r*50
    if NAME[struct.unpack_from(">H",buf,a)[0]]=="UNDERP":
        f=struct.unpack_from(">H",buf,a+0x22)[0]
        struct.pack_into(">H",buf,a+0x22,f & ~0x1000)
        hidden.append((r,f,f&~0x1000))
print("hidden:", ["rec %d +0x22 0x%04X -> 0x%04X"%t for t in hidden])
ps.write(buf,"patched_final")
import shutil
for n,_,_ in pt.PARTS: shutil.copy(os.path.join("patched_final",n), os.path.join("roms_loop/racedriv",n))
print("staged")
