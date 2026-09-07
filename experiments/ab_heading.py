#!/usr/bin/env python3
"""Headless experiment: does the ADSP draw a DOTLINE the camera is inside at
every heading?  Hides every placement except the stock DOTLINE under the start
line (rec 69), rotates it to the given heading, and measures the polygons the
ADSP emits per frame at the start line.  Everything runs from your own ROMs;
writes only under /tmp/abh."""
import os, sys, struct, math, shutil, zipfile, subprocess
import patch_track as pt, patch_segments as ps
H = float(sys.argv[1]); OBJ = int(sys.argv[2]) if len(sys.argv) > 2 else None; TAG = "o%s_h%g" % (OBJ, H)
h=[open(os.path.join("patched_final",n),"rb").read() for n,_,_ in pt.PARTS]
buf=bytearray(len(h[0])*2)
for i in range(len(h[0])): buf[2*i],buf[2*i+1]=h[0][i],h[1][i]
base=struct.unpack_from(">I",buf,pt.DESC)[0]-0x940000
import world
w=world.World(); IDX={w.name(i):i for i in range(390)}
# the stock DOTLINE under the start line, found by position (indices shift after the deletions)
KEEP=min(range(197), key=lambda r: abs(struct.unpack_from(">i",buf,base+r*50+0x14)[0]-209600)+abs(struct.unpack_from(">i",buf,base+r*50+0x1C)[0]-200000)
         + (0 if struct.unpack_from(">H",buf,base+r*50)[0]==IDX["DOTLINE"] else 10**9))
print("keeping record %d (obj %d at %d,%d)" % (KEEP, struct.unpack_from(">H",buf,base+KEEP*50)[0], struct.unpack_from(">i",buf,base+KEEP*50+0x14)[0], struct.unpack_from(">i",buf,base+KEEP*50+0x1C)[0]))
for r in range(197):
    a=base+r*50
    if r!=KEEP:
        f=struct.unpack_from(">H",buf,a+0x22)[0]; struct.pack_into(">H",buf,a+0x22,f & ~0x1000)
a=base+KEEP*50
if OBJ is not None and OBJ >= 0: struct.pack_into(">H",buf,a,OBJ)
if OBJ == -1: struct.pack_into(">H",buf,a+0x22, struct.unpack_from(">H",buf,a+0x22)[0] & ~0x1000)
ca,sa=math.cos(math.radians(H)),math.sin(math.radians(H)); q=lambda v:int(round(v*16384))
struct.pack_into(">9h",buf,a+0x02,q(ca),0,q(sa),0,16384,0,q(-sa),0,q(ca))
out="/tmp/abh/%s"%TAG; shutil.rmtree(out,ignore_errors=True); os.makedirs(out+"/racedriv")
with zipfile.ZipFile("/Users/djb/Developer/Race Drivin/racedriv.zip") as z: z.extractall(out+"/racedriv")
ps.write(buf,out)
for n,_,_ in pt.PARTS: shutil.copy(os.path.join(out,n), out+"/racedriv/")
lua=out+"/probe.lua"
open(lua,"w").write(("local KEEPIDX=%d\n" % KEEP) + r'''
local mach=manager.machine; local apm=mach.devices[":mainpcb:adsp"].spaces["program"]; local adm=mach.devices[":mainpcb:adsp"].spaces["data"]
local P=mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
local function pm(a) return (apm:read_u32(a)>>8)&0xFFFF end
local per, cur, freemin, armed = {}, 0, 65535, false
_G.TAPS={}
_G.TAPS[1]=apm:install_write_tap(0x123F,0x123F,"head",function(o,d,m)
  if not armed then return d end
  local p,n=pm(0x123F),0
  while p>=0x1242 and p<0x1E00 and n<600 do n=n+1; p=pm(p+3) end
  if n>cur then cur=n end
  local f=adm:read_u16(0x0957); if f<freemin then freemin=f end
  if ((d>>8)&0xFFFF)==0x1242 then per[#per+1]=cur; cur=0 end     -- reset = frame boundary
  return d end)
frames=0
_G.sub=emu.add_machine_frame_notifier(function()
  frames=frames+1
  hold(coin,240,285); hold(coin,330,375); hold(key,480,525); hold(key,660,705); hold(key,840,885)
  if frames>300 and frames<1800 then whl:set_value(whl.minvalue) elseif frames>=1800 then whl:set_value(2048) end
  if frames==2400 then armed=true end
  if frames==2700 then armed=false; table.sort(per)
    print(string.format("[h] %d ADSP frames: polys min %d median %d max %d; free-list head min 0x%04X", #per, per[1] or -1, per[math.floor(#per/2)+1] or -1, per[#per] or -1, freemin)) mach:exit() end
end)
''')
r=subprocess.run(["mame","racedriv","-rompath",out,"-autoboot_script",lua,"-video","none","-sound","none","-seconds_to_run","55","-nothrottle"],capture_output=True,text=True)
for line in r.stdout.splitlines()+r.stderr.splitlines():
    if line.startswith("[h]"): print("obj %-4s heading %+6.1f: %s" % (OBJ, H, line[4:]))
