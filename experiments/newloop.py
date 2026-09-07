"""Generate the new speed-track loop: road ribbon, bridge and building.

Centreline comes from the user's sketch (newloop_path.json), traced back into
world coordinates. Units are the ROM's: 40 per foot, Y up.
"""
import json, math

U = 3.280839895 * 40.0          # units per metre
ROAD_HALF = 40.0 * 40.0 / 2.0   # 40 ft wide, matching ROAD1 (1601 units)
STEP = 12.0                     # metres between centreline samples
BRIDGE_CLEAR_M = 7.0            # deck height over the lower leg
RAMP_M = 260.0                  # metres of approach either side of the crossing


def resample(pts, step_u):
    out, carry = [], 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.dist(a, b)
        if seg < 1e-6:
            continue
        t = carry
        while t < seg:
            f = t / seg
            out.append((a[0] + (b[0]-a[0])*f, a[1] + (b[1]-a[1])*f))
            t += step_u
        carry = t - seg
    out.append(tuple(pts[-1]))
    return out


def smooth(pts, k=4, rounds=3):
    """Hand-drawn ink is jittery; a road is not."""
    p = list(pts)
    for _ in range(rounds):
        q = []
        n = len(p)
        for i in range(n):
            lo, hi = max(0, i-k), min(n, i+k+1)
            w = p[lo:hi]
            q.append((sum(x for x, _ in w)/len(w), sum(z for _, z in w)/len(w)))
        p = q
        p[0], p[-1] = pts[0], pts[-1]           # keep the junctions pinned
    return p


def self_crossing(pts, skip=12):
    """Where does the loop cross itself? Returns the two path indices."""
    def seg(a, b, c, d):
        d1 = (b[0]-a[0], b[1]-a[1]); d2 = (d[0]-c[0], d[1]-c[1])
        den = d1[0]*d2[1] - d1[1]*d2[0]
        if abs(den) < 1e-9:
            return None
        t = ((c[0]-a[0])*d2[1] - (c[1]-a[1])*d2[0]) / den
        s = ((c[0]-a[0])*d1[1] - (c[1]-a[1])*d1[0]) / den
        if 0 <= t <= 1 and 0 <= s <= 1:
            return (a[0]+d1[0]*t, a[1]+d1[1]*t)
        return None
    for i in range(len(pts)-1):
        for j in range(i+skip, len(pts)-1):
            p = seg(pts[i], pts[i+1], pts[j], pts[j+1])
            if p:
                return i, j, p
    return None


def near_approach(pts, apart=20):
    """The traced loop passes close to itself rather than crossing exactly -
    hand-drawn ink plus smoothing. Take the closest such pair as the bridge."""
    best = None
    for i in range(len(pts)):
        for j in range(i + apart, len(pts)):
            d = math.dist(pts[i], pts[j])
            if best is None or d < best[0]:
                best = (d, i, j)
    return best


BRIDGE_MARK = (206937, 256304)     # centre of the blue ink in the sketch


def pull_together(pts, i, j, target, reach=14):
    """The traced legs pass ~57 m apart because hand-drawn ink plus smoothing
    lost the crossing. Warp both legs toward the marked point, with a cosine
    falloff, so they genuinely intersect there."""
    p = list(pts)
    for base in (i, j):
        for k in range(max(0, base-reach), min(len(p), base+reach+1)):
            wgt = 0.5 + 0.5*math.cos(math.pi * abs(k-base) / (reach+1))
            p[k] = (p[k][0] + (target[0]-pts[base][0])*wgt,
                    p[k][1] + (target[1]-pts[base][1])*wgt)
    return p


def build():
    raw = [tuple(p) for p in json.load(open("newloop_path.json"))]
    pts = smooth(resample(raw, STEP * U))
    n = len(pts)
    d, i, j = near_approach(pts)
    pts = pull_together(pts, i, j, BRIDGE_MARK)
    pts = smooth(pts, k=2, rounds=1)
    d = math.dist(pts[i], pts[j])
    ramp = int(RAMP_M / STEP)
    # the return leg (later in path order) climbs over the outbound one
    y = [0.0] * n
    for k in range(n):
        dd = abs(k - j)
        if dd <= ramp:
            y[k] = BRIDGE_CLEAR_M * U * (0.5 + 0.5*math.cos(math.pi * dd / ramp))
    return pts, y, (i, j, pts[j], d)


if __name__ == "__main__":
    pts, y, cross = build()
    L = sum(math.dist(pts[i], pts[i+1]) for i in range(len(pts)-1))
    print("centreline: %d samples, %.0f m (%.2f mi), spacing %.0f m"
          % (len(pts), L/U, L/U/1609.34, L/U/(len(pts)-1)))
    i, j, p, d = cross
    print("bridge at (%.0f, %.0f): path index %d passes index %d, %.0f m apart"
          % (p[0], p[1], i, j, d/U))
    print("   the return leg climbs to %.1f m over a %.0f m ramp each side"
          % (max(y)/U, RAMP_M))
    print("   grade: %.1f%%" % (100 * BRIDGE_CLEAR_M / RAMP_M))
