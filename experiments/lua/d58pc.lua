local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]
local frames, rp, wp = 0, {}, {}
_G.rd = sp:install_read_tap(0x900D58, 0x900D59, "r", function()
  local pc = cpu.state["CURPC"].value; rp[pc] = (rp[pc] or 0) + 1; return nil end)
_G.wr = sp:install_write_tap(0x900D58, 0x900D59, "w", function(o,d)
  local pc = cpu.state["CURPC"].value; wp[pc] = (wp[pc] or 0) + 1; return d end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == 2700 then
    local f = io.open("d58pc.txt","w")
    for label,t in pairs({READ=rp, WRITE=wp}) do
      local ks = {}
      for k in pairs(t) do ks[#ks+1]=k end
      table.sort(ks, function(a,b) return t[a]>t[b] end)
      f:write(label.." accessors of 0x900D58 (the current section value):\n")
      for i=1,math.min(#ks,10) do f:write(string.format("   PC 0x%06X  x%d\n",ks[i],t[ks[i]])) end
      f:write("\n")
    end
    f:close(); print("d58pc written"); mach:exit()
  end
end)
