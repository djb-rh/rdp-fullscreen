#!/usr/bin/env python3
"""Generate track segments for the east loop.

Record layout is documented in NOTES.md. Two things that are easy to get wrong:
  * positions are 32-bit stored LOW WORD FIRST, not 16.16
  * the matrix's first COLUMN is the direction of travel, and +0x24 is the
    segment ahead (fitted at 93% against the stock links)
"""
import json, math, struct
import patch_track, layout

BASE, NSEG = 0x049CA, 430
STEP = 3300.0
TEMPLATE = 26                 # plain road: flags 0x0100, +/-800 road.  Its
                              # +0x34/+0x38 (4800) are overwritten: see WINDOW.
ENTER, EXIT = 232, 26         # kept segments either side of the deleted run:
                              # 232 leaves forward into the loop (dot +1.000),
                              # 26 receives it (dot +1.000)


def w32(v):
    """32-bit, low word first."""
    b = struct.pack(">i", v)
    return b[2:4] + b[0:2]


def hword(v):
    """small int in the high word, as the links and edge fields store it"""
    return struct.pack(">i", (v << 16) if v >= 0 else -1)


def centreline(seq, start, step=STEP, close=None):
    """Points along the loop as (x, z, heading, arc-length, spec).

    spec is None for an ordinary sample (flat, +/-WINDOW range) or a dict
    {elev, slope, lo, hi} for one of the segments a piece with relief asks for
    through breakpoints().  Ordinary samples keep to the STEP grid, are dropped
    within CLEAR of a forced one and never fall inside a forced segment's range;
    any gap wider than MAXGAP between ordinary neighbours gets a midpoint, so
    every hand-off lands well inside the next segment's window.
    """
    del centreline.spans[:]
    arc, geom = 0.0, []
    for (name, hand), pose in zip(seq, layout.entry_poses(tuple(start), seq, close)):
        p = layout.piece(name, hand)
        turn, chord = p["turn"], p["chord"]
        r = None if abs(turn) < 1e-9 else (chord/2)/math.sin(math.radians(abs(turn))/2)
        L = chord if r is None else r*math.radians(abs(turn))
        centreline.spans.append((name, arc, arc + L))
        geom.append((p, pose, L, r, arc))
        arc += L
    total = arc

    forced = []
    for name, a0, a1 in centreline.spans:
        for off, spec in breakpoints(name):
            forced.append(((a0 + a1)/2.0 + off, spec))
    forced.sort(key=lambda t: t[0])
    owned = [(fa, fa + sp["hi"]) for fa, sp in forced if sp["hi"] is not None]

    def free(a):
        return (all(abs(a - fa) > CLEAR for fa, _s in forced)
                and not any(lo - 1 <= a <= hi + 1 for lo, hi in owned))
    n = int(total // step) + 1
    samples = [(k*step, None) for k in range(n) if k*step < total and free(k*step)] + forced
    samples = [(a, sp) for a, sp in samples if 0 <= a <= total]
    samples.sort(key=lambda t: t[0])
    i = 0
    while i + 1 < len(samples):
        (a, sp), (b, _t) = samples[i], samples[i+1]
        if b - a > MAXGAP and not (sp and sp["hi"] is not None):
            samples.insert(i+1, ((a + b)/2.0, None))
            continue
        i += 1

    out = []
    for a, spec in samples:
        for p, pose, L, r, a0 in geom:
            if a0 <= a < a0 + L or (a0 + L >= total and a >= a0):
                break
        d = a - a0
        x, z, h = pose
        t = d/L
        ang = p["turn"]*t
        c = p["chord"]*t if r is None else 2*r*math.sin(math.radians(abs(ang))/2)
        th = math.radians(h + ang/2.0)
        out.append((x + math.sin(th)*c, z + math.cos(th)*c, h + ang, a, spec))
    return out


centreline.spans = []
ROADCOL = {38, 40, 58}        # the colour indices every road piece paints with
CLEAR = 1600                  # regular samples this close to a forced one are dropped
MAXGAP = 3300.0               # never leave two ordinary segments further apart than this
WINDOW = 1916                 # +0x34/+0x38: how far ahead/behind its origin a segment owns
                              # the road (stock's modal value, 122 of 430).  NOT a verge -
                              # see NOTES.md "segment ranges".
SIMPLIFY = 25                 # elevation tolerance when reducing a profile
RELIEF  = 300                 # below this a model is treated as flat (DOTLINE's
                              # lane markings stand 208 proud and are not relief)
_prof = {}


def road_profile(name):
    """A piece's elevation profile, read off its own model's road surface.

    Returned as [(offset from the piece centre, elevation)].  Elevation is
    positive DOWN, which is the segment array's convention and the opposite of
    the model's y - stock's UNDERP segments are +720 where the model's road
    surface is -721, and OVERP is negative where its model rises.

    Guessing this shape was the mistake before: a smoothstep starts flat, so the
    drop arrives late, then steepens in the middle, and peaks where the real
    model has 3200 units of flat floor.
    """
    if name in _prof:
        return _prof[name]
    import world
    w = world.World()
    m = w.model({w.name(i): i for i in range(390)}[name])
    verts = m["verts"]
    road = set()
    for idx, col in m["faces"]:
        if col in ROADCOL:
            road.update(i for i in idx if i < len(verts))
    by = {}
    for i in road:
        x, y, z = verts[i]
        by.setdefault(round(z), []).append(-y)
    tab = sorted((z, sum(v)/len(v)) for z, v in by.items())
    if not tab or max(e for _z, e in tab) - min(e for _z, e in tab) < RELIEF:
        _prof[name] = []
        return []
    # The ramps are a staircase of facets whose slopes differ slightly, so every
    # vertex row reads as a kink.  Simplify to the corners that actually matter
    # before deriving segment positions from them.
    _prof[name] = _simplify(tab, SIMPLIFY)
    return _prof[name]


def _simplify(tab, tol):
    """Douglas-Peucker on (offset, elevation), tolerance in elevation units."""
    if len(tab) < 3:
        return tab
    (x0, y0), (x1, y1) = tab[0], tab[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1.0
    worst, at = 0.0, 0
    for i in range(1, len(tab)-1):
        d = abs(dy*(tab[i][0]-x0) - dx*(tab[i][1]-y0)) / n
        if d > worst:
            worst, at = d, i
    if worst <= tol:
        return [tab[0], tab[-1]]
    return _simplify(tab[:at+1], tol)[:-1] + _simplify(tab[at:], tol)


def breakpoints(name):
    """Segments for a piece with relief, as (offset from the piece centre, spec).

    +0x34/+0x38 are a segment's RANGE along its own forward axis - how far ahead
    (hi) and behind (lo, negative) its origin it owns the road.  The DSP moves on
    once the car passes hi and drops back if it finds itself further behind the
    next origin than that segment's lo (with a few hundred units of slack).  A
    flat road at 3300 spacing with +/-1916 hands off 1916 after each origin and
    lands 1384 behind the next - fine.  Our old dip segments 10000 apart with
    +/-1916 handed off at 1916 and landed 8000 behind: advance, retreat,
    advance... every 3 frames, which was the bump, the buried floor and the
    exit that kept climbing.  Stock's underpass is one segment per ramp with
    the ramp LENGTH as its range (seg 40: hi 7980; seg 41: lo -7951).

    So: a flat segment WINDOW before the first corner (hands off exactly at
    it), then one segment per straight run of the profile sitting at the run's
    start with hi = the run's length, so every hand-off lands on the next
    origin (d = 0), and a flat segment on the last corner.
    """
    tab = road_profile(name)
    if not tab:
        return []
    out = [(tab[0][0] - WINDOW, dict(elev=tab[0][1], slope=0.0, lo=-WINDOW, hi=None))]
    for (z0, e0), (z1, e1) in zip(tab, tab[1:]):
        out.append((z0, dict(elev=e0, slope=(e1 - e0)/(z1 - z0), lo=-WINDOW, hi=int(round(z1 - z0)))))
    out.append((tab[-1][0], dict(elev=tab[-1][1], slope=0.0, lo=-WINDOW, hi=None)))
    return out


def grade(spans):
    """Road gradient by arc length: the profile's slope, right-continuous."""
    parts = [((a0 + a1)/2.0, road_profile(nm)) for nm, a0, a1 in spans if road_profile(nm)]

    def f(arc):
        for mid, tab in parts:
            o = arc - mid
            for (z0, e0), (z1, e1) in zip(tab, tab[1:]):
                if z0 <= o < z1:
                    return (e1 - e0)/(z1 - z0)
        return 0.0
    return f


def profile(spans):
    """Elevation as a function of arc length along the whole loop."""
    parts = []
    for nm, a0, a1 in spans:
        tab = road_profile(nm)
        if tab:
            parts.append(((a0+a1)/2.0, tab))

    def f(arc):
        for mid, tab in parts:
            o = arc - mid
            if o < tab[0][0] or o > tab[-1][0]:
                continue
            for i in range(1, len(tab)):
                if o <= tab[i][0]:
                    (z0, e0), (z1, e1) = tab[i-1], tab[i]
                    t = 0.0 if z1 == z0 else (o - z0)/(z1 - z0)
                    return e0 + (e1 - e0)*t
        return 0.0
    return f


def build(pts, first_index, exit_pos=None):
    """Orientation comes from the polyline itself, not from a heading angle.

    layout.py's heading convention and the segment matrices do not agree in sign
    (see NOTES.md), and the disagreement is not a clean mirror, so it cannot be
    corrected by flipping. Deriving the forward axis from (next - current) needs
    no convention at all - and positions are already known to share the segment
    array's coordinate system.
    """
    tmpl = patch_track.load()[BASE+TEMPLATE*64 : BASE+TEMPLATE*64+64]
    elev = profile(centreline.spans)
    slope = grade(centreline.spans)
    recs = []
    for i, (x, z, h, arc, spec) in enumerate(pts):
        r = bytearray(tmpl)
        y = spec["elev"] if spec else elev(arc)
        # placement (x, z) is segment (z, x) - see NOTES.md. Every alignment
        # failure before this was that transpose.  The third 32-bit field is
        # NOT a coordinate: it is elevation.
        r[0:4], r[4:8], r[8:12] = w32(round(z)), w32(round(x)), w32(round(y))
        if i+1 < len(pts):
            nx, nz, narc = pts[i+1][0], pts[i+1][1], pts[i+1][3]
        elif exit_pos is not None:
            nx, nz = exit_pos[1], exit_pos[0]      # exit_pos is in segment frame
            narc = arc + math.hypot(nz - z, nx - x)
        else:
            nx, nz = x + math.sin(math.radians(h)), z + math.cos(math.radians(h))
            narc = arc + 1.0
        dx, dz = nz - z, nx - x                    # transposed: forward = (dz, dx)
        L = math.hypot(dx, dz) or 1.0
        s, c = dx/L, dz/L                       # forward = first matrix column
        # Grade goes in the matrix as well as the position.  Fitted against
        # stock seg 156 (elev -322, pitch -966): with forward = column 0 and no
        # bank, the predicted column 2 is (737, -626, 16355) against an actual
        # (735, -624, 16367).
        th = math.atan(spec["slope"] if spec else slope(arc))
        ct, st = math.cos(th), math.sin(th)
        M = (round(16384*s*ct), round(-16384*c), round(-16384*s*st),
             round(16384*c*ct), round( 16384*s), round(-16384*c*st),
             round(16384*st),   0,               round( 16384*ct))
        struct.pack_into(">9h", r, 0x0C, *M)
        hi = spec["hi"] if spec and spec["hi"] is not None else WINDOW
        lo = spec["lo"] if spec else -WINDOW
        struct.pack_into(">h", r, 0x34, hi)
        struct.pack_into(">h", r, 0x38, lo)
        ahead  = first_index+i+1 if i+1 < len(pts) else EXIT
        behind = first_index+i-1 if i   > 0        else ENTER
        r[0x24:0x28] = hword(ahead)
        r[0x28:0x2C] = hword(behind)
        r[0x2C:0x30] = hword(-1)
        r[0x30:0x34] = hword(-1)
        recs.append(bytes(r))
    return recs


def main():
    S = json.load(open("loop_final.json"))
    pts = centreline(S["seq"], S["start"], close=S.get("close"))
    recs = build(pts, NSEG)
    print("generated %d segments, indices %d..%d" % (len(recs), NSEG, NSEG+len(recs)-1))

    # --- validate ---------------------------------------------------------
    def rp(r): return tuple(struct.unpack(">i", r[o+2:o+4]+r[o:o+2])[0] for o in (0,4,8))
    def rm(r): return struct.unpack_from(">9h", r, 0x0C)
    def rl(r,o):
        v = struct.unpack_from(">i", r, o)[0]; return -1 if v == -1 else v>>16
    bad = 0
    for i, r in enumerate(recs[:-1]):
        p, q = rp(r), rp(recs[i+1])
        d = (q[0]-p[0], q[1]-p[1]); L = math.hypot(*d) or 1
        M = rm(r); f = (M[0]/16384.0, M[3]/16384.0)      # first column
        dot = f[0]*d[0]/L + f[1]*d[1]/L
        if dot < 0.95: bad += 1
    print("  forward axis agrees with travel direction: %d of %d" % (len(recs)-1-bad, len(recs)-1))
    mut = sum(1 for i,r in enumerate(recs[:-1]) if rl(recs[i+1],0x28) == NSEG+i)
    print("  links mutual within the loop: %d of %d" % (mut, len(recs)-1))
    print("  first segment attaches back to %d, last attaches forward to %d"
          % (rl(recs[0],0x28), rl(recs[-1],0x24)))
    buf = patch_track.load()
    def spos(n): return tuple(struct.unpack(">i",
        buf[BASE+n*64+o+2:BASE+n*64+o+4]+buf[BASE+n*64+o:BASE+n*64+o+2])[0] for o in (0,4,8))
    print("  gap to segment %d: %.0f units (%.0f ft)" % (ENTER, math.dist(rp(recs[0])[:2], spos(ENTER)[:2]), math.dist(rp(recs[0])[:2], spos(ENTER)[:2])/40))
    print("  gap to segment %d: %.0f units (%.0f ft)" % (EXIT,  math.dist(rp(recs[-1])[:2], spos(EXIT)[:2]),  math.dist(rp(recs[-1])[:2], spos(EXIT)[:2])/40))
    steps = [math.dist(rp(recs[i])[:2], rp(recs[i+1])[:2]) for i in range(len(recs)-1)]
    print("  step length: min %.0f median %.0f max %.0f units" % (min(steps), sorted(steps)[len(steps)//2], max(steps)))
    open("loop_segments.bin","wb").write(b"".join(recs))
    print("  wrote loop_segments.bin (%d bytes)" % (len(recs)*64))


if __name__ == "__main__":
    main()
