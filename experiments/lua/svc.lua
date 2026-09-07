local m = manager.machine
local f = m.ioport.ports[":mainpcb:IN0"].fields["Service Mode"]
-- DIP switches are set through user_value, not set_value (which is for
-- digital/analog inputs). set_value silently does nothing here.
local ok, err = pcall(function() f.user_value = 0 end)
print(string.format("[svc] mask=%04X default=%d  user_value now %s (%s)",
      f.mask, f.defvalue, tostring(f.user_value), ok and "set ok" or tostring(err)))
local n = 0
_G.sub = emu.add_machine_frame_notifier(function()
  n = n + 1
  if n >= 240 and n % 120 == 0 and n <= 1400 then m.video:snapshot() end
  if n == 1450 then print("[svc] done"); m:exit() end
end)
