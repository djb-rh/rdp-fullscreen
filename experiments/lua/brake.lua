-- Brake diagnostic. Logs every G29 axis next to the value the game actually
-- receives for the brake. That distinguishes the three possible faults:
--   * the pedal moves an axis we did not bind  -> a wrong/combined-pedal mapping
--   * the bound axis does not return on release -> the wheel or its driver
--   * the axis returns but the game value does not -> MAME's analog handling
local mach = manager.machine
local inp  = mach.input

local bf, bp
for _, p in pairs(mach.ioport.ports) do
  if p.fields["Brake Pedal"] then bp, bf = p, p.fields["Brake Pedal"] end
end
if not bf then print("[bk] no Brake Pedal field found"); return end

if os.getenv("BRAKE_REVERSE") == "0" then bf:set_analog_reverse(false) end
for _, port in pairs(mach.ioport.ports) do
  for _, nm in ipairs({"Gas Pedal", "Brake Pedal", "Clutch Pedal"}) do
    local pf = port.fields[nm]
    if pf and pf.is_analog then pf:set_centerdelta(0) end
  end
end

-- Tap what the GAME actually reads from the 12-bit ADC at 0xB80000. That is the
-- number the calibration routine is judging, which may not match the field
-- value MAME reports. Channel select is written to 0xB80000, data read back
-- from 0xB80001 (high nibble first, then low byte).
local sp = mach.devices[":mainpcb:maincpu"].spaces["program"]
local adc = io.open("adc_log.txt", "w")
local nread = 0
_G.tap = sp:install_read_tap(0xB80000, 0xB80001, "adc", function(off, data, mask)
  nread = nread + 1
  if nread <= 400 or nread % 200 == 0 then
    adc:write(string.format("read #%d  addr=0x%06X  data=0x%04X (%d)\n", nread, off, data, data))
    adc:flush()
  end
  return data
end)
print("[bk] ADC read tap installed -> adc_log.txt")

local AX = {"XAXIS", "YAXIS", "ZAXIS", "RXAXIS", "RYAXIS", "RZAXIS", "SLIDER1", "SLIDER2"}
local codes = {}
for _, a in ipairs(AX) do
  local ok, c = pcall(function() return inp:code_from_token("JOYCODE_1_" .. a) end)
  if ok and c then codes[#codes + 1] = {a, c} end
end
print(string.format("[bk] brake reverse=%s  centerdelta=%d  watching %d axes",
    tostring(bf.analog_reverse), bf.centerdelta, #codes))
print("[bk] Press the brake ONCE, release it, wait 3 seconds, then quit MAME.")

local out = io.open("brake_log.txt", "w")
out:write("axes: ")
for _, c in ipairs(codes) do out:write(c[1] .. " ") end
out:write("  | brake value the game receives\n")

local f, last = 0, nil
_G.sub = emu.add_machine_frame_notifier(function()
  f = f + 1
  if f % 6 ~= 0 then return end
  local parts = {}
  for _, c in ipairs(codes) do
    local ok, v = pcall(function() return inp:code_value(c[2]) end)
    parts[#parts + 1] = string.format("%s=%+6d", c[1], ok and v or -999999)
  end
  local ok2, val = pcall(function() return bp:read() & bf.mask end)
  local line = string.format("f%-6d %s  | brake=%4d", f, table.concat(parts, " "), ok2 and val or -1)
  local key = line:gsub("^f%-?%d+%s*", "")
  if key ~= last then print("[bk] " .. line); out:write(line .. "\n"); out:flush(); last = key end
end)
