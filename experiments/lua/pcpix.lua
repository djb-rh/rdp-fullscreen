local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local gsp  = mach.devices[":mainpcb:gsp"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a,0); rgn:write_u8(a+1,0) end
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n, pcs, cnt = 0, {}, 0
local LO, HI = 1500, 1506
_G.hd.t = gsp.spaces["program"]:install_write_tap(0x02000000, 0x020fffff, "px", function (o,d,m)
  if n < LO or n > HI then return end
  cnt = cnt + 1
  local pc = cpu.state["CURPC"].value
  pcs[pc] = (pcs[pc] or 0) + 1
end)
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n == HI + 1 then
    local ks = {}
    for k in pairs(pcs) do ks[#ks+1] = k end
    table.sort(ks, function(a,b) return pcs[a] > pcs[b] end)
    print("pixel writes: " .. cnt .. "  distinct PCs: " .. #ks)
    for i = 1, math.min(#ks, 16) do print(string.format("PIXPC %06X x%d", ks[i], pcs[ks[i]])) end
  end
end)
