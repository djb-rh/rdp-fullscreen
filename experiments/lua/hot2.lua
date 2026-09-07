local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a,0); rgn:write_u8(a+1,0) end
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n = 0
local addrs, pcs = {}, {}
local LO, HI = 1500, 1520
_G.hd.t = sp:install_write_tap(0xc00000, 0xc03fff, "gspio", function (o, d, m)
  if n < LO or n > HI then return end
  addrs[o] = (addrs[o] or 0) + 1
  local pc = cpu.state["PC"].value; pcs[pc] = (pcs[pc] or 0) + 1
end)
local function top(t, label, fmt)
  local ks = {}
  for k in pairs(t) do ks[#ks+1] = k end
  table.sort(ks, function(a,b) return t[a] > t[b] end)
  for i = 1, math.min(#ks, 14) do print(string.format(fmt, label, ks[i], t[ks[i]])) end
end
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n == HI + 1 then top(addrs, "PORT", "%s %08X x%d"); top(pcs, "HOTPC", "%s %06X x%d") end
end)
