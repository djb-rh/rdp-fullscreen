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
                     "flags": FLAGS_ROAD, "ahead": (i+1) % n if closed else (i+1 if i+1 < n else -1), "w26": 0,
                     "behind": (i-1) % n if closed else (i-1 if i else -1), "w2A": 0,
                     "laneL": -1, "w2E": 0xFFFF, "laneR": -1, "w32": 0xFFFF,
                     "hi": s["hi"], "w36": 0, "lo": s["lo"], "w3A": 0, "edgeL": EDGE, "edgeR": -EDGE})
    return recs


def expand(design, cat, obj_index, tails):
    """-> (placements, cells, segments dict, route nodes, start segment)."""
    seq = [(n, bool(r)) for n, r in design["chain"]]
    close = tuple(design["start"]) if design.get("close") else None
    pl, end = chain.run(tuple(design["start"]), seq, close)
    records = []
    for p in pl:
        obj = obj_index[p["name"]]; b, f = tails.get(p["name"], (0, 0x1000))
        records.append(placement_record(obj, p["m"], p["x"], 0, p["z"], b, f))
    for s in design.get("scenery", []):
        obj = obj_index[s["name"]]; b, f = tails.get(s["name"], (0, 0x1000))
        records.append(placement_record(obj, heading_matrix(s.get("heading", 0)), s["x"], s.get("y", 0), s["z"], b, f))
    cells = cells_for(records, cat)
    samples, total = sample_chain(pl)
    segs = segment_records(samples, closed=bool(design.get("close")))
    first_seg = {}
    for i, s in enumerate(samples):
        first_seg.setdefault(s["piece"], i)
    nodes = []
    for r in design["route"]:
        seg = first_seg[r["piece"]] + 1                   # segment index (record 0 is the header)
        nodes.append({"value": seg + BIAS - 1, "value2": seg + BIAS - 1, "w4": 0,
                      "flags": (r.get("marker", 0) << 12) | (r.get("type", 0) << 8) | r.get("name", 1), "wE": 0, "w16": 0, "prev": "self" if not nodes else len(nodes) - 1})
    sp, so = design.get("start_piece", 0), design.get("start_offset", 0)
    start = first_seg[sp] + 1
    for i, s in enumerate(samples):
        if s["piece"] == sp and s["arc"] - samples[first_seg[sp]]["arc"] <= so:
            start = i + 1
    return records, cells, {"bias": BIAS, "start": start, "header_raw": bytes(52).hex(), "segs": segs}, nodes, pl, samples
