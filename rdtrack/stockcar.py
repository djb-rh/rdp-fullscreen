#!/usr/bin/env python3
"""Race Drivin' compact + the Panorama's Stock Car track.

    python3 -m rdtrack.stockcar RACEDRIV.zip RACEDRIVPAN.zip -o OUTDIR [--slapstic free|115|117]

RACEDRIV.zip is a MAME set that carries the compact ROMs (a merged racedriv.zip
with a racedrivc/ folder inside, or a split racedrivc.zip - pass the parent zip
too).  RACEDRIVPAN.zip is the Panorama set.  Nothing but the user's own dumps
goes in; the output is a compact set (racedrivc file names) whose Autocross
slot is the Panorama's Stock Car track: its world, segment table, route,
names, awards, champion, drone traffic and the seven stock-car models.

What the tool does (NOTES.md 2026-09-11):
  * DSK: the compact image with track 1's world/segments/route/names replaced
    by Stock Car's (object indices remapped), its drone tables pointed at the
    Panorama's path slots, the champion and the per-track tables copied.
  * main ROM: the Stock Car drone paths (8 slots) copied to the unreferenced
    region at 0x0C5980, "AUTOCROSS" -> "STOCK CAR", 22 object-table entries
    rewritten over objects the remaining tracks never use, plus the slapstic
    variant: 'free' = the slapfree core/self-test/Y2K edits relocated by
    signature; '115'/'117' = stock arrangement (the program probes both chips
    at boot, so those two are the same bytes) with the Y2K fix.
  * object ROM: the 22 victims' catalogue records become the stock cars', the
    third EPROM pair is the Panorama's (models are position-dependent and the
    Panorama already keeps these at 0x40000+).
  * every touched EPROM gets its byte-sum signature restored (low byte of the
    sum = part-number suffix), as the self-test expects.
"""
import argparse, hashlib, os, re, struct, sys, zipfile
from . import dsk, document, build
from . import compile as comp

COMPACT_MAIN = [("136078-5002.200r", "136078-5001.210r"), ("136078-5004.200s", "136078-5003.210s"),
                ("136078-5006.200t", "136078-5005.210t"), ("136078-4008.200u", "136078-4007.210u"),
                ("136078-4010.200v", "136078-4009.210v"), ("136077-1012.200w", "136077-1011.210w"),
                ("136077-1014.200x", "136077-1013.210x"), ("136078-4016.200y", "136078-4015.210y")]
COMPACT_OBJ = [("136077-1021.10h", "136077-1023.10k"), ("136077-1022.10j", "136077-1024.10l")]
COMPACT_DSK = ("136078-1030.30e", "136078-1031.10e")
COMPACT_FILES = ["136052-1123.65a", "136052-1124.55a", "136052-1126.30a", "136052-3125.45a", "136077-1017.45c",
                 "136077-1032.70n", "136077-1033.45n", "racedrivc.200e", "racedrivc.210e"]
PAN_MAIN = [("088-%d.bin" % (1002 + 2*k), "088-%d.bin" % (1001 + 2*k)) for k in range(8)]
PAN_OBJ = [("088-1018.bin", "088-1017.bin"), ("088-1020.bin", "088-1019.bin"), ("088-1022.bin", "088-1021.bin")]
PAN_DSK = ("rdpd1026.bin", "rdpd1025.bin")
OBJ3 = ("136088-1022.9h", "136088-1021.9k")         # the Panorama's third object pair, its part numbers and ADSP II sockets

STOCKCAR_TRACK = 3          # in the Panorama DSK
SLOT = 1                    # the compact slot it replaces (autocross)
PATHS_AT, NPATH_SLOTS, SLOT_SZ = 0x0C5980, 8, 0x2598
STRINGS_AT = PATHS_AT + NPATH_SLOTS * SLOT_SZ           # 0x0D8640: object-name strings for the new entries
OBJTAB, OBJTAB_N, ENTRY = 0x4362A, 158, 28              # compact object-name table (found by the DOTLINE pointer)
CAT = 18
# objects no remaining track places, no list names, no code copies of their names, no partner of a used car
VICTIMS = "BALE CONEB CONER CONEW CONEY VANL C45R140 C3060 MHSTRT WEED1 WEED2 FLOWER1 FLOWER2 FLOWER3 TREEBLIT BROCK WEED FLOWER CRSHSQ FLOAT65 FLOAT150 NEW150M".split()
SUFFIX = lambda name: int(re.search(r"-(\d+)\.", name).group(1)[-2:], 16)   # 136078-5002.200r -> 0x02


# ------------------------------------------------------------------ inputs ---
def load_sources(paths):
    blobs = {}
    for p in paths:
        if os.path.isdir(p):
            for root, _d, files in os.walk(p):
                for n in files:
                    blobs[n] = open(os.path.join(root, n), "rb").read()
        else:
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        blobs[os.path.basename(info.filename)] = z.read(info)
    return blobs


def pairs(blobs, plist):
    out = bytearray()
    for e, o in plist:
        a, b = blobs[e], blobs[o]
        buf = bytearray(len(a)*2); buf[0::2] = a; buf[1::2] = b; out += buf
    return out


def unpair(img, plist, size=0x10000):
    out = {}
    for k, (e, o) in enumerate(plist):
        chunk = img[k*size*2:(k+1)*size*2]
        out[e], out[o] = bytes(chunk[0::2]), bytes(chunk[1::2])
    return out


def fix_sum(data, want, pad):
    """Restore the byte-sum signature by rewriting the byte at file offset `pad`."""
    d = bytearray(data); d[pad] = 0; d[pad] = (want - (sum(d) & 0xFF)) & 0xFF
    return bytes(d)


# ------------------------------------------------------------- the stock car ---
def panorama_track(pan):
    """Stock Car's structures out of the 256 KB Panorama DSK image."""
    old = dsk.SIZE; dsk.SIZE = len(pan)
    try:
        t = dsk.track_record(pan, STOCKCAR_TRACK)
        w = dsk.world(pan, t["descriptor"]); S = dsk.segments(pan, t["segments"])
        R = dsk.route(pan, t["route"][0]); N = dsk.names(pan, t["names"])
        ents = []
        a = dsk.off(dsk.u32(pan, t["at"] + 0x18))
        while True:
            typ = dsk.u16(pan, a + 4)
            ents.append({"name": bytes(pan[dsk.off(dsk.u32(pan, a)):]).split(b"\0")[0].decode(), "type": typ,
                         "x": dsk.s32(pan, a + 6), "y": dsk.s32(pan, a + 10), "z": dsk.s32(pan, a + 14), "w18": dsk.u32(pan, a + 0x12), "heading": dsk.u16(pan, a + 0x16)})
            if typ == 0: break
            a += 24
        t9c = dsk.off(dsk.u32(pan, t["at"] + 0x9C)); ta0 = dsk.off(dsk.u32(pan, t["at"] + 0xA0))
        nslots, slot0, nlist, listp = struct.unpack_from(">HIHI", pan, t9c)
        drones = []
        for i in range(nlist):
            kind, nm, slot, param, fl, wd = struct.unpack_from(">HIHHHH", pan, listp - dsk.BASE68K + 14*i)
            drones.append((kind, bytes(pan[nm - dsk.BASE68K:]).split(b"\0")[0].decode(), slot, param, fl, wd))
        tc = dsk.off(dsk.u32(pan, t9c + 0xC))
        return {"rec": t, "world": w, "segs": S, "route": R, "names": N, "entities": ents,
                "t9c": bytes(pan[t9c:t9c + 18]), "ta0": bytes(pan[ta0:ta0 + 42]), "tc": bytes(pan[tc:tc + 132]),
                "drones": drones, "nslots": nslots, "slot0": slot0,
                "champion": bytes(pan[dsk.off(dsk.u32(pan, t["at"] + 0x90)):][:80]),
                "block80": bytes(pan[t["block80"]:t["block80"] + dsk.BLOCK80])}
    finally:
        dsk.SIZE = old


def object_names(main, tab, n):
    out = []
    for i in range(n):
        p = struct.unpack_from(">I", main, tab + i*ENTRY + 0x14)[0]
        out.append(main[p:main.index(b"\0", p)].decode("ascii", "replace"))
    return out


def pan_object_table(pm):
    s = pm.find(b"DOTLINE\0"); k = pm.find(struct.pack(">I", s)); e = k - 0x14
    def ok(a): return 0x40000 < struct.unpack_from(">I", pm, a + 0x14)[0] < 0x80000
    while ok(e - ENTRY): e -= ENTRY
    n = 0
    while ok(e + n*ENTRY): n += 1
    return e, n


# ----------------------------------------------------------------- building ---
DSK_SIZE = 0x40000          # two 27C010s on the DSK PCB (A047724-01), as the Panorama fits it
DSK_PARTS = [("136078-1030.30e", 0x30), ("136078-1031.10e", 0x31)]


def build_set(blobs, out_dir, slapstic="free", verbose=print):
    # the DSK grows to 256 KB: three worlds of this size do not fit 128 KB
    dsk.SIZE = DSK_SIZE; dsk.CHECKSUM_AT = DSK_SIZE - 2; comp.LIMIT = DSK_SIZE - 2; dsk.PARTS = DSK_PARTS
    # --- images -------------------------------------------------------------------
    cdsk = pairs(blobs, [COMPACT_DSK]); cmain = pairs(blobs, COMPACT_MAIN); cobj = pairs(blobs, COMPACT_OBJ)
    pan = pairs(blobs, [PAN_DSK]); pmain = pairs(blobs, PAN_MAIN); pobj = pairs(blobs, PAN_OBJ)
    sc = panorama_track(pan)
    verbose("Stock Car: %d placements, %d segments, %d route nodes, %d names, %d drones in %d slots" % (
        len(sc["world"]["placements"]), sc["segs"]["header"]["count"], len(sc["route"]), len(sc["names"]["entries"]), len(sc["drones"]), sc["nslots"]))

    # --- objects: which Panorama objects the track needs, and where they go --------------
    ptab, pn = pan_object_table(pmain)
    pnames = object_names(pmain, ptab, pn); cnames = object_names(cmain, OBJTAB, OBJTAB_N)
    needed = sorted({p["obj"] for p in sc["world"]["placements"]} | {pnames.index(d[1]) for d in sc["drones"]})
    for d in sc["drones"]:
        for v in (d[1] + "STOP", "W" + d[1]):
            if v in pnames: needed.append(pnames.index(v))
    needed = sorted(set(needed))
    remap, new = {}, []
    for i in needed:
        nm = pnames[i]
        if nm in cnames and nm != "-1":
            remap[i] = cnames.index(nm)
        else:
            new.append(i)
    if len(new) > len(VICTIMS):
        raise SystemExit("need %d new objects but only %d replaceable entries" % (len(new), len(VICTIMS)))
    victims = [cnames.index(v) for v in VICTIMS]
    for i, v in zip(new, victims):
        remap[i] = v
    verbose("objects: %d carried by name, %d new over %s" % (len(needed) - len(new), len(new), [VICTIMS[k] for k in range(len(new))]))

    # object ROM: victims' catalogue records <- Panorama records; third pair <- Panorama's
    obj = bytearray(cobj) + bytearray(pobj[0x40000:0x60000])
    for i, v in zip(new, victims):
        rec = pobj[i*CAT:(i + 1)*CAT]
        hi, lo = struct.unpack_from(">II", rec, 10)
        if not (0x40000 <= hi < 0x60000 and 0x40000 <= lo < 0x60000):
            raise SystemExit("object %s keeps a model outside the third pair (0x%X/0x%X)" % (pnames[i], hi, lo))
        obj[v*CAT:(v + 1)*CAT] = rec
    # dead bytes for the sum fix: the first victim's old model data
    dead_obj = struct.unpack_from(">I", cobj, victims[0]*CAT + 10)[0]

    # main ROM: object-name entries, drone paths, strings, selector text
    main = bytearray(cmain)
    main[PATHS_AT:PATHS_AT + NPATH_SLOTS*SLOT_SZ] = pmain[PATHS_AT:PATHS_AT + NPATH_SLOTS*SLOT_SZ]
    sp = STRINGS_AT
    for i, v in zip(new, victims):
        ent = bytearray(pmain[ptab + i*ENTRY:ptab + (i + 1)*ENTRY])
        nm = pnames[i]
        if nm == "-1":
            struct.pack_into(">I", ent, 0x14, struct.unpack_from(">I", cmain, OBJTAB + 156*ENTRY + 0x14)[0])
        else:
            s = nm.encode() + b"\0"; main[sp:sp + len(s)] = s; struct.pack_into(">I", ent, 0x14, sp); sp += len(s) + (len(s) & 1)
        main[OBJTAB + v*ENTRY:OBJTAB + (v + 1)*ENTRY] = ent
    # the victims' old name strings are dead: a pad byte for the 200t/210t sum fix
    dead_name = struct.unpack_from(">I", cmain, OBJTAB + victims[0]*ENTRY + 0x14)[0]
    n_ren = 0
    for m in list(re.finditer(rb"AUTOCROSS", bytes(main))):
        if main[m.start() - 3:m.start()] == b"an ":
            continue
        main[m.start():m.end()] = b"STOCK CAR"; n_ren += 1
    # the program keeps three autocross-only rules behind "track index == 1" (the cone
    # course's lap recording and gate handling); Stock Car in that slot is a race like
    # the speed track, so those tests are made to look for a slot that does not exist
    gates = [mt.start() for mt in re.finditer(rb"\x0c\x79\x00\x01\x00\x90\x17\x56", bytes(main))]
    for g in gates:
        main[g + 3] = 7
    if len(gates) >= 2:
        main[gates[1] + 2] = 1                        # cmpi.w #$0107: the immediate's bytes double as sum pads below
    n_gate = len(gates)
    # ...and the drone placement at the green light hides every drone when the track
    # variable is 1 or 2 (cmpi.w #1,(A4) / #2,(A4) with A4 = the track variable): on
    # those slots the only drone was a ghost.  Slot 1 now races, so the #1 test goes.
    hide = [mt.start() for mt in re.finditer(rb"\x0c\x54\x00\x01\x67.\x0c\x54\x00\x02", bytes(main))]
    if len(hide) != 1:
        raise SystemExit("drone-hide gate matched %d times" % len(hide))
    main[hide[0] + 3] = 7; n_gate += 1
    verbose("main ROM: %d drone slots at 0x%05X, %d object entries, %d 'AUTOCROSS' -> 'STOCK CAR', %d autocross-rule gates disabled" % (NPATH_SLOTS, PATHS_AT, len(new), n_ren, n_gate))

    # --- DSK: the document with track 1 replaced ----------------------------------------
    doc = document.decompile(cdsk)
    t = doc["tracks"][SLOT]
    old_world, old_segs, old_routes, old_names = t["world"], t["segments"], t["routes"], t["names"]
    w = sc["world"]
    doc["worlds"]["S"] = {"desc_words": [w["descriptor"]["stride"], w["descriptor"]["w6"], w["descriptor"]["w8"]],
                          "tail": (b"\xff\xff" + bytes(48)).hex(),
                          "placements": [dict(p, obj=remap[p["obj"]], rt=p["rt"].hex()) for p in w["placements"]],
                          "cells": [{"min": c["min"], "max": c["max"], "recs": c["recs"]} for c in w["cells"]]}
    h = sc["segs"]["header"]
    doc["segments"]["S"] = {"bias": h["bias"], "start": h["start"], "header_raw": h["raw"].hex(), "segs": sc["segs"]["segs"]}
    ats = [n["at"] for n in sc["route"]]
    # route node flags bits 8-11 carry the slot the route belongs to: the program reads the start
    # node's nibble as the track index (0x030038), so Stock Car's 3 becomes the slot it lives in
    nodes = [dict({k: v for k, v in n.items() if k not in ("at", "next", "prev")},
                  flags=(n["flags"] & ~0x0F00) | (SLOT << 8),
                  prev=(ats.index(n["prev"]) if n["prev"] in ats and n["prev"] != n["at"] else "self")) for n in sc["route"]]
    # the start node's prev is not the mirror of a next: stock hangs a copy of the finish node
    # there (value = the finish section) and the race start takes its section from it
    # (0x02FD04: section = start.prev.value); without it the race resets as it begins
    head = sc["route"][0]
    if head["prev"] is not None and head["prev"] not in ats:
        a = head["prev"]
        nodes.append({"value": dsk.u16(pan, a), "value2": dsk.u16(pan, a + 2), "w4": dsk.u32(pan, a + 4),
                      "flags": (dsk.u16(pan, a + 8) & ~0x0F00) | (SLOT << 8), "wE": dsk.u32(pan, a + 0xE), "w16": dsk.u32(pan, a + 0x16),
                      "next": 0, "prev": "self"})
        nodes[0]["prev"] = len(nodes) - 1
        nodes[-2]["next"] = 0                                    # the chain still closes on the head
    doc["routes"]["RS"] = {"nodes": nodes}
    doc["names"]["NS"] = {"entries": [{"name": e["name"], "v": e["v"]} for e in sc["names"]["entries"]]}
    front = bytearray(bytes.fromhex(doc["front"]))
    strpos = {"STRTPOST": 0x113C, "CHKPT": 0x1146, "": 0x1152}
    t.update({"world": "S", "segments": "S", "routes": ["RS", "RS"], "names": "NS",
              "entities": [[dict(e, name_at=strpos[e["name"]]) for e in sc["entities"]]] * 2, "entities_at": [None, None],
              "awards": sc["rec"]["awards"], "block80": sc["block80"].hex()})
    keep = set(os.environ.get("STOCKCAR_KEEP", "").split(","))
    rec = bytearray(bytes.fromhex(t["record"])); prec = sc["rec"]["raw"]; rec0 = bytes.fromhex(doc["tracks"][0]["record"])
    if "b80" in keep: t["block80"] = bytes(cdsk[dsk.off(dsk.u32(cdsk, SLOT*dsk.TRACK_REC + 0x80)):][:dsk.BLOCK80]).hex()
    if "awards" in keep: t["awards"] = document.decompile(cdsk)["tracks"][SLOT]["awards"]
    rec[0x20:0x40] = rec0[0x20:0x40]                    # the speed track's tuning words, compact values
    # +0x84 is the track TYPE the select dial looks for (1F1F0C0C = the autocross position); it
    # stays the slot's own so the dial still finds the record.  +0x94 follows Stock Car's.
    if "w94" not in keep: rec[0x94:0x98] = prec[0x94:0x98]
    if "w20" in keep: rec[0x20:0x40] = bytes.fromhex(t["record"])[0x20:0x40]
    rec[0x8C:0x90] = struct.pack(">I", PATHS_AT)
    if "w98" not in keep: struct.pack_into(">I", rec, 0x98, struct.unpack_from(">I", rec0, 0x98)[0])   # map-screen labels: the speed track's
    t["record"] = rec.hex()
    for k in (old_world,):
        if not any(x["world"] == k for x in doc["tracks"] if x is not t): doc["worlds"].pop(k, None)
    if not any(x["segments"] == old_segs for x in doc["tracks"] if x is not t): doc["segments"].pop(old_segs, None)
    for r in old_routes:
        if not any(r in x["routes"] for x in doc["tracks"] if x is not t): doc["routes"].pop(r, None)
    if not any(x["names"] == old_names for x in doc["tracks"] if x is not t): doc["names"].pop(old_names, None)
    img, L = comp.compile_doc(doc, fixed=False)
    top = max(b for a, b in L.used)
    # front-region tables that the document carries verbatim
    a9c = dsk.off(dsk.u32(img, SLOT*dsk.TRACK_REC + 0x9C)); aa0 = dsk.off(dsk.u32(img, SLOT*dsk.TRACK_REC + 0xA0))
    listp = dsk.u32(img, a9c + 8); tcp = dsk.u32(img, a9c + 0xC)
    struct.pack_into(">HIHI", img, a9c, sc["nslots"], PATHS_AT, len(sc["drones"]), listp)
    if "t9c" not in keep: img[a9c + 0x10:a9c + 0x12] = sc["t9c"][0x10:0x12]
    if "tc" not in keep: img[dsk.off(tcp):dsk.off(tcp) + 132] = sc["tc"]
    ta0 = bytearray(img[aa0:aa0 + 42] if "ta0" in keep else sc["ta0"]); struct.pack_into(">I", ta0, 2, PATHS_AT); struct.pack_into(">I", ta0, 8, listp)
    struct.pack_into(">I", ta0, 0x20, PATHS_AT + sc["nslots"]*SLOT_SZ); ta0[0x26:0x2A] = img[aa0 + 0x26:aa0 + 0x2A]
    img[aa0:aa0 + 42] = ta0
    cp = dsk.off(dsk.u32(img, SLOT*dsk.TRACK_REC + 0x90))
    if "champ" not in keep: img[cp:cp + 80] = sc["champion"]
    # drone list + its car-name strings in the free area above the compiled data
    sp = (top + 1) & ~1
    la = dsk.off(listp)
    for i, (kind, nm, slot, param, fl, wd) in enumerate(sc["drones"]):
        s = nm.encode() + b"\0"; img[sp:sp + len(s)] = s
        struct.pack_into(">HIHHHH", img, la + 14*i, kind, dsk.BASE68K + sp, slot, param, fl, wd); sp += len(s) + (len(s) & 1)
    if sp > comp.LIMIT:
        raise SystemExit("DSK overflow")
    verbose("DSK: data top 0x%05X, %d bytes free" % (sp, comp.LIMIT - sp))

    # --- slapstic / Y2K variant ------------------------------------------------------
    edits = relocated_edits(cmain)
    groups = {"y2k"} | ({"core", "selftest"} if slapstic == "free" else set())
    applied = []
    for cpu, blob, grp, what in edits:
        if grp in groups:
            main[cpu:cpu + len(blob)] = blob; applied.append(what)
    verbose("program edits (%s): %d" % (slapstic, len(applied)))

    # --- files -------------------------------------------------------------------------
    import shutil
    shutil.rmtree(out_dir, ignore_errors=True); os.makedirs(out_dir)
    files = {}
    files.update(unpair(main, COMPACT_MAIN)); files.update(unpair(obj, COMPACT_OBJ + [OBJ3]))
    for n in COMPACT_FILES:
        files[n] = blobs[n]
    dsk.split(img, out_dir)
    # sum signatures: every modified program pair gets a dead byte (an alignment pad
    # after an odd-length string, or a victim's old name), the object pairs their dead model
    pads = {}
    for k, (e, o) in enumerate(COMPACT_MAIN):
        lo, hi = k*0x20000, (k + 1)*0x20000
        if bytes(main[lo:hi]) == bytes(cmain[lo:hi]):
            continue
        if k == 0:
            pe, po = 0x1FFFE, 0x1FFFF                                # the zero pad at the end of the R pair (as slapfree)
        elif k == 1:
            # the immediates of the disabled gates: any high byte with low byte 7, or high byte 1 with any low byte
            pe, po = gates[0] + 2, gates[1] + 3
        elif k == 2:
            pe, po = dead_name, dead_name + 1                        # a victim's dead name string
        elif k == 6:
            pe = po = PATHS_AT + 5*SLOT_SZ + 0x2400                  # slack after slot 5's last keyframe
        else:
            raise SystemExit("unexpected change in pair %d" % k)
        pads[e], pads[o] = (pe - lo)//2, (po - lo)//2
    for k, (e, o) in enumerate(COMPACT_OBJ):
        pads[e] = pads[o] = (dead_obj - k*0x20000)//2
    for n in list(files):
        if n in pads and pads[n] is not None:
            files[n] = fix_sum(files[n], SUFFIX(n) if "-" in n else 0, pads[n])
    for n, data in files.items():
        open(os.path.join(out_dir, n), "wb").write(data)
    open(os.path.join(out_dir, "main_image.bin"), "wb").write(bytes(main))
    open(os.path.join(out_dir, "obj_image.bin"), "wb").write(bytes(obj))
    return files, remap


def relocated_edits(cmain):
    """slapfree's cockpit edits found in the compact program by the bytes around each site."""
    from rdtrack import stockcar_edits as E   # (kept in a sibling module so the cockpit reference bytes stay in one place)
    return E.locate(cmain)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="racedriv.zip (merged, or split + parent) and racedrivpan.zip")
    ap.add_argument("-o", "--out", default="racedrivc_stockcar")
    ap.add_argument("--slapstic", choices=["free", "115", "117"], default="free",
                    help="free: jumper-modified board without the chip; 115/117: the chip stays (same bytes - the program detects which)")
    args = ap.parse_args(argv)
    blobs = load_sources(args.sources)
    missing = [n for n in [x for p in COMPACT_MAIN + COMPACT_OBJ + [COMPACT_DSK] + PAN_MAIN + PAN_OBJ + [PAN_DSK] for x in p] + COMPACT_FILES if n not in blobs]
    if missing:
        sys.exit("missing ROMs: %s" % ", ".join(missing))
    out = os.path.join(args.out, "racedrivc")
    build_set(blobs, out, args.slapstic)
    print("wrote", out)


if __name__ == "__main__":
    main()
