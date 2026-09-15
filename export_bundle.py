#!/usr/bin/env python3
"""Export one Race Drivin' Panorama track as a world bundle for the open renderer.

    python3 export_bundle.py racedrivpan.zip racedriv.zip -o panorama_bundle

Writes world.json: units, every track's placements (object, 3x3 orientation in
1.14 fixed point, position), every object model that decodes (vertices,
faces as [attribute word, normal index, v0, v1, ...] (colour = attr & 0xFF, type = attr >> 12: F normal, 1 fill-to-bottom; the normal index is the face id minus the vertex count minus one), catalogue radius/LOD/cull), the object names,
and the palette banks from rd_palette.bin.  Nothing but your own dumps goes in.
"""
import argparse, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base64
import mesh, codec
from rdtrack import dsk, stockcar

POD_MAIN = [("088-%d.bin" % (2002 + 2*k), "088-%d.bin" % (2001 + 2*k)) for k in range(8)]   # the side pod's 68010 program
POD_TRACK_TABLE, POD_TRACK_STRIDE = 0xA0080, 0xA4     # per-track records in the pod ROM; the palette pointer sits at +0
POD_ASSET_TABLE = 0x060000                              # the pod's 70 packed bitmaps
HORIZON_ASSET = {3: 68, 0: 68, 1: 68, 2: 68}            # sheet per track (68 confirmed for Stock Car; others unverified)
# the horizon sheet as the pod draws it (measured on the MAME pod, 2026-09-15): seven 512-px strips of the
# sheet, each CYCLIC (it wraps) and scrolled at ~9.96 px per degree of heading from its own origin; each is
# drawn only while the heading is inside its sector, at its own view row (car level; pitch moves them).
# The four mountain strips cover about 150..15 degrees through north, the three tree strips the rest.
# Each mountain band's first sheet row carries a 12-px-per-band index marker at its left; the pod never shows it.
HORIZON_ORDER = [5, 4, 2, 1, 0, 3, 6]   # panorama strip i -> sheet record (from the pod's descriptor table, Stock Car)
HORIZON_SEGMENTS = [{"rows": [145, 191], "row": 48, "origin": 316.8, "sector": [295, 15]},
                    {"rows": [97, 143],  "row": 48, "origin": 160.7, "sector": [147, 235]},
                    {"rows": [49, 95],   "row": 53, "origin": 212.0, "sector": [192, 292]},
                    {"rows": [1, 47],    "row": 48, "origin": 261.8, "sector": [262, 348]},
                    {"rows": [228, 245], "row": 77, "origin": 12.6,  "sector": [355, 75]},
                    {"rows": [210, 227], "row": 77, "origin": 62.8,  "sector": [45, 125]},
                    {"rows": [192, 209], "row": 77, "origin": 114.2, "sector": [98, 185]}]



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
                           "faces": [[r["attr"], r["id"] - len(m["verts"]) - 1] + r["idx"] for r in m["records"]],
                           "normals": [list(nv) for nv in m["normals"]]}
        if lo:
            objects[str(i)]["far"] = {"verts": [list(v) for v in lo["verts"]], "faces": [[r["attr"], r["id"] - len(lo["verts"]) - 1] + r["idx"] for r in lo["records"]], "normals": [list(nv) for nv in lo["normals"]]}
    # the pod's own per-track palette (bank 0) and horizon sheet, straight from the pod program ROM
    pod = bytes(stockcar.pairs(blobs, POD_MAIN))
    palettes, horizons = {}, {}
    for t in tracks:
        ptr = struct.unpack_from(">I", pod, POD_TRACK_TABLE + int(t)*POD_TRACK_STRIDE)[0]
        palettes[t] = [[pod[ptr + k*3], pod[ptr + k*3 + 1], pod[ptr + k*3 + 2]] for k in range(256)]
        entry = HORIZON_ASSET.get(int(t))
        if entry is not None:
            ap = struct.unpack_from(">I", pod, POD_ASSET_TABLE + entry*4)[0]
            pix, _end = codec.unpack(pod, ap, limit=512*248)
            # The sheet is a linear stream of seven records: a 12-pixel (6-word) descriptor {height, 512, ...} then
            # height x 512 pixels.  The pod's GSP draws them as a 3584-px panorama in the order of the descriptor
            # pointer table its 68010 sends (HORIZON_ORDER, record indices); see NOTES.md "How the pod really draws the horizon".
            recs, off = [], 0
            while off + 12 <= len(pix) and len(recs) < 7:
                h = pix[off]; w = pix[off+2] | (pix[off+3] << 8)
                if h == 0 or w != 512: break
                recs.append({"offset": off + 12, "height": h}); off += 12 + h*512
            strips = [recs[k] for k in HORIZON_ORDER] if len(recs) == 7 else []
            horizons[t] = {"width": 512, "rows": len(pix)//512, "data": base64.b64encode(bytes(pix)).decode(), "segments": HORIZON_SEGMENTS, "px_per_degree": 512/(360/7), "pitch_rows": 340, "strips": strips}
    pal = open(a.palette, "rb").read() if os.path.exists(a.palette) else b""
    banks = [[[pal[(b*256+k)*3], pal[(b*256+k)*3+1], pal[(b*256+k)*3+2]] for k in range(256)] for b in range(len(pal)//768)]
    for t in tracks:
        tracks[t]["palette"] = palettes[t]
        if t in horizons: tracks[t]["horizon"] = horizons[t]
    bundle = {"format": "rdp-world-6", "units_per_foot": 40, "unit_mm": 7.62,
              "tracks": tracks, "objects": objects, "palette": banks}
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "world.json")
    json.dump(bundle, open(path, "w"), separators=(",", ":"))
    print("wrote %s: tracks %s, %d objects decoded (%d of the placed ones missing), %d palette banks, %.1f MB" % (
        path, {k: len(v["placements"]) for k, v in tracks.items()}, len(objects), len([o for o in used if str(o) not in objects]), len(banks), os.path.getsize(path)/1e6))


if __name__ == "__main__":
    main()
