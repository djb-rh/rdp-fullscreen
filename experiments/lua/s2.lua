local m=manager.machine
m.ioport.ports[":mainpcb:IN0"].fields["Service Mode"].user_value=0
local n=0
_G.sub=emu.add_machine_frame_notifier(function()
  n=n+1
  if n==800 then m.video:snapshot() end
  if n==860 then m:exit() end
end)
