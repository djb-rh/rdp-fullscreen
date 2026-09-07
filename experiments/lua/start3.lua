-- Coin, then keep clicking the key AFTER the "TURN KEY TO START" prompt appears.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local shy=fld(":mainpcb:8BADC.3","Shifter Lever Y"); local shx=fld(":mainpcb:8BADC.4","Shifter Lever X")
local frames, log, last = 0, {}, {}
local function note(s) log[#log+1]=string.format("f%-6d %s",frames,s) end
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  hold(coin, 240, 285)
  -- click the key repeatedly from well after the prompt is up
  if frames >= 1800 and frames < 5400 then
    local p = (frames - 1800) % 240
    if p == 0 then key:set_value(1) elseif p == 45 then key:set_value(0) end
  end
  -- shifter stays centred = automatic
  shy:set_value(128); shx:set_value(128)
  if frames > 2000 then gas:set_value(255); whl:set_value(2048) end
  if frames >= 1500 and frames % 6 == 0 and frames <= 9000 then mach.video:snapshot() end
  local d58  = sp:read_u16(0x900D58)
  local dist = sp:read_u16(0x901FA0)
  local x    = sp:read_u32(0x900044)
  if last.d58 ~= d58 then note("D58 = "..d58); last.d58 = d58 end
  if frames % 300 == 0 then note(string.format("dist=%-6d D58=%-6d carX=%d", dist, d58, x)) end
  if frames == 9600 then
    local f=io.open("start3.txt","w"); for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("start3 written"); mach:exit()
  end
end)
