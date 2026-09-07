#!/usr/bin/env python3
"""Measure every road piece in the object ROM and write parts.json.

    python3 -m rdtrack.parts            # from the repo root (needs rd_*.bin)

How a piece is read: the asphalt is a strip of slabs in colours 40 and 38, and
colour 58 is the centre-line paint.  The dashes give a direction field; the
slab edges that run across that direction are the strip's cross-sections, and
their midpoints, ordered along the strip, are the centreline.  The first and
last cross-sections are the entry and exit; the profile is the centreline's
height by arc length and the bank is each cross-section's tilt.

Names encode the design geometry (D<turn>R<radius ft>, C<turn><radius/10 ft>)
and the measurement is checked against it where a name decodes.
"""
import json, math, re, sys, collections
import world

ASPHALT = {38, 40}
PAINT = 58
FT = 40.0                      # world units per foot


def _merge(verts, faces, cols):
    """Vertices by coordinate (models repeat positions), faces as coord tuples."""
    out = []
    for idx, col in faces:
        if col in cols:
            out.append([tuple(verts[i]) for i in idx if i < len(verts)])
    return out


def _edges(polys):
    cnt = collections.Counter()
    for p in polys:
        for a, b in zip(p, p[1:] + p[:1]):
            cnt[frozenset((a, b))] += 1
    return cnt


def _dir3(a, b):
    d = (b[0]-a[0], b[1]-a[1], b[2]-a[2]); n = math.sqrt(sum(c*c for c in d)) or 1.0
    return tuple(c/n for c in d)


def _pca_dir(pts):
    """Principal horizontal axis of a set of points (x, z)."""
    n = len(pts); mx = sum(p[0] for p in pts)/n; mz = sum(p[2] for p in pts)/n
    sxx = sum((p[0]-mx)**2 for p in pts); szz = sum((p[2]-mz)**2 for p in pts)
    sxz = sum((p[0]-mx)*(p[2]-mz) for p in pts)
    th = 0.5*math.atan2(2*sxz, sxx - szz)
    return (math.cos(th), 0.0, math.sin(th))


def _circle(pts):
    """Least-squares circle through (x, z) points -> (cx, cz, r, rms) or None if collinear."""
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts)/n; mz = sum(p[2] for p in pts)/n
    u = [p[0]-mx for p in pts]; v = [p[2]-mz for p in pts]
    suu = sum(a*a for a in u); svv = sum(b*b for b in v); suv = sum(a*b for a, b in zip(u, v))
    suuu = sum(a**3 for a in u); svvv = sum(b**3 for b in v)
    suvv = sum(a*b*b for a, b in zip(u, v)); svuu = sum(b*a*a for a, b in zip(u, v))
    det = suu*svv - suv*suv
    if abs(det) < 1e-6 * max(1.0, suu*svv):
        return None
    rhs1 = 0.5*(suuu + suvv); rhs2 = 0.5*(svvv + svuu)
    uc = (rhs1*svv - rhs2*suv)/det; vc = (rhs2*suu - rhs1*suv)/det
    r = math.sqrt(uc*uc + vc*vc + (suu + svv)/n)
    cx, cz = uc + mx, vc + mz
    rms = math.sqrt(sum((math.hypot(p[0]-cx, p[2]-cz) - r)**2 for p in pts)/n)
    return cx, cz, r, rms


STUNT = {"RAMP1", "HLOOP", "LAUNCH", "JPART", "JLAND", "TUBE", "CORKS"}


def classify(name, p):
    if name in STUNT:
        return "stunt"
    if p["width"] < 1200:
        return "other"
    if name == "XOVER":
        return "deck"
    if abs(p["turn"]) < 1 and p["sections"] <= 2 and p["chord"] < 2000:
        return "slab"
    if any(abs(b) > 5 for b in p["bank"]):
        return "banked"
    if p["elev_min"] < -100:
        return "bridge"
    if p["elev_max"] > 100:
        return "cutting"
    return "road"


def decode_name(name):
    m = re.fullmatch(r"D(\d+)R(\d+)", name)
    if m:
        return int(m.group(1)), int(m.group(2))*FT
    m = re.fullmatch(r"[MC][LR]?(\d\d)(\d\d)", name)
    if m and name[0] == "C" or (m and name[:2] in ("MR", "ML")):
        return int(m.group(1)), int(m.group(2))*10*FT
    m = re.fullmatch(r"C(\d+)R(\d+)", name)
    if m:
        return int(m.group(1)), int(m.group(2))*FT
    return None


def measure(w, i):
    m = w.model(i)
    if not m:
        return None
    name = w.name(i)
    slabs = _merge(m["verts"], m["faces"], ASPHALT)
    if not slabs:
        return None
    dashes = _merge(m["verts"], m["faces"], {PAINT})
    # direction field: one (centroid, axis) per dash, else the whole strip's axis
    field = []
    for d in dashes:
        c = tuple(sum(v[k] for v in d)/len(d) for k in range(3))
        field.append((c, _pca_dir(d)))
    if not field:
        pts = [v for s in slabs for v in s]
        field.append((tuple(sum(v[k] for v in pts)/len(pts) for k in range(3)), _pca_dir(pts)))

    def along_dir(p):
        c, ax = min(field, key=lambda f: (f[0][0]-p[0])**2 + (f[0][2]-p[2])**2)
        return ax

    cnt = _edges(slabs)
    cross = []
    for e, n in cnt.items():
        a, b = tuple(e)
        d = _dir3(a, b); ax = along_dir(((a[0]+b[0])/2, 0, (a[2]+b[2])/2))
        horiz = math.hypot(d[0], d[2]) or 1e-9
        cosang = abs(d[0]*ax[0] + d[2]*ax[2]) / horiz
        if cosang < 0.5:                      # more across than along
            cross.append((a, b, n))
    if len(cross) < 2:
        return {"name": name, "obj": i, "class": "unmeasured", "why": "no cross-sections"}
    width = sorted(math.dist(a, b) for a, b, _n in cross)[len(cross)//2]
    cross = [(a, b, n) for a, b, n in cross if 0.7*width < math.dist(a, b) < 1.4*width]
    mids = {}
    for a, b, n in cross:
        mid = tuple((a[k]+b[k])/2 for k in range(3))
        key = (round(mid[0]), round(mid[1]), round(mid[2]))
        mids.setdefault(key, (mid, a, b, n))
    # order the cross-sections along the strip: walk from one end by nearest neighbour
    pts = list(mids.values())
    ends = [p for p in pts if p[3] == 1]           # boundary cross-sections
    start = min(pts, key=lambda p: (p[0][2], p[0][0])) if not ends else min(ends, key=lambda p: (p[0][2], p[0][0]))
    order, left = [start], [p for p in pts if p is not start]
    while left:
        last = order[-1][0]
        nxt = min(left, key=lambda p: math.dist(p[0], last))
        order.append(nxt); left.remove(nxt)
    cl = [p[0] for p in order]
    arc = [0.0]
    for a, b in zip(cl, cl[1:]):
        arc.append(arc[-1] + math.hypot(b[0]-a[0], b[2]-a[2]))
    # headings: inward at the entry, outward at the exit, from the neighbouring midpoint
    def hd(a, b):
        return math.degrees(math.atan2(b[0]-a[0], b[2]-a[2]))
    fit = _circle(cl)
    circ = fit is not None and fit[3] < 0.02*fit[2] and fit[2] < 200000   # on-circle within 2% of R

    def tangents():
        """Heading of travel at every centreline point."""
        if circ:
            cx, cz, r, _ = fit
            out = []
            for k, p in enumerate(cl):
                # sense of travel from the LOCAL secant (a hairpin's exit runs opposite its entry)
                a, b = cl[max(k-1, 0)], cl[min(k+1, len(cl)-1)]
                sec = hd(a, b)
                rad = math.degrees(math.atan2(p[0]-cx, p[2]-cz))
                t = rad + 90                       # tangent, one of two
                if math.cos(math.radians(t - sec)) < 0:
                    t -= 180
                out.append(((t + 180) % 360) - 180)
            return out
        # not a circle (banked pieces lift their outer edge, so the plan view is not
        # circular): use local secants
        return [hd(cl[max(k-1, 0)], cl[min(k+1, len(cl)-1)]) for k in range(len(cl))]
        return [hd(cl[0], cl[-1])] * len(cl)
    hs = tangents()
    # make the entry the end that faces +z more, so straights read as travel +z
    if math.cos(math.radians(hs[0])) < 0:
        cl.reverse(); order.reverse(); arc = [arc[-1]-a for a in reversed(arc)]
        hs = tangents()
    # the heading at each end is the normal of the END CROSS-SECTION itself - that
    # is the edge the next piece has to butt against - signed to agree with travel
    def end_heading(sec, ref):
        _mid, a, b, _n = sec
        h = math.degrees(math.atan2(b[0]-a[0], b[2]-a[2])) - 90
        return ((h + 180) % 360) - 180 if math.cos(math.radians(h - ref)) > 0 else ((h + 360) % 360) - 180
    h_in, h_out = end_heading(order[0], hs[0]), end_heading(order[-1], hs[-1])
    turn = ((h_out - h_in + 180) % 360) - 180
    chord = math.hypot(cl[-1][0]-cl[0][0], cl[-1][2]-cl[0][2])
    bank = []
    for (mid, a, b, n), h in zip(order, hs):
        # right-hand side of travel is +90 degrees from the heading
        rx, rz = math.sin(math.radians(h + 90)), math.cos(math.radians(h + 90))
        l, r = (a, b) if (b[0]-a[0])*rx + (b[2]-a[2])*rz > 0 else (b, a)
        bank.append(round(math.degrees(math.atan2(r[1]-l[1], math.hypot(r[0]-l[0], r[2]-l[2]))), 2))
    prof = [(round(s), round(-p[1])) for s, p in zip(arc, cl)]      # elevation positive DOWN
    out = {"name": name, "obj": i, "class": "road",
           "width": round(width), "lanes": max(1, round(width/1601)),
           "entry": [round(cl[0][0], 1), round(cl[0][2], 1), round(h_in, 2)],
           "exit": [round(cl[-1][0], 1), round(cl[-1][2], 1), round(h_out, 2)],
           "chord": round(chord, 1), "turn": round(turn, 2), "length": round(arc[-1], 1),
           "sections": len(cl), "profile": prof, "bank": bank,
           "elev_min": min(e for _s, e in prof), "elev_max": max(e for _s, e in prof),
           "radius_cat": w.catalogue(i)["radius"]}
    if fit:
        out["fit"] = {"cx": round(fit[0], 1), "cz": round(fit[1], 1), "radius": round(fit[2], 1), "rms": round(fit[3], 1), "used": circ}
    out["class"] = classify(name, out)
    dec = decode_name(name)
    if dec:
        t, R = dec
        out["design"] = {"turn": t, "radius": R, "chord": round(2*R*math.sin(math.radians(t)/2), 1),
                         "arc": round(R*math.radians(t), 1)}
    return out


def main():
    w = world.World()
    parts = {}
    for i in range(156):
        r = measure(w, i)
        if r:
            parts[r["name"]] = r
    json.dump(parts, open("parts.json", "w"), indent=1)
    for nm, p in parts.items():
        if p["class"] == "unmeasured":
            print("%-9s %s" % (nm, p["why"])); continue
        d = p.get("design")
        chk = ""
        if d:
            chk = "  design R %6.0f chord %7.1f turn %2d  (meas %+6.1f, %+5.2f deg%s)" % (d["radius"], d["chord"], d["turn"], p["chord"]-d["chord"], abs(p["turn"])-d["turn"],
                   (", fit R %.0f rms %.1f" % (p["fit"]["radius"], p["fit"]["rms"])) if "fit" in p else "")
        print("%-9s %-8s w%5d n%2d  entry (%7.1f,%8.1f,%7.2f) exit (%7.1f,%8.1f,%7.2f) chord %7.1f turn %+7.2f  elev %d..%d bank %s%s"
              % (nm, p["class"], p["width"], p["sections"], *p["entry"], *p["exit"], p["chord"], p["turn"], p["elev_min"], p["elev_max"],
                 ("%+.1f..%+.1f" % (min(p["bank"]), max(p["bank"]))) if any(abs(b) > 1 for b in p["bank"]) else "0", chk))
    print("%d pieces -> parts.json" % len(parts))


if __name__ == "__main__":
    main()
