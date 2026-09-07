-- Which route-graph section is the game on, frame by frame?
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local NODES = {0x1EC,0x206,0x220,0x38C,0x3A6,0x3C0,0x3DA,0x3F4,0x40E,
               0x428,0x442,0x45C,0x476,0x490,0x4AA}
local idx = {}
for i,a in ipairs(NODES) do
  for o = 0, 25 do idx[0x940000 + a + o] = i - 1 end
end
local frames, cur, log, tot = 0, {}, {}, {}
_G.rd = sp:install_read_tap(0x9401EC, 0x9404C5, "route", function(off)
  local i = idx[off]
  if i then cur[i] = (cur[i] or 0) + 1; tot[i] = (tot[i] or 0) + 1 end
  return nil
end)
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  local ks = {}
  for i in pairs(cur) do ks[#ks+1] = i end
  if #ks > 0 then
    table.sort(ks)
    local s = table.concat(ks, ",")
    local last = log[#log]
    if last and last.s == s then last.to = frames
    else log[#log+1] = {s = s, from = frames, to = frames} end
  end
  cur = {}
  if frames == 3600 then
    local f = io.open("routetap.txt", "w")
    f:write(string.format("%d frames\n\ntotal reads per section:\n", frames))
    for i = 0, 14 do
      f:write(string.format("  sec %2d  %d\n", i, tot[i] or 0))
    end
    f:write("\ntimeline (frame range -> sections read):\n")
    for _, e in ipairs(log) do
      f:write(string.format("  %5d-%-5d  %s\n", e.from, e.to, e.s))
    end
    f:close(); print("routetap written"); mach:exit()
  end
end)
