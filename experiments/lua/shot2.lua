local mach=manager.machine
local f=0
_G.sub=emu.add_machine_frame_notifier(function()
  f=f+1
  if f>=200 and f%12==0 and f<=4400 then mach.video:snapshot() end
  if f==4600 then print("done"); mach:exit() end
end)
