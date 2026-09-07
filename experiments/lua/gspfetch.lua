local mach = manager.machine
local gsp  = mach.devices[":mainpcb:gsp"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a,0); rgn:write_u8(a+1,0) end
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n, reads, hist = 0, 0, {}
local LO, HI = 1500, 1501
_G.hd.t = gsp.spaces["program"]:install_read_tap(0xff800000, 0xffffffff, "rd", function (o,d,m)
  if n < LO or n > HI then return end
  reads = reads + 1
  local blk = ((o - 0xffc00000) & 0x3fffff) >> 14      -- 0x4000 bits per block
  hist[blk] = (hist[blk] or 0) + 1
end)
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n == HI + 1 then
    local ks = {}
    for k in pairs(hist) do ks[#ks+1] = k end
    table.sort(ks, function(a,b) return hist[a] > hist[b] end)
    print("GSP-space reads in 2 frames: " .. reads .. "  distinct blocks: " .. #ks)
    for i = 1, math.min(#ks, 14) do print(string.format("RDBLK %3d x%d", ks[i], hist[ks[i]])) end
  end
end)
