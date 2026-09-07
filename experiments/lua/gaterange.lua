local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local BA, BN = 0x944A0A, 430
local frames, copying = 0, false
local lo, hi, n = 0xFFFFFFFF, 0, 0
local firstsrc, firstdst = nil, nil
_G.rd = sp:install_read_tap(BA, BA+BN*64-1, "src", function(off) copying = true; return nil end)
_G.wr = sp:install_write_tap(0x850000, 0x8FFFFF, "dst", function(off, data)
  if copying then
    if off < lo then lo = off end
    if off > hi then hi = off end
    n = n + 1
  end
  return data
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1; copying = false
  if frames == 400 then
    local f = io.open("gaterange.txt","w")
    f:write(string.format("writes into 0x85xxxx during the copy: %d\n", n))
    f:write(string.format("range 0x%06X .. 0x%06X  (span %d bytes, %d words)\n",
                          lo, hi, hi-lo+2, (hi-lo+2)/2))
    f:write(string.format("source array is %d bytes (%d words)\n", BN*64, BN*32))
    f:close(); print("range written"); mach:exit()
  end
end)
