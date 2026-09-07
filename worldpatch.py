"""Patch static world placement records in the Race Drivin' DSK ROM.

Reads your own ROMs, writes new EPROM images with Atari's byte-sum convention
preserved (the low byte of each EPROM's 16-bit sum equals its part-number
suffix). Contains no ROM data.

    python3 worldpatch.py list
    python3 worldpatch.py move 38 --xyz 263000,1600,189000 --out ./patched
    python3 worldpatch.py yaw  38 --deg 90 --out ./patched
"""
import math, os, struct, sys
import routegraph

ROMDIR = os.environ.get("RD_ROMS", "/Users/djb/Developer/Race Drivin/racedriv")
PARTS = [("136077-4030.30e", 0x30, 0), ("136077-4031.10e", 0x31, 1)]
PLACE_BASE, PLACE_N, PLACE_SZ = 0x011D0, 193, 50
PAD_START = 0x1C044          # 16 KB of 0x00 padding; never read.
                             # NOT 0x1C000 - 0x1C000..0x1C043 is the tail of
                             # track B's palette and is read constantly.
TRACK_TABLE = 0x00000        # 328-byte track records
TRACK_STRIDE = 0x148
FREE = 0x1C060               # route graphs go here, clear of the checksum byte
OBJTAB = 0x435BE


def _path(name):
    for c in (name, name + ".bin"):
        p = os.path.join(ROMDIR, c)
        if os.path.exists(p):
            return p
    raise SystemExit("missing ROM: " + name)


def load():
    halves = [open(_path(n), "rb").read() for n, _, _ in PARTS]
    buf = bytearray(len(halves[0]) * 2)
    for i in range(len(halves[0])):
        buf[2*i], buf[2*i+1] = halves[0][i], halves[1][i]
    return buf


def names():
    m = open("rd_maincpu.bin", "rb").read()
    out = []
    for i in range(390):
        p = struct.unpack_from(">I", m, OBJTAB + i*28 + 0x14)[0]
        out.append(m[p:m.index(b"\0", p)].decode("ascii", "replace")
                   if 0 < p < len(m) else "obj%d" % i)
    return out


def get(buf, n):
    a = PLACE_BASE + n * PLACE_SZ
    return {"obj": struct.unpack_from(">H", buf, a)[0],
            "m": [struct.unpack_from(">h", buf, a + 2 + 2*i)[0] for i in range(9)],
            "x": struct.unpack_from(">i", buf, a + 0x14)[0],
            "y": struct.unpack_from(">i", buf, a + 0x18)[0],
            "z": struct.unpack_from(">i", buf, a + 0x1C)[0]}


def put(buf, n, rec):
    a = PLACE_BASE + n * PLACE_SZ
    struct.pack_into(">H", buf, a, rec["obj"])
    for i, v in enumerate(rec["m"]):
        struct.pack_into(">h", buf, a + 2 + 2*i, v)
    for k, off in (("x", 0x14), ("y", 0x18), ("z", 0x1C)):
        struct.pack_into(">i", buf, a + off, rec[k])


def save(buf, outdir):
    """De-interleave and restore each EPROM's byte-sum using a padding byte."""
    os.makedirs(outdir, exist_ok=True)
    for idx, (name, suffix, phase) in enumerate(PARTS):
        half = bytearray(buf[phase::2])
        pad = PAD_START // 2                      # padding start within a half
        half[pad] = 0                             # our correction byte
        need = (suffix - (sum(half) & 0xFF)) & 0xFF
        half[pad] = need
        assert (sum(half) & 0xFF) == suffix
        open(os.path.join(outdir, name), "wb").write(bytes(half))
        print("  %-18s byte-sum 0x%04X, low byte 0x%02X (correction byte 0x%02X "
              "at offset 0x%05X, in padding)"
              % (name, sum(half) & 0xFFFF, suffix, need, pad))


def install_route(buf, track, sections, background=0x0200, at=FREE):
    """Write a route graph into the DSK ROM's free padding and point one of a
    track record's two route pointers at it.

    `track` is 0 or 1; `sections` is a list of (value, marker). Both of the
    record's route pointers are set, so the fork selection lands on the new
    route either way.
    """
    blob = routegraph.encode(sections, at, background=background)
    end = at + len(blob)
    if end > len(buf):
        raise SystemExit("route graph does not fit in the ROM")
    if any(buf[at:end]):
        raise SystemExit("0x%05X..0x%05X is not free" % (at, end))
    buf[at:end] = blob
    rec = TRACK_TABLE + track * TRACK_STRIDE
    for off in (0x08, 0x0C):
        struct.pack_into(">I", buf, rec + off, 0x940000 + at)
    return len(blob)


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    buf, N, cmd = load(), names(), sys.argv[1]
    if cmd == "list":
        for n in range(PLACE_N):
            r = get(buf, n)
            print("%3d %-10s X=%8d Y=%7d Z=%8d" %
                  (n, N[r["obj"]], r["x"], r["y"], r["z"]))
        return
    if cmd == "route": pass
    n = int(sys.argv[2])
    rec = get(buf, n)
    before = dict(rec)
    if cmd == "move":
        x, y, z = (int(v) for v in sys.argv[sys.argv.index("--xyz")+1].split(","))
        rec.update(x=x, y=y, z=z)
    elif cmd == "yaw":
        a = math.radians(float(sys.argv[sys.argv.index("--deg")+1]))
        c, s = int(round(math.cos(a)*16384)), int(round(math.sin(a)*16384))
        rec["m"] = [c, 0, -s, 0, 16384, 0, s, 0, c]
    elif cmd == "route":
        import json
        secs = json.load(open(sys.argv[3]))
        track = int(sys.argv[2])
        n = install_route(buf, track, [(x["value"], x["marker"]) for x in secs])
        print("installed %d-section route (%d bytes) at DSK 0x%05X; "
              "track record %d now points at it"
              % (len(secs), n, FREE, track))
        out = sys.argv[sys.argv.index("--out")+1] if "--out" in sys.argv else "./patched"
        save(buf, out); print("wrote %s" % out); return
    else:
        print(__doc__); return
    put(buf, n, rec)
    assert get(buf, n) == rec, "round-trip failed"
    print("record %d (%s): %s" % (n, N[rec["obj"]],
          "(%d,%d,%d) -> (%d,%d,%d)" % (before["x"], before["y"], before["z"],
                                        rec["x"], rec["y"], rec["z"])
          if cmd == "move" else "yaw set"))
    out = sys.argv[sys.argv.index("--out")+1] if "--out" in sys.argv else "./patched"
    save(buf, out)
    print("wrote %s" % out)


if __name__ == "__main__":
    main()
