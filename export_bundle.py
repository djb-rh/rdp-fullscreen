#!/usr/bin/env python3
"""Export one Race Drivin' Panorama track as a world bundle for the open renderer.

    python3 export_bundle.py racedrivpan.zip racedriv.zip -o panorama_bundle

Writes world.json: units, every track's placements (object, 3x3 orientation in
1.14 fixed point, position), every object model that decodes (vertices,
faces as [attribute word, v0, v1, ...] (colour = attr & 0xFF, type = attr >> 12: F normal, 1 fill-to-bottom), catalogue radius/LOD/cull), the object names,
and the palette banks from rd_palette.bin.  Nothing but your own dumps goes in.
"""
import argparse, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh
from rdtrack import dsk, stockcar

CAT = 18


def catalogue(obj, i):
    r = i * CAT
    return {"radius": struct.unpack_from(">H", obj, r)[0], "lod": struct.unpack_from(">I", obj, r + 2)[0],
            "cull": struct.unpack_from(">I", obj, r + 6)[0], "hi": struct.unpack_from(">I", obj, r + 10)[0],
            "lo": struct.unpack_from(">I", obj, r + 14)[0]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="racedrivpan.zip (and racedriv.zip for the shared files)")
    ap.add_argument("--tracks", default="0,1,2,3", help="track record indexes to export (default all four)")
    ap.add_argument("-o", "--out", default="bundle")
    ap.add_argument("--palette", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "rd_palette.bin"))
    a = ap.parse_args()
    blobs = stockcar.load_sources(a.sources)
    pmain = stockcar.pairs(blobs, stockcar.PAN_MAIN)
    pobj = bytes(stockcar.pairs(blobs, stockcar.PAN_OBJ))
    pan = stockcar.pairs(blobs, [stockcar.PAN_DSK])
    ptab, pn = stockcar.pan_object_table(pmain)
    names = stockcar.object_names(pmain, ptab, pn)
    dsk.SIZE = len(pan)
    tracks = {}
    used = set()
    for t in [int(x) for x in a.tracks.split(",")]:
        rec = dsk.track_record(pan, t)
        w = dsk.world(pan, rec["descriptor"])
        N = dsk.names(pan, rec["names"])
        tracks[str(t)] = {"names": [e["name"] for e in N["entries"]],
                          "placements": [{"o": p["obj"], "m": p["m"], "p": [p["x"], p["y"], p["z"]], "bias": p["bias"], "flags": p["flags"]} for p in w["placements"]]}
        used |= {p["obj"] for p in w["placements"]}
    objects = {}
    for i in range(pn):
        c = catalogue(pobj, i)
        if not (0 < c["hi"] < len(pobj)):
            continue
        try:
            m = mesh.read(pobj, c["hi"])
        except Exception:
            continue
        lo = None
        if c["lo"] != c["hi"] and 0 < c["lo"] < len(pobj):
            try:
                lo = mesh.read(pobj, c["lo"])
            except Exception:
                lo = None
        objects[str(i)] = {"name": names[i], "radius": c["radius"], "lod": c["lod"], "cull": c["cull"],
                           "verts": [list(v) for v in m["verts"]],
                           "faces": [[r["attr"]] + r["idx"] for r in m["records"]],
                           "normals": [list(nv) for nv in m["normals"]]}
        if lo:
            objects[str(i)]["far"] = {"verts": [list(v) for v in lo["verts"]], "faces": [[r["attr"]] + r["idx"] for r in lo["records"]]}
    pal = open(a.palette, "rb").read() if os.path.exists(a.palette) else b""
    banks = [[[pal[(b*256+k)*3], pal[(b*256+k)*3+1], pal[(b*256+k)*3+2]] for k in range(256)] for b in range(len(pal)//768)]
    bundle = {"format": "rdp-world-4", "units_per_foot": 40, "unit_mm": 7.62,
              "tracks": tracks, "objects": objects, "palette": banks}
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "world.json")
    json.dump(bundle, open(path, "w"), separators=(",", ":"))
    print("wrote %s: tracks %s, %d objects decoded (%d of the placed ones missing), %d palette banks, %.1f MB" % (
        path, {k: len(v["placements"]) for k, v in tracks.items()}, len(objects), len([o for o in used if str(o) not in objects]), len(banks), os.path.getsize(path)/1e6))


if __name__ == "__main__":
    main()
