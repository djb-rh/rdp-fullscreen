local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local gas=fld(":mainpcb:8BADC.0","Gas Pedal"); local whl=fld(":mainpcb:12BADC.0","Steering Wheel")
local frames, snaps = 0, {}
local LO, HI = 0x900000, 0x9005FF
local function press(f,on,off,a,b) if frames==a then f:set_value(on) elseif frames==b then f:set_value(off) end end
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  press(coin,0,coin.defvalue,240,270)
  press(key,0,key.defvalue,360,405); press(key,0,key.defvalue,540,585); press(key,0,key.defvalue,720,765)
  if frames > 960 then gas:set_value(255); whl:set_value(2048) end
  if frames > 2000 and frames % 400 == 0 then
    local row = {}
    for a = LO, HI, 2 do
      local ok, v = pcall(function() return sp:read_u32(a) end)
      row[a] = ok and v or 0
    end
    snaps[#snaps+1] = row
  end
  if frames == 6000 then
    -- track B world bounds: X -189603..59168, Z -164744..40166
    local function inb(v)
      if v >= 0x80000000 then v = v - 0x100000000 end
      return v > -220000 and v < 90000
    end
    local f = io.open("findcar.txt","w")
    f:write("addresses holding a plausible track-B coordinate that CHANGES:\n")
    local n = 0
    for a = LO, HI, 2 do
      local vals, changed, allin = {}, false, true
      for i, s in ipairs(snaps) do
        vals[i] = s[a]
        if not inb(s[a]) then allin = false end
        if i > 1 and s[a] ~= snaps[i-1][a] then changed = true end
      end
      if allin and changed then
        n = n + 1
        local ss = {}
        for i = 1, math.min(#vals, 8) do
          local v = vals[i]; if v >= 0x80000000 then v = v - 0x100000000 end
          ss[#ss+1] = string.format("%d", v)
        end
        f:write(string.format("  0x%06X  %s\n", a, table.concat(ss, " ")))
      end
    end
    f:write(string.format("\n%d candidates over %d snapshots\n", n, #snaps))
    f:close(); print("findcar written"); mach:exit()
  end
end)
