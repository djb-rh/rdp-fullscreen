#!/usr/bin/env python3
"""Start the car on a chosen segment.  Record 0 of the segment array is a header
whose word at +0x08 is the start segment (stock: 0x0160 = 352, the start line).
Builds a full ROM set under /tmp/abx/<tag> from patched_final; roms_loop is
untouched."""
import os, sys, struct, shutil, zipfile, patch_track as pt, patch_segments as ps
SEG = int(sys.argv[1]); TAG = sys.argv[2] if len(sys.argv) > 2 else "s%d" % SEG
h=[open(os.path.join("patched_final",n),"rb").read() for n,_,_ in pt.PARTS]
buf=bytearray(len(h[0])*2)
for i in range(len(h[0])): buf[2*i],buf[2*i+1]=h[0][i],h[1][i]
T0=0x049CA
print("start segment %d -> %d" % (struct.unpack_from(">H",buf,T0+8)[0], SEG))
struct.pack_into(">H",buf,T0+8,SEG)
out="/tmp/abx/%s"%TAG; shutil.rmtree(out,ignore_errors=True); os.makedirs(out+"/racedriv")
with zipfile.ZipFile("/Users/djb/Developer/Race Drivin/racedriv.zip") as z: z.extractall(out+"/racedriv")
ps.write(buf,out)
for n,_,_ in pt.PARTS: shutil.copy(os.path.join(out,n), out+"/racedriv/")
print("rompath", out)
