local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local brk=fld(":mainpcb:12BADC.1","Brake Pedal"); local clu=fld(":mainpcb:8BADC.1","Clutch Pedal")
local function s32(a) local v=sp:read_u32(a); if v>=0x80000000 then v=v-0x100000000 end; return v end
local frames, log, prev = 0, {}, nil
local function note(s) log[#log+1]=string.format("f%-6d %s",frames,s) end
local function press(f,on,off,a,b) if frames==a then f:set_value(on) elseif frames==b then f:set_value(off) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin,0,coin.defvalue,240,270)
  press(key,0,key.defvalue,360,405); press(key,0,key.defvalue,540,585); press(key,0,key.defvalue,720,765)
  if frames > 900 then
    gas:set_value(255); whl:set_value(2048)
    brk:set_value(0); clu:set_value(0)
  end
  if frames % 300 == 0 and frames > 600 then
    local ok, x = pcall(function() return s32(0x900044) end)
    if ok then
      local z, y = s32(0x90004C), s32(0x900048)
      local d = prev and math.sqrt((x-prev[1])^2+(z-prev[2])^2) or 0
      note(string.format("pos %8d %7d %8d   moved %7.0f since last   D58=%d",
                         x, y, z, d, sp:read_u16(0x900D58)))
      prev = {x, z}
    end
  end
  if frames == 6000 then
    local f=io.open("gategas2.txt","w"); for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("done"); mach:exit()
  end
end)
