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
    A = D.worlds[D.tracks[0]["descriptor"]]
    cnt = collections.defaultdict(collections.Counter)
    for p in A["placements"]:
        cnt[w.name(p["obj"])][(p["bias"], p["flags"])] += 1
    tails = {nm: c.most_common(1)[0][0] for nm, c in cnt.items()}

    design = json.load(open(args.design))
    recs, cells, segs, nodes, pl, samples = worldgen.expand(design, cat, obj_index, tails)
    if len(segs["segs"]) > 720:
        sys.exit("too many segments: %d (DSP32C table holds 727)" % len(segs["segs"]))
    doc = document.decompile(buf)
    doc["worlds"]["A"] = {"desc_words": [28, 112, 112], "cells": cells,
                          "placements": [{k: (v.hex() if isinstance(v, bytes) else v) for k, v in p.items()} for p in recs]}
    doc["segments"]["A"] = segs
    doc["routes"]["R0"] = {"nodes": nodes}
    doc["tracks"][0]["routes"] = ["R0", "R0"]
    img, L = comp.compile_doc(doc, fixed=False)
    top = max(b for a, b in L.used)
    print("%d placements, %d segments (start %d), %d route sections; image top 0x%05X, %d bytes free" % (
        len(recs), len(segs["segs"]), segs["start"], len(nodes), top, comp.LIMIT - top))
    out = build.stage(args.romset, img, args.out)
    open(os.path.join(args.out, "dsk_image.bin"), "wb").write(bytes(img))
    print("staged %s\nrun:  mame racedriv -rompath %s   (choose the original track)" % (out, os.path.abspath(args.out)))


if __name__ == "__main__":
    main()
