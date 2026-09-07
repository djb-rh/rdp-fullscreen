#!/usr/bin/env python3
"""Extend the gate time awards on track 0 for the longer east-loop lap.

The award a gate hands the clock is

    word[ track_record + 0x40 + (marker & 3) * 8 + kind * 2 ] * 25

(routine 0x3154A), and 250 clock units is one second. Stock track 0 gives 32 s
at the marker-4/8 gates and 29 s at start/finish - 122 s of credit against a
105.3 s lap, a 1.16x margin.

The east loop is a REPLACEMENT, not pure addition. It adds 2376 m, but the
design also deletes 8 road placements - four DOTLINE straights along x=209600
and four D30R917 curves. Measured at segment level (27 segments in the deleted
set, summed along their own road links) that is 1072 m, so the net change is
+1304 m - the "~1.3 km longer lap" this started from, almost exactly.

Against a lap of ~3500 m (inferred from the measured 105.3 s at a plausible
75 mph; the road graph does not close on its own, so it cannot be measured
directly yet) that is 1.37x. Scaling the awards by the same factor keeps Atari's
margin rather than making the track easier or harder.

An earlier version of this used 1.71x, from treating the loop as pure addition
and ignoring the deletion. That was too generous.

Reads your own ROMs; preserves Atari's byte-sum convention. No ROM data here.
"""
import os, struct
import patch_track as pt

TRACK = 0
TABLE = TRACK * 164 + 0x40
RATIO = 1.37
OUT = "patched_awards"


def patch(buf, ratio=RATIO, verbose=True):
    """Scale track 0's 4x4 award table in place. Returns the old/new rows."""
    old, new = [], []
    for row in range(4):
        o = [struct.unpack_from(">H", buf, TABLE + row*8 + k*2)[0] for k in range(4)]
        n = [min(0xFFFF, int(round(v * ratio))) for v in o]
        for k in range(4):
            struct.pack_into(">H", buf, TABLE + row*8 + k*2, n[k])
        old.append(o); new.append(n)
        if verbose:
            print("  marker&3=%d  %s  ->  %s     %4.1f s -> %4.1f s"
                  % (row, " ".join("%4d" % v for v in o), " ".join("%4d" % v for v in n),
                     o[0]*25/250, n[0]*25/250))
    return old, new


def main():
    buf = pt.load()
    print("track %d award table at DSK 0x%05X, scaling by %.2fx\n" % (TRACK, TABLE, RATIO))
    old, new = patch(buf)

    per_old = (old[0][0]*2 + old[1][0] + old[2][0]) * 25 / 250
    per_new = (new[0][0]*2 + new[1][0] + new[2][0]) * 25 / 250
    print("\n  credit per lap  %.0f s -> %.0f s" % (per_old, per_new))
    print("  lap time       105.3 s -> ~%.0f s   margin %.2fx -> %.2fx"
          % (105.3*RATIO, per_old/105.3, per_new/(105.3*RATIO)))

    # read back exactly as routine 0x3154A would
    print("\n  verify (read back through the game's own indexing):")
    for marker in (8, 4, 2, 1):
        row = marker & 3
        v = struct.unpack_from(">H", buf, TABLE + row*8 + 0)[0]
        print("     marker %d -> row %d -> %4d x25 = %5d ticks = %.1f s"
              % (marker, row, v, v*25, v*25/250))

    os.makedirs(OUT, exist_ok=True)
    for name, suffix, phase in pt.PARTS:
        half = bytearray(buf[phase::2])
        pad = 0x1C044 // 2
        half[pad] = 0
        half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
        open(os.path.join(OUT, name), "wb").write(bytes(half))
        ok = (sum(half) & 0xFF) == suffix
        print("  %-18s byte-sum low 0x%02X (want 0x%02X) %s"
              % (name, sum(half) & 0xFF, suffix, "OK" if ok else "MISMATCH"))


if __name__ == "__main__":
    main()
