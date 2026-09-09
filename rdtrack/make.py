#!/usr/bin/env python3
"""Build a playable set from a track design.

    python3 -m rdtrack.make designs/oval.json /path/to/racedriv.zip -o roms_oval

The design replaces world A (track slot 0, "original track" in the menu);
autocross and super stunt stay stock for now.  See worldgen.py for the design
format.  The stock zip is read, never written; the output is a complete loose
MAME set at OUTDIR/racedriv plus the raw image OUTDIR/dsk_image.bin.
"""
import argparse, collections, json, os, sys
from . import dsk, document, worldgen, build
from . import compile as comp


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("design"); ap.add_argument("romset"); ap.add_argument("-o", "--out", default="roms_design")
    args = ap.parse_args(argv)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(here)
    import world as W
    w = W.World(); cat = {i: w.catalogue(i) for i in range(390)}; obj_index = {w.name(i): i for i in range(156)}
    buf = dsk.load(args.romset)
    D = dsk.Dsk(buf)
    # per-object (bias, flags) as stock uses them, world A first, then B and autocross
    cnt = collections.defaultdict(collections.Counter)
    for ti in (0, 2, 1):
        for p in D.worlds[D.tracks[ti]["descriptor"]]["placements"]:
            cnt[w.name(p["obj"])][(p["bias"], p["flags"])] += 1
    tails = {nm: c.most_common(1)[0][0] for nm, c in cnt.items()}
    if not os.path.exists("objects.json"):
        from . import scenery
        scenery.catalogue(w, {"A": D.worlds[D.tracks[0]["descriptor"]], "B": D.worlds[D.tracks[2]["descriptor"]], "AX": D.worlds[D.tracks[1]["descriptor"]]})

    design = json.load(open(args.design))
    recs, cells, segs, nodes, pl, samples, entities = worldgen.expand(design, cat, obj_index, tails)
    if len(segs["segs"]) > 720:
        sys.exit("too many segments: %d (DSP32C table holds 727)" % len(segs["segs"]))
    doc = document.decompile(buf)
    doc["worlds"]["A"] = {"desc_words": [28, 112, 112], "cells": cells,
                          "placements": [{k: (v.hex() if isinstance(v, bytes) else v) for k, v in p.items()} for p in recs]}
    doc["segments"]["A"] = segs
    doc["routes"]["R0"] = {"nodes": nodes}
    # ONE WORLD (PLAN.md): every track slot - original / autocross / super stunt in
    # the menu - runs the design's world with the design's route, so a build owns
    # the whole DSK and stock's worlds B and C are not emitted (their space is
    # free for the one world).  Per-slot leftovers kept from stock: the +0x80
    # blocks, the champion records and the drone path pointers.
    for t in doc["tracks"]:
        t["world"] = "A"; t["segments"] = "A"; t["routes"] = ["R0", "R0"]; t["names"] = doc["tracks"][0]["names"]
        t["awards"] = doc["tracks"][0]["awards"]
        t["entities"] = [entities, entities]; t["entities_at"] = [None, None]
    for k in [k for k in doc["worlds"] if k != "A"]: del doc["worlds"][k]
    for k in [k for k in doc["segments"] if k != "A"]: del doc["segments"][k]
    for k in [k for k in doc["routes"] if k != "R0"]: del doc["routes"][k]
    for k in [k for k in doc["names"] if k != doc["tracks"][0]["names"]]: del doc["names"][k]
    img, L = comp.compile_doc(doc, fixed=False)
    top = max(b for a, b in L.used)
    print("%d placements, %d segments (start %d), %d route sections; image top 0x%05X, %d bytes free" % (
        len(recs), len(segs["segs"]), segs["start"], len(nodes), top, comp.LIMIT - top))
    out = build.stage(args.romset, img, args.out)
    open(os.path.join(args.out, "dsk_image.bin"), "wb").write(bytes(img))
    print("staged %s\nrun:  mame racedriv -rompath %s   (choose the original track)" % (out, os.path.abspath(args.out)))


if __name__ == "__main__":
    main()
