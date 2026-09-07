-- Race Drivin': service mode + checkpoint watching in one script.
--
--   mame racedriv -rompath "/Users/djb/Developer/Race Drivin" -autoboot_script rd.lua
--   SERVICE=1 mame racedriv ... -autoboot_script rd.lua      (boot into TEST MENU)
--
-- Watching runs always. Service mode only when SERVICE=1, and you can flip it
-- off live from Tab -> DIP Switches -> Service Mode -> Off to drop into the
-- game with logging already running.
--
-- Service Mode is PORT_SERVICE(0x20, IP_ACTIVE_LOW) on :mainpcb:IN0 - a DIP
-- SWITCH, so it is under Tab -> DIP Switches, not Input Settings. DIP switches
-- are set through `user_value`; set_value() does nothing on them.
local mach = manager.machine
local cpu  = mach.devices[":mainpcb:maincpu"]
local sp   = cpu.spaces["program"]

local svc = mach.ioport.ports[":mainpcb:IN0"].fields["Service Mode"]
if os.getenv("SERVICE") == "1" then
  svc.user_value = 0
  print("[rd] SERVICE MODE on - boots into TEST MENU. Calibrate under SET CONTROLS.")
  print("[rd] Then Tab -> DIP Switches -> Service Mode -> Off to drop into the game.")
else
  print("[rd] normal boot. Tab -> DIP Switches -> Service Mode -> On for the test menu.")
end

-- Brake. The G29 brake is on RXAXIS (racedriv.cfg, NOT default.cfg) and reads
-- +65536 released / -65536 pressed.
--
-- The game was recalibrated in service mode with 4095 as "foot off", so its
-- stored calibration now reads 4095 as no brake and 0 as full brake. That is the
-- opposite polarity to the factory calibration, which is why the reverse flag
-- had to flip too: the correct running state is now reverse OFF, giving
-- released -> 4095 (no brake) and pressed -> 0 (full brake).
--
-- The startup problem still applies. MAME reports an axis as 0 until the pedal
-- is first moved, and unreversed that leaves the field at 0 - which this
-- calibration reads as FULL BRAKE. The cabinet brake is a force sensor and the
-- game latches a zero baseline at startup, so it would calibrate against that
-- phantom again. So: start REVERSED, which makes the untouched default read 4095
-- (no brake), and drop to the correct unreversed mapping the instant the axis
-- reports for real.
local brake, brake_axis = nil, nil
for _, port in pairs(mach.ioport.ports) do
  if port.fields["Brake Pedal"] then brake = port.fields["Brake Pedal"] end
end
if brake and os.getenv("BRAKE_HOLD") == "0" then
  brake:set_analog_reverse(false)     -- plain running mapping, no hold-until-live
  print("[rd] BRAKE_HOLD=0: plain unreversed brake, no hold-until-live")
elseif brake then
  brake:set_analog_reverse(true)
  local ok, c = pcall(function() return mach.input:code_from_token("JOYCODE_1_RXAXIS") end)
  if ok then brake_axis = c end
  print("[rd] brake held at 'no brake' until the pedal first reports (see NOTES.md)")
end

-- Keyboard pedals: A = gas, S = brake, set here rather than in the cfg so they
-- survive whatever is (or is not) saved there. MAME drives an analog pedal from
-- a digital key through its "increment" sequence, and returns it to rest through
-- centerdelta - so centerdelta must be NON-zero or the pedal stays where the key
-- left it. (An earlier version set it to 0 chasing a stuck brake; the real cause
-- of that turned out to be the reverse flag, see NOTES.md.)
-- The gas is PORT_REVERSE in the driver, so with nothing attached it RESTS at
-- its maximum (255) - and the game reads that as full throttle, which is the
-- stuck throttle. Un-reverse it and it rests at 0. GAS_REVERSE=1 puts it back
-- if a real pedal is ever plugged into this machine.
local PEDAL_KEY = { ["Gas Pedal"] = "KEYCODE_A", ["Brake Pedal"] = "KEYCODE_S" }
local GAS_REV = os.getenv("GAS_REVERSE") == "1"
for _, port in pairs(mach.ioport.ports) do
  for nm, key in pairs(PEDAL_KEY) do
    local pf = port.fields[nm]
    if pf and pf.is_analog then
      local ok, seq = pcall(function() return mach.input:seq_from_tokens(key) end)
      if ok and seq then
        pcall(function() pf:set_input_seq("increment", seq) end)
        pf:set_centerdelta(pf.default_centerdelta > 0 and pf.default_centerdelta or 100)
        if nm == "Gas Pedal" then pf:set_analog_reverse(GAS_REV) end
        print(string.format("[rd] %-12s <- %s   rests at %d, centerdelta %d",
              nm, key, port:read() & pf.mask, pf.centerdelta))
      else
        print("[rd] could not bind " .. key .. " to " .. nm)
      end
    end
  end
end

-- ---------------------------------------------------------------------------
-- Keyboard driving and clock top-up, for testing without a wheel.
--   DRIVE=1  arrow keys steer, [ = 70%% throttle, ] = 100%%, down arrow brakes
--   TIME=1   keep the lap clock topped up so a long loop can be explored
--
-- field:set_value() sets a programmatic override that bypasses the analog
-- pipeline entirely - including PORT_REVERSE. Gas and brake are both reversed in
-- the driver, so the value the game actually reads is inverted: 255 is idle gas
-- and 0 is full, 4095 is brake released and 0 is full. That matches the brake
-- calibration (4095 = foot off), so the same convention holds for both.
local DRIVE = os.getenv("DRIVE") == "1"
local TIMEUP = os.getenv("TIME") == "1"

local function findf(name)
  for _, p in pairs(mach.ioport.ports) do
    if p.fields[name] then return p.fields[name] end
  end
end
local whl = findf("Steering Wheel")
local KEY = {}
if DRIVE or TIMEUP then
  for _, k in ipairs({"LEFT","RIGHT","BACKSPACE","COMMA","STOP"}) do
    local ok, c = pcall(function() return mach.input:code_from_token("KEYCODE_" .. k) end)
    if ok then KEY[k] = c end
  end
end
-- Steering.  MAME's own analog settings (PORT_SENSITIVITY 400, PORT_KEYDELTA 5,
-- and everything under Tab -> Analog Controls) have NO effect while this script
-- runs: set_value() writes the field directly every frame and overrides them.
-- So the feel is entirely these four numbers.
--   STEER_FULL    seconds from centre to full travel while a key is held
--   STEER_V0      mph at which available travel is halved
--   STEER_MIN     floor on travel, as a fraction of full lock
--   STEER_RETURN  self-centring per frame when no key is held
local STEER_FULL   = tonumber(os.getenv("STEER_FULL")   or "1.1")
local STEER_V0     = tonumber(os.getenv("STEER_V0")     or "22")
local STEER_MIN    = tonumber(os.getenv("STEER_MIN")    or "0.10")
local STEER_RETURN = tonumber(os.getenv("STEER_RETURN") or "0.10")
local CENTRE = tonumber(os.getenv("STEER_CENTER") or "")
if not CENTRE then CENTRE = whl and ((whl.minvalue + whl.maxvalue) / 2) or 0 end
local steer = CENTRE
local mph, lastpos = 0.0, nil
local CLOCK = 0x9016DA          -- 32-bit lap clock; 250 units = 1 second
local TIME_S   = tonumber(os.getenv("TIME_S") or "600")   -- seconds to top up to
local TIME_SET = math.floor(TIME_S * 250)
local TIME_LOW = math.floor(TIME_SET / 2)
local CAR = { x = 0x900044, y = 0x900048, z = 0x90004C }
-- The loop's first segment, in SEGMENT-array coordinates. The car's own frame is
-- not yet confirmed to be the same one (placement and segment frames are
-- transposed - see NOTES.md), so BACKSPACE reports rather than warps until a
-- reading from a live car settles which is which.
local LOOP_ENTRY = { 214664, 188964 }

if DRIVE then
  print("[rd] DRIVE: left/right arrows steer. Gas and brake are MAME's own keys,")
  print("[rd]        untouched - see Tab -> Input (this Machine) for what they are.")
  print(string.format("[rd]        , and . trim the steering centre (now %d); pass it back as STEER_CENTER",
        CENTRE))
  print(string.format("[rd]        travel is speed-scaled: full lock at rest, %.0f%% at %d mph, %.0f%% at 100.",
        100*STEER_V0/(50+STEER_V0), 50, 100*math.max(STEER_MIN, STEER_V0/(100+STEER_V0))))
  print("[rd]        STEER_FULL/STEER_V0/STEER_MIN/STEER_RETURN tune it. BACKSPACE reports speed.")
end
if TIMEUP then print(string.format("[rd] TIME: clock topped up to %d s whenever it drops below %d s",
      TIME_S, math.floor(TIME_S/2))) end

-- LOG=1: one CSV line per frame of what the physics thinks is under the car.
-- The DSP32C owns the physics; its result block is mirrored at 0x900C70 and
-- +0x58 of it is the segment index the DSP says we are on (the 68010 turns it
-- into the record address at 0x9016D2).  Drive the crossover both ways with
-- this on and the log shows, frame by frame, which road the game put you on.
local LOGGING = os.getenv("LOG") == "1"
local logf = LOGGING and io.open("drive_log.csv", "w") or nil
if logf then
  local h = {"frame","clock","x","y","z","offroad","sect_val","sect_idx","curseg","d54","d58","d60","polys","listlen","movers","polymax","freemin","resets"}
  for i = 0, 25 do h[#h+1] = string.format("dsp%02X", 0x50 + i*2) end
  logf:write(table.concat(h, ",") .. "\n")
  print("[rd] LOG: writing drive_log.csv every frame")
end
-- Renderer verdicts.  The ADSP gathers the current cell's placement records to
-- 0x809946 (50 bytes each) and writes back into +0x24..+0x31 - camera-relative
-- x/y/z (three s32) and a 16-bit key - and sets runtime bits in +0x22 (0x0001
-- seen on a near object, 0x2001 on a far one).  Log those for the pieces that
-- matter, found in the buffer by their world position.
local BUF = 0x809946
local WATCH = {}
if logf then
  local base = sp:read_u32(sp:read_u32(0x940000))
  for _, r in ipairs({176, 177, 193, 194, 195, 196}) do
    local a = base + r*50
    WATCH[#WATCH+1] = {rec = r, x = sp:read_u32(a + 0x14), z = sp:read_u32(a + 0x1C)}
  end
  local rl = io.open("render_log.csv", "w")
  rl:write("frame,rec,slot,f22,cx,cy,cz,key\n")
  _G.rlog = rl
end
local function rlogline(frames)
  if not _G.rlog or #WATCH == 0 then return end
  local function s32(a) local v = sp:read_u32(a); if v >= 0x80000000 then v = v - 0x100000000 end; return v end
  for slot = 0, 199 do
    local a = BUF + slot*50
    local o = sp:read_u16(a)
    if o > 389 then break end
    local x, z = sp:read_u32(a + 0x14), sp:read_u32(a + 0x1C)
    for _, w in ipairs(WATCH) do
      if x == w.x and z == w.z then
        _G.rlog:write(string.format("%d,%d,%d,%04X,%d,%d,%d,%d\n", frames, w.rec, slot,
          sp:read_u16(a + 0x22), s32(a + 0x24), s32(a + 0x28), s32(a + 0x2C), sp:read_u16(a + 0x30)))
      end
    end
  end
  if frames % 300 == 0 then _G.rlog:flush() end
end

-- Renderer load.  The ADSP keeps a per-frame pool of 495 polygon slots (built
-- by $07C4, free list head at PM $123F, sentinel $1242) and fills it far-to-
-- near from the depth-sorted object list (head at DM $0992, links at word 24
-- of each 25-word record).  When the pool is empty, $0855 skips the insert and
-- the polygon is dropped - and what remains at that point is the nearest
-- geometry, i.e. the road under the car.  Log the free count, the object-list
-- length and the active movers so the crossing can be compared with elsewhere.
local adsp = mach.devices[":mainpcb:adsp"]
local apm = adsp and adsp.spaces["program"]
local adm = adsp and adsp.spaces["data"]
-- Exact per-frame polygon count: the ADSP writes the list head PM $123F on
-- every head insertion and on the per-frame reset, so a write tap sees the
-- chain at those moments; the max between two 68010 frames is the frame's
-- count.  DM $0957 is the free-list head; its minimum shows exhaustion.
local _pmax, _freemin, _resets = 0, 65535, 0
if apm and adm then
  _G.TAPS = _G.TAPS or {}
  _G.TAPS[#_G.TAPS+1] = apm:install_write_tap(0x123F, 0x123F, "head", function(o, d, m)
    local function pm(a) local ok, v = pcall(function() return apm:read_u32(a) end); return ok and ((v >> 8) & 0xFFFF) or 0 end
    local p, n = pm(0x123F), 0
    while p >= 0x1242 and p < 0x1E00 and n < 600 do n = n + 1; p = pm(p + 3) end
    if n > _pmax then _pmax = n end
    if ((d >> 8) & 0xFFFF) == 0x1242 then _resets = _resets + 1 end
    local ok, f = pcall(function() return adm:read_u16(0x0957) end)
    if ok and f < _freemin then _freemin = f end
    return d
  end)
end
local function polymax() local v = _pmax; _pmax = 0; return v end
local function freemin() local v = _freemin; _freemin = 65535; return v end
local function resets() local v = _resets; _resets = 0; return v end

local function polys()
  -- length of the ADSP's depth-sorted polygon list this frame: head at
  -- PM $123F (PM words are 24-bit with the 16-bit value in the top bits),
  -- next pointer at +3 of each entry, sentinel $1236/$1242.  It grows through
  -- the ADSP frame, so the PEAK over a stretch is the per-frame count; the
  -- pool has 495 entries.
  if not apm then return -1 end
  local function pm(a) local ok, v = pcall(function() return apm:read_u32(a) end); return ok and ((v >> 8) & 0xFFFF) or 0 end
  local p, n = pm(0x123F), 0
  while p >= 0x1242 and p < 0x1E00 and n < 600 do n = n + 1; p = pm(p + 3) end
  return n
end
local function listlen()
  if not adm then return -1 end
  local ok, p = pcall(function() return adm:read_u16(0x0992) end)
  if not ok then return -1 end
  local n = 0
  while p ~= 0 and n < 400 do n = n + 1; local ok2, q = pcall(function() return adm:read_u16(p) end); if not ok2 then break end; p = q end
  return n
end
local function movers()
  if not adm then return -1 end
  local n = 0
  for i = 0, 26 do local ok, o = pcall(function() return adm:read_u16(0x0A00 + i*25) end); if ok and o ~= 0xFFFF and o < 390 then n = n + 1 end end
  return n
end

local function logline(frames)
  if not logf then return end
  rlogline(frames)
  local function u16(a) local ok,v = pcall(function() return sp:read_u16(a) end); return ok and v or -1 end
  local function s16(a) local v = u16(a); if v >= 0x8000 then v = v - 0x10000 end; return v end
  local function s32(a) local ok,v = pcall(function() return sp:read_u32(a) end)
    if not ok then return -1 end; if v >= 0x80000000 then v = v - 0x100000000 end; return v end
  local base = sp:read_u32(0x900D5A); local cur = sp:read_u32(0x9016D2)
  local curseg = (base > 0 and cur >= base) and math.floor((cur - base) / 64) or -1
  local r = {frames, s32(0x9016DA), s32(0x900044), s32(0x900048), s32(0x90004C),
             u16(0x9016BA), s16(0x9016C0), u16(0x9016C2), curseg,
             s16(0x900D54), s16(0x900D58), s32(0x900D60), polys(), listlen(), movers(), polymax(), freemin(), resets()}
  for i = 0, 25 do r[#r+1] = s16(0x900C70 + 0x50 + i*2) end
  logf:write(table.concat(r, ",") .. "\n")
  if frames % 300 == 0 then logf:flush() end
end

-- WARP=1: the ROM set in roms_warp/ starts the car on a chosen segment
-- (record 0 of the segment array, +0x08).  The DSP does not follow, so it
-- calls the car off-road and resets it - unless the section is forced through
-- 0x900D54 (value = segment + 69).  Do that for the first 3 s of the clock.
local WARP = os.getenv("WARP") == "1"
local warp_frames = 0
local function warp()
  if not WARP then return end
  local ok, clk = pcall(function() return sp:read_u32(0x9016DA) end)
  if not ok or clk == 0 or warp_frames > 180 then return end
  warp_frames = warp_frames + 1
  local seg = sp:read_u16(sp:read_u32(0x940004) + 8)
  pcall(function() sp:write_u16(0x900D54, seg + 69) end)
end

local out = io.open("watch_log.txt", "w")
local frames = 0
local LO, HI = 0x900000, 0x901FFE
local function u16(a) local ok,v = pcall(function() return sp:read_u16(a) end); return ok and v or 0 end
local function s32(a)
  local ok,v = pcall(function() return sp:read_u32(a) end)
  if not ok then return 0 end
  if v >= 0x80000000 then v = v - 0x100000000 end
  return v
end
local function say(s)
  local l = string.format("f%-7d %6.1fs  %s", frames, frames/60, s)
  out:write(l.."\n"); out:flush(); print("[rd] "..l)
end
local function snap()
  local t = {}
  for a = LO, HI, 2 do t[a] = u16(a) end
  return t
end
say("logging. Cross a checkpoint and the award shows up below it.")

local ring, pending, lastidx, lastsvc = {}, nil, nil, svc.user_value
_G.sub = emu.add_machine_frame_notifier(function()
  warp()
  logline(frames + 1)
  if DRIVE then
    local pressed = function(k) return KEY[k] and mach.input:code_pressed(KEY[k]) end
    -- Steering centre is a trim, not the midpoint of the field: the game keeps
    -- its own wheel calibration and its idea of straight-ahead is not 2048.
    -- , and . nudge it; the value printed is what to pass as STEER_CENTER.
    if pressed("COMMA")  and frames % 4 == 0 then
      CENTRE = CENTRE - 8; say(string.format("steering centre %d", CENTRE)) end
    if pressed("STOP")   and frames % 4 == 0 then
      CENTRE = CENTRE + 8; say(string.format("steering centre %d", CENTRE)) end
    if whl then
      -- Speed comes from the car's own position, not a memory location we would
      -- have to go find: one frame of travel is 1.023 mph per unit.
      local cx, cz = s32(CAR.x), s32(CAR.z)
      if lastpos then
        local d = math.sqrt((cx-lastpos[1])^2 + (cz-lastpos[2])^2) * 1.023
        if d < 400 then mph = mph + (d - mph) * 0.15 end    -- ignore warps
      end
      lastpos = { cx, cz }

      -- Travel shrinks with speed.  A real wheel gives you 135 degrees to meter
      -- out a correction at 100 mph; an arrow key gives you none, so the key has
      -- to be given less of the lock to reach instead.
      local span  = (whl.maxvalue - whl.minvalue) / 2
      local limit = span * math.max(STEER_MIN, STEER_V0 / (mph + STEER_V0))
      local rate  = limit / (60 * STEER_FULL)
      if     pressed("LEFT")  then steer = math.max(CENTRE - limit, steer - rate)
      elseif pressed("RIGHT") then steer = math.min(CENTRE + limit, steer + rate)
      else   steer = steer + (CENTRE - steer) * STEER_RETURN end
      steer = math.max(whl.minvalue, math.min(whl.maxvalue, steer))
      whl:set_value(math.floor(steer))
    end
  end
  if DRIVE and KEY["BACKSPACE"] and mach.input:code_pressed(KEY["BACKSPACE"]) and frames % 30 == 0 then
    local ok, x = pcall(function() return sp:read_i32(CAR.x) end)
    local _,  y = pcall(function() return sp:read_i32(CAR.y) end)
    local _,  z = pcall(function() return sp:read_i32(CAR.z) end)
    if ok then
      say(string.format("%.0f mph, %.0f%% of lock available", mph,
            100 * math.max(STEER_MIN, STEER_V0 / (mph + STEER_V0))))
      say(string.format("car at (%d, %d, %d)   loop entry is (%d, %d) in segment coords",
          x, y, z, LOOP_ENTRY[1], LOOP_ENTRY[2]))
    end
  end
  if TIMEUP and frames % 30 == 0 then
    local ok, v = pcall(function() return sp:read_u32(CLOCK) end)
    if ok and v > 0 and v < TIME_LOW then
      pcall(function() sp:write_u32(CLOCK, TIME_SET) end)
    end
  end
  -- Arm the real brake mapping as soon as the pedal proves it is reporting.
  if brake_axis and brake and brake.analog_reverse then
    local ok, v = pcall(function() return mach.input:code_value(brake_axis) end)
    if ok and v ~= 0 then
      brake:set_analog_reverse(false)
      say("brake pedal is live - running mapping armed (reverse off)")
      brake_axis = nil
    end
  end
  frames = frames + 1
  if svc.user_value ~= lastsvc then
    say(svc.user_value == 0 and "service mode ON" or "service mode OFF - back to the game")
    lastsvc = svc.user_value
  end
  if frames % 30 == 0 then
    ring[#ring+1] = snap()
    if #ring > 3 then table.remove(ring, 1) end
  end
  local idx, head = u16(0x9016C2), s32(0x9015EC)
  if lastidx ~= nil and idx ~= lastidx and head ~= 0 then
    local node = head + idx*26
    local flg = u16(node+8)
    say(string.format("SECTION idx=%-3d value=%-5d flags=%04X (marker %X type %X name %d)",
        idx, u16(node), flg, (flg>>12)&0xF, (flg>>8)&0xF, flg&0xFF))
    pending = {at = frames, before = ring[1]}
  end
  lastidx = idx
  if pending and frames == pending.at + 60 and pending.before then
    local now, rows = snap(), {}
    for a = LO, HI, 2 do
      local b, n = pending.before[a], now[a]
      local d = n - b
      -- A countdown clock is a SMALL number that jumps UP at a gate. Ranking by
      -- raw magnitude buries it under physics and render state churning by tens
      -- of thousands, which is what went wrong before. Keep timer-shaped words:
      -- both values modest, and a positive jump in a plausible range.
      if d > 3 and d < 4000 and b < 5000 and n < 5000 then
        rows[#rows+1] = {a, b, n, d}
      end
    end
    table.sort(rows, function(p,q) return p[4] > q[4] end)
    -- The lap clock, found by disassembly: 32-bit at 0x9016DA, 250 units = 1 second.
    -- Award = word[track_record+0x40 + (marker&3)*8 + kind*2] * 25, so a track-0
    -- checkpoint should read +8000 = +32.0 s exactly.
    local function clock() return (u16(0x9016DA) * 65536) + u16(0x9016DC) end
    say(string.format("  -- CLOCK 0x9016DA = %d  (%.1f s)", clock(), clock() / 250))
    say(string.format("  -- %d timer-shaped words jumped UP here:", #rows))
    for i = 1, math.min(#rows, 16) do
      local r = rows[i]
      say(string.format("       0x%06X  %5d -> %-5d (%+d)   [/60 = %+.1f s]",
          r[1], r[2], r[3], r[4], r[4]/60))
    end
    pending = nil
  end
end)
