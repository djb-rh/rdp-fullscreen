local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]
local frames, pcs, wpcs = 0, {}, {}
_G.rd = sp:install_read_tap(0x9015EC, 0x9015EF, "hd", function(off)
  local pc = cpu.state["CURPC"].value
  pcs[pc] = (pcs[pc] or 0) + 1
  return nil
end)
_G.wr = sp:install_write_tap(0x9015EC, 0x9015EF, "hw", function(off, data)
  local pc = cpu.state["CURPC"].value
  wpcs[pc] = (wpcs[pc] or 0) + 1
  return data
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == 2400 then
    local f = io.open("whopc.txt","w")
    for label, t in pairs({READ = pcs, WRITE = wpcs}) do
      local ks = {}
      for k in pairs(t) do ks[#ks+1] = k end
      table.sort(ks, function(a,b) return t[a] > t[b] end)
      f:write(label .. " accessors of 0x9015EC:\n")
      for i = 1, math.min(#ks, 12) do
        f:write(string.format("   PC 0x%06X  x%d\n", ks[i], t[ks[i]]))
      end
      f:write("\n")
    end
    f:close(); print("whopc written"); mach:exit()
  end
end)
