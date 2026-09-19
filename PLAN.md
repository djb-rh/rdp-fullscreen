# PLAN - Race Drivin' track editor and beyond

Written 2026-09-06, after the east-loop patch was finished and confirmed by
driving.  NOTES.md holds the format facts this plan relies on; WORLD.md and
VIR.md the earlier world/map work.  This file is the roadmap.

## Goals (in order; non-competing)

1. **Track editor** - a slot-car-style builder: snap stock road pieces and
   scenery together, define routes and gates, export ROM images and a
   distributable patch for MAME or real hardware.
2. **Track import** - fit a chain of stock pieces to real course data (the VIR
   centreline, meshes pulled from other games) as closely as this engine allows.
3. **Our own renderer** - consume the same layout/mesh data plus the side-pod
   serial stream for a far richer viewer (RealityKit / Vision Pro as an option,
   higher-detail objects in the original positions, later a real dash once the
   dashboard data is found and added to the stream).

## Decisions taken

* **One world.**  A custom build replaces world A wholesale and points every
  track slot at it.  World B's DSK regions (Super Stunt's grid at 0x0EFFC and
  segment array at 0x101C4) become space for the one world, so a custom track
  can be larger than either stock world.  People who want the stock worlds keep
  a stock set; world switching is a hardware concern (ROM banking), not ours.
* **Slots are routes.**  The track-select menu stays as it is in the main CPU
  ROM; each slot gets its own route over the one world (stock's speed/stunt pair
  is exactly "full course / short course").  Unused slots duplicate route 1.
  Renaming menu entries is a later nicety, not a dependency.
* **Import either stock world as a starting point.**  The decompiler reads a
  world (placements + cell grid + segments + routes) into the document; A and B
  differ only in where they sit.  "New from Speed Track", "New from Super Stunt"
  and "New blank" are one code path.
* **Chain-and-close, not a grid.**  Pieces attach entry-to-exit; stock pieces
  do not tile a grid (chords 1601..22043, turns 10/30/45 degrees) and stock
  itself closes loops with 1-2 degree kinks.  A closure solver spreads the
  residual over the joints (layout.entry_poses(close=) already does this).  The
  UI may draw a grid for scenery, but geometry is pose chaining.
* **The document is the patch.**  Distribute the track document plus the
  apply tool; ROM data never ships.  Also emit a staged MAME set and the two
  27C512 images for hardware.
* **Python stays the reference compiler.**  It exists and has been validated by
  driving; the editor UI is a local web app served by Python so the stock zip
  never leaves the machine.  The document format is the contract, so a Swift or
  TypeScript front end can replace the web UI later without touching the
  compiler.
* **Drones are recordings, and we record them the same way.**  Stock drone
  lines were human laps recorded on development hardware.  Ours will be human
  laps recorded in MAME (rd.lua already logs the car pose per frame), with a
  synthesised racing-line fallback for builders who do not want to drive every
  drone.  During the round-trip phase the stock drones are left alone on
  purpose: if we misplace a segment, they are the first thing to drive on grass.

## What is known (enough to build on)

* Placement records (50 B): object, 3x3 matrix, position, depth bias (+0x20),
  draw-enable bit 12 at +0x22; mirrored matrices are back-face culled.
* Segment records (64 B): position (x/z transposed against placements),
  elevation (positive DOWN), pitch in the matrix, flags, ahead/behind links,
  lane links, **ownership ranges** at +0x34/+0x38, road edges.  The DSP32C
  advances past hi and retreats behind lo; hand-offs must land on the next
  origin with a few hundred units of slack.
* 16-cell placement grid with ascending cell lists; renderer visibility, LOD,
  sort key, the 495-polygon pool; where the padding is and how much.
* Route graph, section values (= segment + 69), gate markers, the award table
  at track record +0x40, the start segment at header +0x08, 250 clock units per
  second, byte-sum checksum bytes 0x30/0x31.
* Piece geometry conventions (chord from the name / model extents, model
  origin offset, elevation profile from the road faces), the XOVER deck rule,
  stock's crossing trio order.
* Headless testing: start-segment builds + section force + snapshots with
  `-str 120`, exact polygon counter, per-frame drive logs.

## What is not known (research items, all findable with the same methods)

| # | Question | Why it matters | Way in |
|---|----------|----------------|--------|
| R1 | What else references world A besides the three track records: attract-mode demo (recorded inputs?), "BEAT x:xx" default times, speed/stunt junction logic, pit/start scenery | whole-world replacement must not break the front end | disassembly around the track records; taps on 0x900D54 and the route walker while attract runs |
| R2 | ~~DSP32C segment-table capacity~~ DONE: 727 segments (table 0x614000-0x61F600); compiler caps at 720 | hard ceiling on segments per world | found in dsp32_hi.dasm |
| R3 | ~~Cell binning~~ DECIDED: stock's lists are an unreproducible ~25% tightening of "within cull distance of the cell box"; the compiler uses the superset rule | defines the cell-list writer | see NOTES.md |
| R4 | ~~Drone path table~~ DONE 2026-09-09: 16 slots of 0x2598 B from 0x0A0000, the drone list/tables at DSK 0x00BFC-0x00E94 decoded, rubber band and keyframe node-count bits understood, rdtrack/drones.py synthesises/installs paths and imports the game's own RAM recording (rd.lua REC=) | new tracks need new drones | see NOTES.md 2026-09-09 |
| R5 | ~~Every road piece's true geometry~~ DONE (rdtrack/parts.py -> parts.json); stunt pieces still need a 3D treatment | the parts library must be complete and trustworthy | measured from the object ROM by tool |
| R6 | Terrain/horizon/sky and the ground colour outside placements | what a blank world looks like | placement-free build and look |
| R7 | Track-select strings and any per-track text in the main ROM | optional renaming of slots | string search |
| R8 | ~~ADSP approach band~~ RESOLVED: the UNDERP's fill-to-bottom faces sort in front of a long carrying road's base; worldgen.carried_bias() computes the road bias from crossing angle and piece length (NOTES.md 2026-09-08) | bands on a straight approach to an underpass | depth key = max z/2 + bias; validator: report the traffic-occlusion zone of a strongly biased piece |

## Phases

### Phase 0 - the library (rdtrack/)  [2026-09-06/07: dsk.py round-trips stock, parts.json written, pieces.py recognises stock chains]
Deliverable: a Python package that reads and writes every DSK structure above,
proven by a **byte-identical round trip of both stock worlds**, plus a parts
library generated from the object ROM (`parts.json`: entry/exit poses, hands,
lane count, elevation profile, catalogue radius, class = road/bridge/deck/
scenery/gate).  Resolves R5.  Consolidates patch_track/patch_segments/
patch_route/patch_awards/mkseg/layout/world into one namespace with tests.

### Phase 1 - the round trip  [raw level done 2026-09-07: fixed layout byte-identical, relocated layout pixel-identical in MAME attract mode]
Deliverable: `decompile` stock world A into a track document; `compile` it
back; the result drives identically with stock drones on it.  Anything that
does not round-trip is a field we do not understand yet.  Resolves R1-R3 as
side effects and starts R4 (drone table located and decoded, budget measured).
This is the highest-information step and the one to start with.

### Phase 2 - the first custom track  [DONE 2026-09-08; underpass crossing DONE 2026-09-08 (R8); one world / all slots DONE 2026-09-09; scenery DONE 2026-09-09 (rdtrack/scenery.py, objects.json, designs/figure8_scenery.json); drones DONE 2026-09-09 (rdtrack/drones.py: synthesised laps, kind 3 and the ghost slot open)]
Deliverable: a hand-written document (an oval with one banked turn and a
bridge, say) compiled from blank, all three slots pointing at it, driven in
MAME and on hardware.  Proves whole-world replacement, R1's answers, and the
validator's budgets against a real build.  Includes the first recorded drone.

### Phase 2b - compact hardware with the Panorama's Stock Car track  [DONE 2026-09-11: rdtrack/stockcar.py, docs_stockcar.md; runs in MAME with traffic; awaiting a human lap and hardware]

### Phase 3 - the editor  [FIRST PASS DONE 2026-09-19: rdtrack/editor.py + editor.html - palette, snap chain, plan view, closure residual per joint, validator panel, route tool, scenery tool (drag on the plan), drone settings + lap recording, save/load designs, Build set, Drive in MAME]
Local web app served by Python:
* palette of parts from `parts.json`; snap-chain placement; hand flip; closure
  solver with the residual shown per joint;
* scenery placement on a grid, elevation-aware (bridges, cuttings) - the format exists (scenery.py: track-relative poses, kits, auto signs, road-overlap warning, objects.json palette); the UI drags it;
* route/gate tool: sections in order, gate markers, awards; start pose;
* drone tool: record (export -> drive in MAME -> import log) or synthesise;
* validator panel: capacity budgets, hand-off slack, ownership ranges on relief
  pieces, joint kinks, mirrored matrices, same-level overlaps, polygon-load
  estimate per viewpoint - every check that a real drive taught us;
* export: document (the patch), staged MAME set, two 27C512 images; import a
  stock world as the starting point.

### Phase 4 - import real courses
Generalise findloop's search into a fitter: given a centreline with elevation
(VIR's, or one extracted from another game's mesh), choose a chain of stock
pieces minimising lateral/heading/elevation error under the engine's
constraints, then hand the result to the editor as a document.  Same closure
solver, same validator.

### Phase 5 - the renderer
Separate project sharing the document and the extracted meshes.  Inputs: the
side-pod serial stream (position/heading today) and later dashboard data once
it is found in the 68010 and added to the stream on modified hardware.
RealityKit/Vision Pro as a target; higher-detail replacement objects keyed by
object index so they land where the originals do.

## Next concrete steps (Phase 0/1, first sessions)

1. Measure every road piece from the object ROM by tool; fix C4512/C4532;
   write `parts.json` (R5).
2. Walk stock world A's placements, cells, segments and routes into a
   document; recompile; diff against stock byte-for-byte, then drive it.
3. Find the DSP32C table capacity and the cell-grid bounds (R2, R3).
4. Tap the mover block for one drone; locate its path table (R4).
5. Watch attract mode with taps on the route walker and start segment (R1).
