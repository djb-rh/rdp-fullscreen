-- Start a game, then walk the car through track B's +0x004 block positions and
-- watch whether the route-section value advances.
local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local BLK, N = 0x950204, 725                 -- track B records, 64 bytes each
local function lo_first(a)                   -- 32-bit, low word first
  local lo = sp:read_u16(a); local hi = sp:read_u16(a+2)
  local v = hi*65536 + lo
  if v >= 0x80000000 then v = v - 0x100000000 end
  return v
end
local frames, log, last, k = 0, {}, {}, 0
local function note(s) log[#log+1] = string.format("f%-6d %s", frames, s) end
local function press(f,on,off,a,b) if frames==a then f:set_value(on) elseif frames==b then f:set_value(off) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin,0,coin.defvalue,240,270)
  press(key,0,key.defvalue,360,405); press(key,0,key.defvalue,540,585); press(key,0,key.defvalue,720,765)
  if frames > 960 then gas:set_value(200); whl:set_value(2048) end
  if frames > 1400 and frames % 3 == 0 and k < N then
    local r = BLK + k*64
    local ok = pcall(function()
      sp:write_u32(0x900044, lo_first(r) % 0x100000000)        -- X
      sp:write_u32(0x90004C, lo_first(r+4) % 0x100000000)      -- Z
      sp:write_u32(0x900048, lo_first(r+8) % 0x100000000)      -- Y
    end)
    k = k + 1
    if k % 100 == 0 then note(string.format("stepped to record %d", k)) end
  end
  local ok1, d58 = pcall(function() return sp:read_u16(0x900D58) end)
  local ok2, cell = pcall(function() return sp:read_u32(0x9001EC) end)
  if ok1 and last.d58 ~= d58 then note(string.format("D58 = %d", d58)); last.d58 = d58 end
  if ok2 and last.cell ~= cell then note(string.format("cell = %08X", cell)); last.cell = cell end
  if frames == 4200 then
    local f=io.open("teleport.txt","w")
    for _,l in ipairs(log) do f:write(l.."\n") end
    f:close(); print("teleport written"); mach:exit()
  end
end)
