-- Race Drivin' checkpoint watcher. Injects NO input - you drive.
--   mame racedriv -rompath "..." -autoboot_script watch.lua
-- Log: watch_log.txt (flushed on every event, so quitting loses nothing)
--
-- Two jobs:
--   1. log each section as you cross it (index, value, marker, name)
--   2. work out what the checkpoint AWARDED, by snapshotting RAM shortly before
--      each crossing and again after, and reporting every word that jumped.
--      The timer is in there; the award is its jump. That gives the unit of the
--      section value without needing to read it off the screen.
local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]
local out  = io.open("watch_log.txt", "w")
local frames = 0

local LO, HI = 0x900000, 0x901FFE          -- the block holding lap/timer state
local function u16(a) local ok,v = pcall(function() return sp:read_u16(a) end); return ok and v or 0 end
local function s32(a)
  local ok,v = pcall(function() return sp:read_u32(a) end)
  if not ok then return 0 end
  if v >= 0x80000000 then v = v - 0x100000000 end
  return v
end
local function say(s)
  local l = string.format("f%-7d %6.1fs  %s", frames, frames/60, s)
  out:write(l .. "\n"); out:flush(); print("[watch] " .. l)
end
local function snap()
  local t = {}
  for a = LO, HI, 2 do t[a] = u16(a) end
  return t
end

say("watching - drive, and cross checkpoints. Log flushes on every event.")

local ring, RINGLEN = {}, 90                -- ~1.5 s of history
local pending, lastidx = nil, nil

_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames % 30 == 0 then                  -- keep a rolling pre-checkpoint snapshot
    ring[#ring+1] = {f = frames, m = snap()}
    if #ring > 3 then table.remove(ring, 1) end
  end

  local idx  = u16(0x9016C2)
  local head = s32(0x9015EC)
  if lastidx ~= nil and idx ~= lastidx and head ~= 0 then
    local node = head + idx*26
    local flg  = u16(node + 8)
    say(string.format("SECTION idx=%-3d value=%-5d flags=%04X (marker %X type %X name %d)"
        .. "  [car %d %d %d]", idx, u16(node), flg, (flg>>12)&0xF, (flg>>8)&0xF, flg&0xFF,
        s32(0x900044), s32(0x900048), s32(0x90004C)))
    pending = {at = frames, before = ring[1]}
  end
  lastidx = idx

  -- a second after the crossing, report what changed
  if pending and frames == pending.at + 60 and pending.before then
    local now = snap()
    local rows = {}
    for a = LO, HI, 2 do
      local d = now[a] - pending.before.m[a]
      if d ~= 0 and math.abs(d) < 60000 then rows[#rows+1] = {a, pending.before.m[a], now[a], d} end
    end
    table.sort(rows, function(p, q) return math.abs(p[4]) > math.abs(q[4]) end)
    say(string.format("  -- words that jumped across that checkpoint (%d of them):", #rows))
    for i = 1, math.min(#rows, 12) do
      local r = rows[i]
      say(string.format("       0x%06X  %6d -> %-6d  (%+d)", r[1], r[2], r[3], r[4]))
    end
    pending = nil
  end

  if frames % 1800 == 0 then
    say(string.format("tick  sec=%d  car %d %d %d", u16(0x9016C2),
        s32(0x900044), s32(0x900048), s32(0x90004C)))
  end
end)
