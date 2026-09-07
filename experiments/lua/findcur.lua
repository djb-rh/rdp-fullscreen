-- Find the RAM variable holding a pointer to the current route-graph section.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local LO, HI = 0x9406FE, 0x94096E          -- track B route nodes
local RANGES = { {0x900000,0x90FFFF}, {0xFF8000,0xFFFFFF} }
local frames, seen, hist = 0, {}, {}
local function scan()
  for _, r in ipairs(RANGES) do
    for a = r[1], r[2] - 3, 2 do
      local ok, v = pcall(function() return sp:read_u32(a) end)
      if ok and v and v >= LO and v <= HI then
        seen[a] = (seen[a] or 0) + 1
        hist[a] = hist[a] or {}
        local h = hist[a]
        if h[#h] ~= v then h[#h+1] = v end
      end
    end
  end
end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames > 900 and frames % 150 == 0 then scan() end
  if frames == 3600 then
    local f = io.open("findcur.txt","w")
    local ks = {}
    for a in pairs(seen) do ks[#ks+1] = a end
    table.sort(ks)
    f:write(string.format("scanned %d times; %d addresses held a route-node pointer\n\n",
                          (frames-900)//150, #ks))
    for _, a in ipairs(ks) do
      local h = hist[a]
      local s = {}
      for i = 1, math.min(#h, 12) do s[#s+1] = string.format("%06X", h[i]) end
      f:write(string.format("  0x%06X  seen %2d  distinct values %2d: %s\n",
                            a, seen[a], #h, table.concat(s, " ")))
    end
    f:close(); print("findcur written"); mach:exit()
  end
end)
