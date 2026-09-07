-- Locate the countdown clock by its counting signature rather than by the size
-- of its jump at a gate. A game clock is the only word in RAM that decrements
-- by exactly 1 once per second, every second, for the whole run.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local LO, HI = 0x900000, 0x901FFE

local function field(name)
  for _, p in pairs(mach.ioport.ports) do
    if p.fields[name] then return p.fields[name] end
  end
end
local coin, key = field("Coin 1"), field("Key")
print(string.format("[ft] coin=%s key=%s", tostring(coin ~= nil), tostring(key ~= nil)))

local prev, dec, seen = {}, {}, {}
local f = 0
_G.sub = emu.add_machine_frame_notifier(function()
  f = f + 1
  -- set_value(1) presses, set_value(0) releases.
  if coin then
    if f == 300 then coin:set_value(1) elseif f == 320 then coin:set_value(0) end
  end
  if key then   -- the start key is spring-loaded; ~500 ms is enough
    if f == 480 then key:set_value(1) elseif f == 510 then key:set_value(0) end
  end
  if f < 900 or f % 60 ~= 0 then return end

  for a = LO, HI, 2 do
    local ok, v = pcall(function() return sp:read_u16(a) end)
    if ok then
      local p = prev[a]
      if p then
        seen[a] = (seen[a] or 0) + 1
        if p - v == 1 then dec[a] = (dec[a] or 0) + 1 end
      end
      prev[a] = v
    end
  end

  if f % 1800 == 0 then
    local r = {}
    for a, c in pairs(dec) do
      if c >= 5 then r[#r+1] = {a, c, seen[a], prev[a]} end
    end
    table.sort(r, function(x, y) return x[2] > y[2] end)
    print(string.format("[ft] f%d -- %d words decrementing by exactly 1/second:", f, #r))
    for i = 1, math.min(#r, 12) do
      print(string.format("[ft]    0x%06X   %d of %d samples   now=%d",
          r[i][1], r[i][2], r[i][3], r[i][4]))
    end
  end
end)