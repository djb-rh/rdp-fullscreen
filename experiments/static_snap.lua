-- static view at a start-segment variant: coin, start, hold, force the route section to SEG, snapshot.
local mach=manager.machine; local sp=mach.devices[":mainpcb:maincpu"].spaces["program"]
local P=mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
local function s32(a) local v=sp:read_u32(a); if v>=0x80000000 then v=v-0x100000000 end; return v end
local SEG=tonumber(os.getenv("SEG"))
frames=0
_G.sub=emu.add_machine_frame_notifier(function()
  frames=frames+1
  hold(coin,240,285); hold(coin,330,375); hold(key,480,525); hold(key,660,705); hold(key,840,885)
  if frames>300 and frames<1800 then whl:set_value(whl.minvalue) elseif frames>=1800 then whl:set_value(2048) end
  if SEG and frames>=1000 and frames<=1180 then sp:write_u16(0x900D54, SEG+69) end
  if frames==2400 or frames==2500 then
    print(string.format("[s] f%d car=(%d,%d,%d) offroad %d curseg %d", frames, s32(0x900044), s32(0x900048), s32(0x90004C), sp:read_u16(0x9016BA), (sp:read_u32(0x9016D2)-sp:read_u32(0x900D5A))//64))
    mach.video:snapshot() end
  if frames>=2520 then mach:exit() end
end)
