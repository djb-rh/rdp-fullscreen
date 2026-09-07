-- Dump the side pod's colour palette to palette.bin (8 banks x 256 RGB triples).
-- Run once against your own pod ROMs; swapart.py needs it to match colours.
--     mame racedrivpans -rompath <dir> -video none -sound none -str 12 \
--          -autoboot_script dumppal.lua
local mach = manager.machine
local lo = mach.memory.shares[":mainpcb:gsp_palram_lo"]
local hi = mach.memory.shares[":mainpcb:gsp_palram_hi"]
_G.hd = {}
local n = 0
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n ~= 400 then return end
  local f = io.open("palette.bin", "wb")
  for i = 0, 2047 do
    local l, h = lo:read_u16(i * 2), hi:read_u16(i * 2)
    f:write(string.char((l >> 8) & 0xff, l & 0xff, h & 0xff))
  end
  f:close()
  print("wrote palette.bin")
end)
