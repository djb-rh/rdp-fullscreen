-- Boot Race Drivin' straight into its operator/test menu, so you can run
-- SET CONTROLS and calibrate the G29's centre.
--
--   mame racedriv -rompath "/Users/djb/Developer/Race Drivin" -autoboot_script service.lua
--
-- Service Mode is PORT_SERVICE(0x20, IP_ACTIVE_LOW) on :mainpcb:IN0 - a DIP
-- SWITCH, not a button, which is why it never appears in Input Settings. It
-- lives under Tab -> DIP Switches. DIP switches are set through `user_value`;
-- `set_value()` does nothing on them.
local f = manager.machine.ioport.ports[":mainpcb:IN0"].fields["Service Mode"]
f.user_value = 0
print("[service] Service Mode ON - the game will boot into TEST MENU.")
print("[service] Calibrate under SET CONTROLS, then quit and relaunch normally.")
