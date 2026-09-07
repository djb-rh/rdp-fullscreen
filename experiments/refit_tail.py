#!/usr/bin/env python3
"""Close the loop exactly: hold the head (through the crossing piece), enumerate
2..4 tail pieces, minimise the miss at the arrival pose A."""
import json, math, itertools
import layout, findloop as F
C = json.load(open("refit_candidates.json"))
PAL = F.PALETTE + [("ROAD1", 0), ("ROAD2", 0)]
def miss(seq):
    x, z, h = F.endpose(seq)
    dpos = math.hypot(x - F.A[0], z - F.A[1]); dh = abs(((h - F.A[2] + 180) % 360) - 180)
    return dpos, dh
def clearance_ok(seq):
    pl, _ = layout.run(F.B, seq)
    for p in pl[1:-1]:
        if min(math.hypot(p["x"]-kx, p["z"]-kz) for kx, kz in F.KEEP) < 12000: return False
    return True
best_all = []
for ci, cand in enumerate(C[:3]):
    seq = [tuple(t) for t in cand["seq"]]
    x = F.crosses(seq)
    if not x: continue
    i, j, *_ = x
    head = seq[:j+1]                       # through the far crossing piece
    best = []
    for n in (2, 3, 4):
        for tail in itertools.product(PAL, repeat=n):
            s = head + list(tail)
            dpos, dh = miss(s)
            if dpos > 3000 or dh > 6: continue
            best.append((dpos + dh*900, dpos, dh, s))
    best.sort(key=lambda t: t[0])
    kept = []
    for t in best:
        if len(kept) >= 40: break
        if clearance_ok(t[3]) and F.crosses(t[3]) and F.crosses(t[3])[:2] == (i, j): kept.append(t)
    print("candidate %d: head %d pieces, %d tails within 3000/6deg, %d pass clearance+crossing; best:" % (ci, len(head), len(best), len(kept)))
    for t in kept[:4]:
        print("   miss %5.0f units (%3.0f ft), heading %4.1f deg, %d pieces: ...%s" % (t[1], t[1]/40, t[2], len(t[3]), " ".join("%s%s"%(n,{1:"+",-1:"-",0:""}[h]) for n,h in t[3][len(head):])))
        best_all.append((t[0], ci, t[3]))
best_all.sort(key=lambda t: t[0])
if best_all:
    json.dump({"seq": best_all[0][2], "from_candidate": best_all[0][1]}, open("refit_best.json", "w"))
    print("\nwrote refit_best.json (candidate %d)" % best_all[0][1])
