# Virginia International Raceway, Full Course

A track built in the ROM's own units and format conventions, from public data
only. Reproduce with:

    python3 vir_fetch.py      # OSM centreline + USGS elevation -> vir_centreline.json
    python3 vir_build.py      # -> vir_world.obj, vir_world.mtl, vir_placements.json
    python3 obj_viewer.py vir_world.obj vir_viewer.html

## Where the data comes from

**Centreline** - OpenStreetMap (ODbL), `highway=raceway` ways in the VIR bbox,
fetched through Overpass. VIR is mapped there with its real corner names.

**Which loop is the Full Course** was decided by measurement, not by assuming a
turn order: a depth-first search over the way graph for closed loops, keeping
the one whose length matches the published 3.27 miles. It came out at
**5262 m = 3.270 mi, 1 m from the published figure**, in this order:

    Horseshoe - NASCAR Bend - Left Hook - Snake - South Bend
    - Oak Tree Curve - Roller Coaster - Hog Pen - start/finish

**Elevation** - USGS 3DEP 10 m NED via OpenTopoData, sampled every 10 m along
the lap and lightly smoothed twice (raw DEM posts are noisy under a road). The
result spans **112.7-152.7 m, a 131 ft range**; VIR publishes "about 130 feet".
Spot-checked against the USGS 1 m EPQS service, which agreed to 0.8 m.

## Geometry

    14 road segments   1082 verts   527 faces
    OAKTREE              96 verts    94 faces
    BRIDGE               40 verts    30 faces
    ---------------------------------------------
    16 models          1218 verts   651 faces

Track width is a uniform 40 ft - which is both VIR's approximate width and
exactly `ROAD1`'s width in the original game (1601 units).

**Segmentation is forced by the format.** Vertices are s16, so no model may
reach beyond +/-32767 units (250 m) from its own origin. 400 m of track per
segment keeps the largest coordinate at **26233 units of the 32767 available**.
This is the same reason the original game builds its track from `D30R917`,
`C4572` and friends rather than one ribbon.

World extent is 0.83 x 1.76 km, against the original world's 2.06 x 1.53 km, so
VIR fits the existing coordinate space comfortably.

## The oak at Oak Tree Curve

The apex was found as the point of maximum curvature within the OSM way named
"Oak Tree Curve": **sample 247, a right-hander at 36.551918, -79.205117,
148.0 m elevation**.

The tree is a 19 m mature white oak with a 22 m spread - short thick bole,
heavy low limbs, canopy broader than tall - leaning 2.6 m back over the track.
96 verts and 94 faces puts it in the same class as the game's own `COW`
(129/96) and `BARN` (141/53), so it reads as period rather than as a modern
mesh dropped into a 1990 renderer.

**It stands on the inside of the turn - the apex side** - trunk 18.5 m from the
centreline, canopy edge reaching about 1.2 m past the track edge: overhanging a
tad. `STAND_M` in `extras()` sets how far back the trunk stands.

Verified rather than asserted: the corner's centre of curvature is 33 m from
the apex and the trunk is 16 m from that centre, so it is unambiguously inside.
(An earlier version negated the side and put the tree on the outside.)

The tree's shape is a plausible mature white oak, not a survey of the actual
tree. Nothing in the public data describes the real one's form.

## The bridge

**North Paddock Road**, the only mapped bridge near the course - a 26 m span
passing 12 m from the centreline. Built as a flat deck with parapets and two
abutments, 7 m wide, deck 6.0 m above the track, abutments 13.2 m either side of
a 6.1 m half-width - clear of the surface. OSM maps it as a 2-point way, so the
span and bearing are real and everything else is a reasonable road bridge.

The span is centred on where the deck line actually crosses the centreline, not
on the OSM way's midpoint, so the abutments sit symmetrically clear of both
edges. Verified: the deck axis is 90 degrees to the track direction.

**Note on `yaw_matrix`.** It must map local +X to the bearing:

    c, s = dx/m, dz/m
    [ c, 0, -s,
      0, 1,  0,
      s, 0,  c ]

An earlier version used `c, s = dz/m, dx/m`, which maps +X to the *perpendicular*
of the bearing. Every placement using it comes out rotated 90 degrees - the
bridge lay along the track instead of over it. Worth remembering when writing
other placements by hand.

## Pit lane, walls and buildings

**Buildings** - 16 real OSM footprints within 250 m of the track, extruded.
**No VIR building carries a `height` or `building:levels` tag**, so heights are
assumed from footprint area (3.5 / 5.5 / 7.0 / 9.0 m); the table is `HEIGHTS` in
`vir_structures.py`. The footprints are real; the heights are a guess.

**Fences and walls** - 25 runs from OSM `barrier` ways (29 fence, 2 wall,
2 guard_rail in the area). Heights assumed likewise. These are paddock and catch
fencing - **OSM maps no trackside armco or tyre walls at VIR**, so there is no
barrier along the racing line unless you generate one.

**Pit lane** - surfaced from the OSM "Pit Lane" way: 663 m, on the left of the
racing line, 10 m wide.

**Pit wall** - not in OSM anywhere, so it is synthesised along the pit lane's
track-facing edge: 1.05 m high, 0.25 m thick.

Three trims matter, and each one was a thing you would have hit:

* The Pit Lane way **merges with the racing line at both ends** - which is real,
  it is how cars get in and out. The wall is therefore built only along the
  contiguous stretch that clears the track edge by 1 m: points 8-56 of 68,
  a 480 m run, entry and exit left open. Untrimmed, 17 of 68 wall points sat
  inside the racing surface.
* The pit **surface** is trimmed the same way rather than overlapping the track,
  which would z-fight along the seam.
* Two mapped **fence points crossed the circuit** - real paddock crossings, but
  solid obstacles if built. Fence runs are split and the crossing stretches
  dropped.

A whole-model check now reports **no geometry within 6.1 m of the centreline
below 4.5 m** except nothing at all - the bridge clears entirely. Re-run it any
time you add something; it is the check that caught all three of the above.

## Model budget

    VIRROAD x14   PITLANE x2   PITWALL x2   BLDG x16
    FENCE  x25   OAKTREE x1   BRIDGE  x1
    ------------------------------------------------
    61 models, 3114 verts, 1938 faces

Against the original game world's 193 placements and 4643 faces, so it fits.
Every model is inside the s16 limit, the largest coordinate being 26233 of
32767. Long runs - road, pit lane, walls, fences - are cut at 300 m by
`_cut()` in `vir_structures.py`, which is a distance budget rather than a
vertex count precisely because a fence sampled every 15 m overflowed s16 when
chunked by count.

## What is approximated

* **Width is uniform.** Real VIR varies; the data does not carry width.
* **No banking or camber.** The DEM gives one elevation per centreline point,
  so the cross-section is level everywhere. VIR's real camber is not in here.
* **10 m sampling** follows the OSM polyline exactly - it does not smooth or cut
  corners - but the OSM polyline is itself a hand-traced approximation.
* **No walls, buildings, kerbs, runoff or trees** beyond the one oak, as asked.

## Getting it into ROM

The placement side is ready: `vir_placements.json` carries a 50-byte instance
per model - object index, 1.14 rotation matrix, s32 X/Y/Z - in the format
documented in WORLD.md, and all 16 fit the coordinate limits.

The model side is not. Writing these back needs an **encoder** for the object
ROM's mesh format: the header, the vertex and normal arrays, the
(pointer, 0xF0nn) pair block, and the 0xFFFF-terminated index lists, with the
pair pointers being low-16-bits-of-absolute-word-address and therefore dependent
on where the model lands. `mesh.py` reads that format; nothing writes it yet.
That encoder is the next piece of work, and it is the real gate on driving this.

## Fitting it in ROM

Target: replace Super Stunt (grid B, placement base 0x94CCF8) and reuse its
geometry space.

**The budget had to be conservative about vehicles.** Four Super Stunt-exclusive
objects are vehicles - `CAR2`, `VAN`, `WPIC`, `WTRUK3` - and dynamic traffic
never appears in either static placement array, so the arrays cannot tell you
whether the other course spawns them. Two attempts to settle it failed and are
recorded so nobody repeats them:

* The object table's `+0x12` remap field turned out to chain only the
  `FLOAT40 -> FLOAT65`, `FLOAT60 -> FLOAT90`, `NEW60M -> NEW90M` jump-distance
  markers. Nothing to do with vehicle variants.
* Searching the main ROM for each object index as a 16-bit value is useless -
  small integers appear tens of thousands of times in a 1 MB image.

So those four are held back:

    Super Stunt-exclusive, static scenery only   50 models   36.6 KB  freeable
    held back as possible traffic                 8 models   12.9 KB  keep

**VIR now costs 31.5 KB, fitting with 5.1 KB to spare** - and nothing was cut to
get there. It was 49.5 KB until the fences were fixed:

    VIRROAD x14   14.8 KB   527 faces
    FENCE   x24    6.3 KB   203 faces      (was 24.3 KB, 993 faces)
    PITWALL x2     3.5 KB   144 faces
    BLDG    x16    2.6 KB    91 faces
    OAKTREE x1     1.9 KB    94 faces
    PITLANE x2     1.7 KB    59 faces
    BRIDGE  x1     0.7 KB    30 faces
    ----------------------------------
    60 models     31.5 KB  1148 faces

The fences were being built as **solid boxes** - four vertices and three faces
per station for something 0.1 m thick. `S.ribbon()` draws them as a flat strip,
two vertices and one face per station, and the sampling went from 15 m to 25 m.
Same 24 fence runs, all 16 buildings, a quarter of the bytes. `barrier=wall`
still gets a real box from `S.wall()`.

Normals are shared one-per-model, which is what the ROM's own road pieces do -
`D30R917` declares one normal for 34 coplanar faces.

Still verified after all of it: every model inside s16 (largest coordinate
26233 of 32767) and nothing on the racing surface.

## VIR's route graph

`vir_route.py` builds it in the ROM's own format, using the **real OSM way
boundaries** of the Full Course as section boundaries - not an even division -
rotated so the lap starts where you put start/finish, 2/3 down pit lane
(centreline sample 481).

    18 sections, 5262 m total - matching the lap exactly

     0 start/finish straight    225 m   marker 1000   start
     1 ...                      227 m          8000
     2 Horseshoe                249 m          4000
     4 NASCAR Bend               72 m          4000
     6 Left Hook                 57 m          4000
     8 Snake                    236 m          4000
     9 (back straight)          945 m          8000
    10 South Bend                54 m          4000
    12 Oak Tree Curve            69 m          4000
    13 (long run)              1240 m          8000
    14 Roller Coaster           126 m          4000
    16 Hog Pen                  281 m          4000
    17 ...                      446 m   marker 2000   finish

The corner lengths land where they should - the tight corners come out 54-72 m
and the two long runs at 945 m and 1240 m.

Markers follow the scheme read off all three stock routes: 0x1000 once on the
first section, 0x2000 once on the last, and 0x4000/0x8000 strictly alternating
between - which is what makes the gates un-retriggerable.

`routegraph.encode()` lays this out as 468 bytes; the ring closes and every
marker is legal. It round-trips all three stock routes (A, B1, B2) with values
and markers matching, and refuses a marker that is not a single top-nibble bit.

**One open parameter.** The unit of the section value is not yet established, so
`vir_route.py` takes a target sum: passing 4674 (Super Stunt's) scales VIR's
metres into the same range. Once the unit is known this becomes a fixed
conversion rather than a scaling.

## Installing the route graph

`worldpatch.py` can now write a route graph into the DSK ROM and repoint a
track record at it:

    python3 worldpatch.py route 1 vir_sections.json --out ./patched

That writes the graph into the free padding at **DSK 0x1C060** and sets *both*
of track record 1's route pointers (+0x08 and +0x0C) to it, so the Speed/Stunt
fork selection at 0x0223C4/0x0223CA lands on the new route either way.

Verified on VIR's 18 sections:

    installed 468 bytes
    track 1 route pointers now 0x0095C060 / 0x0095C060
    read back 18 sections, ring closes, values match
    136077-4030.30e  byte-sum low byte 0x30   correct
    136077-4031.10e  byte-sum low byte 0x31   correct

**Note the base is 0x1C060, not 0x1C044.** The padding starts at 0x1C044, but
0x1C044 is where `save()` puts its checksum-correction byte, so route data
starts clear of it. And it is emphatically not 0x1C000 - that is still track B's
palette.

`install_route()` refuses to write if the target range is not already zero, so
it cannot silently land on live data.

## Status: VIR runs in the game

A complete patched ROM set is built by:

    python3 virrom.py     # object ROM: geometry + catalogue entries
    python3 virdsk.py     # DSK ROM: placements, grid, route, names, track record

It boots, and **selecting Super Stunt loads VIR instead**. Confirmed on the
running machine, not just in the file:

    SECTION idx=1  node=0x95D0B2  value=202  flags=8201
                   (marker 8, type 2, name 1 = VIRGINIA INTER)

That node address is in the route graph `virdsk.py` wrote. The game read our
section, our value, our alternating-gate marker, our route type and our name
index - i.e. **a VIR checkpoint was crossed and counted**.

What is verified:

    74 of 76 models placed in freed Super Stunt space (2 fence runs dropped)
    74/74 re-read correctly from the patched object ROM
    74/74 catalogue entries have a valid model header
    74/74 placements resolve to a decodable model (1131 faces)
    18-section route graph, ring closes
    all six EPROM byte-sums balance (0x21 0x23 0x22 0x24 / 0x30 0x31)

### The open bug: the car does not spawn on the road

The car appears at roughly (-91479, 438, -91016). VIR's geometry spans
X -35991..98480, Z -209851..34791, so the car is outside it - about 569 m from
the nearest placement and ~29 m below road level.

Two things are known about the spawn:

* It is **not** in the DSK ROM as a literal. Searching for stock Super Stunt's
  spawn (22199, 139, 31999) as s32, both byte orders, finds nothing.
* It **changed** when the track data was swapped - stock Super Stunt spawns at
  (22199,139,31999), the VIR build at (-91479,438,-91016). So it is derived
  from data we control, not a constant.

Ruled out: the catalogue entries. Ours are byte-compatible with stock -
`radius / lod=38400 / cull=288000 / hi / lo`, and that exact lod+cull pair is
used by 36 stock objects. At 569 m against a 2195 m cull radius the road should
be drawing, so "no road visible" is a symptom of the car being in the wrong
place, not of a culling or catalogue error.

The prime suspect is the **+0x004 positioned-entity block**. It is the one major
per-track structure not yet rebuilt - track record 2's +0x04 still points at
Super Stunt's. Its 64-byte records carry a position, a 3x3 matrix and a type
word, which is exactly the shape a spawn point would take. Next step: build one
for VIR with a start record on the pit straight and repoint +0x04 at it. There
is ~11 KB of DSK padding left.
