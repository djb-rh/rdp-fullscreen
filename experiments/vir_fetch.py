"""Fetch the VIR Full Course centreline and its elevation from public sources.

  OpenStreetMap (ODbL) via Overpass  -> track centreline geometry
  USGS 3DEP 10 m NED via OpenTopoData -> elevation

Writes vir_centreline.json. Run once; the result is cached.
"""
import json, math, os, time, urllib.request, urllib.parse

BBOX = (36.53, -79.25, 36.61, -79.16)
FULL_COURSE_M = 3.27 * 1609.344          # the published Full Course length
STEP_M = 10.0
EXCLUDE = {"Karting Track", "Pit Lane", "Madison Avenue", "North Paddock",
           "Patriot Course"}
R = 6371000.0

CACHE = "vir_osm_raw.json"

def overpass():
    if os.path.exists(CACHE):
        print("  using cached %s" % CACHE)
        return json.load(open(CACHE))
    q = ('[out:json][timeout:60];(way["highway"="raceway"](%f,%f,%f,%f););out geom;'
         % BBOX)
    for host in ("overpass-api.de", "overpass.osm.ch"):
        try:
            req = urllib.request.Request(
                "https://%s/api/interpreter" % host,
                data=urllib.parse.urlencode({"data": q}).encode(),
                headers={"User-Agent": "rdp-fullscreen/1.0 (hobby ROM research)"})
            d = json.loads(urllib.request.urlopen(req, timeout=90).read())
            if d.get("elements"):
                json.dump(d, open(CACHE, "w"))
                return d
            print("  %s: empty result" % host)
        except Exception as e:
            print("  %s: %s" % (host, e))
    raise SystemExit("no Overpass mirror answered")

def build_ways(d, lat0, lon0):
    def xy(la, lo):
        return (math.radians(lo - lon0) * R * math.cos(math.radians(lat0)),
                math.radians(la - lat0) * R)
    ways = []
    for e in d["elements"]:
        t = e.get("tags", {}); g = e.get("geometry", [])
        if t.get("sport") != "motor" or t.get("area") == "yes":
            continue
        if t.get("name") in EXCLUDE or len(g) < 2:
            continue
        pts = [(p["lat"], p["lon"]) for p in g]
        P = [xy(*p) for p in pts]
        ways.append({"id": e["id"], "name": t.get("name", "(unnamed)"),
                     "oneway": t.get("oneway") == "yes", "pts": pts, "xy": P,
                     "len": sum(math.dist(P[i], P[i+1]) for i in range(len(P)-1))})
    return ways

def find_loop(ways):
    """The Full Course is the closed loop whose length matches the published
    3.27 miles. Identified by measurement, not by assuming a turn order."""
    k = lambda p, g=1.5: (round(p[0]/g), round(p[1]/g))
    adj = {}
    for i, w in enumerate(ways):
        adj.setdefault(k(w["xy"][0]), []).append((k(w["xy"][-1]), i, False))
        if not w["oneway"]:
            adj.setdefault(k(w["xy"][-1]), []).append((k(w["xy"][0]), i, True))
    best = []
    def dfs(start, node, used, path, L):
        if L > 7000 or len(path) > 28:
            return
        if node == start and path:
            best.append((abs(L - FULL_COURSE_M), L, list(path))); return
        for b, i, r in adj.get(node, []):
            if i in used:
                continue
            used.add(i); path.append((i, r))
            dfs(start, b, used, path, L + ways[i]["len"])
            path.pop(); used.discard(i)
    for s in {k(w["xy"][0]) for w in ways}:
        dfs(s, s, set(), [], 0.0)
    best.sort()
    return best[0]

def assemble(ways, path):
    pts = []
    for i, rev in path:
        p = ways[i]["pts"][::-1] if rev else ways[i]["pts"]
        pts.extend(p[1:] if pts else p)
    return pts

def resample(pts, lat0, lon0, step):
    """Walk the polyline at a fixed spacing. This follows the line exactly - it
    does not smooth or cut corners."""
    def xy(la, lo):
        return (math.radians(lo - lon0) * R * math.cos(math.radians(lat0)),
                math.radians(la - lat0) * R)
    P = [xy(*p) for p in pts]
    out, carry = [], 0.0
    for i in range(len(P) - 1):
        a, b = P[i], P[i+1]
        seg = math.dist(a, b)
        if seg < 1e-9:
            continue
        t = carry
        while t < seg:
            f = t / seg
            out.append((a[0] + (b[0]-a[0])*f, a[1] + (b[1]-a[1])*f))
            t += step
        carry = t - seg
    return out

def elevations(latlon):
    out = []
    for i in range(0, len(latlon), 100):
        chunk = latlon[i:i+100]
        q = "|".join("%.7f,%.7f" % p for p in chunk)
        u = "https://api.opentopodata.org/v1/ned10m?locations=" + urllib.parse.quote(q)
        for attempt in range(4):
            try:
                d = json.loads(urllib.request.urlopen(u, timeout=60).read())
                if d.get("status") == "OK":
                    out.extend(r["elevation"] for r in d["results"]); break
            except Exception as e:
                print("   retry %d: %s" % (attempt, e))
            time.sleep(3)
        else:
            raise SystemExit("elevation lookup failed")
        print("   %d/%d" % (len(out), len(latlon)))
        time.sleep(1.2)
    return out

def main():
    print("fetching OSM raceway ways ...")
    d = overpass()
    lat0 = sum(p["lat"] for e in d["elements"] for p in e.get("geometry", [])) \
        / sum(len(e.get("geometry", [])) for e in d["elements"])
    lon0 = sum(p["lon"] for e in d["elements"] for p in e.get("geometry", [])) \
        / sum(len(e.get("geometry", [])) for e in d["elements"])
    ways = build_ways(d, lat0, lon0)
    dv, L, path = find_loop(ways)
    print("  loop: %.0f m (%.3f mi), %+.0f m vs published; %d ways"
          % (L, L / 1609.344, L - FULL_COURSE_M, len(path)))
    print("  " + " -> ".join(ways[i]["name"] for i, _ in path))
    pts = assemble(ways, path)
    xy = resample(pts, lat0, lon0, STEP_M)
    # back to lat/lon for the elevation query
    ll = [(lat0 + math.degrees(y / R),
           lon0 + math.degrees(x / (R * math.cos(math.radians(lat0))))) for x, y in xy]
    print("resampled to %d points at %.0f m; fetching USGS 3DEP elevation ..."
          % (len(ll), STEP_M))
    ele = elevations(ll)
    json.dump({"lat0": lat0, "lon0": lon0, "step": STEP_M, "length_m": L,
               "corners": [ways[i]["name"] for i, _ in path],
               "xy": xy, "latlon": ll, "ele": ele},
              open("vir_centreline.json", "w"))
    print("wrote vir_centreline.json: %d points, elevation %.1f..%.1f m (%.0f ft range)"
          % (len(ele), min(ele), max(ele), (max(ele)-min(ele)) / 0.3048))

if __name__ == "__main__":
    main()
