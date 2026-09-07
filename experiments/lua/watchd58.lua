local mach = manager.machine
local sp   = mach.devices[":mainpcb:maincpu"].spaces["program"]
local frames, log = 0, {}
_G.sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames % 30 == 0 then
    local ok1, head = pcall(function() return sp:read_u32(0x9015EC) end)
    local ok2, d58  = pcall(function() return sp:read_u16(0x900D58) end)
    local ok3, d5a  = pcall(function() return sp:read_u32(0x900D5A) end)
    log[#log+1] = {f=frames, h=ok1 and head or 0, v=ok2 and d58 or 0, w=ok3 and d5a or 0}
  end
  if frames == 5400 then
    local f = io.open("watchd58.txt","w")
    f:write("frame   route head   0x900D58   0x900D5A\n")
    local prev
    for _, e in ipairs(log) do
      local mark = (prev and (prev.h ~= e.h or prev.v ~= e.v)) and "  <-- changed" or ""
      if e.f % 300 == 0 or mark ~= "" then
        f:write(string.format("%5d   %08X   %6d     %08X%s\n", e.f, e.h, e.v, e.w, mark))
      end
      prev = e
    end
    f:close(); print("watchd58 written"); mach:exit()
  end
end)
