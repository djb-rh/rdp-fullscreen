"""Swap UNDERP onto the crossing straight, re-close, and verify.

The check that matters: after substitution the UNDERP's own centre must sit on
the crossing point. Two earlier attempts failed this - once because the re-close
was allowed to revert the pinned piece, once because the crossing had been
computed from piece centres and lay on neither piece.
"""
import json, math, random
import layout, findloop as F

U = layout.U


def verify(seq, under, label):
    x = F.crosses(seq)
    if x is None:
        print("%s: NO CROSSING" % label); return None
    i, j, pt, t, u = x
    pl, _ = layout.run(F.B, seq)
    tot, dpos, dh = F.score(seq)
    d = math.dist((pl[under]["x"], pl[under]["z"]), pt)
    frac = u if under == j else t
    print("%s: %d pieces, %.0f m, join %.1f m / %.1f deg" %
          (label, len(seq), layout.length(seq)/U, dpos/U, dh))
    print("    crossing at (%.0f,%.0f); piece %d is %s, crossed at %.0f%% of it"
          % (pt[0], pt[1], under, seq[under][0], 100*frac))
    print("    that piece's centre is %.0f m from the crossing  %s"
          % (d/U, "OK" if d/U < 12 else "<-- NOT ON THE CROSSING"))
    return d/U


def reclose(seq, pin, tail=4, iters=60000, seed=3):
    """Re-solve only the LAST few pieces, to trim the join.

    Re-solving everything after `pin` re-solves the whole loop when the pin is
    early, which moves the crossing off the UNDERP entirely - that is what went
    wrong before. Only the tail may move.
    """
    rnd = random.Random(seed)
    n_tail = min(tail, len(seq) - pin - 1)
    head = seq[:len(seq) - n_tail]
    best = None
    cur, cs = list(seq), F.score(seq)[0]
    for _ in range(iters):
        cand = head + [rnd.choice(F.PALETTE) for _ in range(n_tail)]
        s = F.score(cand)[0]
        if s < cs or rnd.random() < 0.02:
            cur, cs = cand, s
        if best is None or s < best[0]:
            best = (s, list(cand))
    return best[1]


if __name__ == "__main__":
    S = json.load(open("loop_seq.json"))
    seq = [(n, h) for n, h in S["seq"]]
    under = S["under"]
    verify(seq, under, "searched   ")
    seq2 = list(seq); seq2[under] = ("UNDERP", 0)
    verify(seq2, under, "with UNDERP")
    seq3 = reclose(seq2, under)
    d = verify(seq3, under, "re-closed  ")
    # keep whichever of the two is actually better
    d2 = None
    if d is None or d >= 12 or F.score(seq3)[1]/U > F.score(seq2)[1]/U:
        seq3 = seq2
        d = verify(seq3, under, "kept subst ")
    tot, dpos, dh = F.score(seq3)
    if d is not None and d < 12 and dpos/U < 25 and seq3[under][0] == "UNDERP":
        x = F.crosses(seq3)
        json.dump({"seq": [[n, h] for n, h in seq3],
                   "cross": [x[0], x[1], [round(x[2][0]), round(x[2][1])]],
                   "under": under, "start": list(F.B)},
                  open("loop_final.json", "w"), indent=1)
        print("\nwrote loop_final.json")
    else:
        print("\nnot accepted - the UNDERP is not sitting on the crossing")
