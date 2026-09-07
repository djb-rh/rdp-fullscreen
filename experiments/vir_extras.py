"""The oak at Oak Tree Curve, and the North Paddock Road bridge.

Both are built in the ROM's units: 40 units per foot, Y up. Face counts are kept
near the game's own objects (BARN is 53 faces, COW 96) so the result is in
period, not a modern mesh dropped into a 1990 renderer.
"""
import json, math

U_PER_M = 3.280839895 * 40.0

def ico(cx, cy, cz, rx, ry, rz):
    """A 12-vertex, 20-face icosahedron, scaled to an ellipsoid."""
    t = (1 + 5 ** 0.5) / 2
    raw = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
           (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
           (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    n = math.sqrt(1 + t * t)
    V = [(cx + x / n * rx, cy + y / n * ry, cz + z / n * rz) for x, y, z in raw]
    F = [(0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),(1,5,9),(5,11,4),(11,10,2),
         (10,7,6),(7,1,8),(3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),(4,9,5),
         (2,4,11),(6,2,10),(8,6,7),(9,8,1)]
    return V, F

def tube(path, radii, sides):
    """A tapered prism following `path`, one radius per ring."""
    V, F = [], []
    for k, (c, r) in enumerate(zip(path, radii)):
        for s in range(sides):
            a = 2 * math.pi * s / sides
            V.append((c[0] + math.cos(a) * r, c[1], c[2] + math.sin(a) * r))
    for k in range(len(path) - 1):
        for s in range(sides):
            s2 = (s + 1) % sides
            F.append((k*sides+s, k*sides+s2, (k+1)*sides+s2, (k+1)*sides+s))
    return V, F

def oak(height_m=19.0, spread_m=22.0, lean_m=2.6, lean_dir=(1.0, 0.0)):
    """A mature white oak: short thick bole, heavy low limbs, a canopy broader
    than it is tall. Leaning `lean_m` toward lean_dir so it overhangs."""
    H = height_m * U_PER_M
    S = spread_m * U_PER_M
    lx, lz = lean_dir[0], lean_dir[1]
    m = math.hypot(lx, lz) or 1.0
    lx, lz = lx / m, lz / m
    LE = lean_m * U_PER_M
    verts, faces, mats = [], [], []

    def add(V, F, mat):
        b = len(verts)
        verts.extend(V)
        for f in F:
            faces.append(tuple(b + i for i in f)); mats.append(mat)

    bole = 0.42 * H                                  # oaks branch low
    path = [(0, 0, 0), (0, bole * 0.5, 0), (0, bole, 0)]
    path = [(p[0] + lx * LE * (p[1] / H), p[1], p[2] + lz * LE * (p[1] / H))
            for p in path]
    r0 = 0.65 * U_PER_M
    add(*tube(path, [r0, r0 * 0.78, r0 * 0.62], 8), "bark")

    top = path[-1]
    blobs = [(0.30, 0.62, 1.00), (-0.34, 0.50, 0.74), (0.05, 0.34, 0.80)]
    for i, (dx, dy, sc) in enumerate(blobs):
        cx = top[0] + dx * S * 0.5 + lx * LE * 0.6
        cy = top[1] + dy * (H - bole) + (H - bole) * 0.18
        cz = top[2] + (0.28 if i == 1 else -0.22) * S * 0.5 + lz * LE * 0.6
        limb = [(top[0], top[1], top[2]),
                ((top[0] + cx) / 2, (top[1] + cy) / 2, (top[2] + cz) / 2)]
        add(*tube(limb, [r0 * 0.5, r0 * 0.28], 6), "bark")
        add(*ico(cx, cy, cz, S * 0.30 * sc, (H - bole) * 0.30 * sc, S * 0.30 * sc),
            "leaf")
    return {"verts": verts, "faces": faces, "mats": mats,
            "height_units": H, "spread_units": S}

def bridge(span_m, deck_w_m=7.0, clear_m=5.5, thick_m=0.9, drop_m=6.5):
    """A flat deck with two abutments. Origin at deck centre, X along the span."""
    L = span_m * U_PER_M / 2
    W = deck_w_m * U_PER_M / 2
    T = thick_m * U_PER_M
    Y = clear_m * U_PER_M
    D = drop_m * U_PER_M
    verts, faces, mats = [], [], []

    def box(x0, x1, y0, y1, z0, z1, mat):
        b = len(verts)
        verts.extend([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1),
                      (x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)])
        for f in [(4,5,6,7),(0,3,2,1),(0,1,5,4),(2,3,7,6),(1,2,6,5),(3,0,4,7)]:
            faces.append(tuple(b+i for i in f)); mats.append(mat)
    box(-L, L, Y, Y + T, -W, W, "concrete")                       # deck
    for s in (-1, 1):                                             # parapets
        box(-L, L, Y + T, Y + T + 0.9 * U_PER_M,
            s * W - 0.18 * U_PER_M * s, s * W, "concrete")
    for s in (-1, 1):                                             # abutments
        box(s * L - 1.2 * U_PER_M * s, s * L, Y - D, Y, -W, W, "concrete")
    return {"verts": verts, "faces": faces, "mats": mats}
