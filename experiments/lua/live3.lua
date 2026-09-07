local mach = manager.machine
local gsp  = mach.devices[":mainpcb:gsp"]
local vram = mach.memory.shares[":mainpcb:gsp_vram"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a, 0); rgn:write_u8(a+1, 0) end  -- forward view
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n, wr, rmin, rmax = 0, 0, nil, nil
_G.hd.tap = gsp.spaces["program"]:install_write_tap(0x02000000, 0x020fffff, "px", function (offset, data, mask)
  wr = wr + 1
  local row = ((offset - 0x02000000) // 2) // 512
  if not rmin or row < rmin then rmin = row end
  if not rmax or row > rmax then rmax = row end
end)
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n >= 1500 and n <= 1520 then
    print(string.format("f%4d writes %6d rows %s..%s", n, wr, tostring(rmin), tostring(rmax)))
  end
  wr, rmin, rmax = 0, nil, nil
  if n == 1530 then
    local f = io.open("/Users/djb/Developer/rdp-fullscreen/vram_drive.bin", "wb")
    for i = 0, 262143 do local w = vram:read_u16(i*2); f:write(string.char(w & 0xff, (w >> 8) & 0xff)) end
    f:close(); print("DRIVE VRAM DUMPED")
  end
end)
