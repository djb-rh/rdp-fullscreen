local mach = manager.machine
local frames = 0
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames >= 200 and frames % 10 == 0 and frames <= 3800 then mach.video:snapshot() end
  if frames == 4000 then print("shots done"); mach:exit() end
end)
