local mach = manager.machine
local gsp = mach.devices[":mainpcb:gsp"]
_G.hd = {}
local n = 0
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n ~= 600 then return end
  local names = {}
  for k, v in pairs(gsp.state) do names[#names+1] = k end
  table.sort(names)
  print("GSP state entries: " .. table.concat(names, " "))
  for _, k in ipairs({"PC","CURPC","SP","ST","A0","B0"}) do
    local e = gsp.state[k]
    if e then print(string.format("   %-6s = %08X", k, e.value)) end
  end
  print("GSP suspended/halted? " .. tostring(mach.devices[":mainpcb:gsp"]))
end)
