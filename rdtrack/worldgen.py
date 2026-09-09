"""Expand a track design into world data: placements + cells, segments, route.

design = {
  "start":  [x, z, heading],            # entry pose of chain[0]
  "chain":  [[part, rev], ...],         # road parts in driving order
  "close":  true,                       # spread the closing error over the joints
  "scenery": [{"name":..., "x":..., "z":..., "y": 0, "heading":...}, ...],
  "route":  [{"piece": i, "marker": 1|2|4|8|0, "name": idx}, ...],   # sections start at piece i's first segment
  "start_piece": i, "start_offset": units   # where the car starts (header +8)
}
Everything here is derived from parts.json (measured) and the rules in
NOTES.md: cells = 4x4 uniform grid over the road with the superset membership
rule; segments every STEP along the chain's centreline with +/-WINDOW ranges,
relief pieces as one record per straight run with the run's length as its
range; route section value = segment index + bias - 1.
"""
import math
from . import chain, dsk

STEP = 3300.0
WINDOW = 1916
CLEAR = 1600
MAXGAP = 3300.0
SIMPLIFY = 25
BIAS = 70                   # world A's header +4; section value = segment + BIAS - 1
FLAGS_ROAD = 0x0100
EDGE = 800


# ------------------------------------------------------------ placements ---
def placement_record(obj, M, x, y, z, bias=0, flags=0x1000):
    return {"obj": obj, "m": list(M), "x": int(x), "y": int(y), "z": int(z), "bias": bias, "flags": flags, "rt": b"\0"*12, "w30": 0}


def heading_matrix(h):
    r = math.radians(h); s, c = math.sin(r), math.cos(r)
    q = lambda v: int(round(v*16384))
    return [q(c), 0, q(s), 0, 16384, 0, q(-s), 0, q(c)]


def cells_for(placements, cat, n=4):
    """Uniform n x n grid over the road placements' extent; membership = box within cull."""
    xs = [p["x"] for p in placements]; zs = [p["z"] for p in placements]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    xe = [x0 + (x1 - x0)*k/n for k in range(1, n)]; ze = [z0 + (z1 - z0)*k/n for k in range(1, n)]
    INF = 0x7FFFFFFF
    cells = []
    for iz in range(n):
        for ix in range(n):
            mn = [(-INF if ix == 0 else int(xe[ix-1])), -INF, (-INF if iz == 0 else int(ze[iz-1]))]
            mx = [(INF if ix == n-1 else int(xe[ix])), INF, (INF if iz == n-1 else int(ze[iz]))]
            recs = []
            for k, p in enumerate(placements):
                dx = max(mn[0] - p["x"], 0, p["x"] - mx[0]); dz = max(mn[2] - p["z"], 0, p["z"] - mx[2])
                if math.hypot(dx, dz) <= cat[p["obj"]]["cull"]:
                    recs.append(k)
            cells.append({"min": mn, "max": mx, "recs": recs})
    return cells


# ------------------------------------------------------------- centreline ---
def _simplify(tab, tol):
    if len(tab) < 3:
        return tab
    (x0, y0), (x1, y1) = tab[0], tab[-1]
    dx, dy = x1 - x0, y1 - y0; nrm = math.hypot(dx, dy) or 1.0
    worst, at = 0.0, 0
    for i in range(1, len(tab)-1):
        d = abs(dy*(tab[i][0]-x0) - dx*(tab[i][1]-y0)) / nrm
        if d > worst:
            worst, at = d, i
    if worst <= tol:
        return [tab[0], tab[-1]]
    return _simplify(tab[:at+1], tol)[:-1] + _simplify(tab[at:], tol)


def piece_geometry(pl):
    """World-space centreline polyline of a placed part, in driving order:
    [(x, z, elev, arc)], plus the simplified relief profile [(arc, elev)]."""
    P = chain.parts()[pl["name"]]
    pts = list(P["centreline"])
    if pl["rev"]:
        pts = pts[::-1]
    m = pl["m"]
    out, arc = [], 0.0
    for k, (mx, mz, e) in enumerate(pts):
        wx = pl["x"] + (m[0]*mx + m[2]*mz)/16384.0
        wz = pl["z"] + (m[6]*mx + m[8]*mz)/16384.0
        if k:
            arc += math.hypot(wx - out[-1][0], wz - out[-1][1])
        out.append((wx, wz, e, arc))
    relief = max(e for _x, _z, e, _a in out) - min(e for _x, _z, e, _a in out) >= 300
    prof = _simplify([(a, e) for _x, _z, e, a in out], SIMPLIFY) if relief else []
    return out, prof


def _interp(poly, arc):
    for (x0, z0, e0, a0), (x1, z1, e1, a1) in zip(poly, poly[1:]):
        if a0 <= arc <= a1 or arc < a0:
            t = 0.0 if a1 == a0 else max(0.0, min(1.0, (arc - a0)/(a1 - a0)))
            return x0 + (x1-x0)*t, z0 + (z1-z0)*t, e0 + (e1-e0)*t
    x, z, e, _a = poly[-1]
    return x, z, e


def sample_chain(placements):
    """-> list of samples {x, z, elev, slope, lo, hi, piece, arc} along the whole chain."""
    geoms = [piece_geometry(p) for p in placements]
    total, forced, base = 0.0, [], []
    for (poly, prof) in geoms:
        base.append(total)
        if prof:
            a0 = total
            forced.append((a0 + prof[0][0] - WINDOW, dict(elev=prof[0][1], slope=0.0, lo=-WINDOW, hi=None)))
            for (s0, e0), (s1, e1) in zip(prof, prof[1:]):
                forced.append((a0 + s0, dict(elev=e0, slope=(e1-e0)/(s1-s0), lo=-WINDOW, hi=int(round(s1-s0)))))
            forced.append((a0 + prof[-1][0], dict(elev=prof[-1][1], slope=0.0, lo=-WINDOW, hi=None)))
        total += poly[-1][3]
    forced.sort(key=lambda t: t[0])
    owned = [(a, a + s["hi"]) for a, s in forced if s["hi"] is not None]
    def free(a):
        return all(abs(a - fa) > CLEAR for fa, _s in forced) and not any(lo - 1 <= a <= hi + 1 for lo, hi in owned)
    samples = [(k*STEP, None) for k in range(int(total // STEP) + 1) if k*STEP < total and free(k*STEP)] + forced
    samples = [(a, s) for a, s in samples if 0 <= a < total]
    samples.sort(key=lambda t: t[0])
    i = 0
    while i + 1 < len(samples):
        (a, s), (b, _t) = samples[i], samples[i+1]
        if b - a > MAXGAP and not (s and s["hi"] is not None):
            samples.insert(i+1, ((a+b)/2.0, None)); continue
        i += 1
    # the wrap-around gap (closed loops): last sample to first + total
    while samples and (samples[0][0] + total) - samples[-1][0] > MAXGAP:
        a = samples[-1][0]; samples.append(((a + samples[0][0] + total)/2.0, None))
        samples = [(x, s) for x, s in samples if x < total]
    out = []
    for a, spec in samples:
        k = max(i for i, b in enumerate(base) if b <= a)
        poly, _prof = geoms[k]
        x, z, e = _interp(poly, a - base[k])
        out.append({"x": x, "z": z, "elev": spec["elev"] if spec else e, "slope": spec["slope"] if spec else None,
                    "lo": spec["lo"] if spec else -WINDOW, "hi": (spec["hi"] if spec and spec["hi"] is not None else WINDOW),
                    "piece": k, "arc": a})
    return out, total


def segment_records(samples, closed=True):
    """Samples -> segment dicts in dsk format (positions transposed, forward from travel)."""
    n = len(samples)
    recs = []
    for i, s in enumerate(samples):
        nxt = samples[(i+1) % n] if closed or i+1 < n else None
        if nxt is None:
            prv = samples[i-1]; dx, dz = s["x"] - prv["x"], s["z"] - prv["z"]; de = s["elev"] - prv["elev"]
        else:
            dx, dz = nxt["x"] - s["x"], nxt["z"] - s["z"]; de = nxt["elev"] - s["elev"]
        L = math.hypot(dx, dz) or 1.0
        fs, fc = dx/L, dz/L                        # forward: placement (x, z) -> segment (z, x): matrix col 0 = (fc?, fs?)
        slope = s["slope"] if s["slope"] is not None else de/L
        th = math.atan(slope); ct, st = math.cos(th), math.sin(th)
        # same construction as mkseg.build: forward = first column, with dz/dx swapped for the segment frame
        sX, cX = fx_fz = (dz/L, dx/L)
        M = (round(16384*sX*ct), round(-16384*cX), round(-16384*sX*st),
             round(16384*cX*ct), round(16384*sX), round(-16384*cX*st),
             round(16384*st), 0, round(16384*ct))
        recs.append({"x": int(round(s["z"])), "z": int(round(s["x"])), "elev": int(round(s["elev"])), "m": list(M), "w1E": 0,
                     # links are RECORD indices: record 0 is the header, sample i is record i+1
                     "flags": FLAGS_ROAD, "ahead": ((i+1) % n) + 1 if closed else (i+2 if i+1 < n else -1), "w26": 0,
                     "behind": ((i-1) % n) + 1 if closed else (i if i else -1), "w2A": 0,
                     "laneL": -1, "w2E": 0xFFFF, "laneR": -1, "w32": 0xFFFF,
                     "hi": s["hi"], "w36": 0, "lo": s["lo"], "w3A": 0, "edgeL": EDGE, "edgeR": -EDGE})
    return recs


DECK_OFFSETS = (0,)               # one deck like stock (three at +/-2200 were tried against the approach band: no effect)
CARRY = 200                 # only the piece the crossing falls in rides on the deck (stock: one D30R917);
                            # giving the neighbours -400 too sorted them in front of the cutting banks
BIAS_CARRIED = -400         # stock: the road over the cutting, its only nonzero road bias
MARGIN_KEY = 300            # extra separation in sort-key units (2 world units each)
WALL_OFF, WALL_HALF = 3200, 9600   # the UNDERP's fill walls: lateral offset and half-length


def carried_bias(phi_deg, t_far, bias_underp):
    """Depth bias for the road piece that carries a crossing.

    The renderer keys every polygon by (its farthest vertex depth)/2 + the
    object's bias and paints far to near.  The UNDERP's outer faces are
    fill-to-screen-bottom faces in the ground colour; if they sort NEARER than
    the carrying road's base quad they paint over it, and the only thing that
    repairs the bottom of the screen is the slab under the car - which the
    scan converter drops when a full-width slab's top edge lands on a 1-pixel
    slant.  Hence the bands on a long straight run-in (NOTES.md, R8).
    Condition for no flood, with the camera d before the crossing:
        (d - WALL_OFF/sin phi + WALL_HALF|cos phi|)/2 + bias_U
          >= (d + t_far)/2 + bias_road + margin
    d cancels; phi = angle between the cutting and the road (90 = square),
    t_far = carrying piece beyond the crossing in the driving direction.
    Stock's angled crossing on a curve satisfies it with -400; a square
    crossing on a DOTLINE needs about -6000.  A very negative bias makes the
    road paint over cars driving on that piece near its far end (hidden
    within 2*|bias| of the end), so keep crossings oblique and the carrying
    piece short or curved where traffic matters."""
    s = max(math.sin(math.radians(phi_deg)), 0.2)
    wall_far = -WALL_OFF / s + WALL_HALF * abs(math.cos(math.radians(phi_deg)))
    need = bias_underp + (wall_far - t_far) / 2.0 - MARGIN_KEY
    return int(min(BIAS_CARRIED, round(need / 100.0) * 100))
BIAS_UNDERP = 800           # stock uses +111/+142, but on the approach to the deck the cutting's
                            # ground-level verges (coplanar with the road on top) painted over the
                            # road we were driving on - the camera's own road is drawn outside the
                            # sorted list, so only the cutting's key can be moved.  +600 is the
                            # threshold, +2000 breaks the view from inside the cutting; +800 is clean
                            # at every position tested (NOTES.md, 2026-09-08).


def _seg_cross(p, q, r, t):
    d1 = (q[0]-p[0], q[1]-p[1]); d2 = (t[0]-r[0], t[1]-r[1]); den = d1[0]*d2[1] - d1[1]*d2[0]
    if abs(den) < 1e-9:
        return None
    u = ((r[0]-p[0])*d2[1] - (r[1]-p[1])*d2[0]) / den; v = ((r[0]-p[0])*d1[1] - (r[1]-p[1])*d1[0]) / den
    return (u, v) if 0 <= u <= 1 and 0 <= v <= 1 else None


def crossings(pl, geoms):
    """Where an UNDERP's centreline is crossed by another piece: [(lower k, upper j,
    x, z, upper heading, arc on lower, arc on upper)]."""
    out = []
    for k, p in enumerate(pl):
        if p["name"] != "UNDERP":
            continue
        low = geoms[k][0]
        for j, q in enumerate(pl):
            if j == k or abs(j - k) == 1 or (min(j, k) == 0 and max(j, k) == len(pl) - 1):
                continue
            up = geoms[j][0]
            for a, b in zip(low, low[1:]):
                for c, d in zip(up, up[1:]):
                    h = _seg_cross(a, b, c, d)
                    if h:
                        u, v = h
                        x, z = a[0] + (b[0]-a[0])*u, a[1] + (b[1]-a[1])*u
                        hd = math.degrees(math.atan2(d[0]-c[0], d[1]-c[1]))
                        out.append((k, j, x, z, hd, a[3] + (b[3]-a[3])*u, c[3] + (d[3]-c[3])*v))
    return out


def expand(design, cat, obj_index, tails):
    """-> (placements, cells, segments dict, route nodes, start segment)."""
    seq = [(n, bool(r)) for n, r in design["chain"]]
    close = tuple(design["start"]) if design.get("close") else None
    pl, end = chain.run(tuple(design["start"]), seq, close)
    geoms = [piece_geometry(p) for p in pl]
    lengths = [g[0][-1][3] for g in geoms]
    base = [sum(lengths[:k]) for k in range(len(pl))]
    xs = crossings(pl, geoms)
    carried, decks, cbias = set(), [], {}
    for k, j, x, z, hd, arc_low, arc_up in xs:
        if abs(arc_low - lengths[k]/2) > 1600:
            print("  WARNING: crossing sits %.0f from the UNDERP's centre (floor is +/-1600)" % (arc_low - lengths[k]/2))
        xarc = base[j] + arc_up
        # angle between the cutting's axis and the upper road at the crossing
        low = geoms[k][0]; ia = min(range(len(low)-1), key=lambda i: abs(low[i][3] - arc_low))
        low_hd = math.degrees(math.atan2(low[ia+1][0]-low[ia][0], low[ia+1][1]-low[ia][1]))
        phi = abs(((hd - low_hd + 90) % 180) - 90); phi = 90 - abs(phi - 90) if False else (180 - abs(((hd - low_hd) % 360) - 180))
        phi = min(phi, 180 - phi)
        for i in range(len(pl)):
            if pl[i]["name"] != "UNDERP" and base[i] - CARRY <= xarc <= base[i] + lengths[i] + CARRY:
                carried.add(i)
                t_far = base[i] + lengths[i] - xarc            # carrying piece beyond the crossing
                cbias[i] = min(cbias.get(i, 0), carried_bias(phi, t_far, BIAS_UNDERP))
        for off in DECK_OFFSETS:
            dx, dz = math.sin(math.radians(hd)), math.cos(math.radians(hd))
            decks.append((x + dx*off, z + dz*off, hd - 90))
        print("  crossing: UNDERP piece %d under piece %d (%s) at (%d, %d), angle %.0f deg, deck heading %.1f, carried %s bias %s" % (
            k, j, pl[j]["name"], x, z, phi, hd - 90, sorted(carried), {i: cbias[i] for i in sorted(cbias)}))
    def rec(p, bias=None):
        obj = obj_index[p["name"]]; b, f = tails.get(p["name"], (0, 0x1000))
        return placement_record(obj, p["m"], p["x"], 0, p["z"], b if bias is None else bias, f)
    # stock's crossing trio is road (carried) -> cutting -> deck, adjacent and last
    records = [rec(p) for i, p in enumerate(pl) if i not in carried and p["name"] != "UNDERP"]
    from . import scenery
    def place(obj, hd, x, y, z, b, f):
        return placement_record(obj, heading_matrix(hd), x, y, z, b, f)
    srecs, warnings = scenery.expand(design, pl, geoms, obj_index, tails, scenery.bboxes(), place)
    for wmsg in warnings:
        print("  WARNING:", wmsg)
    records += srecs
    records += [rec(pl[i], cbias.get(i, BIAS_CARRIED)) for i in sorted(carried)]
    records += [rec(p, BIAS_UNDERP) for p in pl if p["name"] == "UNDERP"]
    for x, z, hd in decks:
        b, f = tails.get("XOVER", (-200, 0x1000))
        records.append(placement_record(obj_index["XOVER"], heading_matrix(hd), x, 0, z, b, f))
    cells = cells_for(records, cat)
    samples, total = sample_chain(pl)
    segs = segment_records(samples, closed=bool(design.get("close")))
    first_seg = {}
    for i, s in enumerate(samples):
        first_seg.setdefault(s["piece"], i)
    # the start post: sample `post` on the start piece.  Stock's layout is finish
    # section -> car's start segment -> start section around the post, so the
    # lap completes AT the line: finish node = the post's segment, start node =
    # the one after, header start = the post's segment.
    sp, so = design.get("start_piece", 0), design.get("start_offset", 0)
    post = first_seg[sp]
    for i, s in enumerate(samples):
        if s["piece"] == sp and s["arc"] - samples[first_seg[sp]]["arc"] <= so:
            post = i
    n = len(samples)
    nodes = []
    def node(seg, mk, name, rtype=0):
        nodes.append({"value": seg + BIAS - 1, "value2": seg + BIAS - 1, "w4": 0,
                      "flags": (mk << 12) | (rtype << 8) | name, "wE": 0, "w16": 0, "prev": "self" if not nodes else len(nodes) - 1})
    # The game pays award A only at a marker-4 section, and only once until a
    # marker-8 section re-arms it (0x02F0B8); stock's first CHKPT is a marker-8
    # section and pays nothing.  Here every gate in the design pays: it becomes a
    # marker-4 section and a marker-8 re-arm section follows it (and the start).
    for r in design["route"]:
        mk = r.get("marker", 0); nm = r.get("name", 1); rt = r.get("type", 0)
        if mk == 1:
            node((post + 1) % n + 1, 1, nm, rt); node((post + 2) % n + 1, 8, nm, rt)
        elif mk == 2:
            node(post + 1, 2, nm, rt)
        elif mk in (4, 8):
            seg = first_seg[r["piece"]] + 1                   # segment index (record 0 is the header)
            node(seg, 4, nm, rt); node(seg + 1, 8, nm, rt)
        else:
            node(first_seg[r["piece"]] + 1, 0, nm, rt)
    # start line and gates: at the route's start/gate sections, facing the travel heading
    NAME_START, NAME_GATE = 0x0113C, 0x01146          # "STRTPOST" / "CHKPT" strings in the front region
    entities = []
    for r in design["route"]:
        mk = r.get("marker", 0)
        if mk not in (1, 4, 8):
            continue
        i = post if mk == 1 else first_seg[r["piece"]]; s = samples[i]; nxt = samples[(i + 1) % len(samples)]   # every gate pays now
        hd = math.degrees(math.atan2(nxt["x"] - s["x"], nxt["z"] - s["z"])) % 360
        entities.append({"name_at": NAME_START if mk == 1 else NAME_GATE, "type": 1 if mk == 1 else 2,
                         "x": int(round(s["x"])), "y": int(round(-s["elev"])), "z": int(round(s["z"])), "w18": 0, "heading": int(round(hd / 360 * 65536)) & 0xFFFF})
    entities.sort(key=lambda e: -e["type"] if e["type"] == 1 else 0)     # start first, as stock
    entities.append({"name_at": 0x01152, "type": 0, "x": 0, "y": 0, "z": 0, "w18": 0, "heading": 0})
    start = post + 1
    return records, cells, {"bias": BIAS, "start": start, "header_raw": bytes(52).hex(), "segs": segs}, nodes, pl, samples, entities
