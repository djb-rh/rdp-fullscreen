"""Search for a chain of stock road pieces joining the two open junctions,
looping out far enough to cross itself once."""
import json, math, random
import layout, world

U = layout.U

# keep the new loop clear of everything that stays. The sketch went east because
# that is the empty ground; west is full of the existing track and buildings.
_w = world.World()
_dele = set(json.load(open("delete_list.json")))
KEEP = []
for _r in range(193):
    if _r in _dele:
        continue
    _p = _w.placement(_r)
    KEEP.append((_p["x"], _p["z"]))
A = (138674, 261652, -99.5)          # near BARN, where the loop must arrive
B = (188964, 214664, -40.3)          # OVERP exit, where it leaves

# C4532 and C4512 are excluded: their end cross-sections could not be measured
# reliably, so their chord and origin offset are not trustworthy.
PALETTE = [("DOTLINE", 0), ("DOTLINE", 0), ("DOTLHALF", 0), ("ROAD3", 0),
           ("D30R917", +1), ("D30R917", -1), ("D10R1833", +1), ("D10R1833", -1),
           ("C3060", +1), ("C3060", -1), ("C4572", +1), ("C4572", -1),
           ("C3048", +1), ("C3048", -1)]


def endpose(seq, start=B):
    _pl, pose = layout.run(start, seq)
    return pose


def score(seq):
    x, z, h = endpose(seq)
    dpos = math.hypot(x - A[0], z - A[1])
    dh = abs(((h - A[2] + 180) % 360) - 180)
    s = dpos + dh * 900
    # the whole point is a twist, so a chain that never crosses itself is no good
    x = crosses(seq)
    if x is None:
        s += 250000
    else:
        # UNDERP is a STRAIGHT whose dip is in the middle, so one of the two
        # crossing pieces must itself be a straight and the crossing must land
        # near its centre - otherwise the dip ends up in the wrong place, or the
        # substitution breaks the chain by swapping a curve for a straight.
        i_, j_, _pt, t, u = x
        cands = []
        if layout.ENDS[seq[i_][0]]["turn"] == 0:
            cands.append(abs(t - 0.5))
        if layout.ENDS[seq[j_][0]]["turn"] == 0:
            cands.append(abs(u - 0.5))
        if not cands:
            s += 120000                      # neither leg is a straight
        else:
            s += min(cands) * 90000
    pl, _ = layout.run(B, seq)
    # clearance: no piece centre may sit on top of kept geometry
    CLEAR = 14000                       # ~107 m
    for p in pl[1:-1]:
        d = min(math.hypot(p["x"]-kx, p["z"]-kz) for kx, kz in KEEP)
        if d < CLEAR:
            s += (CLEAR - d) * 3
    # and it should bulge east into the empty ground, as the sketch does
    east = max(p["x"] for p in pl)
    if east < 250000:
        s += (250000 - east) * 1.5
    # stretch it: reward long straights, which give the loop an oval shape
    straight = sum(layout.ENDS[n]["chord"] for n, _h in seq if layout.ENDS[n]["turn"] == 0)
    s -= min(straight, 90000) * 0.6
    return s, dpos, dh


def crosses(seq):
    """Does the chain cross itself, and on which pieces?

    The path must be built from each piece's ENTRY and EXIT, not from piece
    centres - a curve's centre can sit far off the road it carries, so a
    centre-to-centre polyline reports crossings that are not on any piece.
    """
    pl, _ = layout.run(B, seq)
    pts = [pl[0]["entry"]] + [p["exit"] for p in pl]
    for i in range(len(pts) - 1):
        for j in range(i + 3, len(pts) - 1):
            a, b, c, d = pts[i], pts[i+1], pts[j], pts[j+1]
            d1 = (b[0]-a[0], b[1]-a[1]); d2 = (d[0]-c[0], d[1]-c[1])
            den = d1[0]*d2[1] - d1[1]*d2[0]
            if abs(den) < 1e-9: continue
            t = ((c[0]-a[0])*d2[1] - (c[1]-a[1])*d2[0]) / den
            s = ((c[0]-a[0])*d1[1] - (c[1]-a[1])*d1[0]) / den
            if 0 <= t <= 1 and 0 <= s <= 1:
                # segment k of this polyline is piece k
                return (i, j, (a[0]+d1[0]*t, a[1]+d1[1]*t), t, s)
    return None


def search(n_pieces, iters=90000, seed=1):
    rnd = random.Random(seed)
    best = None
    cur = [rnd.choice(PALETTE) for _ in range(n_pieces)]
    cs = score(cur)[0]
    for it in range(iters):
        cand = list(cur)
        for _ in range(rnd.choice((1, 1, 2))):
            cand[rnd.randrange(len(cand))] = rnd.choice(PALETTE)
        s = score(cand)[0]
        if s < cs or rnd.random() < 0.02:
            cur, cs = cand, s
        if best is None or s < best[0]:
            best = (s, list(cand))
    return best


if __name__ == "__main__":
    for n in (14, 16, 18, 20, 22):
        s, seq = search(n)
        tot, dpos, dh = score(seq)
        x = crosses(seq)
        print("%2d pieces: end %6.0f units (%5.1f m) off, heading %5.1f deg off, "
              "length %5.0f m, %s"
              % (n, dpos, dpos/U, dh, layout.length(seq)/U,
                 "crosses itself" if x else "no crossing"))
