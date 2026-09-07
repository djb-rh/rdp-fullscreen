"""Patch the original speed track: delete 17 placements, add the new east loop.

Everything is stock road pieces, so the object ROM is untouched - this is purely
a DSK ROM placement edit.

The array cannot simply grow in place (only 50 spare bytes follow it), so the
placement array and all 16 cell lists are rewritten into the free padding and
the track descriptor is repointed at them.

Reads your own ROMs; preserves Atari's byte-sum convention. No ROM data here.
"""
import json, math, os, struct
import layout, world

ROMDIR = os.environ.get("RD_ROMS", "/Users/djb/Developer/Race Drivin/racedriv")
PARTS = [("136077-4030.30e", 0x30, 0), ("136077-4031.10e", 0x31, 1)]
DESC = 0x037B4          # track 0 descriptor
GRID = 0x037C2          # its 16 cell headers
OLD_BASE = 0x011D0
FREE = 0x1C060          # clear of the checksum byte at 0x1C044
ROUTE_RESERVE = 0x200       # patch_route.py owns the top of the padding
PAD_END = 0x20000 - ROUTE_RESERVE


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



def tails(buf):
    """object index -> (+0x20, +0x22) as stock writes them, read from the ROM.

    +0x22 is a pure function of the object.  +0x20 is not - it varies between
    placements of the same object - but it is nonzero on exactly the large or
    background objects (FLOAT*, HILL*, UNDERP, XOVER), never correlates with any
    elevation, and reads like a depth-sort bias.  Stock never leaves it 0 on an
    UNDERP, so neither should we.""" 
    U = lambda a: struct.unpack_from(">I", buf, a)[0]
    u = lambda a: struct.unpack_from(">H", buf, a)[0]
    h = lambda a: struct.unpack_from(">h", buf, a)[0]
    m = {}
    for rec in (0x00000, 0x000A4, 0x00148):          # the three track records
        desc = U(rec) - 0x940000
        base = U(desc) - 0x940000
        ncell = u(desc + 0x06) // 0x1C
        for c in range(max(1, ncell)):
            p = U(desc + 0x0E + c*0x1C + 0x18) - 0x940000
            if not (0 <= p < len(buf) - 2):
                continue
            k = 0
            while u(p + 2*k) != 0xFFFF and k < 4000:
                a = base + h(p + 2*k)
                if 0 <= a < len(buf) - 0x32:
                    m.setdefault(u(a), []).append(
                    (struct.unpack_from(">h", buf, a + 0x20)[0], u(a + 0x22)))
                k += 1
    # Take the most common pair, not the first one seen: nine of the ten stock
    # D10R1833 records have +0x20 = 0 and one has 2045, and picking the outlier
    # would put it on every piece we lay.
    import collections
    return {o: collections.Counter(v).most_common(1)[0][0] for o, v in m.items()}

def crossing(S):
    """Where the loop passes over itself, and the heading of the upper leg."""
    import mkseg
    pts = mkseg.centreline(S["seq"], S["start"], close=S.get("close"))
    def hit(p, q, r, t):
        d1 = (q[0]-p[0], q[1]-p[1]); d2 = (t[0]-r[0], t[1]-r[1])
        den = d1[0]*d2[1] - d1[1]*d2[0]
        if abs(den) < 1e-9:
            return None
        a = ((r[0]-p[0])*d2[1] - (r[1]-p[1])*d2[0]) / den
        b = ((r[0]-p[0])*d1[1] - (r[1]-p[1])*d1[0]) / den
        return (a, b) if 0 <= a <= 1 and 0 <= b <= 1 else None
    for i in range(len(pts)-1):
        for j in range(i+3, len(pts)-1):
            h = hit(pts[i], pts[i+1], pts[j], pts[j+1])
            if not h:
                continue
            a, b = h
            # the later leg is the one on top - the earlier one is in the cutting
            hx = pts[j][0] + b*(pts[j+1][0]-pts[j][0])
            hz = pts[j][1] + b*(pts[j+1][1]-pts[j][1])
            head = math.degrees(math.atan2(pts[j+1][0]-pts[j][0],
                                           pts[j+1][1]-pts[j][1]))
            upper_arc = pts[j][3] + b*(pts[j+1][3]-pts[j][3])
            return hx, hz, head, upper_arc
    return None


def main():
    buf = load()
    u = lambda a: struct.unpack_from(">H", buf, a)[0]
    s = lambda a: struct.unpack_from(">h", buf, a)[0]
    U = lambda a: struct.unpack_from(">I", buf, a)[0]

    w = world.World()
    IDX = {w.name(i): i for i in range(390)}
    TAIL = tails(buf)
    dele = sorted(set(json.load(open("delete_list.json"))))
    S = json.load(open("loop_final.json"))
    seq = [(n, h) for n, h in S["seq"]]
    pl, _ = layout.run(tuple(S["start"]), seq, S.get("close"))

    # --- the surviving placements, in order, then the new pieces -------------
    keep = [r for r in range(193) if r not in dele]
    remap = {r: i for i, r in enumerate(keep)}          # old index -> new index
    records = []
    for r in keep:
        a = OLD_BASE + r*50
        records.append(bytes(buf[a:a+50]))
    import mkseg
    mkseg.centreline(S["seq"], S["start"], close=S.get("close"))   # populates .spans
    spans = list(mkseg.centreline.spans)
    xarc = crossing(S)[3] if crossing(S) else None
    CARRY = 10000                # reach either side of the crossing, in units

    loop_recs, carried = [], []
    for k, ((nm, hand), p) in enumerate(zip(seq, pl)):
        rec = bytearray(50)
        struct.pack_into(">H", rec, 0x00, IDX[nm])
        for i, v in enumerate(p["matrix"]):
            struct.pack_into(">h", rec, 0x02 + 2*i, v)
        struct.pack_into(">i", rec, 0x14, p["x"])
        struct.pack_into(">i", rec, 0x18, 0)
        struct.pack_into(">i", rec, 0x1C, p["z"])
        # +0x22 is NOT optional padding.  Every one of the 2281 stock placement
        # records in the game has bit 12 set here (0x1000 for road, 0x9000 for
        # scenery - the extra 0x8000 is a separate flag), and the value is a pure
        # function of the object index.  Leaving it zero placed the road, routed
        # through it and gave it collision, but drew nothing.
        t20, t22 = TAIL.get(IDX[nm], (0, 0x1000))
        # +0x20 is a depth bias: negative draws nearer.  Stock's crossing is a
        # strict stack - UNDERP +142 (the cutting), XOVER -200 (the deck),
        # D30R917 -400 (the road on it), and that D30R917 is the ONLY road
        # placement on track 0 with a nonzero value.  Leaving our carried road
        # at 0 sorted it behind its own deck.
        # REVERTED.  A tap on the 68010 shows +0x20 is never read - not by the
        # gather at 0x021E02, not from the buffer it fills at 0x809946 - and
        # forcing -400 here changed nothing on screen.  The depth-bias reading
        # was pattern-matching on 12 objects, not evidence.  Left at the stock
        # per-object value.  (The buffer is DS III shared RAM, so the DSP side
        # could still read it; that needs a tap on the DSP, not on the 68010.)
        struct.pack_into(">h", rec, 0x20, t20)
        struct.pack_into(">H", rec, 0x22, t22)
        if xarc is not None and k < len(spans):
            a0, a1 = spans[k][1], spans[k][2]
            if a0 - CARRY <= xarc <= a1 + CARRY and nm != "UNDERP":
                carried.append(k)
                # Stock's trick, and now it can work: the carrying road gets a
                # -400 depth bias (the ADSP adds +0x20 to its sort key) so it
                # always paints AFTER the cutting's ground plane.  Without it
                # the two keys cross on the approach and the draw order flips
                # frame to frame - the chop that was left once the mirrored
                # pieces were fixed.
                struct.pack_into(">h", rec, 0x20, -400)
        loop_recs.append((k, nm, bytes(rec)))
    # --- a deck over the cutting -------------------------------------------
    # Stock never leaves an underpass without one: UNDERP 101 has an XOVER 194
    # units away.  XOVER is a bridge deck - one road quad 4961 long by 2241 wide
    # at y=0 with 320 of structure beneath - and it runs along its LOCAL X, so it
    # is placed 90 degrees off the road it carries.  Local x maps to world
    # (cos a, -sin a), so a = heading - 90; that predicts 94.1 for stock's XOVER
    # against the 94.0 actually in the ROM.
    xo = crossing(S)
    if xo:
        cx, cz, upper, _arc = xo
        a = math.radians(upper - 90.0)
        q = lambda v: int(round(v * 16384))
        rec = bytearray(50)
        struct.pack_into(">H", rec, 0x00, IDX["XOVER"])
        struct.pack_into(">9h", rec, 0x02,
                         q(math.cos(a)), 0, q(math.sin(a)),
                         0, 16384, 0,
                         q(-math.sin(a)), 0, q(math.cos(a)))
        struct.pack_into(">i", rec, 0x14, int(round(cx)))
        struct.pack_into(">i", rec, 0x18, 0)
        struct.pack_into(">i", rec, 0x1C, int(round(cz)))
        t20, t22 = TAIL.get(IDX["XOVER"], (-200, 0x1000))
        struct.pack_into(">h", rec, 0x20, t20)
        struct.pack_into(">H", rec, 0x22, t22)
        loop_recs.append((None, "XOVER", bytes(rec)))
        print("  deck: XOVER at (%d, %d) heading %.1f (carrying road at %.1f)"
              % (cx, cz, upper - 90.0, upper))

    # Stock keeps a crossing's three placements ADJACENT and in this order:
    # 100 the road, 101 the cutting, 102 the deck.  Cell lists are sorted by
    # index without exception, so index order IS list order, and that order is
    # why the deck exists: the road draws, the cutting's ground (6 faces of
    # colour 53 lying flat at y=0, 6401 x 19201) draws over it, then the deck
    # redraws road on top where the two meet.  Ours ran the other way round -
    # cutting first - so its ground covered the road across the whole 160 ft of
    # UNDERP footprint, which is the stretch either side of the bridge.
    names = {k: nm for k, nm, _b in loop_recs}
    rest = [t for t in loop_recs
            if t[0] not in carried and t[1] not in ("UNDERP", "XOVER")]
    trio = ([t for t in loop_recs if t[0] in carried]
            + [t for t in loop_recs if t[1] == "UNDERP"]
            + [t for t in loop_recs if t[1] == "XOVER"])
    print("  crossing order now %s (stock: road, cutting, deck)"
          % " -> ".join(t[1] for t in trio))
    for _k, _nm, b in rest + trio:
        records.append(b)
    n_new = len(records) - len(keep)
    print("placements: %d kept + %d new = %d" % (len(keep), n_new, len(records)))

    # --- lay the new array and cell lists into the padding -------------------
    at = FREE
    array = at
    for rec in records:
        buf[at:at+50] = rec
        at += 50
    lists = []
    for c in range(16):
        h = GRID + c*0x1C
        p = U(h + 0x18) - 0x940000
        old = []
        k = 0
        while u(p + 2*k) != 0xFFFF:
            old.append(s(p + 2*k)); k += 1
        kept = [remap[o // 50] * 50 for o in old if (o // 50) not in dele]
        # ASCENDING, like every stock cell list without exception.  Putting the
        # loop first was a guess at the invisible-road problem that turned out
        # to be +0x22, and it left all 16 lists in an order the game never sees.
        newoffs = sorted(kept + [(len(keep) + i) * 50 for i in range(n_new)])
        lists.append((h, newoffs, len(old)))
    for h, offs, oldn in lists:
        struct.pack_into(">I", buf, h + 0x18, 0x940000 + at)
        for o in offs:
            struct.pack_into(">h", buf, at, o); at += 2
        struct.pack_into(">H", buf, at, 0xFFFF); at += 2
    struct.pack_into(">I", buf, DESC + 0x00, 0x940000 + array)
    print("new array at 0x%05X, cell lists to 0x%05X; %d of %d padding bytes used"
          % (array, at, at - FREE, PAD_END - FREE))
    if at > PAD_END:
        raise SystemExit("overran the padding")

    # --- verify by walking it exactly as the game would ---------------------
    base = U(DESC) - 0x940000
    okc = 0
    for c in range(16):
        p = U(GRID + c*0x1C + 0x18) - 0x940000
        k = 0
        while u(p + 2*k) != 0xFFFF:
            a = base + s(p + 2*k)
            oi = u(a)
            if not (0 <= oi < 390):
                raise SystemExit("bad object index in cell %d" % c)
            k += 1
        okc += k
    print("walked all 16 cells: %d placement references, all valid" % okc)

    os.makedirs("patched_track", exist_ok=True)
    for name, suffix, phase in PARTS:
        half = bytearray(buf[phase::2])
        pad = 0x1C044 // 2
        half[pad] = 0
        half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
        open(os.path.join("patched_track", name), "wb").write(bytes(half))
        print("  %-18s low byte 0x%02X (want 0x%02X) %s"
              % (name, sum(half) & 0xFF, suffix,
                 "OK" if (sum(half) & 0xFF) == suffix else "MISMATCH"))


if __name__ == "__main__":
    main()
