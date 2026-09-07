"""Turn the fetched VIR centreline into game-format track geometry.

Units follow the ROM: 40 units per foot (1 unit = 0.3 in = 7.62 mm), Y up.
Vertices are s16, so no single model may reach beyond +/-32767 units (250 m)
from its own origin - that is what forces the track to be cut into segments,
exactly as the original game cuts its track into road pieces.

  python3 vir_build.py            -> vir_world.obj, vir_placements.json
"""
import json, math, sys
import vir_extras as X
import vir_structures as S

U_PER_M = 3.280839895 * 40.0        # 131.234 units per metre
WIDTH_FT = 40.0                     # VIR is ~40 ft; also exactly ROAD1's width
HALF = WIDTH_FT * 40.0 / 2.0        # 800 units
SEG_M = 175.0                       # metres of track per model; shorter pieces
                                    # pack far better into the fragmented free
                                    # space Super Stunt leaves behind
S16 = 32767

def smooth(v, k=2):
    n = len(v)
    return [sum(v[(i+j) % n] for j in range(-k, k+1)) / (2*k+1) for i in range(n)]

def build():
    d = json.load(open("vir_centreline.json"))
    xy, ele, step = d["xy"], d["ele"], d["step"]
    n = len(xy)
    ele = smooth(smooth(ele))            # 10 m DEM posts are noisy for a road
    # centreline in game units, Y up, closed loop
    C = [(xy[i][0]*U_PER_M, ele[i]*U_PER_M, xy[i][1]*U_PER_M) for i in range(n)]
    # left/right edges from the local tangent
    L, Rt = [], []
    for i in range(n):
        a, b = C[(i-1) % n], C[(i+1) % n]
        tx, tz = b[0]-a[0], b[2]-a[2]
        m = math.hypot(tx, tz) or 1.0
        px, pz = -tz/m, tx/m
        L.append((C[i][0]+px*HALF, C[i][1], C[i][2]+pz*HALF))
        Rt.append((C[i][0]-px*HALF, C[i][1], C[i][2]-pz*HALF))
    per = max(2, int(round(SEG_M / step)))
    segs = []
    i = 0
    while i < n:
        j = min(i + per, n)
        idx = list(range(i, j))
        if j == n:
            idx.append(0)                # close the loop
        elif j < n:
            idx.append(j)                # share the seam vertex
        pts = [L[k % n] for k in idx] + [Rt[k % n] for k in idx]
        ox = sum(p[0] for p in pts)/len(pts)
        oy = sum(p[1] for p in pts)/len(pts)
        oz = sum(p[2] for p in pts)/len(pts)
        verts, m = [], len(idx)
        for k in idx:
            verts.append((L[k % n][0]-ox, L[k % n][1]-oy, L[k % n][2]-oz))
        for k in idx:
            verts.append((Rt[k % n][0]-ox, Rt[k % n][1]-oy, Rt[k % n][2]-oz))
        faces = [(a, a+1, m+a+1, m+a) for a in range(m-1)]
        segs.append({"origin": (ox, oy, oz), "verts": verts, "faces": faces,
                     "n_cross": m})
        i = j
    return d, C, segs

def report(d, segs):
    worst = 0; nv = nf = 0
    for s in segs:
        nv += len(s["verts"]); nf += len(s["faces"])
        worst = max(worst, max(max(abs(c) for c in v) for v in s["verts"]))
    print("VIR Full Course: %.0f m (%.3f mi), %d segments" %
          (d["length_m"], d["length_m"]/1609.344, len(segs)))
    print("  %d vertices, %d faces total" % (nv, nf))
    print("  largest vertex coordinate in any segment: %d units (%.0f m) - s16 limit %d %s"
          % (worst, worst/U_PER_M, S16, "OK" if worst <= S16 else "OVERFLOW"))
    xs = [s["origin"][0] for s in segs]; zs = [s["origin"][2] for s in segs]
    ys = [s["origin"][1] for s in segs]
    print("  world extent %.0f x %.0f units (%.2f x %.2f km); elevation span %.0f ft"
          % (max(xs)-min(xs), max(zs)-min(zs),
             (max(xs)-min(xs))/U_PER_M/1000, (max(zs)-min(zs))/U_PER_M/1000,
             (max(ys)-min(ys))/40.0))

MATS = {"asphalt": (0.20, 0.20, 0.22), "bark": (0.24, 0.17, 0.11),
        "leaf": (0.20, 0.36, 0.14), "concrete": (0.62, 0.61, 0.57),
        "building": (0.46, 0.42, 0.38), "fence": (0.36, 0.38, 0.40)}


def yaw_matrix(dx, dz):
    """1.14 fixed-point rotation about Y, the form every placement record uses."""
    m = math.hypot(dx, dz) or 1.0
    c, s = dx / m, dz / m          # local +X -> (dx, 0, dz)
    q = lambda v: int(round(v * 16384))
    return [q(c), 0, q(-s), 0, 16384, 0, q(s), 0, q(c)]


def extras(d, C):
    """The oak at Oak Tree Curve's apex, and the North Paddock Road bridge."""
    f = json.load(open("vir_features.json"))
    n = len(C)
    out = []

    # --- the oak ----------------------------------------------------------
    i = f["apex"]
    a, b = C[(i - 3) % n], C[(i + 3) % n]
    tx, tz = b[0] - a[0], b[2] - a[2]
    m = math.hypot(tx, tz) or 1.0
    # The apex is the inside of the corner. f["side"] is +1 when the track
    # bends left, and (-tz, tx) is the left perpendicular, so the inside is
    # simply +side. (This was negated once, which put the tree on the outside.)
    sgn = f["side"]
    px, pz = (-tz / m) * sgn, (tx / m) * sgn
    STAND_M = 18.5                       # trunk this far from the centreline
    ox = C[i][0] + px * STAND_M * U_PER_M
    oz = C[i][2] + pz * STAND_M * U_PER_M
    t = X.oak(lean_dir=(-px, -pz))       # lean back over the track
    out.append({"name": "OAKTREE", "origin": (ox, C[i][1], oz),
                "verts": t["verts"], "faces": t["faces"], "mats": t["mats"],
                "matrix": [16384,0,0, 0,16384,0, 0,0,16384],
                "note": "trunk %.0f m from the centreline, on the inside "
                        "(apex side) of the turn" % STAND_M})

    # --- the bridge -------------------------------------------------------
    BP = f["bridge_xy"]
    (x0, z0), (x1, z1) = BP[0], BP[-1]
    span = math.dist((x0, z0), (x1, z1))
    # Centre the span on where the deck line actually crosses the centreline,
    # so the abutments sit symmetrically clear of both track edges.
    dx, dz = x1 - x0, z1 - z0
    L2 = dx * dx + dz * dz or 1.0
    def foot(p):
        t = max(0.0, min(1.0, ((p[0]-x0)*dx + (p[1]-z0)*dz) / L2))
        return math.dist((x0 + t*dx, z0 + t*dz), p), t
    k = min(range(n), key=lambda j: foot((C[j][0]/U_PER_M, C[j][2]/U_PER_M))[0])
    _, t = foot((C[k][0]/U_PER_M, C[k][2]/U_PER_M))
    cx = (x0 + t * dx) * U_PER_M
    cz = (z0 + t * dz) * U_PER_M
    br = X.bridge(span, clear_m=6.0)
    out.append({"name": "BRIDGE", "origin": (cx, C[k][1], cz),
                "verts": br["verts"], "faces": br["faces"], "mats": br["mats"],
                "matrix": yaw_matrix(x1 - x0, z1 - z0),
                "note": "%.0f m span, deck 6.0 m over the track" % span})
    return out


def rotate(v, M):
    return (sum(M[0+j] * v[j] for j in range(3)) / 16384.0,
            sum(M[3+j] * v[j] for j in range(3)) / 16384.0,
            sum(M[6+j] * v[j] for j in range(3)) / 16384.0)


def write_obj(path, models, scale=1.0 / 256.0):
    with open(path, "w") as f:
        f.write("# Virginia International Raceway, Full Course\n")
        f.write("# centreline: OpenStreetMap contributors (ODbL)\n")
        f.write("# elevation:  USGS 3DEP 10 m NED via OpenTopoData\n")
        f.write("# units: 40 per foot (1 unit = 0.3 in), Y up - Race Drivin' convention\n")
        f.write("mtllib %s\n" % path.replace(".obj", ".mtl").split("/")[-1])
        base = 0
        for mo in models:
            ox, oy, oz = mo["origin"]
            M = mo["matrix"]
            f.write("o %s\n" % mo["name"])
            for v in mo["verts"]:
                r = rotate(v, M)
                f.write("v %.4f %.4f %.4f\n" % ((r[0]+ox)*scale, (r[1]+oy)*scale,
                                               -(r[2]+oz)*scale))
            last = None
            for fc, mt in zip(mo["faces"], mo["mats"]):
                if mt != last:
                    f.write("usemtl %s\n" % mt); last = mt
                f.write("f " + " ".join(str(base+i+1) for i in fc) + "\n")
            base += len(mo["verts"])
    with open(path.replace(".obj", ".mtl"), "w") as f:
        for k, (r, g, b) in MATS.items():
            f.write("newmtl %s\nKd %.3f %.3f %.3f\n\n" % (k, r, g, b))


def write_placements(path, models):
    out = []
    for mo in models:
        ox, oy, oz = mo["origin"]
        out.append({"name": mo["name"], "matrix": mo["matrix"],
                    "x": int(round(ox)), "y": int(round(oy)), "z": int(round(oz)),
                    "nverts": len(mo["verts"]), "nfaces": len(mo["faces"]),
                    "note": mo.get("note", "")})
    json.dump(out, open(path, "w"), indent=1)


def resample_line(P, step, closed=False):
    out, carry = [], 0.0
    rng = range(len(P)) if closed else range(len(P) - 1)
    for i in rng:
        a, b = P[i], P[(i + 1) % len(P)]
        seg = math.dist(a, b)
        if seg < 1e-9:
            continue
        t = carry
        while t < seg:
            f = t / seg
            out.append((a[0] + (b[0]-a[0])*f, a[1] + (b[1]-a[1])*f))
            t += step
        carry = t - seg
    out.append(P[-1])
    return out


def _runs(flags, minlen=2):
    """Contiguous index runs where flags[i] is true."""
    out, cur = [], []
    for i, ok in enumerate(flags):
        if ok:
            cur.append(i)
        elif cur:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [r for r in out if len(r) >= minlen]


def structures(d, C):
    """Pit lane and its wall, plus the buildings and fences OSM has mapped."""
    lat0, lon0 = d["lat0"], d["lon0"]
    CLm = [(p[0] / U_PER_M, p[2] / U_PER_M) for p in C]

    def xy(la, lo):
        return (math.radians(lo - lon0) * S.R * math.cos(math.radians(lat0)),
                math.radians(la - lat0) * S.R)

    def dist_to_track(P):
        return min(min(math.dist(p, q) for q in CLm) for p in P)

    osm = json.load(open("vir_osm_raw.json"))
    bb = json.load(open("vir_bb_raw.json"))
    models = []
    want = []

    pit = [e for e in osm["elements"]
           if e.get("tags", {}).get("name") == "Pit Lane"][0]
    PL = resample_line([xy(p["lat"], p["lon"]) for p in pit["geometry"]], 10.0)
    want += [(round(p[0], 1), round(p[1], 1)) for p in PL]

    blds = [e for e in bb["elements"] if "building" in e.get("tags", {})
            and len(e.get("geometry", [])) > 3]
    blds = [e for e in blds
            if dist_to_track([xy(p["lat"], p["lon"]) for p in e["geometry"]]) < 250]
    cents = []
    for e in blds:
        P = [xy(p["lat"], p["lon"]) for p in e["geometry"]]
        c = (sum(p[0] for p in P)/len(P), sum(p[1] for p in P)/len(P))
        cents.append(c); want.append((round(c[0], 1), round(c[1], 1)))

    bars = [e for e in bb["elements"] if "barrier" in e.get("tags", {})
            and len(e.get("geometry", [])) > 1]
    bars = [e for e in bars
            if dist_to_track([xy(p["lat"], p["lon"]) for p in e["geometry"]]) < 250]
    barP = []
    for e in bars:
        P = resample_line([xy(p["lat"], p["lon"]) for p in e["geometry"]], 25.0)
        barP.append(P); want += [(round(p[0], 1), round(p[1], 1)) for p in P]

    print("  fetching ground elevation for %d points ..." % len(set(want)))
    G = S.ground(sorted(set(want)), lat0, lon0)
    g = lambda p: G[(round(p[0], 1), round(p[1], 1))] * U_PER_M

    # --- pit lane surface and its wall -----------------------------------
    # The OSM Pit Lane way merges with the racing line at both ends - that is
    # real, it is how cars get in and out. So the pit SURFACE is allowed to run
    # the whole length (tapering so it never overlaps the racing surface), but
    # the WALL is built only along the contiguous stretch where it genuinely
    # clears the track edge. Without that trim the wall crosses the racing line
    # at the pit entry and exit, and you drive straight into it.
    TRACK_EDGE = 6.1
    CLEAR = 1.0
    left, right, keep = [], [], []
    for i, p in enumerate(PL):
        a, b = PL[max(0, i-1)], PL[min(len(PL)-1, i+1)]
        dx, dz = b[0]-a[0], b[1]-a[1]
        m = math.hypot(dx, dz) or 1.0
        px, pz = -dz/m, dx/m
        k = min(range(len(CLm)), key=lambda j: math.dist(CLm[j], p))
        toward = (CLm[k][0]-p[0], CLm[k][1]-p[1])
        if px*toward[0] + pz*toward[1] < 0:          # make (px,pz) face the track
            px, pz = -px, -pz
        off = math.dist(CLm[k], p)
        inner = min(S.PIT_HALF_M, max(0.0, off - (TRACK_EDGE + 0.3)))
        y = g(p)
        left.append(((p[0]+px*inner)*U_PER_M, y, (p[1]+pz*inner)*U_PER_M))
        right.append(((p[0]-px*S.PIT_HALF_M)*U_PER_M, y,
                      (p[1]-pz*S.PIT_HALF_M)*U_PER_M))
        keep.append(off - S.PIT_HALF_M >= TRACK_EDGE + CLEAR)
    # The surface too must stop at the track edge rather than lie on top of it;
    # a pit lane that overlaps the racing surface z-fights and reads as a seam.
    onpit = [math.dist(CLm[min(range(len(CLm)), key=lambda j: math.dist(CLm[j], p))], p)
             >= TRACK_EDGE + 0.4 for p in PL]
    for r in _runs(onpit):
        models += S.strip("PITLANE", [left[i] for i in r], [right[i] for i in r],
                          "asphalt")
    runs = _runs(keep)
    if runs:
        best = max(runs, key=len)
        print("  pit wall spans pit-lane points %d-%d of %d (%.0f m); "
              "entry and exit left open"
              % (best[0], best[-1], len(PL), (best[-1]-best[0]) * 10.0))
        models += S.wall("PITWALL", [left[i] for i in best],
                         S.PIT_WALL_H, S.PIT_WALL_T, "concrete")

    # --- buildings --------------------------------------------------------
    for e, c in zip(blds, cents):
        P = [xy(p["lat"], p["lon"]) for p in e["geometry"]]
        area = abs(sum(P[i][0]*P[(i+1) % len(P)][1] - P[(i+1) % len(P)][0]*P[i][1]
                       for i in range(len(P)))) / 2
        h = next(v for lim, v in S.HEIGHTS if area < lim)
        models.append(S.extrude("BLDG%02d" % len(models), 
                                [(p[0]*U_PER_M, p[1]*U_PER_M) for p in P],
                                g(c), h, "building"))

    # --- fences and walls -------------------------------------------------
    # Some mapped fences run straight across the circuit - real paddock
    # crossings, but solid obstacles if built. Keep only the stretches that
    # stay clear of the racing surface.
    dropped = 0
    for e, P in zip(bars, barP):
        kind = e["tags"]["barrier"]
        clear = [math.dist(CLm[min(range(len(CLm)),
                 key=lambda j: math.dist(CLm[j], p))], p) >= 8.0 for p in P]
        dropped += sum(1 for x in clear if not x)
        for r in _runs(clear):
            path = [(P[i][0]*U_PER_M, g(P[i]), P[i][1]*U_PER_M) for i in r]
            if kind == "wall":                       # a real wall has thickness
                models += S.wall("FENCE%02d_" % len(models), path,
                                 S.FENCE_H[kind], S.FENCE_T[kind], "concrete")
            else:
                models += S.ribbon("FENCE%02d_" % len(models), path,
                                   S.FENCE_H.get(kind, 2.0), "fence")
    if dropped:
        print("  dropped %d fence points that crossed the racing surface" % dropped)
    return models


if __name__ == "__main__":
    d, C, segs = build()
    models = []
    for i, s in enumerate(segs):
        models.append({"name": "VIRROAD%02d" % i, "origin": s["origin"],
                       "verts": s["verts"], "faces": s["faces"],
                       "mats": ["asphalt"] * len(s["faces"]),
                       "matrix": [16384,0,0, 0,16384,0, 0,0,16384]})
    models += extras(d, C)
    models += structures(d, C)
    report(d, segs)
    worst = max(max(max(abs(c) for c in v) for v in m["verts"]) for m in models)
    print("  every model within s16: largest coordinate %d of %d" % (worst, S16))
    for m in models[len(segs):]:
        print("  %-8s %3d verts %3d faces  %s" %
              (m["name"], len(m["verts"]), len(m["faces"]), m.get("note", "")))
    write_obj("vir_world.obj", models)
    write_placements("vir_placements.json", models)
    print("wrote vir_world.obj, vir_world.mtl, vir_placements.json (%d models)"
          % len(models))
