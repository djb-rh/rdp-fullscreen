-- Back the car up along its own direction of travel, then gas it forward so it
-- crosses the start/finish line under the game's own physics.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local function s32(a) local v = sp:read_u32(a); if v>=0x80000000 then v=v-0x100000000 end; return v end
local function w32(a,v) sp:write_u32(a, v % 0x100000000) end
local X,Y,Z = 0x900044, 0x900048, 0x90004C
local frames, log, last = 0, {}, {}
local p1, vdir, cycle, backups = nil, nil, 0, 0
local function note(s) log[#log+1]=string.format("f%-6d %s",frames,s) end
local function press(f,on,off,a,b) if frames==a then f:set_value(on) elseif frames==b then f:set_value(off) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin,0,coin.defvalue,240,270)
  press(key,0,key.defvalue,360,405); press(key,0,key.defvalue,540,585); press(key,0,key.defvalue,720,765)
  if frames > 960 then gas:set_value(255); whl:set_value(2048) end
  local ok, cx = pcall(function() return s32(X) end)
  if not ok then return end
  local cz = s32(Z)
  -- learn the direction of travel from real motion
  if frames == 1100 then p1 = {cx, cz} end
  if frames == 1160 and p1 then
    local dx, dz = cx-p1[1], cz-p1[2]
    local m = math.sqrt(dx*dx+dz*dz)
    if m > 50 then vdir = {dx/m, dz/m}; note(string.format("travel dir %.3f,%.3f (|v|=%.0f/min)", dx/m, dz/m, m)) end
  end
  -- every 900 frames: jump back along -vdir, then let it drive forward again
  if vdir and frames > 1200 and (frames - 1200) % 900 == 0 and backups < 5 then
    local D = 12000                                   -- ~90 m back
    w32(X, math.floor(cx - vdir[1]*D))
    w32(Z, math.floor(cz - vdir[2]*D))
    backups = backups + 1
    note(string.format("backed up %d units, run %d", D, backups))
  end
  local d58  = sp:read_u16(0x900D58)
  local head = sp:read_u32(0x9015EC)
  local d60  = sp:read_u32(0x900D60)
  if last.d58 ~= d58 then note("D58 = "..d58); last.d58 = d58 end
  if last.head ~= head then note(string.format("head = %08X", head)); last.head = head end
  if last.d60 ~= d60 then note("D60 = "..d60); last.d60 = d60 end
  if frames == 7200 then
    local f=io.open("gategas.txt","w"); for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("gategas written"); mach:exit()
  end
end)
