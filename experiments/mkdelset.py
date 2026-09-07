#!/usr/bin/env python3
"""Work out which segments belong to the deleted road pieces.

Assign every segment to its NEAREST road piece, not to any piece within a
radius. Consecutive DOTLINEs sit 10400 units apart but are ~18300 long, so
their footprints overlap heavily and a radius test lets a deleted piece claim
segments that belong to the piece next door. That is how segment 352 - the one
the start line sits on - ended up deleted, which is what made the game report
"Off Road" on the grid.
"""
import json, math, struct
import world, patch_track

T0 = 0x049CA


def centreline(W, P, ENDS, p, nm, n=24):
    m = p["m"]; a = math.atan2(m[2], m[0])
    ox, oz = ENDS[nm]["mid"]
    cx = p["x"] + (m[0]*ox + m[2]*oz)/16384.0
    cz = p["z"] + (m[6]*ox + m[8]*oz)/16384.0
    ch, turn = P[nm]["chord"], P[nm]["turn"]
    out = []
    if abs(turn) < 1e-9:
        for t in [i/n for i in range(n+1)]:
            d = (t-0.5)*ch
            out.append((cx + math.sin(a)*d, cz + math.cos(a)*d))
    else:
        r = (ch/2)/math.sin(math.radians(abs(turn))/2)
        h0 = math.degrees(a) - turn/2.0
        ex, ez = cx - math.sin(a)*ch/2, cz - math.cos(a)*ch/2
        for t in [i/n for i in range(n+1)]:
            ang = turn*t
            c = 2*r*math.sin(math.radians(abs(ang))/2)
            th = math.radians(h0 + ang/2.0)
            out.append((ex + math.sin(th)*c, ez + math.cos(th)*c))
    return out


def compute(verbose=True):
    buf = patch_track.load()
    W = world.World()
    P = json.load(open("pieces.json")); ENDS = json.load(open("piece_ends.json"))
    dele = set(json.load(open("delete_list.json")))

    def s32(a):
        lo, hi = struct.unpack_from(">HH", buf, a)
        return struct.unpack(">i", struct.pack(">HH", hi, lo))[0]
    n = s32(T0)
    segs = {i: (s32(T0+i*64), s32(T0+i*64+4)) for i in range(1, n+1)}

    lines = {}
    for r in range(world.PLACE_N):
        p = W.placement(r); nm = p["name"]
        if nm in P and P[nm].get("chord") and nm in ENDS:
            lines[r] = [(z, x) for (x, z) in centreline(W, P, ENDS, p, nm)]

    owner, dist = {}, {}
    for i, s in segs.items():
        best, bd = None, 1e18
        for r, line in lines.items():
            d = min(math.dist(s, q) for q in line)
            if d < bd: best, bd = r, d
        owner[i], dist[i] = best, bd

    LAT = 1200.0
    out = sorted(i for i in segs if owner[i] in dele and dist[i] < LAT)
    if verbose:
        print("segments assigned to each deleted road piece (nearest-piece rule):")
        for r in sorted(dele):
            mine = [i for i in out if owner[i] == r]
            if mine or r in lines:
                print("   placement %3d %-9s -> %s" % (r, W.placement(r)["name"], mine))
        print("\n  delete set (%d): %s" % (len(out), out))
        print("  segment 352 (start line) owned by placement %d, %.0f units -> deleted: %s"
              % (owner[352], dist[352], 352 in out))
    return out


if __name__ == "__main__":
    ds = compute()
    json.dump(ds, open("delete_segments.json", "w"))
    print("\nwrote delete_segments.json")
