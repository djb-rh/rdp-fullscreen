#!/usr/bin/env python3
"""Recognise a world's road placements as chained parts.

    python3 -m rdtrack.pieces racedriv.zip [A|B|C]

Every placement whose object is a measured road part gets its two end poses
(from parts.json, in model coordinates) carried into the world through the
placement's matrix and position.  Ends that meet - within GAP units and with
facing headings within KINK degrees - are joints; the joints knit the pieces
into chains.  What comes out is how Atari's tool actually chained the pieces:
the real joint gaps and kinks, the dead ends (junctions into pieces we do not
measure yet), and the chains themselves.
"""
import json, math, sys, collections
from . import dsk

GAP = 800       # units: ends closer than this are candidates
KINK = 8.0      # degrees: facing headings within this
OVERLAP = 8000  # units: a collinear end this far along another piece's end still counts
ROADCLASS = {"road", "bridge", "cutting", "banked", "deck", "slab"}


def world_pose(p, mx, mz, mh):
    """Model (x, z, heading) -> world through placement p (row-major 1.14 matrix)."""
    m = p["m"]
    X = p["x"] + (m[0]*mx + m[2]*mz) / 16384.0
    Z = p["z"] + (m[6]*mx + m[8]*mz) / 16384.0
    dx, dz = math.sin(math.radians(mh)), math.cos(math.radians(mh))
    wx = (m[0]*dx + m[2]*dz) / 16384.0
    wz = (m[6]*dx + m[8]*dz) / 16384.0
    return X, Z, math.degrees(math.atan2(wx, wz))


def ends(parts, world, names):
    """Per placement: [(x, z, outward heading, 'entry'|'exit')] for road parts."""
    out = {}
    for n, p in enumerate(world["placements"]):
        nm = names.get(p["obj"])
        part = parts.get(nm)
        if not part or part.get("class") not in ROADCLASS:
            continue
        ex, ez, eh = world_pose(p, *part["entry"])
        xx, xz, xh = world_pose(p, *part["exit"])
        out[n] = {"name": nm, "ends": [(ex, ez, (eh + 180) % 360, "entry"), (xx, xz, xh % 360, "exit")]}
    return out


def joints(E):
    """Match ends pairwise: (rec a, end i, rec b, end j, gap, kink)."""
    allends = [(n, i, e) for n, d in E.items() for i, e in enumerate(d["ends"])]
    used, out = set(), []
    for k, (n, i, e) in enumerate(allends):
        if (n, i) in used:
            continue
        best = None
        for m, j, f in allends:
            if m == n or (m, j) in used:
                continue
            gap = math.hypot(e[0]-f[0], e[1]-f[1])
            if gap > GAP:
                continue
            kink = abs(((e[2] - f[2] - 180 + 180) % 360) - 180)      # facing = 180 apart
            if kink > KINK:
                continue
            if best is None or gap < best[4]:
                best = (n, i, m, j, gap, kink)
        if best:
            out.append(best); used.add((n, i)); used.add((best[2], best[3]))
    # second pass: collinear OVERLAPS.  Stock lets a branch's end sit thousands of
    # units into a straight it rejoins (rec 73 -> DOTLINE 69 by 2940 in world A), so
    # an end that lies ON another piece's end line, facing it, within OVERLAP along,
    # is a joint too - flagged so the editor can tighten it.
    for k, (n, i, e) in enumerate(allends):
        if (n, i) in used:
            continue
        best = None
        for m, j, f in allends:
            if m == n:
                continue
            kink = abs(((e[2] - f[2] - 180 + 180) % 360) - 180)
            if kink > 4:
                continue
            fx, fz = math.sin(math.radians(f[2])), math.cos(math.radians(f[2]))
            dx, dz = e[0]-f[0], e[1]-f[1]
            along = dx*fx + dz*fz; lat = abs(dx*fz - dz*fx)
            if lat > 300 or abs(along) > OVERLAP:
                continue
            if best is None or abs(along) < abs(best[4]):
                best = (n, i, m, j, along, kink, "overlap")
        if best:
            out.append(best); used.add((n, i))
    return out


def chains(E, J):
    adj = collections.defaultdict(list)
    for n, i, m, j, gap, kink, *_ in J:
        adj[n].append(m); adj[m].append(n)
    seen, out = set(), []
    for n in E:
        if n in seen:
            continue
        # walk to an end of the component, then along it
        comp, stack = [], [n]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x); stack.extend(adj[x])
        out.append(comp)
    return out


def main():
    src = sys.argv[1]; wid = sys.argv[2] if len(sys.argv) > 2 else "A"
    parts = json.load(open("parts.json"))
    import world as W
    w = W.World(); names = {i: w.name(i) for i in range(156)}
    D = dsk.Dsk(dsk.load(src))
    world = list(D.worlds.values())["ABC".index(wid)]
    E = ends(parts, world, names)
    J = joints(E)
    print("world %s: %d placements, %d are measured road parts: %s" % (wid, len(world["placements"]), len(E),
          dict(collections.Counter(d["name"] for d in E.values()).most_common())))
    ov = [j for j in J if len(j) > 6]; J0 = [j for j in J if len(j) == 6]
    print("%d butt joints; gap median %.0f max %.0f; kink median %.2f max %.2f deg; plus %d overlap joints" % (
        len(J0), sorted(j[4] for j in J0)[len(J0)//2], max(j[4] for j in J0), sorted(j[5] for j in J0)[len(J0)//2], max(j[5] for j in J0), len(ov)))
    for n, i, m, j, along, kink, _o in ov:
        print("   overlap: rec %3d %-8s %-5s sits %6.0f along rec %3d %-8s %-5s (kink %.1f)" % (n, E[n]["name"], E[n]["ends"][i][3], along, m, E[m]["name"], E[m]["ends"][j][3], kink))
    J = J0 + ov
    hist = collections.Counter(int(j[5]) for j in J0)
    print("kink histogram (deg -> joints):", dict(sorted(hist.items())))
    print("joints with kink >= 1 deg or gap >= 100:")
    for n, i, m, j, gap, kink in sorted(J0, key=lambda t: -t[5]):
        if kink >= 1 or gap >= 100:
            print("   rec %3d %-8s %-5s <-> rec %3d %-8s %-5s  gap %4.0f kink %5.2f" % (n, E[n]["name"], E[n]["ends"][i][3], m, E[m]["name"], E[m]["ends"][j][3], gap, kink))
    matched = {(n, i) for n, i, m, j, g, k, *_ in J} | {(m, j) for n, i, m, j, g, k, *_ in J}
    loose = [(n, i) for n, d in E.items() for i in range(2) if (n, i) not in matched]
    print("%d loose ends:" % len(loose))
    for n, i in loose:
        e = E[n]["ends"][i]
        near = min(((math.hypot(e[0]-f[0], e[1]-f[1]), m, f[3]) for m, d in E.items() if m != n for f in d["ends"]), default=None)
        print("   rec %3d %-8s %-5s at (%7.0f,%7.0f) heading %6.1f; nearest other end rec %d %s at %.0f" % (n, E[n]["name"], e[3], e[0], e[1], e[2], near[1], near[2], near[0]))
    C = chains(E, J)
    print("chains: %s" % sorted((len(c) for c in C), reverse=True))
    # walk each chain in order, noting which end we enter each piece by
    link = {}
    for n, i, m, j, gap, kink, *_ in J:
        link.setdefault((n, i), (m, j)); link.setdefault((m, j), (n, i))
    for comp in sorted(C, key=len, reverse=True):
        if len(comp) < 3:
            continue
        loose = [(n, i) for n in comp for i in range(2) if (n, i) not in link]
        n, i = loose[0] if loose else (comp[0], 0)          # start at a loose end, else anywhere (a loop)
        seq, seen = [], set()
        while n not in seen:
            seen.add(n)
            seq.append("%d:%s%s" % (n, E[n]["name"], "" if i == 0 else "(rev)"))
            other = (n, 1 - i)
            if other not in link:
                break
            n, i = link[other]
        print("chain of %d%s: %s" % (len(comp), " (loop)" if not loose else "", " ".join(seq)))
    # rotation quantisation of the road placements
    res = collections.Counter()
    for n in E:
        m = world["placements"][n]["m"]
        h = math.degrees(math.atan2(m[2], m[0])) % 360
        for q in (360/256, 360/512, 1.0, 0.5, 0.1):
            r = abs((h / q) - round(h / q))
            res[q] += r < 0.05
    print("road placement headings on a grid (of %d): %s" % (len(E), {"%.3f deg" % q: c for q, c in res.items()}))


if __name__ == "__main__":
    main()
