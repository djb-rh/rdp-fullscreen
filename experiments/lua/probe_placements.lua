-- Headless probe: coin up, pick the ORIGINAL track and the AUTOMATIC car, then
-- tap memory while the world renders.  No wheel needed, no test drive needed.
--
--   mame racedriv -rompath .../roms_loop -autoboot_script probe_placements.lua \
--        -video none -sound none -seconds_to_run 60 -nothrottle
--
-- Selection is by STEERING, not buttons: full left picks the original track,
-- then full left again picks the automatic car.  The manual car has no usable
-- shifter binding here and sits in neutral, which is why an earlier version of
-- this never moved and kept landing on Super Stunt (section 724).
--
-- Two traps that cost a lot of time:
--   * the pedal is PORT_REVERSEd - set_value(0) is FULL THROTTLE, 255 is idle
--   * KEEP A REFERENCE to whatever install_read_tap returns.  A collected tap
--     object silently uninstalls itself and the counts just stop rising.
local mach = manager.machine
local cpu = mach.devices[":mainpcb:maincpu"]
local sp = cpu.spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local function hold(f,a,b) if frames==a then f:set_value(1) elseif frames==b then f:set_value(0) end end
local BUF, N = 0x809946, 156
local pc20, pc22, offc = {}, {}, {}
_G.TAPS = {}
_G.TAPS[1] = sp:install_read_tap(BUF, BUF + N*50 + 1, "buf", function(o,d,m)
  local off = (o - BUF) % 50
  offc[off] = (offc[off] or 0) + 1
  local pc = cpu.state["PC"].value
  if off == 0x20 then pc20[pc] = (pc20[pc] or 0) + 1 end
  if off == 0x22 then pc22[pc] = (pc22[pc] or 0) + 1 end
  return d
end)
frames=0
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  hold(coin,240,285); hold(coin,330,375)
  hold(key,480,525); hold(key,660,705); hold(key,840,885)
  if frames > 300 and frames < 1800 then whl:set_value(whl.minvalue)
  elseif frames >= 1800 then whl:set_value(2048); gas:set_value(0) end
  if frames == 3000 then
    local l={} ; for o,c in pairs(offc) do l[#l+1]={o,c} end
    table.sort(l, function(a,b) return a[1]<b[1] end)
    local s=""; for _,e in ipairs(l) do s=s..string.format("+%02X:%d ", e[1], e[2]) end
    print("[r] buffer offsets read: "..s)
    local function top(t, tag)
      local p={} ; for pc,c in pairs(t) do p[#p+1]={pc,c} end
      table.sort(p, function(a,b) return b[2]<a[2] end)
      for i=1,math.min(#p,6) do print(string.format("[r] %s read at PC %06X  x%d", tag, p[i][1], p[i][2])) end
      if #p==0 then print("[r] "..tag.." never read") end
    end
    top(pc20, "+0x20"); top(pc22, "+0x22")
    mach:exit()
  end
end)
