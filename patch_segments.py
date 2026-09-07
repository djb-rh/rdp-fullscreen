#!/usr/bin/env python3
"""Add the east loop's road segments to track 0.

Track 0 has 430 segments and only 44 spare slots before track 1's array; the
loop needs 94. But track 1 (autocross) declares just 49 records inside a
16716-byte region, so sliding its array to the TOP of its own region frees
13.5 KB immediately after track 0 - no padding needed, and the padding is
nearly full anyway once patch_track.py has run.

Reads your own ROMs; preserves Atari's byte-sum convention. No ROM data here.
"""
import json, math, os, struct
import patch_track as pt
import mkseg

T0, T1, T2 = 0x049CA, 0x0C078, 0x101C4
CEILING = 0x0EFEE      # super stunt's descriptor - the hard ceiling
REC0, REC1 = 0x00, 0xA4          # track record offsets
ENTER, EXIT = mkseg.ENTER, mkseg.EXIT


def swap32(buf, a):
    lo, hi = struct.unpack_from(">HH", buf, a)
    return struct.unpack(">i", struct.pack(">HH", hi, lo))[0]


def put_swap32(buf, a, v):
    b = struct.pack(">i", v)
    buf[a:a+4] = b[2:4] + b[0:2]


def apply(buf):
    """Grow track 0's segment array over autocross's data.

    Autocross is given up deliberately. Its descriptor (0x0BFE4) and segment
    array (0x0C078) sit directly behind track 0's segments, and they are the
    only thing in the way - nothing outside track 1's own record points into
    that span. Super stunt's descriptor at 0x0EFEE is the hard ceiling and is
    left untouched.
    """
    n0 = swap32(buf, T0)
    S = json.load(open("loop_final.json"))
    def segpos(n): return tuple(swap32(buf, T0+n*64+o) for o in (0,4,8))
    recs = mkseg.build(mkseg.centreline(S["seq"], S["start"], close=S.get("close")), n0 + 1, exit_pos=segpos(EXIT))
    new_total = n0 + len(recs)
    end0 = T0 + (new_total + 1) * 64
    print("track 0: %d segments + %d new = %d, array 0x%05X..0x%05X"
          % (n0, len(recs), new_total, T0, end0))
    if end0 > CEILING:
        raise SystemExit("would reach 0x%05X, past super stunt's descriptor at 0x%05X"
                         % (end0, CEILING))
    print("  ceiling is 0x%05X (super stunt's descriptor); %d bytes to spare"
          % (CEILING, CEILING - end0))

    # --- append, update the count ------------------------------------------
    buf[T0 + (n0+1)*64 : end0] = b"".join(recs)
    put_swap32(buf, T0, new_total)

    # --- autocross is now gone; point its record at track 0 so selecting it
    #     lands on a real track instead of reading whatever we wrote over it
    for off in (0x00, 0x04, 0x08, 0x0C, 0x10):
        struct.pack_into(">I", buf, REC1 + off, struct.unpack_from(">I", buf, REC0 + off)[0])
    print("  autocross record repointed at track 0's data (its own is overwritten)")

    # --- unlink the segments the design deletes -----------------------------
    # From mkdelset.py, which assigns each segment to its NEAREST road piece.
    # A radius test is not good enough: consecutive DOTLINEs sit 10400 apart but
    # are ~18300 long, so a deleted piece can claim segments belonging to the
    # piece next door - which is how the start line's segment (352) got deleted
    # and the game reported "Off Road" on the grid.
    DEL = set(json.load(open("delete_segments.json")))
    cleared = 0
    for n in range(1, new_total + 1):
        for o in (0x24, 0x28):
            v = struct.unpack_from(">i", buf, T0 + n*64 + o)[0]
            m = -1 if v == -1 else v >> 16
            if m in DEL or (n in DEL and m != -1):
                struct.pack_into(">i", buf, T0 + n*64 + o, -1)
                cleared += 1
    print("  unlinked %d deleted segments: %d link slots cleared" % (len(DEL), cleared))

    first = n0 + 1
    struct.pack_into(">i", buf, T0 + ENTER*64 + 0x24, first << 16)
    struct.pack_into(">i", buf, T0 + EXIT*64 + 0x28, new_total << 16)
    print("  linked: segment %d forward -> %d, segment %d back -> %d"
          % (ENTER, first, EXIT, new_total))

    # --- verify by walking it as the game would ----------------------------
    def link(n, o):
        v = struct.unpack_from(">i", buf, T0 + n*64 + o)[0]
        return -1 if v == -1 else v >> 16
    def pos(n):
        return tuple(swap32(buf, T0 + n*64 + o) for o in (0, 4, 8))
    prev, cur, walked, dist = ENTER, n0 + 1, 0, 0.0
    while walked < len(recs) + 4:
        nxt = link(cur, 0x24)
        if nxt == -1: break
        dist += math.dist(pos(cur)[:2], pos(nxt)[:2])
        prev, cur = cur, nxt
        walked += 1
        if cur == EXIT: break
    print("  walk from %d: %d segments, reached %d (want %d) %s, %.0f m"
          % (n0+1, walked, cur, EXIT, "OK" if cur == EXIT else "FAIL", dist/40*0.3048))
    back = link(EXIT, 0x28)
    print("  reverse link from %d -> %d %s" % (EXIT, back, "OK" if back == new_total else "FAIL"))
    print("  declared count now %d %s" % (swap32(buf, T0), "OK" if swap32(buf, T0) == new_total else "FAIL"))

    return buf


def main():
    buf = apply(pt.load())
    os.makedirs("patched_loop", exist_ok=True)
    write(buf, "patched_loop")


def write(buf, out):
    os.makedirs(out, exist_ok=True)
    for name, suffix, phase in pt.PARTS:
        half = bytearray(buf[phase::2])
        pad = 0x1C044 // 2
        half[pad] = 0
        half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
        open(os.path.join(out, name), "wb").write(bytes(half))
        print("  %-18s byte-sum low 0x%02X (want 0x%02X) %s"
              % (name, sum(half) & 0xFF, suffix, "OK" if (sum(half) & 0xFF) == suffix else "MISMATCH"))


if __name__ == "__main__":
    main()
