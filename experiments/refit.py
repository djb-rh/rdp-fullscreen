#!/usr/bin/env python3
"""Re-fit the east loop against the CORRECTED piece geometry.

Seeded from loop_final.json (UNDERP treated as the DOTLINE it replaces), the
search closes onto the arrival pose A and adds stock's crossing configuration
as a constraint: the crossing lands on a DOTLINE (so the UNDERP substitutes
exactly) AND near the centre of BOTH legs' pieces.  Reports the best candidates;
does not write anything."""
import json, math, random, sys
import layout, findloop as F
U = layout.U
S = json.load(open("loop_final.json"))
seed_seq = [tuple(t) for t in S["seq"]]
under = S["under"]
seed_seq[under] = ("DOTLINE", 0)

def crossing_terms(seq):
    x = F.crosses(seq)
    if x is None: return None
    i, j, pt, t, u = x
    return i, j, t, u

def score2(seq):
    s, dpos, dh = F.score(seq)
    x = crossing_terms(seq)
    if x is None: return s + 300000, dpos, dh, None
    i, j, t, u = x
    # one leg must be a DOTLINE with the crossing near its centre (the UNDERP goes there)
    opts = []
    if seq[i][0] == "DOTLINE": opts.append((abs(t-0.5), abs(u-0.5), i))
    if seq[j][0] == "DOTLINE": opts.append((abs(u-0.5), abs(t-0.5), j))
    if not opts: return s + 150000, dpos, dh, x
    dself, dother, k = min(opts)
    s += dself * 90000 + dother * 60000       # both legs centred, like stock
    return s, dpos, dh, (i, j, t, u, k)

def search(seed, iters, rnd, mutate_all):
    cur = list(seed); cs = score2(cur)[0]; best = (cs, list(cur))
    n = len(cur)
    for _ in range(iters):
        cand = list(cur)
        for _ in range(rnd.choice((1, 1, 2))):
            k = rnd.randrange(n) if mutate_all else rnd.randrange(max(0, n-6), n)
            cand[k] = rnd.choice(F.PALETTE)
        s = score2(cand)[0]
        if s < cs or rnd.random() < 0.02: cur, cs = cand, s
        if s < best[0]: best = (s, list(cand))
    return best

results = []
for seed in range(6):
    rnd = random.Random(seed)
    b = search(seed_seq, 12000, rnd, mutate_all=(seed % 2 == 1))
    s, dpos, dh, x = score2(b[1])
    results.append((s, dpos, dh, x, b[1]))
results.sort(key=lambda r: r[0])
print("seed sequence: end miss %.0f units, heading %.1f" % F.score(seed_seq)[1:])
for s, dpos, dh, x, seq in results[:4]:
    i, j, t, u, k = x if x else (-1, -1, 0, 0, -1)
    print("\nscore %8.0f  end miss %5.0f units (%3.0f ft)  heading %4.1f deg  crossing on pieces %d/%d at %.2f/%.2f, UNDERP -> piece %d  length %.0f ft"
          % (s, dpos, dpos/40, dh, i, j, t, u, k, layout.length(seq)/40))
    print("   " + " ".join("%s%s" % (n, {1:"+",-1:"-",0:""}[h]) for n, h in seq))
json.dump([{"seq": r[4], "under": r[3][4] if r[3] else -1} for r in results[:4]], open("refit_candidates.json", "w"))
