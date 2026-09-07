-- Autopilot lap with periodic screen captures, so the run can be watched back.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local PATH = dofile("trackB_path.lua")
local function s32(a) local v=sp:read_u32(a); if v>=0x80000000 then v=v-0x100000000 end; return v end
local frames, log, wp, prev, last = 0, {}, 1, nil, {}
local SIGN, lastwp, stall = 1, 1, 0
local snaps, nextSnapF = {}, 1500
local function note(s) log[#log+1]=string.format("f%-6d %s",frames,s) end
local function press(f,on,off,a,b) if frames==a then f:set_value(on) elseif frames==b then f:set_value(off) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin,0,coin.defvalue,240,270)
  press(key,0,key.defvalue,360,405); press(key,0,key.defvalue,540,585); press(key,0,key.defvalue,720,765)
  if frames >= 780 and frames % 6 == 0 and frames <= 7980 then
    mach.video:snapshot()                       -- ~10 fps of the run
  end
  if frames < 900 then return end
  local ok, x = pcall(function() return s32(0x900044) end)
  if not ok then return end
  local z = s32(0x90004C)
  while wp < #PATH do
    local t = PATH[wp]
    if (x-t[1])^2+(z-t[2])^2 < 4000^2 then wp = wp + 1 else break end
  end
  local t = PATH[math.min(wp+3, #PATH)]
  local steer, hd = 2048, nil
  if prev then
    local hx, hz = x-prev[1], z-prev[2]
    local hm = math.sqrt(hx*hx+hz*hz)
    if hm > 5 then
      hx, hz = hx/hm, hz/hm
      local tx, tz = t[1]-x, t[2]-z
      local tm = math.sqrt(tx*tx+tz*tz)
      if tm > 1 then
        tx, tz = tx/tm, tz/tm
        local cross = hx*tz - hz*tx
        steer = 2048 + SIGN*cross*1800
        if hx*tx+hz*tz < 0 then steer = 2048 + SIGN*(cross>=0 and 1800 or -1800) end
        hd = cross
      end
    end
  end
  whl:set_value(math.max(16, math.min(4080, math.floor(steer))))
  gas:set_value(hd and math.abs(hd) > 0.5 and 120 or 220)
  prev = {x, z}
  if frames % 240 == 0 then
    if wp <= lastwp then
      stall = stall + 1
      if stall == 2 then SIGN = -SIGN; stall = 0 end
    else stall = 0 end
    lastwp = wp
  end
  -- RAM snapshots on a fixed frame schedule (waypoint triggers proved unreliable)
  if frames >= nextSnapF and #snaps < 8 then
    nextSnapF = frames + 700
    local row = {}
    for a = 0x900000, 0x901FFE, 2 do
      local o, v = pcall(function() return sp:read_u16(a) end)
      row[a] = o and v or 0
    end
    snaps[#snaps+1] = {wp = wp, f = frames, row = row}
    note(string.format("RAM snapshot %d at wp %d", #snaps, wp))
  end
  if frames % 600 == 0 then
    note(string.format("wp %4d/%d  pos %7d %7d  D58=%d", wp, #PATH, x, z, sp:read_u16(0x900D58)))
  end
  if frames == 8400 then
    local f=io.open("record.txt","w")
    for _,l in ipairs(log) do f:write(l.."\n") end
    if #snaps >= 5 then
      f:write("\nwords moving monotonically with lap progress:\n")
      for a = 0x900000, 0x901FFE, 2 do
        local up, dn, dif = 0, 0, 0
        for i = 2, #snaps do
          local p, c = snaps[i-1].row[a], snaps[i].row[a]
          if c > p then up = up+1 elseif c < p then dn = dn+1 end
          if c ~= p then dif = dif+1 end
        end
        if dif >= #snaps-2 and (up == 0 or dn == 0) then
          local vs = {}
          for i=1,#snaps do vs[#vs+1] = snaps[i].row[a] end
          f:write(string.format("  0x%06X  %s\n", a, table.concat(vs," ")))
        end
      end
    end
    f:close(); print("record written"); mach:exit()
  end
end)
