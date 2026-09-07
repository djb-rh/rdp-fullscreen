local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(tag, name) local p = P[tag]; return p and p.fields[name] end
local coin  = fld(":mainpcb:IN0", "Coin 1")
local gas   = fld(":mainpcb:8BADC.0", "Gas Pedal")
local wheel = fld(":mainpcb:12BADC.0", "Steering Wheel")
local shy   = fld(":mainpcb:8BADC.3", "Shifter Lever Y")
local shx   = fld(":mainpcb:8BADC.4", "Shifter Lever X")

local NODES = {0x6FE,0x718,0x732,0x74C,0x766,0x780,0x79A,0x7B4,0x7CE,0x7E8,0x802,0x81C,0x86A,
               0x884,0x89E,0x8B8,0x8D2,0x8EC,0x906,0x920,0x96E}
local idx = {}
for i,a in ipairs(NODES) do for o=0,25 do idx[0x940000+a+o] = i-1 end end
local frames, events, lastd58 = 0, {}, -1
_G.rd = sp:install_read_tap(0x9406FE, 0x940987, "route", function(off)
  local i = idx[off]
  if i then
    local e = events[#events]
    if not (e and e.i == i and e.to >= frames - 2) then
      events[#events+1] = {i=i, from=frames, to=frames}
    else e.to = frames end
  end
  return nil
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == 300 then coin:set_value(0) end
  if frames == 315 then coin:set_value(1) end
  if frames > 360 then
    gas:set_value(255)
    shy:set_value(255); shx:set_value(0)      -- into gear
    wheel:set_value(2048)
  end
  local ok, d = pcall(function() return sp:read_u16(0x900D58) end)
  if ok and d ~= lastd58 then
    events[#events+1] = {d58=d, from=frames}
    lastd58 = d
  end
  if frames == 7200 then
    local f = io.open("drive.txt","w")
    for _, e in ipairs(events) do
      if e.d58 then f:write(string.format("f%-6d 0x900D58 = %d\n", e.from, e.d58))
      else f:write(string.format("f%-6d route node %d read (to f%d)\n", e.from, e.i, e.to)) end
    end
    f:close(); print("drive written"); mach:exit()
  end
end)
