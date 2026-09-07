local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin  = fld(":mainpcb:IN0","Coin 1")
local abort = fld(":mainpcb:a80000","Abort")
local gas   = fld(":mainpcb:8BADC.0","Gas Pedal")
local wheel = fld(":mainpcb:12BADC.0","Steering Wheel")
local shy   = fld(":mainpcb:8BADC.3","Shifter Lever Y")
local shx   = fld(":mainpcb:8BADC.4","Shifter Lever X")
local frames, log, last = 0, {}, {}
local function note(k,v)
  if last[k] ~= v then log[#log+1] = string.format("f%-6d %-14s %s", frames, k, v); last[k]=v end
end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  -- coin: press to 0, release to the field's own default
  if frames == 240 then coin:set_value(0) end
  if frames == 260 then coin:set_value(coin.defvalue) end
  if frames == 280 then coin:set_value(0) end
  if frames == 300 then coin:set_value(coin.defvalue) end
  -- tap Abort (the start/select button) every second for a while
  if frames > 330 and frames < 900 then
    if frames % 60 == 0 then abort:set_value(0)
    elseif frames % 60 == 10 then abort:set_value(abort.defvalue) end
  end
  if frames > 900 then
    gas:set_value(255); wheel:set_value(2048)
    shy:set_value(255); shx:set_value(0)
  end
  local function u16(a) local ok,v = pcall(function() return sp:read_u16(a) end); return ok and v or -1 end
  local function u32(a) local ok,v = pcall(function() return sp:read_u32(a) end); return ok and v or -1 end
  if frames % 15 == 0 then
    note("0x900D58", u16(0x900D58))
    note("routehead", string.format("%08X", u32(0x9015EC)))
    note("0x901116",  u16(0x901116))
    note("credits?",  u16(0x900018))
  end
  if frames == 9000 then
    local f=io.open("drive2.txt","w")
    for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("drive2 written"); mach:exit()
  end
end)
