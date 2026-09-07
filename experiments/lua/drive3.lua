local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin = fld(":mainpcb:IN0","Coin 1")
local key  = fld(":mainpcb:a80000","Key")        -- IPT_START1: the start button
local gas  = fld(":mainpcb:8BADC.0","Gas Pedal")
local whl  = fld(":mainpcb:12BADC.0","Steering Wheel")
local shy  = fld(":mainpcb:8BADC.3","Shifter Lever Y")
local shx  = fld(":mainpcb:8BADC.4","Shifter Lever X")
local frames, log, last = 0, {}, {}
local function note(k,v)
  if last[k] ~= v then log[#log+1]=string.format("f%-6d %-11s %s",frames,k,v); last[k]=v end
end
local function press(f, on, off, a, b)
  if frames == a then f:set_value(on) elseif frames == b then f:set_value(off) end
end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin, 0, coin.defvalue, 240, 260)
  press(coin, 0, coin.defvalue, 280, 300)
  -- The Key is spring-loaded: a momentary click, not a held switch.
  -- spring-loaded: click and hold ~750 ms (45 frames at 60 Hz)
  press(key, 0, key.defvalue, 360, 405)
  press(key, 0, key.defvalue, 540, 585)
  press(key, 0, key.defvalue, 720, 765)
  -- Leave the shifter at its centre detent (128,128) = AUTOMATIC.
  -- Forcing it to a corner selects the manual-transmission car.
  if frames > 960 then
    gas:set_value(255); whl:set_value(2048)
    shy:set_value(shy.defvalue); shx:set_value(shx.defvalue)   -- stay automatic
  end
  local function u16(a) local ok,v=pcall(function() return sp:read_u16(a) end); return ok and v or -1 end
  local function u32(a) local ok,v=pcall(function() return sp:read_u32(a) end); return ok and v or -1 end
  if frames % 10 == 0 then
    note("D58", u16(0x900D58))
    note("head", string.format("%08X", u32(0x9015EC)))
    note("D5A", string.format("%08X", u32(0x900D5A)))
    note("D60", u32(0x900D60))
  end
  if frames == 12000 then
    local f=io.open("drive3.txt","w")
    for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("drive3 written"); mach:exit()
  end
end)
