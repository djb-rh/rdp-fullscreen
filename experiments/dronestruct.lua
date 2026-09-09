local mach=manager.machine; local sp=mach.devices[":mainpcb:maincpu"].spaces["program"]
local P=mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
local function s32(a) local v=sp:read_u32(a); if v>=0x80000000 then v=v-0x100000000 end; return v end
local function s16(a) local v=sp:read_u16(a); if v>=0x8000 then v=v-0x10000 end; return v end
local N=tonumber(os.getenv("NDR") or "5")
frames=0
_G.sub=emu.add_machine_frame_notifier(function()
  frames=frames+1
  hold(coin,240,285); hold(coin,330,375); hold(key,480,525); hold(key,660,705); hold(key,840,885)
  if frames>300 and frames<1800 then whl:set_value(whl.minvalue) elseif frames>=1800 then whl:set_value(2048) end
  if frames>=1900 and frames%150==0 then
    local out={}
    for i=0,N-1 do local a=0x901F58+0x76*i; local path=sp:read_u32(a+0x52); local kfp=sp:read_u32(a); local mv=sp:read_u32(a+0x3A)
      local kfi=(kfp>=path+0x38) and ((kfp-path-0x38)//12) or -1
      out[#out+1]=string.format("d%d[kf%d t%d t0%d r%04X/%04X sec%d pos(%d,%d)]", i, kfi, s32(a+0x42), s32(a+0x46), sp:read_u16(a+0x4A), sp:read_u16(a+0x4C), sp:read_u16(a+0x56), s32(mv), s32(mv+8)) end
    print(string.format("[d] f%d clk%d psec%d %s", frames, s32(0x9016DA), sp:read_u16(0x9016BE), table.concat(out," ")))
  end
  if frames==2100 or frames==3300 then mach.video:snapshot() end
  if frames>=3610 then mach:exit() end
end)
