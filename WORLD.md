# The 3D world - where it is, and what it will take

Status: **reconnaissance done, decoding not started.** This file records what is
established so a later session starts from facts rather than guesses.

## The 2D horizon strips (found, extractable now)

The "mountain pictures" that band the 3D world are ordinary entries in the
bitmap table documented in ARTWORK.md, so `swapart.py` already extracts and
replaces them. They are **sheets of stacked horizontal bands**, not single
images - six bands to a sheet, each band a horizon strip:

| entry | ROM | size | what |
|---|---|---|---|
| 7  | 0x065AAE | 512x246 | green/snow mountain range, 6 bands |
| 8  | 0x06CE3A | 512x234 | desert/canyon range, 6 bands, on a transparent key colour |
| 13 | 0x07D562 | 512x234 | third range |
| 68 | 0x09387E | 512x246 | fourth range |
| 9, 11, 12, 67 | | 512x193 | track overview maps (the aerial circuit diagram between races) |
| 10 | 0x07789C | 512x144 | (52 colours - richer, probably a title or attract image) |

    python3 swapart.py <romdir> extract 7 mountains.png --palette palette.bin

**Position data for these is not yet extracted.** Each band has to be drawn at
some screen row and horizontal offset that follows the car's heading - that is
what makes the horizon scroll. Finding it means locating the code that blits a
band and reading where it gets its row and scroll offset. That is a bounded job
and the obvious next step, because the sheets themselves are already in hand.

## The 3D geometry

Lives in the **ADSP "object ROM"**, MAME region `user1` - a 384K region with
256K populated on Race Drivin' (`136077-2021/2023` at 0x00000 and
`136077-1022/1024` at 0x20000, interleaved big-endian).

The ADSP does not address it randomly. The 68010 sets a base
(`m_adsp_eprom_base`) and the ADSP streams words through `/SIMBUF`, an
auto-incrementing port (`hdadsp_special_r` case 0). So the database is read as
**runs of consecutive words**, and the discontinuities are record boundaries.

### What the reconnaissance shows

Static structure, from `rd_objrom.bin`:

- Byte-stride autocorrelation over the first 8K peaks hard at **18 bytes** (and
  its multiple 36), so the head of the file is a table of 18-byte records.
- Read as `u16` then four `s32` (offset +2 aligns them cleanly), the fields look
  like world coordinates - 0x7080, 0x17700, 0x30000, 0x342B8 - not pointers.
- There is a dense block at roughly **0x1F000-0x30000** where every byte is
  non-zero; the rest is patchier. That block is the best candidate for packed
  geometry.

Runtime, from an attract-mode lap with `RDP_SIMLOG` (a logging hook added to
`hdadsp_special_r` in `harddriv_m.cpp`, gated on that environment variable, which
records each run as `start length`):

- 677,053 runs in one lap, over 22,953 distinct start addresses.
- Reads cover **0x00009-0x1D08E only** - about 119K of the 256K. The rest is
  presumably the other two tracks.
- Run lengths cluster at **1, 2, 5 and 6 words**, with a tail at 21, 33, 39, 66.
  Five and six word runs are the interesting ones - a vertex plus attributes, or
  a short polygon record.

## SETTLED: it is a mesh, not track segments

Definitively. The evidence:

1. **The head table has only 26 records.** Far too few to be a track segment
   list, and exactly the shape of a table of models. Each record is
   `u16, s32, s32, u32, u32`: an id, two size/extent fields that take only a
   handful of distinct values (38400/28800/153600 and 288000/134400/96000), and
   **two pointers**, all landing in 0x30000-0x38E48.
2. **The pointer targets are mesh headers.** Every one begins
   `total, nverts, nfaces` where **total = nverts + nfaces** - checked on all of
   them, it holds every time:

        0x317D8:   5 =  4 +  1
        0x316B8:  13 = 12 +  1
        0x31818: 112 = 96 + 16
        0x30000: 307 = 260 + 47

3. **Explicit vertices follow**, as signed 16-bit XYZ triples. The 4-vertex
   object at 0x317D8 is a flat square in the Y=0 plane:
   (-817,0,816) (816,0,816) (816,0,-817) (-817,0,-817).
4. **Explicit faces follow the vertices**, each with a normal in 1.14 fixed
   point (16384 = 1.0 - the square's normal is literally `0, 16384, 0`),
   attribute words, and a list of **1-based vertex indices terminated by -1**.

Vertices and faces, stored explicitly, with faces referencing vertices by
index. That is a polygon mesh by any definition. Nothing procedural, no
curvature or segment-length parameters.

### The format

    u16 total        = nverts + nfaces
    u16 nverts
    u16 nfaces
    vertices[]       s16 x, y, z
    faces[]          s16 nx, ny, nz    normal, 1.14 fixed point
                     s16 a, b, c       attributes - colour, plane constant, flags
                     s16 pad, pad
                     s16 ...           1-based vertex indices, terminated by -1

`mesh.py` implements this. Decoded object sizes come out sensible - 4/1, 12/1,
96/12, 180/30, 260/40 - and `model_30000.obj` renders as a coherent solid.

**Not yet exact:** the face walker recovers 40 of the 47 faces the header
promises for 0x30000, and object end offsets land a few words short of the next
object, so a word or two of the face record is still mis-read. That is a detail
to finish, not a doubt about the format.

## Decoded, and the format is confirmed

The layout was wrong in one important way on the first pass: **the normals are a
separate array**, not interleaved with the face records.

    u16 total        = nverts + nfaces
    u16 nverts
    u16 nfaces
    vertices[]       three s16, x y z
    normals[]        three s16 per face, 1.14 fixed point (16384 = 1.0)
    ...              per-face data, two-word entries, not decoded yet -
                     probably plane constants
    faces[]          s16 attribute word, then 1-based vertex indices,
                     terminated by 0xFFFF

`mesh.py` finds the index lists by scanning for the 0xFFFF terminators, which is
robust to not knowing the length of the undecoded block. It now recovers
**exactly the declared face count on every model** - 1/1, 16/16, 47/47, 177/177,
tested across the lot. That is the confirmation the format is right.

## Face colours - decoded

After the normals comes **one (pointer, colour) pair per face**:

    u16 pointer      low 16 bits of the ABSOLUTE word address of that face's
                     index list - resolve it against the object's own high bits
    u16 0xF0nn       nn is the colour

The pointer being a truncated absolute address is the part that took a while.
Within one object it looks like a small offset with 0x8000 set - for the car at
0x30000 the first pointer is 0x843D and 0x843D - 0x8000 = 0x43D = 1085, exactly
the first face record's word offset. But for a model higher in the ROM the tag
is 0xB0xx instead, because it is not a tag at all: it is the real word address
with the high bits cut off. Resolve as

    absolute_word = (object_base // 2 & 0xFFFF0000) | pointer

and every pointer lands on a face record. The deltas between consecutive
pointers equal each face record's length in words - 18, 18, 6, 6 for records of
36, 36, 12, 12 bytes - which is what confirmed the reading.

**All 38 models now decode completely**: face count matches the header and every
face carries a colour. The car at 0x30000 uses colour 2 on 35 faces (the body),
32 on 11 (glass and wheels) and 54 on one - exactly the distribution a flat
shaded car should have.

The word before each index list, which looked like an attribute, is not: it is
the face's own id in a **combined index space** where 1..nverts are vertices and
nverts+1.. are faces. That is what the header's `total = nverts + nfaces`
counts.

### Palette caveat

The colour *indices* are certainly right - they separate body, glass and wheels
cleanly. Turning them into RGB needs the palette bank the 3D renderer is using
at draw time, and `rd_palette.bin` was dumped at an arbitrary moment, so the
hues in the preview (olive car, magenta loop) are probably the wrong bank.
`write_mtl(..., bank=n)` takes the bank, so this is a one-line fix once the
right bank is identified - watch `gsp_control_hi` during a race.

## The object table is a level-of-detail table

Each 18-byte record holds **two** pointers, and they are a near/far pair of the
same object:

    [ 0] id 355  near 0x30000 (260 verts, 47 faces)  far 0x342B8 (16 verts, 9 faces)
    [ 1] id 355  near 0x30CD8 (180 verts, 33 faces)  far 0x34420 (14 verts, 9 faces)

The dimensions match within a few units - 228x221x545 against 217x149x549 - so
they are the same object at two detail levels. Where a model is simple enough
the two pointers are identical.

## Identified objects

- **0x30000 - the car**, 260 vertices, 47 faces. Side view shows wheels, bonnet,
  windscreen, roofline and boot; the 3/4 view is unmistakably a saloon.
  `car_hi.obj`, with its far-LOD twin as `car_lo.obj`.
- **0x30CD8 - the second car**, 180 vertices, 33 faces. `car2_hi.obj`.
- **0x35690 - the loop**, 238 vertices, 177 faces. A perfect circle in side
  view, twin rails from the front, with its road surface. `loop.obj`.
- **0x34820** - 336 vertices, 10 faces, concentric rings.
- 34 others, from four-vertex ground quads to signs and scenery.

`objdump.py` lists the table and exports the lot:

    python3 objdump.py rd_objrom.bin list
    python3 objdump.py rd_objrom.bin extractall models/

38 models come out as OBJ, which macOS previews in Quick Look with no install -
select the file in Finder and press space.

## What this means for the round trip

## How the world is assembled

**No master mesh, and the models carry no position.** Every model is in local
coordinates - the car sits on its own origin with y starting at 0, the ground
plane - so nothing in a model says where it belongs in the world.

What does exist is an **object catalogue**: the 18-byte table at offset 0, which
is far longer than first thought - **156 records**, ending at 0x00AF8:

    u16  object id
    u32  near threshold   only a few distinct values (28800, 38400, 153600)
    u32  far threshold    likewise (96000, 134400, 288000)
    u32  near model pointer
    u32  far model pointer

The two thresholds are almost certainly the level-of-detail switch distance and
the cull distance, which is why they take so few values. Between them the 156
records reference **206 distinct models**, scattered right through the ROM - not
just the 38 above 0x30000 that the first pass found.

### The ADSP walks it itself

`m_adsp_eprom_base` is set by the **ADSP**, not the 68010 (`hdadsp_special_w`
case 7, /MP), so the ADSP navigates the database under its own control.

Logging every read during a lap shows the same three-step pattern before every
single model fetch:

    0x00168 x1     object table, record 20, the id word at +0
    0x00172 x2     object table, record 20, the pointers at +10
    0x34200 x21    the model itself

The addresses land exactly on 18-byte boundaries - 0x168 = 20x18, 0x5A0 = 80x18,
0x912 = 129x18 - and the second read is always +0x0A into the record, which is
precisely where the two pointers sit. That is the catalogue being used as a
catalogue, and it confirms the record layout from the other direction.

Interleaved with it are single-word reads in 0x22000-0x25000. Those are not
world data: 0x22000 is a linear ramp (4096, 4095, 4094...) and 0x24000 a slowly
decaying curve (2048, 2048, 2048, 2047...), so they are the trig and reciprocal
tables the transform runs on. They dominate the read counts, which is why they
looked interesting at first and are not.

### What changes as you drive

Slicing a lap's log into twenty parts, two regions stay constant - the maths
tables and the catalogue, read every frame - while the third-placed region
drifts steadily: 0x30000, then 0x20000, 0x08000, 0x18000, 0x0C000, 0x04000.
That is different scenery being drawn in different places. So something keeps a
per-location list of what to draw, and the objects themselves are just entries
in the catalogue.

### SETTLED: the world layout is 68010-side

Tapping the 68010's window onto ADSP data memory (0x808000-0x80BFFF, installed
in `init_adsp`) settles it. Each frame the 68010 writes a **draw list** of
object instances at 0x809400, **50 bytes (25 words) per instance**:

    3x3 orientation matrix   s16 each, 1.14 fixed point (0x4000 = 1.0)
    world position           three s32
    scale                    0x1000 = 0.25, one per axis
    object/flags word        varies per instance

Ten instances in the captured frame, each with its own coordinates and its own
trailing word:

    [0] coords 118990, 24564941, 18890746   flags 10D8
    [1] coords 4734976,        0,    16384   flags 10D8
    [3] coords 6549086,    15749,    16384   flags 10D8
    [5] coords 6488064,    49152,    16384   flags 30D9
    [6] coords 3014656,    16384,    16384   flags 30D8
    [8] coords 2740425,    54476,    16384   flags 10D9

Instance [0] carries the same numbers the 68010 also writes to 0x80BFEC-0x80BFF8
- that block is the viewpoint, so instance [0] is the player's own car sitting at
the camera.

So the answer to "does the loop have location information": **no**. Models are
local-coordinate parts with the origin on the ground plane. Nothing places
itself. Each frame the 68010 decides what is visible, works out a matrix and a
world position for each instance, and hands the ADSP that list; the ADSP
transforms it and pulls the geometry through the catalogue.

**The track and world description therefore live in the 68010's program ROM.**
The object ROM is a parts bin: geometry, the 156-record catalogue, and the trig
and reciprocal tables. That also explains why the third-placed read region
drifted across a lap - different catalogue entries being resolved as the 68010
put different objects on the list, not a world being streamed.

### CORRECTION: the draw list is 134 instances, not 10

The earlier capture caught only 10 because it recorded *writes*, and most of the
list does not change from frame to frame. The 68010 keeps two counts:

    0x90017A = 10    dynamic entities
    0x90017C = 134   total instances

So ten cars and 124 pieces of static world, all in the same 50-byte format.

## The full chain, traced

**1. The draw list** at ADSP 0x809400, 50 bytes per instance, built every frame
by the 68010 routine at **0x021640**.

**2. Dynamic entities** come from a doubly-linked list in DSK RAM. A pool of
**36 nodes of 70 bytes** starting at 0x9002CC is built at 0x022CBC and threaded
onto a free list; the active head is 0x900C5E, with prev at +0x3E and next at
+0x42. The emitter at **0x021AB4** turns each node into an instance:

    node[+0x0C]        pointer to a 28-byte object definition
    node[+0x00..0x0F]  -> instance +0x14
    node[+0x10..]      -> instance +0x02   (the matrix)
    node[+0x32]        -> instance +0x20
    node[+0x34]        flags

The first instance word is `(node[+0x0C] - 0x435BE) / 28` - the object's index in
the definition table.

**3. Static world** comes from **0x021D46**. It walks a list of **16-bit
offsets**, adds each to a base, and copies a **50-byte placement record**
verbatim into the draw list - twelve longs and a word, exactly one instance. The
record's first word is the object index, which it uses to reach the definition
table and may substitute from `definition[+0x12]`.

**4. The object definition table** is at ROM **0x435BE**, 28 bytes per record,
and it mirrors the ADSP catalogue - the same LOD and cull thresholds appear in
both (0x7080 / 0x17700 for record 0, and so on). Each record also points into a
list of short entries around 0x44906.

So the world is: **a flat list of 50-byte placement records**, each naming an
object and carrying its matrix and position, with a per-frame visibility list of
16-bit offsets choosing which to emit. That is a very editable structure.

## Where the placement records live - not yet closed

At run time the records are in **DSK RAM (0x900000-0x90FFFF)**; every draw-list
write sources from there or from ADSP memory, never directly from ROM. So they
are loaded once at track load.

Tracing that load is the remaining step, and the obvious attempt did not settle
it: tapping DSK RAM writes and recording A0 pointed at ROM 0x046000, but that
region disassembles as **68010 code**, so A0 was just holding a code address
rather than the copy source.

The strongest candidate for the track data is a **directory at ROM 0x0E0000**:

    +04  0x000E0036
    +08  0x000E22F8
    +0C  0x000E8C1C     three sections, and Race Drivin' has three tracks
    +18  "Copyright 1990 ATARI GAMES"

Section 0x0E22F8 is full of values like 0xC000 (-1.0 in 1.14 fixed point) mixed
with small coordinates - matrix and position data, which is what a placement
list should look like.

**Next step**: identify the loader by content rather than by register guessing -
watch DSK RAM writes, and for each value written search the ROM for where that
exact byte sequence lives. That gives the source region without assuming which
register holds the pointer. Then confirm whether 0x0E0036 / 0x0E22F8 / 0x0E8C1C
are the three tracks.

### What that means for editing


Two separable jobs, and the first is much easier than the second:

1. **Editing objects** - a car, the loop, a sign - is now a solved round trip in
   principle: decode with `mesh.py`, edit as OBJ, re-encode, write back. Nothing
   outside the object ROM needs to change.
2. **Editing the world layout** - moving the loop, changing the track - means
   finding and editing the 68010's track description, which has not been located
   yet. The draw list is generated, not stored, so the thing to look for is
   whatever the 68010 walks to produce it.

## The static world placement database — FOUND

It lives in the **DSK board ROM**, MAME region `mainpcb:user3`
(`136077-4030.30e` even / `136077-4031.10e` odd, 0x20000 bytes interleaved
big-endian). Build the linear image as `rd_dskrom.bin`.

Mapped at 68010 `0x940000` by `hd68k_dsk_small_rom_r`:
`m_dsk_rom[offset & 0x1ffff]`, i.e. 68k address A -> DSK ROM byte `A - 0x940000`.

### Placement records — 193 x 50 bytes @ 68k 0x9411D0 (ROM byte 0x011D0)

    +0x00 u16  object index (into the object table, below)
    +0x02 9x s16  3x3 rotation matrix, 1.14 fixed point (0x4000 = 1.0)
    +0x14 s32  X
    +0x18 s32  Y      (0 = ground; 1600 = on a hill)
    +0x1C s32  Z
    +0x20      14 bytes of per-instance state
    +0x30 u16  zero

These are copied **verbatim** into the 50-byte draw-list instances, so a record
is literally the instance the renderer consumes.

### Spatial index — two 4x4 grids of cells, 28 bytes per cell header

    +0x00 s32 minX   +0x0C s32 maxX
    +0x04 s32 minY   +0x10 s32 maxY
    +0x08 s32 minZ   +0x14 s32 maxZ
    +0x18 u32 pointer to a u16 list of record offsets, terminated 0xFFFF
                     (offsets are multiples of 50 from the 0x9411D0 base)

    grid A @ 0x037C2 (68k 0x9437C2) - 16 cells, 193 objects
    grid B @ 0x0EFFC (68k 0x94EFFC) - 16 cells, 178 objects

Outer cells use +/-0x7FFFFFFF so the grid tiles the whole plane.

### The consumer — 68010 routine 0x021D46

    A1 = arg0 -> D4 = (A1)          record array base (0x9411D0)
    A0 = arg1 -> D3 = (A0+0x18)     the cell's offset list
    A2 = arg2                       output draw list
    loop: read s16 offset; stop on 0xFFFF
          copy 50 bytes from D4+offset to A2
          remap (A2) via object table +0x12 when it is not 0xFFFF
          A2 += 0x32

For the cell the car starts in (0x94F1A0) this emits **124** instances, which
with the 10 dynamic entities gives the 134 total counted at ADSP 0x90017C.

### Object table @ main CPU ROM 0x435BE, 28 bytes/record, 390 entries

    +0x12 u16  object-index remap (0xFFFF = none)
    +0x14 u32  pointer to a NUL-terminated ASCII **name** in main ROM

Every object is named. The name block runs from 0x44906:
CAR1 CAR2 TESTOBJ ROAD2 GRASS HOUSE ROAD1 ROAD3 STORE STREET HILL1 HILL2 BARN
SQUARE VAN DOTLINE DIP BROWN LBROWN LGREEN DGREEN BPAVE SKIDPAD RAMP1 OVERP
SWEEPER C45R140 EZJUMP TREEBLIT BRIDGE LCURV RCURV SORS TRAIN RRCAR BROCK WEED
TRUK3 UNDERP DOTLHALF HILL3 GRHORIZ C4532 D10R1833 D30R917 FLOWER LITERED
LITEYEL LITEGRN STRTPOST ... COW WWAY SIGNPOST FER ... DINER RESTSTOP PTABLE
PBENCH JAG ... HLOOP ... HILL_A HILL_B1..HILL_D5 ... FINISH CHKPT LAUNCH

### Sample of the decoded world

    # 37 BARN      X=264413 Y=1600 Z=189079
    # 38 COW       X=263662 Y=1600 Z=189092   <- the cow beside the barn
    # 39 SIGNPOST  X=261240 Y=1600 Z=187120
    # 87 TRAIN     X=195271 Y= 480 Z=203179

Editing a placement is a 50-byte write at `0x011D0 + 50*record` in the DSK ROM
image, then de-interleave to the two EPROMs and fix each one's byte-sum.

## Object catalogue and a correction to the mesh header

The catalogue sits at the **head of the object ROM** (`user1`), 18 bytes per
record, indexed by the same object index the placement records carry. Its first
10 bytes are mirrored by the main-CPU object table at 0x435BE, which is how the
two were tied together:

    +0x00 u16  bounding radius
    +0x02 u32  LOD switch distance
    +0x06 u32  cull distance
    +0x0A u32  byte address of the hi-detail model
    +0x0E u32  byte address of the lo-detail model

**Correction to the model header.** The third word is the number of face
**normals**, not the number of faces. A flat road piece such as `D30R917`
declares one normal and carries 34 coplanar polygons; `BARN` declares 17 and
has 53. The face count has to come from the (pointer, 0xF0nn) pair block, and
two things about the old parse were wrong:

* the pointer does **not** always have bit 15 set (`D30R917` uses 0x2625), and
* the pair run has to be bounded by the next model's address, or it walks
  straight into the following object.

Bounded that way, 197 of 206 models decode with a face count exactly equal to
their number of 0xFFFF index-list terminators - two independent counts agreeing.
`mesh.read()` now takes an `end=` argument for this.

## world.py

    python3 world.py list                    the 193 placements, named
    python3 world.py cells                   the two 4x4 grids
    python3 world.py export rd_world.obj     the whole world as OBJ + MTL
    python3 world.py export cell.obj --cell 0x0F1A0
    python3 world.py export near.obj --around 264413,189079 --radius 20000
    python3 world.py export w.obj --palette rd_palette.bin

Exports **193/193 placements, 13442 vertices, 4643 faces**. The top-down plot of
the result is the Race Drivin' circuit: the finish line, the north straight, the
skidpad and its pond, the bridge, the barns and stores, and the train.

Reads only your own ROM dumps; contains no ROM data.

## Scale: the unit is real and recoverable

The world is not in arbitrary units. **1 unit = 1/40 foot = 0.3 inch = 7.62 mm
exactly**, i.e. 40 units per foot. Three independent confirmations:

**The road is a round number.** `ROAD1`, `ROAD2` and `ROAD3` are all 1601 units
across - exactly 40.0 ft of pavement.

**The curve pieces carry their radius in their name.** `D30R917` is a 30-degree
arc of 917 ft radius, `D10R1833` is 10 degrees at 1833 ft. Measuring the chord
across each model's outermost vertices and solving for the radius:

    name       name says   measured   residual
    D30R917       917 ft     937 ft     +20 ft
    D10R1833     1833 ft    1854 ft     +21 ft
    C4532         320 ft     340 ft     +20 ft
    C3048         480 ft     501 ft     +21 ft
    C4572         720 ft     741 ft     +21 ft
    C3060         600 ft     621 ft     +21 ft

The residual is **constant at +20-21 ft**, not proportional - it is exactly half
the 40 ft road width, because the chord is taken across the outside edge rather
than the centreline. A constant residual is what proves the scale; a wrong scale
would give a residual that grew with radius. (The `C` curves name their radius in
tens of feet, the `D` curves in feet.)

**The objects come out life-sized.**

    FER        2.00 x 1.13 x 4.40 m   (Testarossa: 1.976 x 1.130 x 4.485)
    CAR1       1.74 x 1.68 x 4.15 m
    COW        2.39 m long, 1.39 m at the shoulder
    BARN      15.55 m square, 9.30 m tall
    CONEB      0.77 m wide, 0.91 m tall
    TRAIN     30.69 m long, 4.37 m wide
    BARRIER    6.10 m section, 1.52 m tall

### Build volume

    track extent   2.06 km x 1.53 km
    per model      vertices are s16 -> +/-250 m from the object's own origin,
                   so a single object can be at most ~499 m across
    placement      X/Y/Z are s32 -> +/-16364 km; effectively unlimited

So the ceiling on world size is not the coordinate space. It is the 193-record
placement array, the 16 cells per grid, and each object's cull distance.

## Viewing it

`qlmanage`/Quick Look chokes on the 193-object OBJ - it never finished a
thumbnail in two minutes, so Finder's space-bar preview is not a usable route.

`viewer.py` writes a self-contained WebGL page instead:

    python3 viewer.py rd_world_viewer.html

0.5 MB, no libraries, no network, opens by double-clicking. Drag to orbit,
wheel to zoom, shift-drag to pan; Top / 3-4 / Ground presets; a Find list that
flies to each object and cycles through its instances; and a palette-bank
switcher.

**The palette bank is still unresolved.** Of the eight banks in a live dump,
4-7 are entirely black for the colour indices the world uses, bank 2 maps every
one of them to the same brown, and bank 0 hands out pure red, green and cyan -
that reads as a debug palette. Bank 1 is the only naturalistic one and is the
viewer's default, but nothing yet *proves* the 3D renderer draws from it. The
switcher is there so the question stays open and testable.

Face colours in the world span indices 1..63 - six bits - so the high bits come
from somewhere outside the face record, which is probably where the bank
selection lives too.

One display-only fudge: road markings (`DOTLINE`, `DOTLHALF`, `GRDARROW`,
`FINISH` and friends) are authored at exactly the pavement's Y, which the real
hardware resolved by draw order and a depth buffer cannot. `viewer.py` lifts
them 4 units. The exported OBJ is untouched.

## The model format, complete - and an encoder

Every word is now accounted for, verified against the whole catalogue:

    u16  total = nverts + nnormals
    u16  nverts
    u16  nnormals
         vertices   3 x s16 per vertex
         normals    3 x s16 per normal, 1.14 fixed point
    u16  pointer to the pair block
         pairs      two words per face:
                      u16 pointer to that face's index list
                      u16 attribute: low byte the colour, high byte the draw
                         mode - 0xF0 flat shaded (5473 faces), 0x10 on the
                         billboard-like objects TREEBLIT and BROCK (12 faces)
    u16  0x0000, u16 0x0000        terminates the pair block
         index lists  per face: face id, 1-based vertex indices, 0xFFFF

Two things that had been guesswork are now settled:

* **The face count is not in the header.** The third word counts *normals*.
  Faces are counted by walking the pair block to its zero terminator. This
  replaces the extent-bounded longest-run heuristic entirely - no more needing
  to know where the next model starts.
* **The word after the normals** is a pointer to the pair block itself, i.e.
  the model self-locates. `read()` uses that as a validity check.

Both pointer kinds are the **low 16 bits of an absolute word address**, so they
resolve against the model's own high bits and depend on where it is placed.

### Verification

    206 of 206 catalogue models re-encode BYTE-IDENTICALLY at their own address
    206 of 206 survive relocation to a fresh address and read back unchanged

`mesh.encode(model, base)` returns the bytes for placement at `base`. It
refuses a base that would make the model straddle a 0x10000-word (128 KB)
boundary, because the truncated pointers would resolve into the wrong half.

Model sizes run 50 to 5346 bytes; the 206 models total 185.6 KB, which is why
the 256 KB object ROM has only 1.3 KB of padding left.

## Correction: the two grids are two TRACKS, with separate placement arrays

Earlier this file said both 4x4 grids indexed one shared 193-record array. That
was wrong - it came from picking the base by "does the rotation matrix look
valid", which 17 different bases satisfied. The coordinates settle it:

    grid A @ 0x037C2  base 0x011D0 (68k 0x9411D0)  193 records
                      X  84299..334480   Z  102236..287200
    grid B @ 0x0EFFC  base 0x0CCF8 (68k 0x94CCF8)  178 records
                      X -189603.. 59168   Z -164744.. 40166

Disjoint coordinate regions, each matching its own grid's cell splits. Two
tracks, two arrays.

**Grid B is Super Stunt.** Its exclusive objects are the stunt furniture:
`HLOOP` x2, `CORKS` x4, `LAUNCH` x2, `JPART`, `JLAND` x2, `TUBE` x4, `BANK` x2,
plus the diner scene (`DINER`, `RESTSTOP`, `PTABLE`, `PBENCH`) and the terrain
hills `HILL_A`..`HILL_D5`.

**Grid A is the original course** - `SKIDPAD`, `EZJUMP`, `RAMP1`, `LOFT`,
`BRIDGE` x2, `OVERP` x2, `UNDERP` x2, `XOVER`, `RRCAR` x3, `HUT`.

27 object kinds are shared; 21 are A-only and 36 are B-only.

## The object ROM is now fully accounted for

    catalogue        390 x 18 bytes         6.9 KB
    models           206 distinct          186.4 KB
    reciprocal table 0x22000..0x30000       56.0 KB
    padding                                  1.3 KB
                                          ---------
                                           250.6 KB of 256 KB

The 56 KB block that had never been identified is a **1/x lookup table**:
`value[k] = 16777216 / (4096 + k)`, 28672 entries, i.e. 1/x in 12.12 fixed
point over x = 1.0 to 8.0. Verified against all 28672 entries with a single
rounding-level mismatch. That is the perspective divide the ADSP needs, and it
is not reclaimable.

## Space budget for swapping Super Stunt out

    freeing every model reachable ONLY from Super Stunt-exclusive
    objects (58 models)                                    49.4 KB

    VIR, one normal per face                               60.5 KB
    VIR, one normal per model (what D30R917 does)          49.5 KB

So it fits, but only just - about a hundred bytes of margin, and only with
normals shared per model rather than per face.

**One caveat before trusting that number.** Roughly 14 KB of the "freeable" set
is vehicle geometry - `CAR2`, `VAN`, `WL`/`WWL`, `WPIC`, `WTRUK3` - which is
static in Super Stunt but may also be spawned dynamically on the other course by
the 36-node entity pool at 0x9002CC. If those must stay, only ~35 KB is really
free and VIR has to shed about 15 KB. Resolving that means checking what the
dynamic spawner at 0x022CBC can reference, which is not yet done.

## Track selection - found, and it is data, not code

The reason nothing in the main CPU ROM references the grid base addresses is
that the track table lives in the **DSK ROM, at offset 0x00000**. It holds
**328-byte (0x148) records, and there are exactly two** - a scan of the whole
DSK ROM finds only two structures of the descriptor shape.

Each record begins with a pointer to a **14-byte track descriptor**, which sits
immediately before that track's grid cell array:

    +0x00 u32  placement array base
    +0x04 u16  cell header stride (0x1C)
    +0x06 u16  0x0070
    +0x08 u16  0x0070
    +0x0A u32  grid header array   (always the 14 bytes right after this one)

    track A descriptor @ 0x9437B4 -> placements 0x9411D0, grid 0x9437C2
    track B descriptor @ 0x94EFEE -> placements 0x94CCF8, grid 0x94EFFC

The rest of the 328-byte record is a pointer block. What each one reaches:

    +0x00  the track descriptor above
    +0x04  a block of position/orientation records (1.14 identity matrices are
           visible in it); variable-length, stride not yet pinned down
    +0x08  route descriptor  (A: one, used twice; B: two different)
    +0x0C  route descriptor
    +0x10  the named-section table, below
    +0x14  0x940560 - the SAME pointer for both tracks, so track-independent
    +0x18  \ per-track structures that begin with a pointer
    +0x1C  /
    +0x80  0x95B744 / 0x95BD44
    +0x90, +0x98, +0x9C, +0xA0, +0xC0   further per-track blocks

### The named-section table (+0x10), 12 bytes per record

    u32 pointer to a NUL-terminated name
    u16 value       (5200, 5700, 6700, 6933 ...)
    u16, u16, u16

    track A: START, SPEED, STUNT, DROPOFF, BRIDGE, LOOP, JUMP,
             BANKED TURN, SPD UNDERP, BRDG LDG          (10 records)
    track B: SUPER STUNT, SPLIT LOOP                     (2 records)

Those are the section names the game displays, and they confirm the track
identities independently of the geometry: track A carries the Hard Drivin'
speed/stunt route names, track B the Super Stunt ones.

### What this unlocks

Swapping Super Stunt for another course is now a **data edit**, not a code
patch: point track record 1 (DSK 0x00148) at a new descriptor carrying a new
placement base and grid header array, and replace its name table.

### What is still missing

The **checkpoint gate positions and the timer extension** are not decoded. The
+0x004 block is the strongest candidate - it holds position and orientation
records - but its records are variable-length and the two header counts (70 for
track A, 25 for track B) do not obviously match a fixed stride. That, plus lap
progress, is what still stands between a placed track and a playable one.

## The +0x004 block: the per-track positioned-entity array

Each track record's `+0x004` pointer reaches a header followed by an array of
**64-byte records**. Two things pinned the format down:

* **32-bit fields are stored LOW WORD FIRST.** The header value that read as
  0x01AE0000 is just 430; the coordinates only make sense read this way.
* **The third coordinate is the vertical**, not the second. Track A's first
  record is X=262660, Z=122005, Y=2 - on the ground, on the track. Read as
  X/Y/Z it lands nowhere.

    +0x00  s32  X          (low word first)
    +0x04  s32  Z
    +0x08  s32  Y          vertical
    +0x0C  9 x s16  rotation matrix, 1.14, plain big-endian
    +0x1E  u16  0
    +0x20  u16  type / flags
    +0x22  ...  further fields, not yet identified
    ---- 64 bytes ----

The header's first longword is the **total** record count; the next two are
sub-counts:

    track A  430 = 70 + 352 + 8     records 0x04A0A..0x0B58A
    track B  725 = 25 + 700         records 0x10204..0x1B744

Track B's array **ends exactly at 0x1B744**, which is the address track A's
`+0x080` pointer already pointed at - an independent confirmation of both the
64-byte stride and the count.

### Verification

    track B   725/725 records carry a valid rotation matrix
              661/725 lie inside the track's coordinate bounds
    track A   415/430 valid matrices, 405/430 inside bounds

Type words seen: 0x0100 (243/262), 0xC100 (90/328), 0x0900, 0x2900, 0x3F00,
0x3900, 0x8100, 0x4100, and a few singletons. The two common types dominate.

Plotted over track A's static geometry, the 0x0100 records **trace continuous
paths along the road** - including routes the static geometry does not cover,
which fits track A carrying both the Speed and Stunt routes (its section table
names START, SPEED, STUNT, DROPOFF, BRIDGE, LOOP, JUMP, BANKED TURN,
SPD UNDERP, BRDG LDG). Median spacing between consecutive records is 3.8 m on
track B, 29.4 m on track A.

### What is NOT established

The records' **heading agrees with the direction to the next record only 23-38%
of the time**, so these are not simply forward-facing waypoints along a spline.
The matrix may orient a gate across the road rather than along it, or the array
may interleave several routes. Until that is resolved, do not assume record
order is lap order.

Which type word marks a **checkpoint / continuation gate** is therefore still
open. The rare types (0x3F00, 0x3900, 0x8100, 0x4100 - a handful each) are the
obvious candidates, and 0x2900/0x0900 the next, but nothing here proves it.

### Attempts to resolve the heading, and what they showed

Four probes, none conclusive - recorded so they are not repeated:

1. **Heading vs the next record by index** - agrees 23% (track A) / 38% (B).
2. **Heading vs the direction to the spatially nearest record.** Testing every
   matrix axis: local X is parallel 50% of the time and perpendicular only 7%,
   local Z parallel 43%. Local X is the best candidate but the split between
   two axes suggests two populations rather than one convention.
3. **The same test split by type word.** No type comes out cleanly parallel or
   perpendicular. The best is 0xC100 on track B at 62% parallel, 8%
   perpendicular - suggestive, not decisive.
4. **Finding the code that walks the block.** A search for `mulu #$148` (the
   328-byte track-record stride) returns **nothing**, so the record is not
   selected by multiplication - its address is probably stashed in RAM after
   selection. A scan for `lsl.l #6` (the 64-byte stride) returned 19 sites, but
   disassembling them showed the mask was matching bytes *inside* other
   instructions, not real instruction boundaries. That probe produced no
   information.

The 0x940000 immediate does appear at 0x011D82, but that is the **self-test**:
it sums 0x10000 bytes of the DSK ROM into two accumulators, even and odd, which
is the routine that checks the EPROM byte-sums this project already relies on.
Worth knowing, unrelated to track data.

**Recommended next step is empirical, not static.** Run the game on a known
track under MAME, tap reads of the +0x004 block, and watch which records the
code touches as the car passes them. That identifies the gate type directly
instead of inferring it from geometry, and the harness for it already exists.

### Empirical: how the +0x004 block is actually used

Run under MAME 0.289 with a read tap on the DSK ROM window (`gatetap.lua`):

    track A: 430 of 430 records read, exactly 64 reads each, 27520 total,
             all within frames 242-249
    track B: 0 of 725 records read

Three things follow.

**The record count and stride are confirmed independently.** The tap covered
exactly 430 x 64 bytes for track A and 725 x 64 for track B. Track A came back
100% covered with a perfectly uniform 64 reads per record - no partial records,
no spillover past the end. A wrong stride or count would have shown up as
either.

**It is a one-shot bulk load at track init, not a per-frame scan.** Nothing
re-reads the array while the demo drives. So the gate question cannot be
answered by watching ROM reads - by the time the car is moving, the ROM is no
longer involved.

**The destination is the ADSP.** Writes during the copy land almost entirely in
0x85C000..0x85C810 - only 2 KB of address range for 14061 writes, so that is a
**streaming window, not a linear buffer**. The 68010 reads the array out of the
DSK ROM and pushes it through that port into ADSP internal memory.

That the ADSP consumes it fits the rest of the picture: the ADSP does the 3D
transform and the physics, and road objects carry no collision box in the object
table because the drivable surface comes from geometry rather than from a
separate collision database.

**Consequence for finding the gates:** they have to be found on the ADSP side.
The next probe is a tap on the ADSP's own data space, watching which of these
records it reads as the car moves - not the 68k bus, which goes quiet after
frame 249.

Scripts: `gatetap.lua`, `gatedst.lua`, `gaterange.lua`.

## The route graph - the lap structure

Track record `+0x008` and `+0x00C` point at **route descriptors**, and each is
the head of a **doubly-linked circular list of track sections**. 26 bytes per
node:

    +0x00  u16  length
    +0x02  u16  length again (occasionally +1 or +5)
    +0x04  u32  0
    +0x08  u16  flags
    +0x0A  u32  next
    +0x0E  u32  previous
    ---- 26 bytes ----

Every list closes: the last node's `next` is the head. That is the lap.

    track A route   15 nodes, lengths sum 3922
    track B route1  13 nodes, lengths sum 4674
    track B route2   8 nodes, lengths sum 2572

**Track A has one route and track B has two**, which matches the track records -
track A's `+0x008` and `+0x00C` both point at the same descriptor, track B's
point at two different ones. Track B's route2 is a **short variant that reuses
route1's sections**: the nodes carrying 184, 190, 242, 344, 747 and 356 appear
in both lists at different addresses, so the fork rejoins.

The flag word is where section identity lives. Track B's route1 shows a single
distinct high bit on individual sections - 0x1200, 0x8200, 0x4200, 0x2200
against a background of 0x0200 - and track A shows 0x1000, 0x8000, 0x0008 and
0x4001 against a background of 0x0001. Single-bit markers on individual
sections of a closed lap is exactly the shape a checkpoint or continuation gate
would take, and it is the best candidate found so far.

**This supersedes the +0x004 block as the place to look for gates.** That block
was ruled out empirically: only 3% of its records lie on a road-surface polygon,
and a systematic search over every offset and both 32-bit byte orders never got
above 15%, so it is not positions along the racing line. It is bulk-loaded once
at track init and streamed to the **DSP32C** (0x85C000-0x85C7FF,
`hd68k_dsk_dsp32_r/w`, with the DSK control register at 0x85C800) - a maths
coprocessor, not the gameplay logic. What it holds is still unidentified.

### The section-name table's fourth field is a route id

    track A   START 0 | SPEED 1, SPD UNDERP 1 | STUNT, DROPOFF, BRIDGE, LOOP,
              JUMP, BANKED TURN, BRDG LDG all 2
    track B   SUPER STUNT 4, SPLIT LOOP 4

That is **Hard Drivin's fork**, in the data: START is common (0), the Speed
Track branch carries 1 and owns SPEED and SPD UNDERP, and the Stunt Track branch
carries 2 and owns the loop, the jump, the banked turn, the bridge and the
bridge landing. It matches the track record having two route pointers, and it
matches track B's two routes sharing sections.

The table's first field is 5200 for most sections but 6933 for BRIDGE, 6700 for
LOOP and SPD UNDERP, and 5700 for BRDG LDG - a per-section value whose meaning
is not established.

### Route node flags: a one-hot marker in the top nibble

Stripping the per-track background bit (bit 0 on track A, bit 9 on track B),
what remains is **exactly one of 0x1000 / 0x2000 / 0x4000 / 0x8000, or nothing**:

    track A, 15 sections:  0x1000 on section 0
                           0x8000 on section 1
                           0x4000 on section 9
                           0x2000 on section 14
                           (also 0x0008 alone on section 8)
              - one of each marker, spread around the lap

    track B, 13 sections:  0x1000 on 1; 0x2000 on 12;
                           0x8000 on 2, 4, 8, 11; 0x4000 on 3, 7, 10

Four distinct one-hot markers distributed around a closed lap, exactly one of
each on track A, is the clearest candidate yet for the checkpoint / continuation
gate mechanism. Section lengths accumulate to 3922 (track A), 4674 (track B
route1) and 2572 (route2), giving each marker a position along the lap.

What is not yet established: which marker means what, and the unit of the
length field.

## The 3D palette - found, and it settles an open question

Tapping the DSK ROM window *while the game is driving* (`livetap.lua`) shows the
busiest reads by far are DSK 0x1BD00-0x1C0FF - 161k reads over 3000 frames -
and 0x1BD44 is exactly what track B's record `+0x080` points at.

That block is **768 bytes: 256 RGB triples. It is the 3D renderer's palette,
and there is one per track.**

    track A palette  DSK 0x1B744
    track B palette  DSK 0x1BD44

Compared against the palette previously dumped out of GSP VRAM:

    VRAM bank 0 vs DSK track B block:  768/768 bytes match
    VRAM bank 0 vs DSK track A block:  651/768
    every other bank:                  <= 500/768

**Bank 0 is the right palette.** Earlier notes in this file speculated bank 0
was "a debug palette" because it hands out pure red, green and cyan, and picked
bank 1 as the viewer default on the grounds that it looked more naturalistic.
That was wrong: bank 0 is what the ROM loads, and the pure primaries are simply
what the game uses. The 768/768 match against track B also tells us the VRAM
dump was taken while Super Stunt was loaded, which is consistent with the
attract demo running track B.

`viewer.py` now defaults to bank 0. `pal_trackA.bin` and `pal_trackB.bin` hold
the two palettes.

### Two corrections that came out of the same run

* The attract demo runs **track B**, not track A. During driving the game reads
  grid B's cell headers (0x0F1xx) and track B's record; track A's +0x004 block
  is read once at boot and then never again.
* The "16316 bytes of 0x00 padding at 0x1C044" recorded earlier is right only
  from 0x1C044 - 0x1C000..0x1C043 is the tail of track B's palette and is read
  constantly. Anything relying on that padding must start at 0x1C044, not
  0x1C000.

## The route graph, confirmed live

Tapping RAM found two words holding a pointer into track B's route nodes, and
tracing their accessors (`whopc.lua`, which logs `CURPC` inside the tap) gave
the code:

    0002239C  ...
    000223B2  tst.w   $901116
    000223BA  bne     $223C4
    000223BC  tst.w   $46E16
    000223C2  beq     $223CA
    000223C4  move.l  ($0C,A2), (A4)     ; route B
    000223C8  bra     $223CE
    000223CA  move.l  ($08,A2), (A4)     ; route A
    000223CE  move.l  ($10,A2), $9015F0
    000223D6  move.l  ($14,A2), $9015F4

**A2 is the track record**, which confirms the field map from the code side:
`+0x08` and `+0x0C` are the two route descriptors and this is the branch that
chooses between them - the Speed Track / Stunt Track fork - and `+0x10` is the
named-section table.

The reader at 0x022456 takes the selected route head and copies **the node's
first word** into 0x900D58:

    00022450  cmpi.w  #-1, D2
    00022454  bne     $22460
    00022456  movea.l (A4), A0
    00022458  move.w  (A0), $900D58

### Live RAM map

    0x9015EC   pointer to the current route-graph node
    0x9015F0   the track's named-section table  (record +0x10)
    0x9015F4   record +0x14
    0x900D58   the current section's first word
    0x900D5A   pointer to the track's +0x004 block

Watched over 5400 frames (`watchd58.lua`), these move together exactly as the
structures predict:

    frame 240   head 0x009401EC   value  200   block 0x009449CA   <- track A
    frame 390   head 0x009406FE   value  724   block 0x009501C4   <- track B

200 is track A's first section length and 0x9449CA is track A's `+0x004`
pointer; 724 and 0x9501C4 are track B's. The whole chain - track record to route
descriptor to first node, and track record to positioned-entity block - is
confirmed end to end against the running game, and the switch from track A to
track B at frame 390 is the attract demo choosing Super Stunt.

### Still open

The section value **does not advance during the attract demo** - it sits at 724
for 5000 frames. So section progress is either driven from somewhere else or
the demo never completes a section. Identifying what advances 0x9015EC needs a
run that actually drives a lap, not attract mode, and that is where the meaning
of the one-hot marker bits and the unit of the length field will come from.

## The marker bits: start, finish, and alternating checkpoints

Listing every route's markers together makes the scheme obvious:

    route A   15 sections   s0=1000  s1=8000            s9=4000           s14=2000
    route B1  13 sections   s1=1000  s2=8000 s3=4000 s4=8000 s7=4000
                                     s8=8000 s10=4000 s11=8000            s12=2000
    route B2   8 sections   s1=1000  s2=4000 s3=8000 s5=4000 s6=8000       s7=2000

In all three:

* **0x1000 appears exactly once, at or near the first section** - the start.
* **0x2000 appears exactly once, on the LAST section** - the finish.
* **0x4000 and 0x8000 strictly alternate** in between. Route B1 runs
  8,4,8,4,8,4,8; route B2 runs 4,8,4,8; route A has just two, 8 then 4.

Alternating markers around a closed lap is the standard way to make checkpoints
un-retriggerable: you can only satisfy the next one if you passed the previous,
so a car that stops on a gate or reverses over it cannot farm it. That makes
0x4000/0x8000 the **continuation gates**, with the alternation carrying the
ordering.

Route A has only two intermediate gates for 15 sections; route B1 has seven for
13. That fits Super Stunt being the longer, more demanding course.

`routegraph.py` reads and writes these:

    routegraph.read(dsk, head)                 walk a route from its head
    routegraph.encode(sections, base)          lay out a new circular route
    routegraph.verify(blob, base)              read it back, check the ring closes

`encode()` round-trips route B1's 13 sections with matching values, and refuses
a marker that is not 0 or a single bit of the top nibble.

Still unknown: the unit of the section value. Sums are 3922 (A), 4674 (B1) and
2572 (B2).

### The section-value consumer

Tapping 0x900D58 for its accessors gives one reader, 0x0234FE:

    000234FE  cmpi.w  #-1, $900D58      ; anything pending?
    00023506  beq     $23536
    00023508  move.l  $900D5A, -(A7)    ; push the +0x004 block pointer
    0002350E  jsr     $23A74
    0002351C  move.w  $900D58, D0
    00023524  sub.l   $900D60, D0       ; value - 0x900D60
    0002352A  move.w  D0, ($0E,A4)
    0002352E  move.w  #-1, $900D58      ; consume

and 0x23A74 copies **exactly 64 bytes - one record's worth** from the block
pointer, passes the first two longs through 0x28F4C, and keeps the second:

    00023A9E  movea.l A2, A0            ; A2 = the block pointer argument
    00023AA6  move.l  (A0)+, (A1)+      ; x16 = 64 bytes
    00023AB6  jsr     (A3)              ; A3 = 0x28F4C, on the first long
    00023ABA  move.l  (-$40,A6), $900D60  ; the second long
    00023AC8  jsr     (A3)              ; on it too
    00023ACA  subq.l  #1, $900D60

0x28F4C being applied to every longword read out of this data is independent
confirmation of the **low-word-first** 32-bit encoding - it is the swap.

**A near miss worth recording so it is not chased again.** 0x900D5A holds the
block's *header* address, not a record, so 0x900D60 becomes header[1] - 1. For
track B that gives 724 - 24 = 700, which is exactly header[2] - very tempting.
It does not generalise: track A gives 200 - 69 = 131 against a header[2] of 352.
Coincidence, not mechanism.

### Driving attempts

Two scripted runs (`drive.lua`, `drive2.lua`) failed to start a game. The first
had a real bug - the coin input was released to 1 instead of its default 128, so
it never returned to idle. With that fixed and the Abort button pulsed as a
start candidate, the machine still only cycles attract: the route head goes
0x9401EC (track A) then 0x9406FE (track B), clears, and repeats about every
1000 frames, with the section value never leaving 724.

So section advance has still never been observed, and the unit of the section
value remains unknown. Starting a real credit needs the correct start input,
which these runs did not find.

## The car's own state in RAM

Found by snapshotting 0x900000-0x9005FF during a real driving session and
keeping only longwords that stay inside track B's coordinate bounds while
changing:

    0x900044  s32  car X
    0x900048  s32  car Y  (vertical)
    0x90004C  s32  car Z
    0x900054       the orientation matrix (already known - it is the source of
                   the matrix copied into each draw-list instance)

The position sits immediately before the matrix, which is what you would expect
of a single car-state structure. Writing these three longs **teleports the car**,
verified: stepping through all 725 of track B's +0x004 block positions drives
the grid-cell pointer at 0x9001EC through cells 0x94F088, 0x94F0C0, 0x94F0F8,
0x94F114, 0x94F168, 0x94F184 and back, hundreds of times.

### Starting a real game

    Coin 1   press to 0, release to its default 128 (not 1)
    Key      IPT_START1, spring-loaded: click and hold ~750 ms (45 frames)
    Shifter  leave at its centre detent 128,128 = AUTOMATIC.
             Forcing it to a corner picks the manual-transmission car.

"Abort" is IPT_START2 and is not the start button.

### Section advance: still not observed

With a game running and the car driven under power, the grid cell changes and
the draw list repopulates - the car is genuinely moving. Teleporting it through
every one of the 725 block positions moves it across the whole map. **In neither
case does the section value at 0x900D58 ever leave 724, and the node pointer at
0x9015EC never advances.**

That is useful negative evidence: section advance is **not purely positional**.
Dropping the car onto a gate does not trigger it. It presumably requires
legitimate progress - crossing gates in order, on the road, under the game's own
physics - which scripted input has not yet achieved.

## Lap-progress variables - found by driving

An autopilot (`record.lua`) follows a road centreline built from track B's own
road-piece placements, chained with heading continuity seeded from the car's
observed direction out of the start box. It reaches waypoint ~413 of 606, about
two thirds of a lap.

Snapshotting 0x900000-0x901FFF at eight points along that lap and keeping only
words that move monotonically gives:

    0x900D76   27  859 3710 6560 9411 10070 10070 11612
    0x901F9C    7  855 3696 6555 9395 10053 10053 11602
    0x901FA0    0  850 3650 6550 9350 10050 10050 11600
    0x901F5A 3732 3936 4608 5304 5976  6144  6144  6516
    0x901006 1882 2879 3823 4663 5552  6747  7828  8793

**0x901FA0 is distance travelled along the lap.** It is the clean one - round
numbers - and it *stalls* between snapshots 6 and 7, which is exactly when the
car was wedged at waypoint 207. 0x901F9C and 0x900D76 shadow it with small
offsets. 0x901006 rises steadily whether or not the car moves, so it is a timer.

**0x900D76 sits in the same block as 0x900D58 / 0x900D5A / 0x900D60** - the
route-section mailbox, the +0x004 block pointer and the reference value. So the
lap tracking and the route graph do live in one structure after all, even though
0x900D58 itself never advanced.

### Standing negative result

Across a full-throttle run, a teleport through all 725 block positions, and an
autopilot lap covering two thirds of the course on the road, **0x900D58 never
left 724 and 0x9015EC never advanced**. Whatever completes a section, it is not
simply reaching a place on the track.

## The route-node flags word, fully decoded

Found from the code at 0x02FF30, which reads a route node's flags:

    0002FF32  move.b  ($9,A0), D0       ; LOW byte of the flags word
    0002FF48  asl.l   #2, D2            ; x4
    0002FF4E  adda.l  A0, A0            ; x8
    0002FF50  adda.l  D0, A0            ; x12  -> 12-byte records
    0002FF52  move.l  $9015F0, D0       ; the section-NAME TABLE pointer
    0002FF58  move.w  ($a,A0,D0.l), $9016C6
    ...
    0002FF64  and.b   ($8,A0), D0       ; HIGH byte, masked with 0x0F
    0002FF6C  move.w  D1, $90173E

So the word is three fields, not "a marker plus a background bit":

    bits 15-12  marker      1 = start, 2 = finish, 4/8 = alternating gates
    bits 11-8   route type  copied to 0x90173E, compared against 2 at 0x0223DA
    bits  7-0   index into the 12-byte section-name table (record +0x10)

### Verification

Every one of the 36 stock sections decodes to an **in-range** name index, and
the names read as the route:

    route A   START, START, START, SPEED, SPEED, SPEED, SPEED, SPEED,
              SPD UNDERP, SPEED, SPEED, SPEED, SPEED, SPEED, SPEED
    route B1  SUPER STUNT x9, SPLIT LOOP at s9, SUPER STUNT x3
    route B2  SUPER STUNT, ..., SPLIT LOOP at s4, ..., SUPER STUNT

Track A's route is the **Speed Track** - it names SPEED throughout and SPD
UNDERP exactly once, at s8. Track B names SPLIT LOOP exactly at its split. The
route type is 0 for track A and 2 for track B in every section.

This **corrects** the earlier note in this file that called the low bits "a
per-track background bit (bit 0 on track A, bit 9 on track B)". Bit 0 was a name
index of 1 (SPEED); "bit 9" was route type 2 in bits 11-8.

`routegraph.flags(marker, route_type, name_index)` and `split_flags()` build and
split the word; the split round-trips all 36 stock sections with no mismatches.

## Drones - how they were made (from the user, who knows the machine)

Not yet verified against the ROM; recorded because it shapes where to look.

* Drone paths were **recorded by a human driving the course** on custom
  development hardware. The recorded path is what the drone replays in game.
* Replay is **not rigid**. Drones can deviate somewhat from the recorded line to
  avoid a player car already occupying the space they want, then rejoin the
  programmed line when they can.
* The same recording capability shows up elsewhere in the game: **Phantom
  Photon** on the original track is a recorded lap, and beating it replaces it
  with *your* lap for the next player. The qualifying time also decays over time
  since boot so it stays beatable.

Implication for editing: new road needs new drone lines. There is no way to
"derive" them from the geometry the way a racing line could be fitted - the
originals are performances, not calculations. Recreating them means driving the
new section and recording, or synthesising a plausible line and accepting it
will not have the human character of the originals.

### Does this explain the +0x004 block?

**Hypothesis, not established.** The per-track +0x004 block is an array of
64-byte records, each carrying a **position (X, Z, Y), a 3x3 rotation matrix and
a type word** - which is precisely the shape of a recorded car pose. Counts are
430 for track 0 and 725 for track 2, plausible for a lap sampled at a few Hz.

Evidence against, and it is not weak: only **3% of those records fall inside a
road-surface polygon**, and a systematic search over every field offset and both
32-bit byte orders never got above 15%. A recorded driven lap should sit almost
entirely on the road. The block is also streamed to the **DSP32C**, a maths
coprocessor, which is an odd destination for gameplay path data.

So the shape fits and the position does not. Worth re-testing properly if drone
work starts: check whether the records cluster along the racing line *in order*,
rather than testing polygon containment, which is sensitive to how the road
polygons were reconstructed.

**Resolved (2026-09-06): the +0x004 block is the ROAD SEGMENT table**, not a
drone path - position/elevation/pitch matrix/links/ownership ranges, streamed to
the DSP32C because the DSP32C is the physics processor (see NOTES.md).  The 3%
containment was the transposed x/z.  So the drone recordings live somewhere
else, almost certainly the 1 MB main CPU ROM; the way in is the mover block the
68010 rebuilds at 0x809400 (routine 0x021B88, position via 0x2162A): tap the
writes, follow the mover state back to the ROM table it is replayed from.
