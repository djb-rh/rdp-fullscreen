local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local BASES = {0x9015C0, 0x901740}
local frames, snaps = 0, {}
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames > 900 and frames % 300 == 0 then
    local row = {}
    for _, b in ipairs(BASES) do
      for o = 0, 0x3E, 2 do
        local ok, v = pcall(function() return sp:read_u16(b + o) end)
        row[#row+1] = ok and v or 0
      end
    end
    snaps[#snaps+1] = {f = frames, r = row}
  end
  if frames == 4200 then
    local f = io.open("watchcur.txt","w")
    local n = #snaps[1].r
    f:write("fields that CHANGE across the run (base, offset, values):\n")
    for i = 1, n do
      local vals, distinct = {}, {}
      for _, s in ipairs(snaps) do
        vals[#vals+1] = s.r[i]
        distinct[s.r[i]] = true
      end
      local nd = 0
      for _ in pairs(distinct) do nd = nd + 1 end
      if nd > 1 then
        local b = BASES[math.floor((i-1)/32) + 1]
        local o = ((i-1) % 32) * 2
        local ss = {}
        for j = 1, math.min(#vals, 10) do ss[#ss+1] = string.format("%04X", vals[j]) end
        f:write(string.format("  0x%06X+%02X  %2d distinct: %s\n", b, o, nd,
                              table.concat(ss, " ")))
      end
    end
    f:close(); print("watchcur written"); mach:exit()
  end
end)
