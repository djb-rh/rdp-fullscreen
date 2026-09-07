local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a,0); rgn:write_u8(a+1,0) end
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n, ahi, alo, log = 0, 0, 0, {}
local LO, HI = 1500, 1508
_G.hd.t1 = sp:install_write_tap(0xc00002, 0xc00003, "ah", function (o,d,m) ahi = d & 0xffff end)
_G.hd.t2 = sp:install_write_tap(0xc00004, 0xc00005, "al", function (o,d,m)
  alo = d & 0xffff
  if n >= LO and n <= HI then
    local a = (ahi << 16) | alo
    if (a & 0xFFF00000) ~= 0x02000000 or (a & 0x000FFFFF) == 0 then
      log[#log+1] = string.format("f%4d ADDR %08X  PC %06X", n, a, cpu.state["PC"].value)
    end
  end
end)
_G.hd.t3 = sp:install_write_tap(0xc0000c, 0xc0000d, "dat", function (o,d,m)
  local a = (ahi << 16) | alo
  if n >= LO and n <= HI and (a & 0xFFF00000) == 0xC0000000 then
    log[#log+1] = string.format("f%4d   -> reg %2d = %04X", n, (a & 0xfff) >> 4, d & 0xffff)
  end
end)
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n == HI + 1 then
    local seen, out = {}, 0
    for _, s in ipairs(log) do
      if not seen[s] then seen[s] = true; out = out + 1; if out < 60 then print(s) end end
    end
    print("total distinct lines: " .. out)
  end
end)
