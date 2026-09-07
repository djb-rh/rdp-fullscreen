-- Race Drivin' Panorama side pod: 3D render filling all 288 display rows.
--
-- Two stages, applied to the GSP's unpacked program in VRAM:
--   1. viewport bottom edge Y 0x11F (287) -> 0x17F (383)   192 -> 288 rows
--   2. pin the buffer, drawing origin and display start to buffer A, so the
--      two now-288-row buffers stop overlapping
--
-- Stage 2 must come after stage 1 has taken effect, and the pod must already be
-- rendering (i.e. in the driving view) when they are applied.
--
--   FROM=<frame>  when to apply stage 1     (default 5100)
--   GAP=<frames>  delay before stage 2      (default 120)
local mach = manager.machine
local vram = mach.memory.shares[":mainpcb:gsp_vram"]
local rgn  = mach.memory.regions[":mainpcb:maincpu"]
for _, a in ipairs({0x4742E, 0x4743E}) do rgn:write_u8(a, 0); rgn:write_u8(a + 1, 0) end   -- forward view

local VIEWPORT = {                       -- 288-row viewport
  {0xFFF61380, 0x017F}, {0xFFF622C0, 0xFE80}, {0xFFF622F0, 0x017F},
  {0xFFF62420, 0xFE80}, {0xFFF62450, 0x017F}, {0xFFF639A0, 0xFE80},
  {0xFFF64AB0, 0x017F},
}
local PINS = {                           -- single buffer in VRAM blocks 0-71
  {0xFFF5AEA0, 0x0200},                  -- B-arm base    -> 0x02000000
  {0xFFF5AD80, 0xFFFC},                  -- A-arm display -> block 0 (was block 48)
  {0xFFF5ADF0, 0x0203},                  -- A-arm handshake -> report buffer B, so the
                                         --   68010 paints its panel at block 96, off screen
  {0xFFF64800, 0x01FE},                  -- drawing origin-> 0x01FE8000
}
local function apply(t)
  for _, s in ipairs(t) do vram:write_u16(((s[1] - 0xFFC00000) >> 4) * 2, s[2]) end
end

local FROM = tonumber(os.getenv("FROM") or "5100")
local GAP  = tonumber(os.getenv("GAP")  or "120")
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n = 0
_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n == FROM       then apply(VIEWPORT); print("[288] viewport widened") end
  if n == FROM + GAP then apply(PINS);     print("[288] buffer pinned")    end
  if n > FROM + GAP and n % 150 == 0 then mach.video:snapshot() end
end)
