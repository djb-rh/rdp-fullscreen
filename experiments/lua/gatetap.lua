-- Which records of the per-track +0x004 block does the game actually read?
--
-- Taps the DSK ROM window and buckets every read into a record index for both
-- tracks' 64-byte arrays. If the game scans the whole array each frame the
-- counts are flat; if it reads only what is near the car they move as it drives.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]

local BLOCKS = {
  A = {base = 0x944A0A, n = 430},
  B = {base = 0x950204, n = 725},
}
local hits, frames, other = {A = {}, B = {}}, 0, 0
local seen_order = {A = {}, B = {}}

_G.hd = sp:install_read_tap(0x940000, 0x95FFFF, "dsk", function(offset, data, mask)
  local matched = false
  for k, b in pairs(BLOCKS) do
    if offset >= b.base and offset < b.base + b.n * 64 then
      local i = math.floor((offset - b.base) / 64)
      hits[k][i] = (hits[k][i] or 0) + 1
      if seen_order[k][i] == nil then seen_order[k][i] = frames end
      matched = true
    end
  end
  if not matched then other = other + 1 end
  return data
end)

local LIMIT = tonumber(os.getenv("FRAMES") or "1800")
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == LIMIT then
    local f = io.open("gatetap.txt", "w")
    f:write(string.format("frames %d, reads outside both blocks %d\n", frames, other))
    for _, k in ipairs({"A", "B"}) do
      local n, tot = 0, 0
      for i, c in pairs(hits[k]) do n = n + 1; tot = tot + c end
      f:write(string.format("\ntrack %s: %d of %d records read, %d reads total\n",
                            k, n, BLOCKS[k].n, tot))
      local idx = {}
      for i in pairs(hits[k]) do idx[#idx + 1] = i end
      table.sort(idx)
      for _, i in ipairs(idx) do
        f:write(string.format("  rec %4d  reads %6d  first seen frame %d\n",
                              i, hits[k][i], seen_order[k][i]))
      end
    end
    f:close()
    print("gatetap: wrote gatetap.txt")
    mach:exit()
  end
end)
