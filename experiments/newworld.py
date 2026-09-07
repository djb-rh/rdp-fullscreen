"""Render the edited original speed track: existing world minus the deleted
placements, plus the new loop, its bridge and the new building.

Writes newworld.obj / .mtl for viewing. Nothing here touches a ROM.
"""
import json, math, world, newloop

U = newloop.U
HALF = newloop.ROAD_HALF


def ribbon(pts, ys, half):
    """Road surface: two edges from the local tangent, quads between."""
    L, R = [], []
    n = len(pts)
    for i in range(n):
        a, b = pts[max(0, i-1)], pts[min(n-1, i+1)]
        dx, dz = b[0]-a[0], b[1]-a[1]
        m = math.hypot(dx, dz) or 1.0
        px, pz = -dz/m*half, dx/m*half
        L.append((pts[i][0]+px, ys[i], pts[i][1]+pz))
        R.append((pts[i][0]-px, ys[i], pts[i][1]-pz))
    V = L + R
    F = [(i, i+1, n+i+1, n+i) for i in range(n-1)]
    return V, F


def box(cx, cy, cz, sx, sy, sz):
    V = [(cx-sx, cy,    cz-sz), (cx+sx, cy,    cz-sz),
         (cx+sx, cy,    cz+sz), (cx-sx, cy,    cz+sz),
         (cx-sx, cy+sy, cz-sz), (cx+sx, cy+sy, cz-sz),
         (cx+sx, cy+sy, cz+sz), (cx-sx, cy+sy, cz+sz)]
    F = [(4,5,6,7),(0,3,2,1),(0,1,5,4),(2,3,7,6),(1,2,6,5),(3,0,4,7)]
    return V, F


def main():
    w = world.World()
    dele = set(json.load(open("delete_list.json")))
    pts, ys, (ci, cj, cp, cd) = newloop.build()
    bld = json.load(open("newloop_building.json"))

    objs = []          # (name, verts, faces, material)
    # --- existing world, minus the deletions ---------------------------------
    kept = 0
    for r in range(193):
        if r in dele:
            continue
        p = w.placement(r); mo = w.model(p["obj"])
        if not mo or not mo["faces"]:
            continue
        t = (p["x"], p["y"], p["z"])
        V = [world.transform(v, p["m"], t) for v in mo["verts"]]
        objs.append(("%03d_%s" % (r, p["name"]), V,
                     [f for f, _c in mo["faces"]], "existing"))
        kept += 1
    # --- the new road --------------------------------------------------------
    V, F = ribbon(pts, ys, HALF)
    objs.append(("NEWLOOP_road", [(v[0], v[1], v[2]) for v in V], F, "newroad"))
    # --- bridge: parapets alongside the elevated deck, piers beside the road --
    n = len(pts)
    span = 9                                  # samples either side of the crossing
    for k in range(cj-span, cj+span+1):
        if not (0 <= k < n) or ys[k] < 1.5*U:
            continue
        a, b = pts[max(0,k-1)], pts[min(n-1,k+1)]
        dx, dz = b[0]-a[0], b[1]-a[1]
        m = math.hypot(dx, dz) or 1.0
        tx, tz = dx/m, dz/m                    # along the road
        px, pz = -tz, tx                       # across it
        for s_ in (-1, 1):                     # a parapet each side
            ex = pts[k][0] + px*HALF*s_
            ez = pts[k][1] + pz*HALF*s_
            V2 = [(ex - tx*600 - px*90, ys[k],          ez - tz*600 - pz*90),
                  (ex + tx*600 - px*90, ys[k],          ez + tz*600 - pz*90),
                  (ex + tx*600 + px*90, ys[k],          ez + tz*600 + pz*90),
                  (ex - tx*600 + px*90, ys[k],          ez - tz*600 + pz*90),
                  (ex - tx*600 - px*90, ys[k]+1.0*U,    ez - tz*600 - pz*90),
                  (ex + tx*600 - px*90, ys[k]+1.0*U,    ez + tz*600 - pz*90),
                  (ex + tx*600 + px*90, ys[k]+1.0*U,    ez + tz*600 + pz*90),
                  (ex - tx*600 + px*90, ys[k]+1.0*U,    ez - tz*600 + pz*90)]
            F2 = [(4,5,6,7),(0,3,2,1),(0,1,5,4),(2,3,7,6),(1,2,6,5),(3,0,4,7)]
            objs.append(("NEWLOOP_parapet_%d_%d" % (k, s_+1), V2, F2, "concrete"))
    # piers: set back along the deck so they clear the road passing underneath
    a, b = pts[cj-1], pts[cj+1]
    dx, dz = b[0]-a[0], b[1]-a[1]
    m = math.hypot(dx, dz) or 1.0
    tx, tz = dx/m, dz/m
    for s_ in (-1, 1):
        k = cj + s_*6
        if not (0 <= k < n):
            continue
        V2, F2 = box(pts[k][0], 0, pts[k][1], 420, max(ys[k], 1.0), 420)
        objs.append(("NEWLOOP_pier%d" % (s_+1), V2, F2, "concrete"))

    # --- the building --------------------------------------------------------
    cx, cz = bld["centre"]; sx, sz = bld["size"][0]/2, bld["size"][1]/2
    V3, F3 = box(cx, 0, cz, sx, 9.0*U, sz)
    objs.append(("NEWLOOP_building", V3, F3, "building"))

    MAT = {"existing": (0.26,0.27,0.30), "newroad": (0.20,0.44,0.24),
           "concrete": (0.62,0.61,0.57), "building": (0.46,0.42,0.38)}
    scale = 1.0/256.0
    with open("newworld.obj", "w") as f:
        f.write("# edited original speed track: %d kept, %d deleted, new loop %.0f m\n"
                % (kept, len(dele), sum(math.dist(pts[i],pts[i+1])
                                        for i in range(len(pts)-1))/U))
        f.write("mtllib newworld.mtl\n")
        base = 0
        for name, V, F, mat in objs:
            f.write("o %s\n" % name)
            for x, y, z in V:
                f.write("v %.4f %.4f %.4f\n" % (x*scale, y*scale, -z*scale))
            f.write("usemtl %s\n" % mat)
            for face in F:
                f.write("f " + " ".join(str(base+i+1) for i in face) + "\n")
            base += len(V)
    with open("newworld.mtl", "w") as f:
        for k, (r, g, b) in MAT.items():
            f.write("newmtl %s\nKd %.3f %.3f %.3f\n\n" % (k, r, g, b))
    nf = sum(len(F) for _n, _V, F, _m in objs)
    print("kept %d placements, deleted %d" % (kept, len(dele)))
    print("new road: %d samples, bridge deck %.1f m up at (%.0f, %.0f); "
          "legs %.0f m apart there"
          % (len(pts), ys[cj]/U, pts[cj][0], pts[cj][1], cd/U))
    print("wrote newworld.obj  (%d objects, %d faces)" % (len(objs), nf))


if __name__ == "__main__":
    main()
