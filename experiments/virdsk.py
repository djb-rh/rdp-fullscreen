"""Build the patched DSK ROM: VIR's placements, spatial grid, route graph,
section names and track descriptor, with track record 2 (Super Stunt) repointed
at them. Reads your own ROMs; preserves Atari's byte-sum convention.
"""
import json, math, os, struct
import routegraph as R, vir_build as B, vir_route

ROMDIR = os.environ.get("RD_ROMS", "/Users/djb/Developer/Race Drivin/racedriv")
PARTS = [("136077-4030.30e", 0x30, 0), ("136077-4031.10e", 0x31, 1)]
FREE  = 0x1C060          # clear of the 0x1C044 checksum byte
TRACK_REC = 2 * 164      # Super Stunt's record


def _path(n):
    for c in (n, n + ".bin"):
        p = os.path.join(ROMDIR, c)
        if os.path.exists(p):
            return p
    raise SystemExit("missing " + n)


def load():
    h = [open(_path(n), "rb").read() for n, _, _ in PARTS]
    b = bytearray(len(h[0]) * 2)
    for i in range(len(h[0])):
        b[2*i], b[2*i+1] = h[0][i], h[1][i]
    return b


def main():
    buf = load()
    layout = json.load(open("vir_layout.json"))
    d, C, segs = B.build()
    models = [{"name": "VIRROAD%02d" % i, "origin": s["origin"],
               "matrix": [16384,0,0, 0,16384,0, 0,0,16384]} for i, s in enumerate(segs)]
    models += [{"name": m["name"], "origin": m["origin"], "matrix": m["matrix"]}
               for m in B.extras(d, C) + B.structures(d, C)]
    models = [m for m in models if m["name"] in layout]
    print("placing %d models" % len(models))

    # Move VIR bodily so its start/finish line lands on the spawn point the
    # game already uses for this track record (observed live at 22199,139,31999).
    # Cheaper and more reliable than hunting the spawn variable, and only the
    # placement origins move - model-local vertices are untouched.
    OFF = (69734, -15093, -30944)
    for m in models:
        m["origin"] = (m["origin"][0] + OFF[0],
                       m["origin"][1] + OFF[1],
                       m["origin"][2] + OFF[2])
    print("  shifted VIR by %+d %+d %+d onto the existing spawn" % OFF)

    at = FREE
    def alloc(n):
        nonlocal at
        a = at; at += n + (n & 1); return a

    # --- 50-byte placement records ----------------------------------------
    place = alloc(50 * len(models))
    for k, m in enumerate(models):
        a = place + k*50
        struct.pack_into(">H", buf, a, layout[m["name"]]["index"])
        for i, v in enumerate(m["matrix"]):
            struct.pack_into(">h", buf, a + 2 + 2*i, v)
        for key, off in (("x", 0x14), ("y", 0x18), ("z", 0x1C)):
            i = {"x": 0, "y": 1, "z": 2}[key]
            struct.pack_into(">i", buf, a + off, int(round(m["origin"][i])))

    # --- one cell listing everything, with an infinite box (as Autocross does)
    offs = alloc(2 * len(models) + 2)
    for k in range(len(models)):
        struct.pack_into(">h", buf, offs + 2*k, k * 50)
    struct.pack_into(">H", buf, offs + 2*len(models), 0xFFFF)

    desc = alloc(14)
    grid = desc + 14
    assert grid == at, "the grid must sit immediately after its descriptor"
    at = grid + 28
    struct.pack_into(">I", buf, desc + 0x00, 0x940000 + place)
    struct.pack_into(">H", buf, desc + 0x04, 0x001C)
    struct.pack_into(">H", buf, desc + 0x06, 0x0070)
    struct.pack_into(">H", buf, desc + 0x08, 0x0070)
    struct.pack_into(">I", buf, desc + 0x0A, 0x940000 + grid)
    for i, v in ((0x00, -0x7FFFFFFF), (0x04, -0x7FFFFFFF), (0x08, -0x7FFFFFFF),
                 (0x0C,  0x7FFFFFFF), (0x10,  0x7FFFFFFF), (0x14,  0x7FFFFFFF)):
        struct.pack_into(">i", buf, grid + i, v)
    struct.pack_into(">I", buf, grid + 0x18, 0x940000 + offs)

    # --- section names -----------------------------------------------------
    secs = vir_route.sections(unit_per_metre=1.0, target=4674)
    names, strtab = [], b""
    for s in secs:
        n = s["name"][:14].upper().encode("ascii", "replace")
        if n not in names:
            names.append(n)
    strpos = {}
    blob = b""
    for n in names:
        strpos[n] = len(blob); blob += n + b"\0"
    strs = alloc(len(blob))
    buf[strs:strs+len(blob)] = blob
    ntab = alloc(12 * len(names))
    for i, n in enumerate(names):
        struct.pack_into(">I", buf, ntab + i*12, 0x940000 + strs + strpos[n])
        struct.pack_into(">H", buf, ntab + i*12 + 4, 5200)
        struct.pack_into(">H", buf, ntab + i*12 + 10, 2)      # route type 2

    # --- route graph -------------------------------------------------------
    route = alloc(26 * len(secs))
    blobr = R.encode(
        [(s["value"], s["marker"],
          (2 << 8) | names.index(s["name"][:14].upper().encode()))
         for s in secs], route)
    buf[route:route+len(blobr)] = blobr

    # --- repoint Super Stunt's track record --------------------------------
    struct.pack_into(">I", buf, TRACK_REC + 0x00, 0x940000 + desc)
    struct.pack_into(">I", buf, TRACK_REC + 0x08, 0x940000 + route)
    struct.pack_into(">I", buf, TRACK_REC + 0x0C, 0x940000 + route)
    struct.pack_into(">I", buf, TRACK_REC + 0x10, 0x940000 + ntab)
    print("  placements 0x%05X  cell list 0x%05X  descriptor 0x%05X  grid 0x%05X"
          % (place, offs, desc, grid))
    print("  names 0x%05X  route 0x%05X  -> used %d bytes of free space"
          % (ntab, route, at - FREE))

    # --- verify ------------------------------------------------------------
    nodes = R.read(bytes(buf), route)
    print("  route reads back: %d sections, ring closes: %s"
          % (len(nodes), nodes[-1]["next"] == 0x940000 + route))

    os.makedirs("patched", exist_ok=True)
    for name, suffix, phase in PARTS:
        half = bytearray(buf[phase::2])
        pad = 0x1C044 // 2
        half[pad] = 0
        half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
        open(os.path.join("patched", name), "wb").write(bytes(half))
        print("  %-18s low byte 0x%02X (want 0x%02X) %s"
              % (name, sum(half) & 0xFF, suffix,
                 "OK" if (sum(half) & 0xFF) == suffix else "MISMATCH"))


if __name__ == "__main__":
    main()
