#!/usr/bin/env python3
"""Build a full ROM set under /tmp/abx/<tag> with the car starting on SEG and
one edit applied to the placement array: hide=<rec> | obj=<rec>:<objidx> |
bias=<rec>:<value>.  roms_loop is untouched."""
import os, sys, struct, shutil, zipfile, patch_track as pt, patch_segments as ps
SEG=int(sys.argv[1]); TAG=sys.argv[2]; edits=sys.argv[3:]
h=[open(os.path.join("patched_final",n),"rb").read() for n,_,_ in pt.PARTS]
buf=bytearray(len(h[0])*2)
for i in range(len(h[0])): buf[2*i],buf[2*i+1]=h[0][i],h[1][i]
struct.pack_into(">H",buf,0x049CA+8,SEG)
base=struct.unpack_from(">I",buf,pt.DESC)[0]-0x940000
for e in edits:
    k,v=e.split("=",1)
    if k=="hide":
        a=base+int(v)*50; struct.pack_into(">H",buf,a+0x22, struct.unpack_from(">H",buf,a+0x22)[0] & ~0x1000)
    elif k=="obj":
        r,o=map(int,v.split(":")); struct.pack_into(">H",buf,base+r*50,o)
    elif k=="bias":
        r,b=map(int,v.split(":")); struct.pack_into(">h",buf,base+r*50+0x20,b)
out="/tmp/abx/%s"%TAG; shutil.rmtree(out,ignore_errors=True); os.makedirs(out+"/racedriv")
with zipfile.ZipFile("/Users/djb/Developer/Race Drivin/racedriv.zip") as z: z.extractall(out+"/racedriv")
ps.write(buf,out)
for n,_,_ in pt.PARTS: shutil.copy(os.path.join(out,n), out+"/racedriv/")
