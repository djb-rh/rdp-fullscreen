-- Where does the +0x004 block get copied to?
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local BA, BN = 0x944A0A, 430
local frames, copying, dst = 0, false, {}
local firstf, lastf = nil, nil

_G.rd = sp:install_read_tap(BA, BA + BN*64 - 1, "src", function(offset, data, mask)
  copying = true
  if not firstf then firstf = frames end
  lastf = frames
  return data
end)
_G.wr = sp:install_write_tap(0x000000, 0xFFFFFF, "dst", function(offset, data, mask)
  if copying then
    local b = offset & 0xFFFFF000
    dst[b] = (dst[b] or 0) + 1
  end
  return data
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  copying = false
  if frames == 400 then
    local f = io.open("gatedst.txt", "w")
    f:write(string.format("source reads seen on frames %s..%s\n",
                          tostring(firstf), tostring(lastf)))
    local ks = {}
    for k in pairs(dst) do ks[#ks+1] = k end
    table.sort(ks)
    f:write("writes during those frames, by 4 KB page:\n")
    for _, k in ipairs(ks) do
      if dst[k] > 200 then
        f:write(string.format("  0x%06X  %d writes\n", k, dst[k]))
      end
    end
    f:close()
    print("gatedst: written")
    mach:exit()
  end
end)
