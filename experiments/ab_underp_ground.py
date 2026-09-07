#!/usr/bin/env python3
"""A/B experiment: make the UNDERP model's ground faces invisible.

The six colour-53 faces lying flat at y=0 (the ground either side of the
cutting, 6401 x 19201) are the only large flat surfaces at road height near the
crossing.  If the road either side of the bridge renders cleanly with them gone,
the sort-position theory holds and the loop needs re-fitting so the carrying
road piece is centred on the crossing.  If it still flashes, the theory is wrong.

Each face's index list is rewritten in place so every vertex index equals the
first - a zero-area polygon - which changes no pointers, no counts and no
shared vertices.  Both LODs are done.  Object ROM pair 10h/10k only.

Reads your own ROMs (rd_objrom.bin is the linear image of them); writes
roms_loop/racedriv/136077-2021.10h and 136077-2023.10k with Atari's byte-sum.
NOTE: build_all.py re-stages the STOCK object ROMs, which undoes this.  Re-run
this script after any build_all.py while the experiment is on.
"""
import os, struct, world, mesh

obj = bytearray(open("rd_objrom.bin", "rb").read())
w = world.World(); o = {w.name(i): i for i in range(390)}["UNDERP"]
COLOUR = 53
u = lambda a: struct.unpack_from(">H", obj, a)[0]

touched = 0
for lod in ("hi", "lo"):
    base = w.catalogue(o)[lod]
    m = mesh.read(bytes(obj), base)
    hi = (base // 2) & 0xFFFF0000
    n0 = 3 + len(m["verts"]) * 3 + len(m["normals"]) * 3
    k, pairs = n0 + 1, []                 # walk the pair block IN ORDER: pair i <-> record i
    while True:
        ptr, attr = u(base + 2*k), u(base + 2*k + 2)
        if ptr == 0:
            break
        pairs.append((base + 2*((hi | ptr) - base // 2), attr))
        k += 2
    assert len(pairs) == len(m["records"]), (lod, len(pairs), len(m["records"]))
    for (addr, attr), rec in zip(pairs, m["records"]):
        if (attr & 0xFF) != COLOUR:
            continue
        n = len(rec["idx"])
        first = u(addr + 2)               # addr holds the face id; indices follow
        for i in range(n):
            struct.pack_into(">H", obj, addr + 2 + 2*i, first)
        assert u(addr + 2 + 2*n) == 0xFFFF
        touched += 1
        print("  %s face id %3d at 0x%05X: %d indices -> all %d" % (lod, rec["id"], addr, n, first))
print("degenerated %d colour-%d faces" % (touched, COLOUR))

# verify by re-reading
for lod in ("hi", "lo"):
    m = mesh.read(bytes(obj), w.catalogue(o)[lod])
    bad = [f for f in m["records"] if f["colour"] == COLOUR and len(set(f["idx"])) != 1]
    ok  = [f for f in m["records"] if f["colour"] != COLOUR]
    print("  %s re-read: colour-%d faces all degenerate: %s; other faces intact: %d" % (lod, COLOUR, not bad, len(ok)))

OUT = "roms_loop/racedriv"
for name, suffix, phase, base in (("136077-2021.10h", 0x21, 0, 0), ("136077-2023.10k", 0x23, 1, 0)):
    half = bytearray(obj[base + phase: base + 0x20000: 2])
    pad = len(half) - 1
    while pad > 0 and half[pad] == 0:
        pad -= 1
    pad += 1
    assert pad < len(half), "no padding byte for the checksum"
    half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
    open(os.path.join(OUT, name), "wb").write(bytes(half))
    print("  %-18s byte-sum low 0x%02X (want 0x%02X) %s" % (name, sum(half) & 0xFF, suffix,
          "OK" if (sum(half) & 0xFF) == suffix else "MISMATCH"))
