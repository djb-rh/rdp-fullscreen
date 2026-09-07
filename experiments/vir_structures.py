"""Pit lane and its walls, buildings, and fences for the VIR model.

  buildings / fences  real OSM footprints and lines; heights are NOT in the
                      data and are assumed - see HEIGHTS below
  pit lane            surfaced from the OSM "Pit Lane" way
  pit wall            not in OSM anywhere; synthesised along the pit lane's
                      track-facing edge
"""
import json, math, os, time, urllib.parse, urllib.request

U = 3.280839895 * 40.0
R = 6371000.0
GROUND = "vir_ground.json"

# No VIR building carries height or building:levels, so these are assumed from
# footprint area. Change them here if you have better numbers.
HEIGHTS = [(100, 3.5), (600, 5.5), (1500, 7.0), (1e9, 9.0)]
PIT_HALF_M = 5.0            # 10 m pit lane
PIT_WALL_H = 1.05
PIT_WALL_T = 0.25
FENCE_H = {"fence": 2.4, "wall": 1.8, "guard_rail": 0.75}
FENCE_T = {"fence": 0.10, "wall": 0.35, "guard_rail": 0.30}


def ll(x, z, lat0, lon0):
    return (lat0 + math.degrees(z / R),
            lon0 + math.degrees(x / (R * math.cos(math.radians(lat0)))))


def ground(points, lat0, lon0):
    """Elevation for arbitrary (x, z) metres. Cached; batched 100 at a time."""
    cache = json.load(open(GROUND)) if os.path.exists(GROUND) else {}
    need = [p for p in points if "%.1f,%.1f" % p not in cache]
    for i in range(0, len(need), 100):
        chunk = need[i:i+100]
        q = "|".join("%.7f,%.7f" % ll(x, z, lat0, lon0) for x, z in chunk)
        u = "https://api.opentopodata.org/v1/ned10m?locations=" + urllib.parse.quote(q)
        for _ in range(4):
            try:
                d = json.loads(urllib.request.urlopen(u, timeout=60).read())
                if d.get("status") == "OK":
                    for p, r in zip(chunk, d["results"]):
                        cache["%.1f,%.1f" % p] = r["elevation"]
                    break
            except Exception as e:
                print("   retry: %s" % e); time.sleep(3)
        else:
            raise SystemExit("elevation lookup failed")
        print("   ground %d/%d" % (min(i+100, len(need)), len(need)))
        time.sleep(1.2)
    json.dump(cache, open(GROUND, "w"))
    return {p: cache["%.1f,%.1f" % p] for p in points}


def _model(name, verts, faces, mats):
    ox = sum(v[0] for v in verts) / len(verts)
    oy = sum(v[1] for v in verts) / len(verts)
    oz = sum(v[2] for v in verts) / len(verts)
    return {"name": name, "origin": (ox, oy, oz),
            "verts": [(v[0]-ox, v[1]-oy, v[2]-oz) for v in verts],
            "faces": faces, "mats": mats,
            "matrix": [16384, 0, 0, 0, 16384, 0, 0, 0, 16384]}


MAX_SPAN_U = 300.0 * U      # 300 m per model; s16 reaches 250 m from centre


def _cut(path, i):
    """Advance from i until the run would span more than MAX_SPAN_U."""
    j = i + 1
    while j < len(path) - 1:
        d = math.dist((path[i][0], path[i][2]), (path[j+1][0], path[j+1][2])) \
            if len(path[i]) == 3 else math.dist(path[i], path[j+1])
        if d > MAX_SPAN_U:
            break
        j += 1
    return j


def strip(name, left, right, mat, chunk=None):
    """A quad strip between two edges, cut into models that fit s16."""
    out = []
    i = 0
    while i < len(left) - 1:
        j = _cut(left, i)
        idx = list(range(i, j + 1))
        m = len(idx)
        verts = [left[k] for k in idx] + [right[k] for k in idx]
        faces = [(a, a+1, m+a+1, m+a) for a in range(m-1)]
        out.append(_model("%s%02d" % (name, len(out)), verts, faces,
                          [mat] * len(faces)))
        i = j
    return out


def wall(name, path, h, t, mat):
    """An upright slab following `path` (list of (x, y, z) in game units)."""
    L, Rt = [], []
    n = len(path)
    for i in range(n):
        a, b = path[max(0, i-1)], path[min(n-1, i+1)]
        dx, dz = b[0]-a[0], b[2]-a[2]
        m = math.hypot(dx, dz) or 1.0
        px, pz = -dz/m*t*U/2, dx/m*t*U/2
        L.append((path[i][0]+px, path[i][1], path[i][2]+pz))
        Rt.append((path[i][0]-px, path[i][1], path[i][2]-pz))
    out = []
    i = 0
    while i < n - 1:
        j = _cut(path, i)
        idx = list(range(i, j+1)); m = len(idx)
        V, F = [], []
        for k in idx: V.append(L[k])
        for k in idx: V.append((L[k][0], L[k][1]+h*U, L[k][2]))
        for k in idx: V.append(Rt[k])
        for k in idx: V.append((Rt[k][0], Rt[k][1]+h*U, Rt[k][2]))
        for a in range(m-1):
            F.append((a, a+1, m+a+1, m+a))                    # left face
            F.append((2*m+a+1, 2*m+a, 3*m+a, 3*m+a+1))        # right face
            F.append((m+a, m+a+1, 3*m+a+1, 3*m+a))            # cap
        out.append(_model("%s%02d" % (name, len(out)), V, F, [mat]*len(F)))
        i = j
    return out


def ribbon(name, path, h, mat):
    """A thin barrier as a flat double-sided strip: two vertices per station,
    one face per segment. A fence is 0.1 m thick - building it as a solid box
    costs four times the bytes for nothing you can see."""
    n = len(path)
    out, i = [], 0
    while i < n - 1:
        j = _cut(path, i)
        idx = list(range(i, j + 1)); m = len(idx)
        V = [path[k] for k in idx] + \
            [(path[k][0], path[k][1] + h * U, path[k][2]) for k in idx]
        F = [(a, a + 1, m + a + 1, m + a) for a in range(m - 1)]
        out.append(_model("%s%02d" % (name, len(out)), V, F, [mat] * len(F)))
        i = j
    return out


def extrude(name, ring, y, h, mat):
    """A closed footprint pushed up: walls plus a flat roof."""
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    m = len(ring)
    V = [(x, y, z) for x, z in ring] + [(x, y + h*U, z) for x, z in ring]
    F = [(i, (i+1) % m, m + (i+1) % m, m+i) for i in range(m)]
    F += [tuple(range(m, 2*m))[::-1]]
    return _model(name, V, F, [mat]*len(F))
