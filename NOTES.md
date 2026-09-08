# RDP side pod - filling all 288 display rows with render

Working notes. Goal: make the pod's 3D view cover the whole 512x288 screen
instead of only the top 192 rows.

## Tools built here

- `dasm` - standalone disassembler for **68010** (byte addresses, big-endian)
  and **TMS34010** (bit addresses, little-endian), built from MAME's own
  disassembler cores so output matches the MAME debugger.
  Build: see `build_dasm.sh`. Usage:
      ./dasm 68k maincpu.bin 0 0x4dfd0 0x140
      ./dasm gsp vram.bin 0xffc00000 0xffc00000 0x400
- `build_images.py` - builds `maincpu.bin` (1MB 68010 program, from 088-2001..2016)
  and `user1.bin` (384KB object ROM, from 088-1017..1022) as linear images.
- Lua probes: `trace_draw.lua`, `flip3.lua`, `mapscan.lua`, `live3.lua`.

MAME's `-debugger none -debugscript` does **not** run debugger commands
headlessly - that route is a dead end, hence the standalone `dasm`.

## How the pod's video actually works

**The TMS34010 GSP never executes a single instruction.** Verified: PC, SP and
every A/B register read 0 the whole run, and the reset vector at 0xFFFFFFE0 is
0. It is a display controller and a pixel expander, nothing more.

**All rasterization is 68010 code.** The 68010 draws through the GSP host port
(0xC00000 = HSTDATA/HSTADR/HSTCTL) into the 2bpp window at GSP address
0x02000000. That window is the Atari pixel expander: each 16-bit write covers
8 pixels, the data bits act as a mask, and the colour comes from a latch the
68010 writes at GSP address 0xF4000000 (`gsp_control_lo`). It is a span filler,
not a general blitter - you cannot copy arbitrary pixel data through it.

### Address arithmetic

    gsp_vram is 512KB = 256 "blocks" of 1024 x 16-bit words (2048 bytes).
    One block holds 4 display rows of 512 pixels (1 byte per pixel).

    linear VRAM view : GSP bit address 0xFFC00000 + block*0x4000
    pixel window     : GSP bit address 0x02000000 + 2*pixel  (2 bits per pixel)
                       => 1024 bits per display row, block B at 0x02000000 + B*0x1000

### Video timing (table at ROM 0x4DFD0, 8 entries of {u32 reg addr, u16 value},
### written by the loop at 0x4E006)

    VTOTAL 0x133=307  VSBLNK 0x131=305  VEBLNK 0x011=17  VESYNC 4
    HTOTAL 0x142=322  HSBLNK 0x13A=314  HEBLNK 0x03A=58  HESYNC 0x14=20

    visible = 305-17 = 288 rows, (314-58)*2 = 512 pixels.

### Framebuffer layout (measured, driving view)

| blocks  | what                                              |
|---------|---------------------------------------------------|
| 0-47    | 3D buffer A, 192 rows                             |
| 48-95   | 3D buffer B, 192 rows                             |
| 96-119  | door card, always display rows 192-287             |
| 120-123 | 68010 working data (changes between idle/driving)  |
| 124-206 | static artwork / tables (identical idle vs driving)|
| 207-255 | 68010 scratch + display lists (0xFFF9xxxx-0xFFFExxxx) |

The 68010 only has 32KB of its own RAM (0xFF8000-0xFFFFFF), so it uses the top
of VRAM as work memory. That is what all the 0xFFFAxxxx host-port writes are.

### It is a hardware split screen

Verified by stamping markers into the first display row of blocks 0, 48 and 96
after each rendered frame and snapshotting consecutive frames:

- display row 0 alternates between block 0's marker and block 48's marker
  => the top 192 rows are double buffered and the display base flips each frame
- display row 192 shows block 96's marker on **every** frame
  => the bottom 96 rows always come from blocks 96-119, whichever buffer is front

So the screen is: 192 rows of double-buffered 3D + 96 rows of fixed panel.

Per-frame render extent, measured with a write tap on the pixel window while
driving (each ~20,300 writes):

    f1501 rows 0..191      f1505 rows 0..191      f1509 rows 0..191
    f1503 rows 192..383    f1507 rows 192..383    f1511 rows 192..383

(pixel-window rows 0-383 = blocks 0-95; "row 919" entries are the 68010 scratch
area at block 229, not framebuffer.)

## What filling 288 rows requires

Two 288-row buffers need 72 blocks each = 144 blocks, and they must each be
contiguous because the display scans linearly. Freeing the door card gives one
contiguous run of blocks 0-119 (120 blocks). Everything from 120 up is working
data, artwork and 68010 scratch. So:

- **two** 288-row buffers do NOT fit without relocating ~24 blocks of artwork
  out of 120-143 and finding every reference to it;
- **one** 288-row buffer fits exactly in blocks 48-119 (the currently displayed
  region) with no relocation at all.

### Planned first milestone: single 288-row buffer

Three changes, all in 68010 ROM:
1. renderer vertical extent 192 -> 288
2. render target pinned to the displayed buffer (drop the page flip)
3. drop the mid-frame split so all 288 rows come from one base

Costs tearing, since it gives up double buffering. Proves the projection and
clipping extend cleanly before taking on the harder memory relocation.

## CORRECTION: the GSP does run code

The earlier claim in this file that "the GSP never executes an instruction" was
WRONG. `gsp.state["PC"]` reads 0 because MAME does not sync CPU state outside
the debugger. A read tap on the GSP program space settles it: ~122,000 fetches
in two frames, concentrated in VRAM block 216. **The GSP runs the renderer.**
Its program is unpacked at boot into VRAM blocks ~214-232 (GSP bit addresses
0xFFF58000-0xFFFA0000) by the decompressor at 68010 ROM 0x2F110, which is why no
straight copy of it appears anywhere in the ROMs.

Disassemble it with the tool here:

    ./dasm gsp vram_drive.bin 0xffc00000 0xfff58000 0x4C000 > gsp.asm

The 68010 still does plenty of drawing through the host port - text, the HUD and
the door card - but the 3D scene is GSP code.

## How the 3D viewport is defined

The GSP draws with OFFSET (B4) as the drawing origin, DPTCH (B3) = 0x400 bits
per row, and WSTART/WEND (B5/B6) as the clip window; CONTROL bits 6-7 are set to
11 (`MOVI C0h,@C00000B0h`) to enable window clipping.

Two buffers, each addressed through an origin shifted 96 rows from its base:

| buffer | base       | drawing origin | viewport Y 96..287 lands on |
|--------|------------|----------------|-----------------------------|
| A      | 0x02000000 | 0x01FE8000     | pixel rows 0..191   (blocks 0-47)  |
| B      | 0x02030000 | 0x02018000     | pixel rows 192..383 (blocks 48-95) |

So **the viewport is Y 96..287 in drawing space** - 192 rows - and the origin
shift is what puts the horizon 96 rows down.

Swap routine at **FFF64750**: compares B4 against the two origins and loads the
other one. Display start: the GSP writes `@FFF8C230h` to DPYSTRT (0xC0000090)
and DPYADR (0xC00001E0), unrolled 4x at FFF5B490-FFF5B6C0. The value is chosen
at **FFF5AD40** (buffer A: B4=0x02000000, DPYSTRT=0xFCFC) and **FFF5AE80**
(buffer B: B4=0x02030000, DPYSTRT=0xFFFC).

The door card is drawn by the **68010**, straight into linear VRAM at
0xFFD80000 (block 96), from a table at ROM 0x047440 with a 0x2A-byte stride;
the destination 0xFFD80000 appears 7 times in the ROM. The GSP also has a panel
drawing context at FFF7C520 (OFFSET 0x02060000, clip Y 0..96) but neutering that
alone does not remove the card - the 68010 repaints it.

## Result so far: the viewport does extend to 288 rows

`full288b.lua` applies five changes at runtime and the render fills the screen:

1. **Viewport bottom edge Y 0x11F (287) -> 0x17F (383)**, 7 sites, found by
   pattern: word 0x011F after 0x01FF or a `MOVI ,An` opcode -> 0x017F, and word
   0xFEE0 after a `CMPI ,An` opcode -> 0xFE80 (TMS34010 CMPI stores the ones
   complement, ~0x011F = 0xFEE0, ~0x017F = 0xFE80).
2. **FFF64840: 0x01FE -> 0x0201** - the swap now returns the same origin, so
   drawing is pinned to buffer B (0x02018000), whose 288 rows are pixel rows
   192..479 = blocks 48..119 = exactly the visible area.
3. **FFF5AD60: 0x0200 -> 0x0203** - buffer base pinned to match.
4. **FFF5AD80: 0xFCFC -> 0xFFFC** - display start pinned to that buffer.
5. **ROM: every 0xFFD80000 -> 0xFFC00000** (7 sites) - the door card is painted
   into block 0 instead, which the pinned buffer no longer uses.

Measured effect: per-frame render extent goes from `0..191` / `192..383` to
`192..479` every frame. Screenshots: `viewport192.png` before, `viewport288.png`
after.

## SOLVED: the viewport bound, and a 288-row render

The 3D viewport is GSP state, and its bottom edge is the constant **0x11F (287)**
in the GSP's drawing space. Extending it to **0x17F (383)** makes the renderer
cover 288 rows. Seven sites carry it, found by pattern in the unpacked GSP code:

| GSP address | was | becomes | form |
|---|---|---|---|
| FFF61380 | 011F | 017F | `MOVI 11F01FFh,B6` high word |
| FFF622C0 | FEE0 | FE80 | `CMPI 11Fh,A1` (ones complement) |
| FFF622F0 | 011F | 017F | `MOVI 11Fh,A1` |
| FFF62420 | FEE0 | FE80 | `CMPI 11Fh,A3` |
| FFF62450 | 011F | 017F | `MOVI 11Fh,A3` |
| FFF639A0 | FEE0 | FE80 | `CMPI 11Fh,A6` (range assertion) |
| FFF64AB0 | 011F | 017F | `MOVI 11F01FFh,B6` high word |

Pattern for finding them: a word 0x011F preceded by 0x01FF or a `MOVI ,An`
opcode (0x09C0-0x09CB), or a word 0xFEE0 preceded by a `CMPI ,An` opcode
(0x0B40-0x0B4B). TMS34010 `CMPI` stores the ones complement, so ~0x011F = 0xFEE0
and ~0x017F = 0xFE80.

**Patching WEND alone does nothing** - that was the first false trail. WEND is a
safety clip; the seven sites above are what the pipeline actually bounds itself
with.

### Buffer arrangement

With 288-row buffers, buffer A (blocks 0-71) and buffer B (blocks 48-119)
overlap, so the top third flickers between one buffer's sky and the other's
road. Pinning everything to buffer A removes the overlap:

| GSP address | was | becomes | meaning |
|---|---|---|---|
| FFF5AEA0 | 0203 | 0200 | buffer base always 0x02000000 (block 0) |
| FFF5AD80 | FCFC | FFFC | display start (the swap's other arm) |
| FFF64800 | 0201 | 01FE | drawing origin always 0x01FE8000 = base - 96 rows |

That gives a single 288-row buffer in blocks 0-71, and the door card - which the
**68010** paints into linear VRAM at 0xFFD80000 (block 96) - is simply off
screen. No door-card patch is needed.

`single288.lua` does exactly this. Applied once while the pod is driving, it
produces a full 512x288 render: road and shoulder stripes right to the bottom
edge, no seam, no door card. See `stock_192.png` vs `full_288.png` /
`full_288b.png`.

### Supporting facts established along the way

- Display start law is **empirical, not the obvious reading of MAME's TMS34010
  model**: DPYSTRT 0xFCFC and 0xFFFC select the two buffers, and deriving a
  general block<->DPYSTRT formula from the emulator source gave the wrong answer
  twice. Measure it, do not derive it.
- The renderer's polygon fill is `FILL XY` at **FFF5F0E0**; it draws into the
  extended band once the viewport is widened (~20,000 writes a frame), so the
  geometry really is there.
- The GSP's PC **is** readable inside a memory tap (`gsp.state["CURPC"]`), even
  though it reads 0 from a frame notifier. That is how FFF5F0E0 was identified.
- Useful 68010 landmarks: IRQ vector table at ROM 0x20000 (VBR is set to 0x20000
  at 0x4DC80); IRQ3 = GSP interrupt, handler 0x4DE48, fires per frame; IRQ5
  handler 0x4DDF8 bumps a tick counter at 0xFF8014 (~3.3 ticks per frame, and it
  resets when the pod does). Free ROM: 0x05043E-0x060000 (64KB of zeros) in the
  same EPROM pair (088-2005/2006) as the IRQ3 handler. Untouched 68010 RAM: an
  11KB run of always-zero longwords from 0xFFABE4.

## Corrections to earlier entries in this file

- **Display start law** (measured with per-block markers, not derived):
  `block = (0xFFFC - DPYSTRT) / 16`, so **DPYSTRT 0xFFFC = block 0** and
  **0xFCFC = block 48**. An earlier note here said the opposite; that error sent
  the buffer-relocation work down a blind alley. The swap sets DPYSTRT to
  display the buffer *just finished*, which is why the two values look swapped
  relative to the base being loaded.
- **The renderer draws into the back buffer** at FFF5B040-FFF5B180: it saves B4
  to @FFF8E380h, switches OFFSET to the other buffer, calls FFF612C0, restores.
  Point that at an unused block and the scene disappears - it is the scene
  render, not an overlay.

## Why the door card cannot simply be moved

The panel is painted by the **68010**, into the bottom third of *whichever
buffer is current*, coordinated by a handshake: the GSP writes the buffer base
to @FFF8E300h (FFF5ADD0/FFF5AE00 for buffer A, FFF5AF10/FFF5AF40 for B) and
spins until the 68010 clears it. So the panel always lands 48 blocks after the
base - exactly the bottom 96 rows of a 288-row buffer.

**The panel and a full-height 3D view want the same memory by design.** It has
to be suppressed, not relocated. Nulling the handshake value (writing 0 instead
of the base) does stop the panel, but also kills the render: the 68010 does more
than panel painting in that exchange.

## The GSP frame loop

    FFF5A840  wait for the frame counter @FFF8E330 to reach @FFF94B00
              CALLA FFF7C330 / FFF7C370      set up drawing context
              CALLA FFF612C0                 draw the frame into B4
              ...
    FFF5ACB0  swap:
                if B4 == 0x02000000 -> FFF5AE80  B4 := 0x02030000
                                                 DPYSTRT := 0xFFFC  (block 0)
                                                 handshake := 0x02030000
                if B4 == 0x02030000 -> FFF5AD40  B4 := 0x02000000
                                                 DPYSTRT := 0xFCFC  (block 48)
                                                 handshake := 0x02000000
                then spin on @FFF8E300h until the 68010 clears it
    FFF5B1B0  JR FFF5A840

Each arm sets DPYSTRT to display the buffer *just drawn*, and hands the 68010 a
base so it can paint the panel into that buffer's bottom third.

## The complete 288-row site list (11 sites)

Both arms have to agree, or one frame after any mode change the display jumps to
block 48 *and* the 68010 is told to paint its panel into the visible buffer.
That was the cause of the "it works then reverts" behaviour.

    viewport, 192 -> 288 rows
      FFF61380  011F -> 017F      MOVI 11F01FFh,B6 high word
      FFF622C0  FEE0 -> FE80      CMPI 11Fh,A1
      FFF622F0  011F -> 017F      MOVI 11Fh,A1
      FFF62420  FEE0 -> FE80      CMPI 11Fh,A3
      FFF62450  011F -> 017F      MOVI 11Fh,A3
      FFF639A0  FEE0 -> FE80      CMPI 11Fh,A6   (range assertion)
      FFF64AB0  011F -> 017F      MOVI 11F01FFh,B6 high word

    single buffer in blocks 0-71, both swap arms in agreement
      FFF5AEA0  0203 -> 0200      B-arm base       -> 0x02000000
      FFF5AD80  FCFC -> FFFC      A-arm DPYSTRT    -> block 0
      FFF5ADF0  0200 -> 0203      A-arm handshake  -> report buffer B, so the
                                  68010 paints its panel at block 96, off screen
      FFF64800  0201 -> 01FE      drawing origin   -> 0x01FE8000 (base - 96 rows)

Applied in two stages (viewport first, pins ~120 frames later) while the pod is
driving, this holds: 17 of 17 sampled frames across a full replay showed real
rendered content below row 192, with no door card. `single288.lua` does it;
`full_288c.png` is the result.

## CORRECTION: no correct full-height render has been demonstrated

Earlier entries in this file, and the screenshots `full_288.png`,
`full_288b.png` and `full_288c.png`, were presented as a working 288-row view.
They are not. Measuring them against a stock frame:

    stock_192_b.png   horizon at display row 97   (mid-view, correct)
    full_288.png      horizon at display row 44
    full_288b.png     horizon at display row 44
    full_288c.png     horizon at display row 44

The horizon jumps up by about 53 rows in every "working" shot. Widening the
viewport downward should leave the horizon where it is and reveal more near
ground beneath it. Instead the whole view is displaced upward, and the bottom
row of all three is a flat colour (003CA2), not scenery. What those images show
is a **shifted, wrong picture**, not a taller one.

That also explains the "sometimes works" impression: the crude metrics used to
score runs (colour counts and write volume in the bottom band) cannot tell a
displaced view with a flat skirt from a genuinely extended one, and they scored
the former as success repeatedly.

## What is actually established

- **Architecture** (all verified directly, and still good): the GSP runs the
  renderer from a program unpacked into VRAM blocks ~214-232; the frame loop at
  FFF5A840 draws then swaps at FFF5ACB0; each swap arm sets a buffer base, a
  DPYSTRT and a handshake word at @FFF8E300h; the door card is painted by the
  **68010** into the bottom third of whichever buffer that handshake names.
- **The seven viewport constants and the four pins** exist and do change what
  the renderer does - the write extent goes from rows 0..191 / 192..383 to
  0..287 / 192..479. That part is real and measured.
- **But changing them does not produce a correct wider view.** The projection is
  not being extended, only displaced.

## What is not established

That the pod can be made to render a correct 512x288 view at all by this route.
The viewport constants bound where pixels may land; they do not appear to be
what defines the projection's vertical extent. That question is open again.

## The harness (now genuinely sound, after a bug fix)

`rdp_link_player_device` in `src/mame/atari/harddriv.cpp`, slot option
`linkplay`, replays a recorded link with its recorded per-byte timing in
**emulated** time:

    RDP_LINK_BIN=capture/link.bin RDP_LINK_TIMES=capture/link.bin.times \
    mame racedrivpans -mainpcb:rs232 linkplay

It had a pacing bug on the first cut worth remembering: `tra_complete()` called
`feed_next()`, which transmitted unconditionally, so each finished byte
immediately pulled the next one and the whole capture went out back to back at
the line rate - exactly the bitbanger behaviour it was meant to avoid. The
symptom was the pod reading the DUART furiously for ~1000 frames and then going
quiet. `feed_next()` now checks the byte's due time before transmitting.

With that fixed the pod behaves like a real one: DUART reads settle to a
realistic rate, framebuffer rendering is sustained (~3M pixel writes per 300
frames, rows 0..383), and the driving view comes up around frame 2250.

Both earlier harnesses were invalid: a host pty is wall-clock paced and not
reproducible; a plain bitbanger is reproducible but ~13x too fast.

## Verdict on the 11-site patch: it does not work

Measured on the good harness, applying the sites continuously from the start of
the driving view:

| applied | pixel-window rows written |
|---|---|
| nothing | 0..383  (two 192-row buffers) |
| 7 viewport sites | 0..479 |
| all 11 | 0..287  (one 288-row buffer) |

So the sites do exactly what the disassembly says, reproducibly. **But the
screen does not change.** With all 11 applied the display still shows the stock
layout: 192 rows of view with the door card below it (the card's own palette
entries are still at display rows 200 and 240). The render extent moves; the
picture does not.

That is consistent with the correction above - the viewport constants bound
where pixels may land, they are not what places the view on the screen or what
sets the projection's vertical extent.

`fill288.py` therefore patches ROMs to no useful effect. Do not burn it.

## Next

The open question is unchanged and now properly framed: what sets the vertical
extent of the projected geometry, and what places the view within the 288
display rows. Both are upstream of the clip window. Work it on `linkplay`, where
the driving view is live from about frame 2250 and results repeat exactly.

## Lap timer and gate awards (found by disassembly, 2026-09-03)

The route-node "value" is **not** a time award. At 0x02FC2E it is loaded and
stored to 0x9016C0, and at 0x02FF7A that word is `asl.l #6` (x64) and added to
the base pointer at 0x900D5A. So the value is an **index into the track's
64-byte-per-record geometry array**. That is why value/seconds was never a
constant - I was reading the wrong field entirely.

The clock is the 32-bit word at **0x9016DA**:

  0x02FE52  move.l #$249F0, $9016DA    ; starts at 150000
  0x029C62  subq.l #1, $9016DA         ; ticks down
  0x02F164  add.l  D0, $9016DA         ; award A - by gate marker
  0x02F62A  add.l  D0, $9016DA         ; award B - from a RAM table

**250 clock units = 1 second.** A checkpoint on track 0 awards 320 x 25 = 8000,
and that was observed on real play as +32 s. So the 150000 start = 600 s.

Award A (routine 0x3154A):

    award = word[ track_record + 0x40 + (marker & 3) * 8 + kind * 2 ] * 25

`marker` is the top nibble of the node flags, `kind` comes from 0x9016C8 via
0x314C0 (clamped to 4). The table is 4 rows x 4 words = 32 bytes. In stock ROMs
every column of a row is equal, so only `marker & 3` matters:

    track 0 (original)     row0 320 (32 s)  rows1-3 290 (29 s)
    track 1 (autocross)    all   30  (3 s)
    track 2 (super stunt)  row0 310 (31 s)  rows1-3 290, last word 29

Note marker 8 and marker 4 both map to row 0, so both award 32 s on track 0.

Award B (routine 0x31360) uses a **RAM** table at 0x90183C selected by 0x9016C8
(+2 if 1, +4 if 2, else +6), same x25 scaling. Start/finish appears to use this
path: two 29 s awards would give 58 s, but ~44 s was observed.

**Consequence for the east loop:** a longer lap is made completable by editing
the 32-byte table at track_record + 0x40 - not by inventing section values.
Section values must stay correct geometry indices.

## G29 brake sticking on (diagnosed 2026-09-03)

Measured with brake.lua, which logs every joystick axis beside the value the
brake field delivers to the game.

**The live bindings are in `cfg/racedriv.cfg`, not `cfg/default.cfg`.** The game
cfg wins, and it binds the wheel to XAXIS, the **brake to RXAXIS**, the gas to
ZAXIS, and the clutch to nothing.

The brake pedal itself is healthy - it reads +65536 released, -65536 pressed,
and returns cleanly every time:

    f6     every axis 0, pedal untouched   brake = 4095   <- full on
    f600   RXAXIS = +65536  released       brake =    0
    f654   RXAXIS = -65536  pressed        brake = 4095
    f702   RXAXIS = +65536  released       brake =    0

The fault is the first line. MAME reports an axis as 0 until it is first moved,
so the field sits at its defvalue of 0, and `PORT_REVERSE` (harddriv.cpp:864)
turns that into 4095 - full brake. The cabinet brake is a **force sensor**
("12 bit ADC 1 - force brake") and the game latches a zero baseline at startup,
so it calibrates against that phantom full-brake reading and is wrong for the
rest of the session. Hand-calibrating in service mode fixes it only for that
session, because by then the pedal has been moved and real data is flowing.

Fix in rd.lua: start the brake **unreversed** so the untouched default reads as
released, then switch to the correct reversed mapping on the first frame the
axis reports a nonzero value.

Two dead ends ruled out along the way, both by reading the code: setting the
reverse flag in the cfg cannot work (MAME writes it but its loader is `#if 0`,
ioport.cpp ~2526), and `set_user_settings` does round-trip the input sequences,
so setting reverse from Lua does not wipe the binding.

### Polarity update after recalibration (2026-09-03)

The brake was recalibrated in service mode with **4095 as "foot off"**, so the
stored calibration is now the opposite polarity to the factory one:

    4095 = no brake        0 = full brake

The running mapping is therefore **reverse OFF** (released +65536 -> 4095,
pressed -65536 -> 0). The startup hold in rd.lua inverts to match: hold the brake
**reversed** so the untouched default reads 4095 (no brake), then drop to
unreversed on the first frame the axis reports.

Note the reverse flag and the game's calibration have to move together - flipping
either alone gives a stuck-on brake. This is why "reverse ON" was right before
recalibration and "reverse OFF" is right after. `BRAKE_HOLD=0` gives the plain
running mapping with no hold, for redoing a calibration.

## The track segment array (found 2026-09-04)

The route node "value" indexes this array, so it has to be understood before
the east loop can be given route sections.

**Track record +0x04 is a pointer to it** (`0x022448 move.l ($4,A2),$900d5a`,
A2 = track record). Records are 64 bytes (`asl.l #6` at 0x02FF7A).

    track 0  DSK 0x049CA      track 1  DSK 0x0C078      track 2  DSK 0x101C4

**Record 0 is a header**, not a segment: its first three 16.16 words read
(430, 70, 352). 430 is the segment count for track 0, and the speed route's
highest section value is 405, which fits.

Record layout, as far as it is decoded:

    +0x00  s32 x     **stored LOW WORD FIRST** - the same word-swap convention as
    +0x04  s32 z     the +0x004 block (swap routine at 0x28F4C). Plain world units
    +0x08  s32 elev  (1/40 ft), NOT 16.16. Reading them as 16.16 looks plausible -
           you get small tidy numbers - but it silently truncates to +/-32767 and
           wraps. The tell was road links coming out at ~65271 units, i.e. 65536.
           Corrected, the longest link is 19200 = the DOTLINE/UNDERP chord (19201)
           and the track spans 4894 x 5877 ft, with coordinates that match the
           ones layout.py produces.
    +0x0C  3x3 rotation matrix, nine s16 in 1.14 - same convention as the
           placement matrices; row magnitudes come out at 16384

    The third 32-bit field is ELEVATION, not a third horizontal axis - it was
    mislabelled 'z' here for a long time and the loop was built flat because of
    it.  136 of track 0's 430 segments are nonzero, range -4960..+720.  It is a
    property of the PLACEMENT, not the object: DOTLINE sits at -800 under two
    placements and at 0 under five others.

    The matrix carries the grade as well.  With forward = COLUMN 0, pitch theta
    and no bank:

        [ 16384*s*cos0  -16384*c        -16384*s*sin0 ]
        [ 16384*c*cos0   16384*s        -16384*c*sin0 ]
        [ 16384*sin0     0               16384*cos0   ]

    Fitted against stock seg 156 (elev -322, m[6] = -966): predicted column 2
    (737, -626, 16355) against an actual (735, -624, 16367).  m[6] is the sign
    of the grade - +1500 climbing into the underpass hump, 0 at the apex, -1501
    descending.

    An UNDERP carries its road 720 units (18 ft) up: stock placement 59 has
    placement y = 0 and all three of its segments at elevation 720, so the deck
    and both ramps are in the MODEL and only the segments need raising.  Stock
    seg 40 (0) -> 42 (720) -> 41 (0) at 10000-unit spacing is a 7.2% grade.

    Piece names encode their own geometry: D<turn>R<radius in feet> and
    C<turn><radius/10 ft>.  Confirmed by measurement - 7 adjacent same-type
    D30R917 pairs on track 0 have origin spacing 18803..19096, median 18966,
    against an ideal 2R*sin(15 deg) = 18988 for R = 917 ft.  piece_ends.json's
    measured chords were all 1-4% SHORT of ideal (D30R917 18437, below the entire
    observed range).  CORRECTED - the raw model vertex extents settle it without
    any fitting: DOTLINE/UNDERP/OVERP are 19201 along z, DOTLHALF 9601, ROAD1/2
    1601.  For arcs the model WIDTH corroborates the full-arc sagitta, since a
    curve is 1601 of road plus its own bulge: C4572 1601+2192 = 3793 against an
    actual 3777, C3060 2419 vs 2401, C3048 2255 vs 2241.  The old numbers are
    self-consistent with an arc clipped ~1 degree at each end - C4572's chord of
    21115 implies 43.01 deg retained, which predicts a sagitta of 2008 against
    the 2007 that was recorded.  So both fields were shrunk by the same fitting
    error.  piece_ends.json now carries chord = 2R*sin(turn/2) and mid = the full
    sagitta for every piece whose width check passes; C4512 and C4532 fail it
    (they are not 1601-wide road) and are left as measured.

    A piece's elevation profile is in its own model, and mkseg.road_profile()
    reads it: take the vertices on road-coloured faces (38, 40, 58), group by z,
    negate y.  UNDERP comes out as (-9601, 0) (-1601, 721) (1600, 721) (9600, 0)
    - linear ramps at 9.0% and 3200 units of FLAT floor, not a hump or a curve.
    Stock has TWO conventions for a dip and they do not drive the same.  Its
    underpass puts segments ON the corners and stores a 9.2% pitch on segments
    that sit at grade (seg 40 and 41, elev 0, pitch +/-1501); the surface is
    fitted through position AND slope, so a slope that steep at zero elevation
    overshoots above grade on the way out - felt as a jump leaving the dip.  Its
    OVERP dip (segments 292/156/155/154/232, the one immediately before the east
    loop) does the opposite and reads better: the grade-level segments carry
    pitch 0 and the sloped samples sit partway down the ramps.  mkseg samples one
    point in the MIDDLE of each stretch of the profile and none on the corners,
    which reproduces the OVERP shape.

    Pitch is the MODEL's local gradient, not the slope between segment points.
    Stock's underpass segments sit ~400 units beyond the piece where the road is
    still flat, so the chord slope between them is 7.2% while the stored pitch is
    9.2% - the UNDERP model's own ramp is 721/8000 = 9.01%.  OVERP agrees: 5.9%
    stored against a 6.3% model gradient.  DOTLINE's 208-unit lane markings are below the
    RELIEF threshold and correctly read as flat.
    +0x1E  2 bytes padding
    +0x20  s32  high word is a FLAGS bitfield, not a number. 0x0100 is set on
           almost everything (243 of 429 have only that) and reads as "ordinary
           road". Seen: 0x0100, 0xC100 (89), 0x0900 (46), 0x2900 (31), 0x3F00,
           0x3900, 0x8100, 0x4100, 0x0F00, 0x2800.
    +0x24  s32  neighbour segment index, 16.16 (so index = value >> 16), -1 = none
    +0x28  s32  the other neighbour
           These two are the road graph: 747 of 819 links point back at their
           source, and 399 of 429 segments have degree 2. The ~72 one-way links
           are the branches - the figure-8 crossover and the speed/stunt fork.
    +0x2C  s32  secondary reference, -1 in 221 of 429
    +0x30  s32  secondary reference, -1 in 225 of 429
           NOT a symmetric graph (179 mutual, 232 not) and it changes almost
           every segment (222 constant runs over 429). The referenced segment
           sits a median 2564 units away - about one road width - so these look
           like the adjacent/parallel road surface rather than a route link.
           **175 segments have both at -1, and 171 of those are ordinary
           degree-2 road, so new road with nothing beside it sets both to -1.**
    +0x34  s32  terrain left edge, 16.16   (typically +1916, i.e. 48 ft)
    +0x38  s32  terrain right edge         (-1916)
    +0x3C  s16  road left edge   +800  = 20 ft
    +0x3E  s16  road right edge  -800  -> a 40 ft road inside a ~96 ft terrain
           strip. The two pairs are independent: they agree in only 7 of 429.

Segment spacing along the track is not uniform: 222 units minimum, 3896 median
(~30 m), 81883 maximum. Segments sit where the road changes, not on a grid.

**Consequence for the east loop.** `patch_track.py` adds the loop as *placements
only* - visual road models. The drivable surface is this segment array, which is
a separate structure, so the loop currently renders but cannot be driven and
cannot be given route sections that point anywhere real. Adding it needs:

1. ~~fields decoded~~ done, see above. A plain new road segment is: position,
   matrix, flags 0x0100, the two road-graph links, both secondary refs -1, and
   width values cloned from an existing plain segment (segment 14 is a clean
   template).
2. segments generated for the loop - position and matrix already come from
   `layout.py`, so that half is in hand. **Segments do not map 1:1 to pieces**:
   only 11% of segment lengths match a piece chord, and the median segment is
   3543 units (89 ft) against pieces of 126-567 ft. So a piece subdivides into
   several segments and the loop needs roughly 8196 ft / 89 ft = **~92**.
3. room. Track 0 uses 430 of the 474 records that fit before track 1's array,
   so only 44 are spare - not enough for ~92. The array has to be relocated into
   the padding at 0x1C060 exactly as the placement array already is, with the
   track record's +0x04 repointed. Note record 0 is the header and its first
   16.16 word (430) is the segment count, so that has to be updated too.

## Gate awards extended for the longer lap (2026-09-04)

`patch_awards.py` scales track 0's table at record +0x40 by 1.71x.

**The basis is an assumption, not a measurement.** The loop adds 2498 m, which is
solid - it comes from piece geometry. The existing lap length is not: the road
graph at +0x24/+0x28 does not close on its own (a directed walk from the start
section runs 42 segments and dead-ends), because the route sections are what
resolve which way to go at each junction. So the 1.71x rests on the lap being
~3500 m, inferred from the measured 105.3 s at a plausible 75 mph average. Total
road across the whole track is 9607 m, so ~3500 m for the speed lap is credible.

Worth re-deriving once the loop is drivable and a lap can be timed directly.

    marker 4/8 gates   320 -> 547   (32.0 s -> 54.7 s)
    start / finish     290 -> 496   (29.0 s -> 49.6 s)

Credit per lap goes 122 s -> 209 s against a lap that goes 105 s -> ~180 s, so
the 1.16x margin Atari set is preserved rather than the track getting easier.

## East loop segments (2026-09-04)

`mkseg.py` generates them, `patch_segments.py` writes them.

**Matrix convention, fitted not assumed.** Testing every axis/sign combination
against the stock links: the matrix's first COLUMN is the direction of travel and
**+0x24 is the segment ahead** - 93% agreement over 795 directed samples, against
19% for the obvious wrong choice. So for heading h the matrix is

    [ sin h  -cos h   0 ]
    [ cos h   sin h   0 ]  x 16384
    [   0       0     1 ]

Atari's own matrices are up to 0.8% denormalised, so expect element errors of
~130 when comparing; generated ones are exact.

**Packing.** Track 0 needed 94 more records and had 44 spare. The DSK padding is
nearly full once patch_track.py has run (14224 of 16288). But track 1 declares
only 49 records inside a 16716-byte region, so sliding its array to the top of
its own region frees 13.5 KB directly after track 0 - no padding touched.

**Attachment.** Segments 135 (OVERP exit) and 146 (DOTLHALF entry) each carry a
dangling road link in stock, on exactly the side the loop needs, and both sit in
the main 422-segment component. The loop fills those two dead ends.

Generated: 94 segments at 3300-unit steps, indices 430..523. Internal checks all
pass - forward axis matches travel direction 93/93, links mutual 93/93, the walk
from 430 reaches 146 in 94 hops over 2376 m, and the byte-sums hold.

**OPEN: the heading convention does not reconcile.** junctions.json and
layout.py give the OVERP exit as -40.3 deg where segment 135's matrix says its
forward is +40.4; at the other end the junction says -99.5 where segment 146 says
+71.4. Positions agree well (the junction is 46 ft and 103 ft ahead of the two
segments respectively, and "ahead" is confirmed by the dot product), so the two
worlds share a coordinate system but not a heading sign convention - and the
second pair is not a clean mirror of the first, so it is not just a sign flip.
**Do not trust the generated orientations until this is resolved**; the road
would be laid facing the wrong way even though it is in the right place.

### Where this stopped, and why (2026-09-04)

The segments are generated and the geometry inside the loop is good - median
heading change 6.9 deg per segment, only 1 of 95 steps over 30 deg. What is not
settled is how the loop joins the existing road.

**The two ends cannot both align.** Testing both traversal directions against
segments 135 and 146: whichever way round, one end lines up almost perfectly
(dot +0.985) and the other is backwards (-0.221). So filling those two dangling
links is not the right operation - the loop has to be spliced into live road,
which means breaking existing links, not just filling dead ends.

**The deletion does not remove road.** `delete_list.json` holds 17 *placement*
indices; `patch_track.py` removes the visual models and nothing touches the
segment array, so the deleted road is still there in the physics. Located
properly (world.py returns y as elevation and z as the second horizontal - do
not compare against y), the deleted placements are mostly a straight run at
x = 209600 with z stepping 210400, 229600, 248800, 268000, 287200 - i.e. spaced
at the 19201 DOTLINE chord. Only 3 of 17 are anywhere near the 73-segment path a
BFS finds between the two junctions, and that BFS path is itself suspect because
BFS shortcuts through junction links.

**This also puts the award scaling in doubt.** `patch_awards.py` scaled by 1.71x
on the assumption that the loop is pure addition. If it largely replaces that
deleted straight (roughly 1925 m against the loop's 2376 m) the net change is a
few hundred metres, not 2498, and 1.71x is far too generous. Do not treat the
award patch as final until the replaced stretch is identified at segment level.

Next: map the deleted placements to the segments they sit on, which gives both
the splice points and the true net length change.

### The deletion, measured (2026-09-04)

8 of the 17 deleted placements are road; the other 9 are scenery (FLOAT90,
SKIDPAD, BPAVE, RCURV, DIP, LCURV):

    4 x DOTLINE   19201 units each   the straight along x = 209600
    4 x D30R917   19616 units each   the curves leading off it
    ------------- 155269 units = 1183 m removed

So the loop is a **replacement**, not an addition: +2376 m of loop against
-1183 m of deleted road = **net +1193 m**, which is the "~1.3 km longer lap"
this whole thing started from. `patch_awards.py` now scales by 1.34x, not 1.71x.

Segments 135 and 146 both fall inside the deleted road - 135 under the D30R917
at (183775, 222698) and 146 under the one at (148193, 262158). That is why the
loop's junctions land on them, and it means the splice is: delete the segments
belonging to those 8 placements, then join the loop's two ends to whatever the
deleted run was attached to.

### The placement and segment frames are TRANSPOSED (2026-09-04)

This was the thing behind every alignment failure above.

**Placement (x, z) is segment (z, x).** Summed over all 86 road placements, the
nearest-segment distance is 1269652 units read directly and 54372 transposed;
for the 8 deleted road pieces it is 61788 direct against 308 transposed, with
four of them landing at exactly 0. Headings follow: **segment heading = 90 deg
minus world heading.**

That is a reflection, which is exactly why the loop could be made to align at one
junction or the other but never both.

With the frame corrected the junctions identify cleanly, by heading and not just
by proximity:

    OVERP exit    world heading  -40.3  ->  segment 133, heading +130.4 (predicted 130.3)
    DOTLHALF entry world heading -99.5  ->  segment  26, heading -170.5 (predicted -170.5)

**The deleted road covers 27 segments** in four runs:

    [16..25, 281..290]   the main stretch
    [149..152, 352]      the straight along x = 209600
    [132]  [133]         singletons, 133 being the OVERP junction itself

They touch kept road at 232, 135, 148, 26, 131 and 15 - those are the splice
points. Road inside the deleted set measures **1072 m**, so replacing it with the
2376 m loop is **net +1304 m**, and the award scaling is 1.37x.

Still to do: regenerate the loop's segments with positions transposed into the
segment frame, unlink the 27 deleted segments, and splice the loop's ends to the
boundary. The generator and the packing already work; only the coordinates and
the endpoint wiring change.

### East loop: done (2026-09-04)

`build_all.py` applies everything to one ROM in order (the order matters -
patch_track's cell lists end at 0x1F7F0, which is why the route sits at 0x1F800):

    1. placements   delete 17, add the loop's road pieces
    2. segments     splice 94 new segments in place of the 27 deleted ones
    3. awards       gate table scaled 1.37x for the +1304 m lap
    4. route        16 sections, a new one (value 477) inserted after 313

The splice is 232 -> loop -> 26, chosen by alignment and not by proximity: seg
232's forward axis dots +1.000 with the step into the loop and +0.998 with the
loop's initial direction; seg 26 dots +1.000 with the loop's final direction.
Worst heading error anywhere along the 96-segment chain is 1.3 deg, median turn
6.9 deg per segment, and no kept segment still points into deleted road.

Not yet driven. The route section at 477 carries marker 0 deliberately - the loop
needs a section boundary for granularity over 2394 m, but the extra lap time is
already paid for by scaling the four existing gates. A fifth gate would blow the
margin.

### There is no room for the loop's segments (2026-09-04)

The segment array **cannot grow and cannot be moved**, and an earlier version of
`patch_segments.py` corrupted the ROM by assuming otherwise.

The stock array is **431 records (indices 0..430)** - record 430 is itself a
valid segment, so the header count of 430 means 1..430, not 0..429. It ends at
0x0B58A and what follows is **live data, not padding**: 831 non-zero bytes before
track 1's array at 0x0C078. Appending at index 430 destroyed a segment plus that
data, which is why the game reported "Off Road" on the start line.

Relocation is not available either. The only all-zero run of any size in the
whole DSK ROM is **0x1C044..0x20000, 16316 bytes**, and patch_track.py already
uses 14224 of it for the placement array and cell lists. The array needs 33600.

So loop segments can only come from slots freed by deleting original road, and
the current deletion frees **27**. The loop needs ~94 at stock granularity.
`patch_segments.py` now refuses to write rather than corrupting the ROM.


## What the placement record's tail fields actually do

Established by tapping the 68010 while the game renders (probe_placements.lua):

  +0x22 bit 12 (0x1000) is DRAW ENABLE.  The gather routine at 0x021E02 walks a
  cell list, copies each 50-byte record into a buffer, and the only field it
  interprets is this one:

      021E42  cmp.l D1, D0      ; D1 = 0x6E = 110 (GRDARROW)
      021E46  tst.w (A4)        ; A4 = 0x901116
      021E56  bclr  #$4, ...    ; clear bit 4 of the HIGH byte of +0x22

  That is how the ground arrows are hidden.  Every stock record has the bit set;
  leaving it clear on the east loop placed the road, routed through it and gave
  it collision, but drew nothing.

  +0x20 is NEVER read by the 68010 - not by the gather, not from the buffer it
  fills at 0x809946.  It is nonzero on exactly the large or background objects
  (FLOAT*, HILL*, UNDERP, XOVER, and the one D30R917 that carries the road over
  an underpass), which looks like a depth bias, but forcing -400 onto the loop's
  carried road changed nothing on screen.  The buffer is DS III shared RAM, so
  the DSP side may read it; proving that needs a tap on the DSP, not the 68010.
  Until then, leave it at whatever stock uses for the same object.


## Segment +0x2C / +0x30 are lane links, not crossing links

Derived from every stock segment that sets them (209 and 205 of 430):

    +0x2C  the road on my LEFT    189 of 209 on the left side, median lateral 1607
    +0x30  the road on my RIGHT   186 of 205 on the right side, median lateral 1647

One lane width, i.e. these knit terrain between PARALLEL lanes - including across
big elevation differences (the banked oval, segs 182-209 -> 140/141, dElev to
4960).  They are not about grade crossings: the clean upper-road segment at the
stock crossing, 372, refs 59/60 - two upper lanes - and the only cross-level
link there, 60 -> 171, is on a degenerate merge-taper segment (flags 0x2900,
road edges -462/-800).  Every stock single-lane road carries -1/-1, so -1 is
correct for the east loop.

## Why the road either side of the bridge renders as ground - working theory

Not terrain widths, not +0x20, not draw order, not polygon load (our crossing
has FEWER faces than stock's at every radius: 190 vs 243 at 20000).  What is
left is sort POSITION.  If objects paint far-to-near by distance to their
origin:

    stock   XOVER 102   194 from the crossing      ours   XOVER 196       1
            UNDERP 101  194                               UNDERP 195   1314
            D30R917 100 583  <- near-tie, -400 wins       DOTLINE 193  8148  <- loses outright
                                                          C4572 194   12656

Stock's carrying road is CENTRED on the crossing, so it ties with the cutting
and +0x20 = -400 breaks the tie its way.  Ours crosses on a JOINT - the DOTLINE
ends 1444 past the crossing point - so no road piece has its origin there, the
cutting's 6401-wide colour-53 ground (flat at y=0) always paints over the road
for ~166 ft, and the deck restores it only within its own +/-2480.  That matches
"the bridge looks right, the approaches do not", and why -400 alone did nothing.
finalize_loop.py pinned the UNDERP's centre to the crossing but never the return
leg's piece.  Fix = re-fit with BOTH centred on the crossing, then -400.


## The physics lives on the DSP32C (found 2026-09-06)

The 68010 does not decide which segment the car is on.  At 0x0233D8 it reads
the index from +0x58 of the DSP32C's result block, mirrored in DSK RAM at
0x900C70 (so the DSP's current segment is the word at 0x900CC8), and turns it
into a record address:

    0233D8  move.w  ($58,A2), D0       ; A2 = 0x900C70
    0233F0  asl.l   #6, D0
    0233F2  add.l   $900d5a, D0        ; [0x900D5A] = the segment array (ROM, from track +0x04)
    0233F8  move.l  D0, $9016d2        ; current segment record address

0x9016D6 is the last current segment whose flags bits 11-13 were zero (the
junction-type field).  0x900D54 / 0x900D58 are force-segment commands (-1 =
none); 0x900D60 = header +0x04 - 1, the index bias between DSP and route values.

The segment array is uploaded to the DSP at load by 0x023A74 through the PIO
port at 0x85C000 (PCR at 0x85C016 = 0x61, PAR = 0x4000): the 64-byte header
first, then count x 32 words from record 1, where count is the word-swapped
+0x00 of the header - the field patch_segments.py updates, so the loop IS
uploaded.  It lands at DSP 0x614000, byte-swapped, 64 bytes per record.  Stock's
431 records end at 0x61ABC0; ours (548) at 0x61CB00.  In stock that span is
empty at load and untouched at rest for 60 s, and the next live table starts
around 0x61D8C0 - so the longer table clobbers nothing.

Consequences: the driven road height and the on/off-road decision are DSP32C
code (uploaded from the 68010 ROM; MAME's unidasm can disassemble dsp32c), and
so is the 3D transform.  Both open problems - the dip that feels the same under
three different segment layouts, and the road either side of the bridge
rendering as ground - are on that side.  rd.lua LOG=1 writes drive_log.csv:
per frame, car x/y/z, off-road, section value/index, current segment, the
force-segment words, and 26 words of the DSP result block from +0x50.

Ruled out for the bridge, in order: terrain apron width; +0x20 (a tap shows the
68010 never reads it); the missing XOVER deck (fixed the bridge itself only);
draw order / unsorted cell lists; +0x2C/+0x30 lane links; polygon load (we have
fewer faces than stock's crossing); the UNDERP's colour-53 ground faces (A/B
with them degenerated: identical); DSP table overflow.


## What drive_log.csv showed (2026-09-06, one speed lap + one stunt lap)

THE BRIDGE.  On the return leg over the cutting the DSP's current segment does
not advance - it thrashes: 531 -> 532 -> 531 -> 532 -> 533 -> 532 -> 533, a flip
every few frames.  Per-frame lateral offsets explain it exactly: the car sat
240-516 units off centre (normal for keyboard steering) and 532-534 carried the
236-unit verges from the "don't lid the cutting" trim.  The DSP will not settle
on a segment the car is outside laterally, so it fell back to a neighbour, and
back again.  The cutting (verges 1916, car at -127..-189) advances cleanly
448 -> 465; stock's crossing (upper road 372 at +/-1916) advances cleanly
373 -> 372 -> 371 -> 74 -> 370.  Rendering is evidently keyed to the current
segment - the thrash IS the flashing.  Every earlier build thrashed for a
different reason: at 4800 the return leg's bounds overlapped the cutting's; at
"1916" the below-road trim had already narrowed the crossing segments.  No build
before this one matched stock's configuration.  Fix: no verge trimming against
roads at a different level (stock never does it); 530-535 are +/-1916 now.

THE REJOIN GAP the user saw before start/finish: the car was between two lanes
for 136 frames (1000-4000 from every candidate road) - off the pavement, flag 6,
and the DSP thrashing 240 <-> 231 <-> 241 <-> 357 for the same reason.  Stock
geometry, not a defect.  Stock marks its merge segments with the junction-type
bits (flags 11-13) so 0x9016D6 holds a stable segment while 0x9016D2 thrashes;
our crossing segments have junction-type 0.

THE DIP, driven, depth = 139 - car y (positive down), along the pass:

    stock UNDERP 59 (segs 40/42/41, ~10000 apart, pitch +9.2/0/-9.2)
        descent begins at -10030 = seg 40's point, 400 units BEFORE the model's
        corner; ~9.2% down; floor 714-758 for ~3300 units; smooth rise; then
        -9 .. -50 (ABOVE grade) for ~900 units after the exit.  The exit lip the
        user feels is in stock's own underpass.
    ours, dense 800-unit build
        depth stays 0 until about -6500 - the descent starts ~3000 units (75 ft)
        LATE relative to both the model and stock - then drops steeply to catch
        up, overshoots the floor to 823, holds a shelf at ~686 on the exit where
        the model is already at 653 -> 586, then a -105 lip.  "goes a tad far in,
        then drops abruptly" exactly.

    The DSP's segment boundaries in our dense build are compressed toward the
    centre (it reports 446 from -6500 where the record sits at -8801; 469 from
    +8274 where it sits at +9600), and while on 445 (elev 0, pitch +4.5%) the
    surface stayed at 0 - the pitch was not applied to the surface.  How the DSP
    turns the record's position, elevation and pitch into a surface is still not
    understood; what IS established is that stock's three-point layout with the
    outer segments 400 outside the piece produces a profile that follows the
    model closely and feels right, and dense sampling does not.


## The renderer, as far as the logs show it (2026-09-06)

The 3D draw is the ADSP-2101 on the DS III board (0x800000-0x81FFFF from the
68010).  It has NO copy of the segment table - not in the 68010's view of its
memory, not in its own data space - so it draws PLACEMENTS ONLY.  The ground is
a flat fill, and the segment verges are physics, which is why no verge change
ever touched the picture.  It does not receive the current segment either.

The 68010 builds two things for it: the per-cell gather at 0x809946 (50-byte
placement records, sorted by index) and, just before it at 0x809400, a block of
27 x 50-byte records rebuilt continuously for the MOVING objects (cars, drones:
object index from a pointer into the 28-byte object table at 0x435BE, matrix
from +0x10 of the mover, position via 0x2162A).  Not a near-road path.

Per record the ADSP writes back +0x24/+0x28/+0x2C = camera-relative x/y/z
(cx = -dz, cz = dx; cy ~ -140 is the road under the eye), +0x30 = a slot key in
25-word steps (6359, 6409, 6434 ...) and runtime bits in +0x22 (0x0001 near,
0x2000 far).  For a NEAR object cz alternates with cz + catalogue radius - it
sorts near objects by their far extent.

Once the camera is INSIDE a placement's bounding sphere its key goes to 0 and
it leaves the sorted list: the DOTLINE the car is on (177) shows key 0 from
cz ~ 9480 on, and the road still draws - so a separate inside-sphere path draws
it.  On the return leg over the crossing, 193 (the carrying DOTLINE) had key 0
for all 450 frames and was NOT visible.  The difference is overlap: there the
camera is inside 193's sphere (9634), the UNDERP's (10155, origin 1314 from the
crossing) and the XOVER's at once, and 194's (11438) from ~1000 before the
crossing.  Working theory: that path has a small capacity and 193/194 lose to
the UNDERP.  Stock's crossing road is centred on its UNDERP, a 2-sphere overlap
for its whole length, with the deck covering the 3-sphere zone (+/-2792).
A/B in ab_underp_radius.py: UNDERP catalogue radius 10155 -> 3000.

The dip is rebuilt to stock's three-segment layout (443 flat, 444 elev 0 pitch
+1471 at 400 outside the piece, 445 elev 721 pitch 0, 446 elev 0 pitch -1471,
10000 apart), after drive_log.csv showed the dense build starting its descent
3000 units late and overshooting.  Both changes are in the same staged build.


## ADSP-2101 (the renderer): what is dumped and mapped

adsp_program.bin / adsp_program.dasm (unidasm -arch adsp21xx -flipped; 16K
words, PC seen at 0x056D) and adsp_data.bin (16K words) are dumps taken at the
start line via /tmp/adspdump.lua.  Mapping, confirmed by `I0 = $0A00` at pc
0x0017 being the mover block the 68010 writes at 0x809400:

    ADSP DM word = (68010 address - 0x808000) / 2
    mover block   DM $0A00   27 x 25 words, rebuilt continuously by 0x021B88
    gather buffer DM $0CA3   per-cell placement records, 25 words each
                             (terminator/count written at 68010 0x809944 = DM $0CA2)
    DM $2000-$2007           an I/O window - the object ROM is read through it;
                             the catalogue (radius/lod/cull) is NOT in DM, so the
                             radius the renderer applies comes from the object
                             ROM, which is why ab_underp_radius.py reaches it
    DM $0927/$0928           a swapped pointer pair - double-buffered output

The 0x11B6-0x11CF stretch is a data table, not code.  The object loop and the
inside-sphere branch have not been located yet; that is the next job if the
radius A/B shows the sphere-overlap theory is wrong.


## The ADSP renderer, decoded from adsp_program.dasm (2026-09-06)

Main loop (pc 0x0006..0x00CC): 0x07C4 rebuilds a POLYGON POOL of 495 x 6-word
entries in PM at $1242 (CNTR = $01EF); 0x0900 walks the object list and depth-
sorts it; 0x0040.. walks the sorted list far-to-near drawing each object;
0x00CB restarts the frame.

Object list (0x0900): starts at DM($001B) = $0A00 (the 27 mover slots) and
runs straight on into the gather buffer at $0CA3 - one contiguous list of
25-word placement records, terminated by object index 0xFFFF.  Per record:
    catalogue via the ROM window: DM($2001) = (obj*9)>>1, longs from DM($2000)
    +0x22 bit 12 clear -> strip bit 0, skip (DRAW ENABLE, confirmed in code)
    +0x20 sign-extended into DM($0027/28); 0x7FFF is special (flag 0x100)
Per drawable (0x06AD): rel = pos - camera; Manhattan distance vs catalogue cull
-> skip; vs lod -> set bit 13 (LO model); camera-space (cx,cy,cz) via the
camera matrix; VISIBLE iff cz + radius >= 100 and |cx|, |cy| < cz/2 + 1.125r
(bit 0 of +0x22 = visible); record +0x24/+0x28 = cx, cy; +0x2C = SORT KEY =
cz + (+0x20) + radius  <- +0x20 IS a depth bias, and the 68010 never reads it
because the ADSP is the consumer; +0x30 = link to the next record in the
sorted list.  0x0945 inserts into a DESCENDING list (head DM($0992)); the walk
draws far-to-near, so the TAIL is the nearest object, drawn last, and its link
is 0.  A zero link does NOT mean undrawn - the road under the car is always
the tail.

Polygons: each drawn object's polygons are merged into a global depth-sorted
polygon list (0x0855; head PM($123F), next at +3, sentinels $1236/$1242) taken
from the 495-entry pool; DM($0957) is the free head.  The list grows through
the frame (222 at the start line) and is then sent to the GSP.  When the pool
is exhausted the remaining polygons - the NEAREST geometry, i.e. the road the
car is on - are dropped.  This is the working theory for the road either side
of the bridge: everything data-side that was changed left the polygon count in
view untouched, which is why none of it helped.  Static faces do not separate
the cases (220 at our crossing, 219 on piece 1, 424 at stock's crossing), so
the load must be dynamic - drones in view across the cutting, or near-plane
clipping multiplying polygons.  rd.lua LOG=1 now logs `polys` (the list length
at the 68010 frame boundary; take the peak over a stretch), `listlen` (objects)
and `movers`.  ab_hide_underp.py clears the UNDERP's draw bit (-59 faces) as
the direct test.


## THE BRIDGE RENDERING - root cause (2026-09-06)

layout.place built every hand=-1 curve by MIRRORING the right-hand model
(matrix [-ca,0,sa; 0,1,0; sa,0,ca], determinant -1).  A mirror flips the
winding of every face; the ADSP back-face culls; the piece draws nothing.
The loop had exactly two hand=-1 pieces - 15 (C3060, rec 190) immediately
before the bridge and 17 (C4572, rec 194) immediately after - which is "the
road before and after the bridge".  Stock has no negative-determinant
placement among its 193; it ships separate left and right models (LCURV/RCURV)
rather than mirroring.  Fix: a left-hand curve is the right-hand model driven
BACKWARDS - rotate it 180 degrees.  The chord is symmetric so the chain is
unchanged, and the model's arc lands on the correct side.

Thirteen theories were tested before this: terrain widths, +0x20 (which IS a
depth bias - the ADSP consumes it, the 68010 never reads it), the deck, draw
order, lane links, polygon load, the UNDERP's ground faces, DSP table
overflow, current-segment thrash (real, and fixed - but not the picture),
sphere overlap / catalogue radius, LOD, orientation, and the 495-entry polygon
pool (which is FULL at the start line from the drones alone, and harmless).
Every one of them was a way the renderer could drop a visible object; the
truth was that the object's own faces were all back-facing.

What finally found it: static reproduction.  Record 0 of the segment array
holds the START SEGMENT at +0x08 (stock 352); setting it to a loop segment puts
the car there at the start (ab_start.py / ab_variant.py build such a set under
/tmp/abx).  Writing the section value (segment + 69) to 0x900D54 stops the
DSP from calling it off-road and resetting.  With -video soft -nowindow and
mach.video:snapshot() that gives a frame from any spot, no wheel, no driver.
Add -str 120: MAME skips the startup warning screen (the incorrect-ROM /
imperfect-emulation click-through) whenever seconds_to_run is under 300, and
it also hard-stops the run.  Without it the headless run sits on that screen
until somebody presses a key.
From segment 511 (on rec 194): no road; swapping in a DOTLINE at the same
placement: still no road -> not the model, the placement; determinants -> -1.
Snapshots from 511 and 507 on the fixed build show the road.

Also learned on the way, all real: +0x22 bit 12 = draw enable, bit 13 = far
LOD (set by the ADSP); the sort key = cz + (+0x20) + radius; the sorted list is
descending and the nearest object is the tail (link 0); the ADSP subdivides
polygons by depth so a single driven-on road piece is ~450 of the 495 pool;
the engine needs the key HELD once TURN KEY TO START shows; the automatic's
shifter could not be put in Drive from Lua.


## After the mirror fix (2026-09-06, later)

Leaving the bridge renders perfectly; the approach is better but still chops.
The exact polygon counter (rd.lua LOG=1, `polymax`) shows the 495 pool FULL
everywhere - start straight, piece 1, the perfect departure, all at 496 for a
large share of frames - so saturation is the normal state and harmless.  What
separates the approach from the departure is that the UNDERP's ground plane
is AHEAD on the approach and its sort key crosses the carrying road's as the
car closes in, flipping road-vs-cutting draw order frame to frame.  Stock's
answer is the -400 depth bias on its crossing road (rec 100); it is restored on
our carried pieces (patch_track, `carried`).  The earlier -400 test could not
show anything because those pieces were mirrored and invisible.

Warping: roms_warp/ is the normal build with the header start segment set to
232 (just past the OVERP hump, facing the loop entry).  rd.lua WARP=1 forces
0x900D54 = start segment + 69 for the first 3 s of the clock so the DSP tracks
the car instead of counting it off-road and resetting.  The user still does
the track/car selection and the key.

    WARP=1 LOG=1 DRIVE=1 TIME=1 mame racedriv -rompath .../roms_warp -autoboot_script rd.lua

The DSP32C physics program is dumped: dsp32_lo.bin/.dasm (boot stub at 0,
jumps to 0x600000) and dsp32_hi.bin/.dasm (the program, 0x600000+, PC seen at
0x602B4C; unidasm -arch dsp32c, 2 unknowns in 65536 lines).  Its copy of the
segment table is at 0x614000.  The surface-height routine - the dip - is in
there and has not been read yet.

Still open: the dip (bumpy at entry and exit, "at its best" level), the exit
splice / checkpoint attachment (125 ft gap; needs the loop re-fit against the
corrected piece geometry), and the approach chop if the bias does not settle it.


## Approach chop, dip brackets (2026-09-06, evening)

The road the car is ON does not go through the ADSP's polygon pool at all:
hiding the carrying piece from a static view leaves the exact per-frame count
unchanged (507: 471/471, 511: 496/496, piece 1: 435/435).  The inside-sphere
path draws it separately.  So neither pool saturation nor pool share can be
the approach chop; a POOLED coplanar surface painted over the separately-drawn
road can - the UNDERP's colour-53 ground plane at y=0, ahead across the road
on the approach, behind on the departure (which is perfect).  The earlier
"ground faces removed" A/B was confounded by the mirrored, invisible piece
190; roms_warp_ab/ repeats it on today's build.

The -400 depth bias is confirmed in the ROM on 193/194 (patch_track,
`carried`).  The dip's pitched outer segments are now bracketed by FLAT ones
1500 further out (mkseg BRACKET; forced samples no longer dedupe each other),
because the DSP extends a segment's pitch to the next segment and the exit
kept climbing past the visible flat.  Layout now: flat / +9% / floor / -9% /
flat, matching stock's 305 / 40 / 42 / 41 / 292 in structure.


## Where the three open problems stand (2026-09-06, night)

1. THE DIP is the segment thrash again, seen at 60 Hz: curseg flips 446<->447
   for the whole descent (-6017..-2825) and 447<->448 for the whole ascent
   (+1807..+7196); every flip swaps the plane the car rides -> bumps.  Stock's
   underpass, same three-segment structure, walks 40 -> 42 -> 41 cleanly,
   switching ~2100 before each segment.  Verges are not it (car within +/-200
   of centre, verges 1916).  Field-by-field the only differences from stock's
   40/42/41 are lane links (stock multi-lane, ours -1 as on stock's own
   single-lane road), asymmetric verges, and a ~1.043 matrix scale - which the
   survey shows is Atari-tool noise (0.99..1.17 across stock, on flat straights
   too, no relation to anything).  Bracketing the pitched segments with flats
   (BRACKET=1500) changed nothing the user could feel.  The selector itself has
   to be read: dsp32_hi.dasm is compiled C (frame r14, fields as `rNe = rNe +
   $off` then a load).  The table base is loaded at 0x607a48..0x607b8c
   ($614000/$61400c/$614008/$614040).  The cluster at 0x602040..0x602420 is the
   OFF-ROAD detector: lateral vs +$3c/+$3e, with junction-type 5 on the
   ahead/behind record exempting the edge.  The advance/selection code is not
   yet located; look for +$c (matrix) used together with +$0/+$4 (position) and
   +$24/+$28.

2. THE APPROACH BANDS.  The road the car is on bypasses the polygon pool
   (hiding it changes the exact count by 0), so it is emitted directly during
   the object walk; the pool is flushed to the GSP at the END of the frame -
   i.e. every pooled polygon is painted AFTER the road the car is on.  Normally
   harmless (far objects sit above the road on screen); at a grade crossing the
   cutting's BANKS (colour 44, sloping from y=0 down to -721) lie physically
   under the road ahead, project onto it, and paint over it in slivers.  The
   ground-face (colour 53) A/B changed nothing, consistent with the banks, not
   the ground, being what shows.  Leaving the bridge the banks are behind ->
   perfect.  Untested; candidate mitigations: raise the carrying road a few
   units, or shorten the banks' reach across the crossing road.

3. THE CHECKPOINT ATTACH is the 125 ft exit splice gap; the loop has never been
   re-fitted since the piece geometry was corrected.  Offline, deterministic,
   findloop.py has the fitter.  Constraint to add: the carrying piece centred on
   the crossing (stock's configuration) while closing both splices.

## Re-fit of the loop (2026-09-06, later still)

The checkpoint mis-attachment was the exit splice: the fitted loop ended
2279 units (57 ft) and 4.2 deg short of the arrival pose A (rec 114 DOTLHALF
entry).  refit.py re-searched with the crossing constrained to a DOTLINE
centred on both legs; refit_tail.py then held the head through the crossing
piece and enumerated every 2-4 piece tail from the palette.  Result: end miss
402 units (10 ft), 0.8 deg, crossing on piece 3 at 0.54/0.57 of both legs,
clearance intact, every placement matrix det +1.

    C4572+ DOTLINE ROAD3 UNDERP ROAD3 C4572+ C4572+ DOTLINE C3048+ C3060+
    ROAD3 C4572+ C4572+ C4572+ DOTLINE C3048+ D30R917- C3048- ROAD1 D30R917- C3060+

Segment table: 232 -> 431 along 2067 / lateral 45; 525 -> 26 along 7567 /
lateral 0 (mkseg aims the last sample at 26).  Note the segment table stores
x/z SWAPPED relative to the placement records (new seg 431 = (214664,188964),
B = (188964,214664)).  roms_loop and roms_warp (start 232) both rebuilt.

### Closing the last 0.8 degrees (2026-09-06)

Every palette piece turns a multiple of 5 degrees, but A-B = -59.2 degrees,
so no chain of pieces can meet A tangentially: 0.8 degrees is left over
whatever the tail.  Stock has the same problem and simply kinks: the four
D30R917 between the OVERP and the DOTLHALF kink 2.0, 2.3 and 1.2 degrees at
their joints (mid-headings -25.35, -25.34, -53.37, -85.63 from the matrices).
So layout.entry_poses(start, seq, close=A) now spreads the residual over the
joints - 1/N of the heading error per joint, (k+0.5)/N of the position error
per piece - and layout.run / mkseg.centreline take close= (loop_final.json
carries "close": A).  With the refit_tail2.py tail (23 pieces) the raw miss
was 258 units / 0.8 deg; after distribution the end pose is 14 units off A,
joint gaps <= 28 units, kinks 0.035 deg.  Snapshot from segment 525 (3800
units before the join) shows the dashes running straight through.

## Segment ranges: +0x34/+0x38 are NOT verges (2026-09-06)

The dip was never a height-model problem.  Per-frame drive_log.csv through the
dip, with every segment switch tabulated against the car's distance from each
origin, gave the DSP32C's selection rule directly:

  * it ADVANCES to the next record once the car is ~1900 past the current
    origin (that is +0x34, 1916 on ordinary road, less a frame of look-ahead);
  * it RETREATS when it finds itself further behind the current origin than
    +0x38 allows (1916 again), with roughly 350-550 units of slack;
  * it evaluates every 3 frames.

+0x34 is therefore how far AHEAD of its origin a segment owns the road, +0x38
how far BEHIND (negative), along the record's own forward axis.  Stock says so
plainly once you look: its underpass ramp segments carry the RAMP LENGTH -
seg 40 (entry ramp top) is [0, 7980], seg 41 (exit ramp top, sitting 400 past
the piece) is [-7951, -330], the OVERP down-ramp seg 154 is [-7773, 5532] -
and a straight three-lane underpass has no business having a 7980/0 "verge".
Stock's hand-offs land right on the next origin (40 -> 42 lands 2020 behind a
lo of -1589; 154 -> 232 lands 1950 behind a lo of -1931: slack ~0, and it is
fine).  Ordinary 3300 spacing with +/-1916 lands 1384 behind, slack 532.

Our dip records were 10000 apart with +/-1916: advance at 1916, land 8000
behind, retreat, advance... every 3 frames (drive_log frames 2282-2338 and
2393-2474).  That alternation between the floor plane and the ramp plane WAS
the entry bump and the "buried" floor, and the exit kept climbing because the
exit ramp's plane (elev 0 at its origin, pitch up, no clamp at ground level)
governed until 1900 past its origin, 2300 past where the model turns flat -
the car launched to y=370 and landed 6000 units later.

mkseg.breakpoints() now does what stock does: a flat record WINDOW (1916)
before the first corner so it hands off exactly there, then one record per
straight run of the model's profile sitting at the run's start with
hi = the run's length (entry ramp [-1916, 8000], floor [-1916, 3201], exit
ramp [-1916, 8000]) so each hand-off lands on the next origin, then a flat
record on the last corner.  Ordinary samples never fall inside an owned
range, and any gap over MAXGAP between ordinary records gets a midpoint.
verges() is gone: its "trim where roads run alongside" only ever changed
these ranges, and trimming to 236 was the 531<->532<->533 flashing over the
cutting (advance at 236, land 3064 behind).  The two splices: 232 -> 431 lands
116 past the origin, 527 -> 26 lands 3444 behind a lo of -4800.

Also fixed on the way: patch_segments built the segment table WITHOUT the
closure distribution (close=), so the table followed the unclosed chain while
the placements followed the closed one - up to 250 units apart at the end.

## Entry point (2026-09-06)

apply_patch.py is the patcher to hand out:

    python3 apply_patch.py /path/to/racedriv.zip [-o OUTDIR] [--warp]

It checks the two DSK ROMs' SHA1s against stock, regenerates rd_dskrom /
rd_maincpu / rd_objrom.bin from the set (byte-identical to the hand-made ones -
MAME's ROM_LOAD16_BYTE order for maincpu, user1 and user3), runs
patch_track -> patch_segments -> patch_awards -> patch_route, and stages a
complete loose set at OUTDIR/racedriv.  build_all.py is now just the local
wrapper that produces roms_loop/ and roms_warp/ from the zip in ~/Developer.
The patch modules read $RD_ROMS at import, so apply_patch rebinds their ROMDIR
for repeat calls in one process.

## Layout (2026-09-06)

The design and probe scripts moved to experiments/ (with the MAME Lua probes in
experiments/lua/); see experiments/README.md.  The root holds the patcher
(apply_patch.py + the patch_*/mkseg/layout/world modules), the layout JSONs,
rd.lua and the notes.  The directory is a git repo now; .gitignore whitelists
code, JSON and notes only, so no ROM-derived file can be committed by accident.

## Phase 0 (2026-09-06): rdtrack/ library and the parts measurement

**rdtrack/dsk.py** parses the DSK image into dicts and re-encodes every
structure to the bytes it came from (114 structures, 0 mismatches on stock;
85.5% of the ROM accounted for, the rest being small per-track blocks and the
padding).  Two corrections to WORLD.md fell out of the pointer map:

* The track table is **three 164-byte (0xA4) records**, not two of 328:
  0x000 speed/stunt (world A), **0x0A4 autocross**, 0x148 super stunt (world
  B).  Route A's first node at 0x1EC sits inside the supposed 328-byte record
  1, which is what gave it away.  Autocross has its own small world: 52
  placements at 0x0B58A in ONE cell (descriptor 0x0BFE4, grid 0x0BFF2), 49
  segments at 0x0C078 (start 32), one route used twice, names "AUTOCROSS" /
  "For the fastest laps, enter the turns at the red cones,".  That region is
  what the east-loop build overwrote when track 0's array grew (hence
  "autocross record repointed").
* Each record's +0x80 points at a **768-byte block**; the three sit at
  0x1B744 / 0x1BA44 / 0x1BD44 and end exactly at the checksum byte 0x1C044.
  Contents unknown (opaque in the round trip; candidates for R4).
* Descriptor words +6/+8 are 0x70/0x70 for the 4x4 worlds and 0x1C/0x1C for
  the one-cell autocross world: cell strides (4 x 28), so the grid shape is
  data, not fixed at 4x4.

Still opaque, all referenced from the track records: +0x14 -> 0x00560 (shared
by all three), +0x18/+0x1C (0x00566, 0x0069A, 0x00988/0x00A00), +0x90 (0x00B0C
/ 0x00B5C / 0x00BAC), +0x98, +0x9C, +0xA0 - a ~2.7 KB soup between the route
nodes and the placements.  Phase 1's round trip will say which of them care
about geometry.

**rdtrack/parts.py -> parts.json** measures every road piece from the object
ROM: the asphalt is a strip of slabs in colours 40 and 38, and **colour 58 is
the centre-line paint** - its dashes give a direction field, the slab edges
running across it are the cross-sections, their midpoints the centreline.
33 pieces measured (entry/exit pose in model coordinates, width, chord, turn,
length, elevation profile, bank per section, circle fit, name-decoded design).
Findings: the design geometry decodes from the names exactly (C4512 = 45 deg
R 120 ft, chord 3673.8 measured 3672.6); the END CROSS-SECTIONS of some pieces
are skewed up to 1 deg from the design tangent (C3048 -0.97, C4572 -0.76,
D10R1833 +0.38) - the model is the truth for butt joints, the closure solver
absorbs the drift; MR4512/ML4512 are separate right/left models of C4512 with
slightly different vertices; banked pieces (BANK 90 deg, BANKED1 180 deg
hairpin) lift the outer edge so their plan view is not circular; SWEEPER is
the unbanked BANK.  Stunt pieces (RAMP1, HLOOP, LAUNCH, JPART, JLAND, TUBE,
CORKS) are classed but not yet measured meaningfully; CHKPT is the gate arch.

## Phase 1, raw level (2026-09-07): decompile / compile round trip

rdtrack/document.py turns the DSK image into a track document (JSON) and
rdtrack/compile.py turns it back.  Two layouts:

* `--fixed` puts every structure at the offset it came from: the compiled
  image is BYTE-IDENTICAL to stock (0 differing bytes) once two things are
  carried as data - route nodes' `prev` links, which are not the mirror of
  `next` (heads point at themselves, and route A's head points at an orphan
  node at 0x004DE in the front region), and the 50-byte terminator record
  (object 0xFFFF) that follows every placement array.
* fresh: everything above 0x011D0 laid out again from scratch with every
  pointer regenerated (worlds, grids, cell lists, segment tables, +0x80
  blocks move; route nodes / name tables / strings stay in the verbatim front
  region when unchanged).  Re-parses with 0 mismatches and decompiles to the
  same document.  MAME attract mode run headless on stock and on the
  relocated image with identical inputs gives PIXEL-IDENTICAL frames at
  300/900/1500/2100/2700/3300 - the demo drives Super Stunt from relocated
  data - so nothing in the game holds an absolute address to these
  structures other than the track-record pointers we regenerate.

The front region (0x00000-0x011D0) is carried verbatim: track records (whose
owned fields are patched), route nodes, name strings and the still-unknown
small blocks.  rdtrack/build.py stages a loose MAME set from a compiled image.

## Pieces layer, R2, R3 (2026-09-07)

**rdtrack/pieces.py** carries every measured part's entry/exit pose through
its placement and matches ends: world A's 92 road placements knit into one
74-piece speed+stunt graph plus a 6-piece side road and the 4-DOTLINE skidpad
straight.  What stock's joints look like: 79 butt joints with gap median 41
units (1 ft), kink median 0.42 deg, tail to 6.3 deg; 5 collinear OVERLAPS
where a branch's end sits thousands of units into the straight it rejoins
(rec 73 D10R1833 -> 2937 into DOTLINE 69; rec 23/21 overlap 3217; rec 14 ->
3190 into ROAD2 12).  That is how the speed/stunt fork is built - no junction
piece, just overlapping road.  Many joints are exit<->exit: pieces placed
backwards (the left-hand-curve-is-a-rotated-right-hand-model rule).  Road
placement headings sit on no angular grid (~30% land on any of 1/256 turn,
1, 0.5, 0.1 deg): Atari's tool used free rotations.  RCURV/LCURV/DIP/FLOAT*
are curve-warning signs, not road.  Autocross (world at track record 1) is a
closed 18-piece C45R140 loop; Super Stunt's road recognises as a 34-piece
chain plus fragments (the stunt pieces are not measured yet).

**R2 - DSP32C segment table capacity.**  RAM is 0x600000-0x63FFFF; the table
loads at 0x614000 and the program references a fixed buffer at 0x61F600
(dsp32_hi.dasm 0x0fbe4/0x0fcf4), so the table has 0xB600 bytes = 728 records
including the header: **727 segments**.  Super Stunt's 725 sits 2 under it.
Cap the compiler at 720.

**R3 - cell membership.**  Not a clean rule.  Everything stock lists is within
the object's catalogue cull distance of the cell box (0 exceptions over all
three worlds), but the lists are tighter than that by ~25% (521 of 2068 refs
in world A) in a way that no catalogue field, no per-object threshold and no
distance-from-the-road-in-the-cell reproduces (a Super Stunt cell with no
road in it still lists objects).  Most likely a visibility precomputation in
Atari's tool.  Compiler rule: **list an object in every cell whose box is
within the object's cull distance** - a strict superset of stock, safe, at
the cost of ~30 more gather copies per cell per frame.  Tighten later if the
68010 budget ever shows it.

## R4 - drone paths, decoded (2026-09-07)

Found by tapping the mover block and reading registers in the tap callback
(MAME Lua: `cpu.state["PC"].value`, `cpu.state["A1"].value` inside an
install_write_tap callback give the writer's PC and registers - the reported
PC is the address AFTER the writing instruction).

**Movers.**  A linked list headed at RAM 0x900C5E, 70 (0x46) bytes each,
player at 0x900044: +0x00/+0x04/+0x08 position, +0x0C object-table pointer
(0x435BE + 28*obj), +0x10 3x3 matrix, +0x34 flags, +0x3A its 50-byte slot in
the 0x809400 block, +0x3E partner mover, +0x42 next.  In a race world A has 27:
six drones (CAR1, TRUK3, VAN, VET3, POR, CAR2) each with a *STOP partner
(parked model), CAR2A, the two CHECKPOINT GATES (CHKPT movers at (138000,0,
261480) and (182640,0,131520) - the gates are movers, not placements),
LITEGRN/STRTPOST, GRHORIZ (the horizon, rides with the car), PIC/FER unused.
0x10000000 in a position = parked/inactive.

**Replay struct** (RAM ~0x901F58, 0x76 apart, one per drone):
    +0x00 current keyframe pointer (main ROM)      +0x04/+0x08/+0x0C base x/y/z
    +0x10/+0x12/+0x14 this keyframe's dx/dy/dz     +0x16 current 3x3, +0x28 next 3x3
    +0x3A mover   +0x3E descriptor (RAM 0x902486 + 22*i: start, end, current,
    +0x0C start again, +0x10 loop-restart, +0x14 stride 12)   +0x52 path header
Interpolator 0x036282: mover pos = base + delta * ((now - t0) << 14) / 50:
**one keyframe per 50 clock units = 0.2 s** (12 frames).  Loader 0x0360F0:
base += delta; delta = next record; at the end pointer the descriptor's
loop-restart pointer wraps it (0x03AB58), and if the path is exhausted the
deltas aim at the header's start position instead (rejoin).

**Path in main ROM** (the 1012/1011 pair, 0x0A0000-0x0BFFFF, the ROMs that
never changed revision): a 56-byte header then 12-byte keyframes:
    header +0x00 type (1 = drone)   +0x1C total keyframes   +0x1E run-in count
           +0x20/+0x24/+0x28 start position   +0x2C/+0x30/+0x34 parked position
           +0x0C.. a 3x3-ish block (initial orientation)
    keyframe: dx, dy, dz (s16, per 0.2 s), pitch, roll (s16, small), heading
              (u16, 1/65536 turn - checked against atan2(dx, dz), the few
              degrees of difference being the car's slip)
Run-in keyframes (from the parked spot to the racing line) are played once;
the lap section repeats from keyframe `run-in`.  Drone 1 (0x0A0000): 47 run-in
+ 452 lap = 90.4 s, lap closes to (-389, -33, 1), path length 436489 units
(3.33 km), mean 82 mph.  Track 0's six drones: 0x0A0000 (500), 0x0A2598 (567),
0x0A4B30 (523), 0x0A70C8 (566), 0x0A9660 (444, starts mid-track at (160920,
150934) - oncoming), 0x0AE190 (460, oncoming).  0x0B2CC0 and 0x0B9D88 are
1549-keyframe, no-run-in, zero-start recordings referenced from the champion
records: the **PHANTOM PHOTON / HELEN WEALES ghost laps**.  0x0B77F0 (201) is
autocross's drone.  Track record +0x8C -> the track's first path; the
+0x90 block (80 bytes per track at DSK 0x00B0C/0x00B5C/0x00BAC) is the
champion record (name, time 0x5AD2 = 93.0 s, parameters) and the list at
0x00BFC.. carries the path/ghost pointers per track - not fully decoded.

**Budget.**  60 bytes per drone-second; six drones on a 3-minute lap = 65 KB
of the 128 KB region, plus 18.6 KB per ghost lap.  Recording in MAME = log
position, heading, pitch, roll every 12 frames (rd.lua already logs per
frame), difference into keyframes, prepend a run-in from the parked spot.

## Phase 2 milestone (2026-09-08): the oval

designs/oval.json (DOTLINE + 4 x C4572 + DOTLINE + 4 x C4572, closing exactly)
compiled by rdtrack.make replaces world A in an otherwise stock image: 10
placements, 67 segments, 5 route sections.  Driven by the user: laps count,
the start/finish and a checkpoint per lap work, "qualified for championship".
So the checkpoint gate movers place themselves from the route's gate markers
(4/8) - nothing else was provided - and the start light/post from the start
marker.  One bug on the way: segment ahead/behind links are RECORD indices
(record 0 is the header), so sample i links to i+2; with i+1 the first
segment pointed at itself and the DSP never advanced (drive_log curseg stuck
at 1, off-road on the first curve).  The generator now walks the links.
