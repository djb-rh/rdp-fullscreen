#!/usr/bin/env python3
"""Longer tails, composed analytically (rigid 2D transforms per piece) so 5-6
piece tails are cheap; the best few are re-verified through layout.run."""
import json, math, itertools, sys
import layout, findloop as F
S = json.load(open("loop_final.json")); seq = [tuple(t) for t in S["seq"]]
seq[S["under"]] = ("DOTLINE", 0)
PAL = sorted(set(F.PALETTE + [("ROAD1", 0), ("ROAD2", 0), ("ROAD3", 0), ("DOTLHALF", 0)]))
# per-piece transform from the origin pose
T = {}
for p in PAL:
    px, pz, ph = F.endpose([p], start=(0.0, 0.0, 0.0))
    T[p] = (px, pz, ph)
def step(pose, p):
    x, z, h = pose; px, pz, ph = T[p]
    r = math.radians(h); c, s = math.cos(r), math.sin(r)
    # try convention: rotate local offset by heading (x' = px*c + pz*s, z' = -px*s + pz*c)
    return (x + px*c + pz*s, z - px*s + pz*c, h + ph)
# verify the convention against layout.run on the current seq
pose = tuple(F.B)
for p in seq: pose = step(pose, p)
ref = F.endpose(seq)
err = math.hypot(pose[0]-ref[0], pose[1]-ref[1])
if err > 5:
    def step(pose, p):
        x, z, h = pose; px, pz, ph = T[p]
        r = math.radians(h); c, s = math.cos(r), math.sin(r)
        return (x + px*c - pz*s, z + px*s + pz*c, h + ph)
    pose = tuple(F.B)
    for p in seq: pose = step(pose, p)
    err = math.hypot(pose[0]-ref[0], pose[1]-ref[1])
print("compose check: %.1f units, heading %.2f" % (err, ((pose[2]-ref[2]+180) % 360) - 180))
assert err < 5
def miss(pose):
    x, z, h = pose
    return math.hypot(x-F.A[0], z-F.A[1]), abs(((h-F.A[2]+180) % 360)-180)
HEAD = int(sys.argv[1]) if len(sys.argv) > 1 else 17
MAXN = int(sys.argv[2]) if len(sys.argv) > 2 else 6
head = seq[:HEAD]
hp = tuple(F.B)
for p in head: hp = step(hp, p)
found = []
for n in range(2, MAXN+1):
    cnt = 0
    for tail in itertools.product(PAL, repeat=n):
        pose = hp
        for p in tail: pose = step(pose, p)
        dpos, dh = miss(pose)
        if dpos < 800 and dh < 2.5:
            found.append((dpos + dh*900, dpos, dh, list(tail)))
    print("n=%d: %d candidates so far" % (n, len(found)), flush=True)
found.sort(key=lambda t: t[0])
ci, cj = F.crosses(seq)[:2]
ok = []
seen = set()
for sc, dpos, dh, tail in found:
    s = head + tail
    key = tuple(tail)
    if key in seen: continue
    seen.add(key)
    x = F.crosses(s)
    if not x or x[:2] != (ci, cj): continue
    pl, _ = layout.run(F.B, s)
    if any(min(math.hypot(p["x"]-kx, p["z"]-kz) for kx, kz in F.KEEP) < 12000 for p in pl[1:-1]): continue
    rx, rz, rh = F.endpose(s)
    d2, h2 = miss((rx, rz, rh))
    ok.append((d2 + h2*900, d2, h2, s))
    print("  miss %4.0f units (%2.0f ft) heading %.2f deg  len %d: ...%s" % (d2, d2/40, h2, len(s), " ".join("%s%s" % (nm, {1:"+",-1:"-",0:""}[hh]) for nm, hh in tail)), flush=True)
    if len(ok) >= 12: break
ok.sort(key=lambda t: t[0])
if ok:
    json.dump({"seq": ok[0][3], "head": HEAD}, open("refit_best2.json", "w"))
    print("best -> refit_best2.json: %.0f units %.2f deg" % (ok[0][1], ok[0][2]))
