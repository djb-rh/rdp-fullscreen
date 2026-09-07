-- Trace GSP writes into the 2bpp pixel window to find the render target & extent.
-- pixel window: bitaddr 0x02000000 + 2*pixelindex ; 512 px per display row => 1024 bits/row
local mach = manager.machine
local gsp  = mach.devices[":mainpcb:gsp"]
local sp   = gsp.spaces["program"]
_G.hd = {}
local key = mach.ioport.ports[":mainpcb:a80000"].fields["Key"]
local n = 0
local rows = {}      -- row -> count, for the current window
local blocks = {}    -- 4-row block -> count
local lo, hi = nil, nil

_G.hd.tap = sp:install_write_tap(0x02000000, 0x020fffff, "px", function (offset, data, mask)
  local px = (offset - 0x02000000) // 2      -- linear pixel index
  local row = px // 512
  rows[row] = (rows[row] or 0) + 1
  local b = row // 4
  blocks[b] = (blocks[b] or 0) + 1
  if lo == nil or px < lo then lo = px end
  if hi == nil or px > hi then hi = px end
end)

local function runs(t)
  local ks = {}
  for k in pairs(t) do ks[#ks+1] = k end
  table.sort(ks)
  local out, s, p = {}, nil, nil
  for _, x in ipairs(ks) do
    if s == nil then s = x
    elseif x ~= p + 1 then out[#out+1] = (s==p) and tostring(s) or (s.."-"..p); s = x end
    p = x
  end
  if s then out[#out+1] = (s==p) and tostring(s) or (s.."-"..p) end
  return table.concat(out, ",")
end

_G.hd.fn = emu.add_machine_frame_notifier(function ()
  n = n + 1
  if n > 30 and n < 700 then key:set_value(1)
  elseif n % 90 == 30 then key:set_value(1)
  elseif n % 90 == 50 then key:clear_value() end
  if n % 200 == 0 then
    print(string.format("frame %5d  pixels %s..%s  rows[%s]  blocks[%s]",
      n, tostring(lo), tostring(hi), runs(rows), runs(blocks)))
    rows, blocks, lo, hi = {}, {}, nil, nil
  end
end)
