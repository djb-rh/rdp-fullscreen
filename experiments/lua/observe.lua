-- Coin, ONE long key turn, then no further input. Watch what happens.
local mach = manager.machine
local P = mach.ioport.ports
local function fld(t,n) local p=P[t]; return p and p.fields[n] end
local coin=fld(":mainpcb:IN0","Coin 1"); local key=fld(":mainpcb:a80000","Key")
local frames = 0
_G.log = {}
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == 240 then coin:set_value(1) end
  if frames == 300 then coin:set_value(0) end
  -- one deliberate, long key turn
  if frames == 3600 then key:set_value(1); _G.log[#_G.log+1]="key ON at 3600" end
  if frames == 3720 then key:set_value(0); _G.log[#_G.log+1]="key OFF at 3720 (2s)" end
  if frames >= 3400 and frames % 8 == 0 and frames <= 11000 then mach.video:snapshot() end
  if frames == 11400 then
    local f=io.open("observe.txt","w")
    for _,l in ipairs(_G.log) do f:write(l.."\n") end
    f:write("key field found: "..tostring(key ~= nil).."\n")
    f:close(); print("observe done"); mach:exit()
  end
end)
