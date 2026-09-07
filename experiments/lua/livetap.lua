-- What does the game read from the DSK ROM window once it is actually driving?
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local frames, hits, early = 0, {}, 0
_G.rd = sp:install_read_tap(0x940000, 0x9FFFFF, "dsk", function(off)
  if frames > 600 then
    local b = off & 0xFFFFFF00
    hits[b] = (hits[b] or 0) + 1
  else early = early + 1 end
  return nil
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == 3600 then
    local f = io.open("livetap.txt","w")
    local ks, tot = {}, 0
    for k,v in pairs(hits) do ks[#ks+1]=k; tot=tot+v end
    table.sort(ks, function(a,b) return hits[a]>hits[b] end)
    f:write(string.format("reads before frame 600: %d\nreads after: %d over %d pages\n\n",
                          early, tot, #ks))
    f:write("busiest 256-byte pages after frame 600:\n")
    for i=1,math.min(#ks,25) do
      f:write(string.format("  0x%06X  (DSK 0x%05X)  %d reads\n",
                            ks[i], ks[i]-0x940000, hits[ks[i]]))
    end
    f:close(); print("livetap written"); mach:exit()
  end
end)
