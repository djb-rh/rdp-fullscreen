# rdp-fullscreen: Race Drivin' track tools, editor and research notes

The working repository behind [racedrivin-tools](https://github.com/djb-rh/racedrivin-tools).
Where that repo is the curated, hardware-ready subset, this one holds everything: the track
data library and compiler, the browser track editor, the ROM patchers, the MAME Lua scripts,
and the notes recording how each piece of the game's data was worked out.

**No ROM data is here.**  The `.gitignore` is a whitelist (code, JSON layouts, notes, scripts);
every helper image, dump, disassembly and built set is regenerated from your own ROMs and
stays out of git.

## What is in it

- `rdtrack/` — the track library: read, measure and compile the DSK track data; world
  generation from parts; drones; scenery; the Stock Car and pod-stream patchers (the copies
  in racedrivin-tools are taken from here).
- `rdtrack/editor.py` + `editor.html` — the track editor: `python3 -m rdtrack.editor` serves
  it on http://127.0.0.1:8765.  Parts palette, snap chain, plan view, a validator that runs
  the real compiler on every edit, route and scenery tools, drone settings, lap recording
  through MAME, build, drive, and EPROM export.  Second pass; a set built through it has not
  yet been driven on hardware.
- `designs/` — track designs in the editor's JSON format (oval, figure-8 with underpass, ...).
- `apply_patch.py` and the `patch_*.py` scripts — the original east-loop splice for the
  cockpit's speed track, and the single-purpose patchers it grew from.
- `experiments/` — MAME Lua scripts and write-ups (linked play, the pod stream on Serial B).
- `NOTES.md` — the record of every ROM-format and renderer finding, in date order.
  `PLAN.md` is the roadmap, `WORLD.md`, `ARTWORK.md` and `VIR.md` are topic notes.  Read
  NOTES.md before touching a ROM format; the hard-won facts are there.

The `vir_*` files are a hand-fitted attempt at a real circuit (Virginia International Raceway).
It is parked: the right shape is an import path in the editor, not a one-off.

## Requirements

Python 3.8+ for the tools; a MAME built from source with the patches in `experiments/` and
racedrivin-tools for the driving and link tests.  Headless MAME runs must use
`-video none -sound none` or they take over the screen.

## License

GPL-3.0.
