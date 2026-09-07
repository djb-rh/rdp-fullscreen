-- Correct MAME digital-input semantics: set_value(1) PRESSES, set_value(0) RELEASES.
-- (defvalue is the port's default bit pattern, NOT the released state.)
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local frames, log, last = 0, {}, {}
local function note(s) log[#log+1]=string.format("f%-6d %s",frames,s) end
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  hold(coin, 240, 285)          -- insert a coin
  hold(coin, 330, 375)          -- and a second
  hold(key,  480, 525)          -- spring-loaded key: click ~750 ms
  hold(key,  660, 705)
  hold(key,  840, 885)
  if frames > 1000 then gas:set_value(255); whl:set_value(2048) end
  if frames >= 200 and frames % 6 == 0 and frames <= 5000 then mach.video:snapshot() end
  local d58 = sp:read_u16(0x900D58)
  local dist = sp:read_u16(0x901FA0)
  if last.d58 ~= d58 then note("D58 = "..d58); last.d58 = d58 end
  if frames % 300 == 0 then note(string.format("dist=%d D58=%d", dist, d58)) end
  if frames == 5400 then
    local f=io.open("start2.txt","w"); for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("start2 written"); mach:exit()
  end
end)
