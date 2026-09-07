# experiments

One-shot tools and A/B probes from designing the east loop, kept for the record.
Nothing here is needed to apply the patch (that is `../apply_patch.py`).

* `findloop.py`, `finalize_loop.py`, `refit.py`, `refit_tail*.py` - the search
  that produced `../loop_final.json` (fit a chain of stock pieces between the two
  open junctions, then close the exit onto the checkpoint straight).
* `mkdelset.py` - built `../delete_segments.json` (nearest-piece assignment).
* `render_loop.py`, `newloop.py`, `newworld.py` - top-down renders / OBJ exports.
* `ab_*.py` - build variant ROM sets under /tmp/abx for A/B tests
  (`ab_start.py SEG` starts the car on a chosen segment).
* `vir_*.py`, `virdsk.py`, `virrom.py` - the Virginia-map experiment (see ../VIR.md).
* `lua/` - MAME Lua probes and taps used to reverse the DSP32C / ADSP behaviour.
  `../rd.lua` is the one that is still a tool.

They read `loop_final.json` etc. from the repo root and import the modules
there, so run them from the root:

    PYTHONPATH=. python3 experiments/refit.py
    mame racedriv -rompath ... -autoboot_script experiments/lua/probe_placements.lua
