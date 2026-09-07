#!/usr/bin/env python3
"""Add a route section for the east loop.

The loop is spliced into the road between segments 232 and 26, and walking back
from the entry reaches section start 313 - so the loop lies inside section 313's
stretch, which is index 12 in the chain, followed by 367. A new section is
inserted between them with its start at a mid-loop segment.

Marker 0, deliberately: the loop needs a section boundary so the section
machinery has sensible granularity over 2394 m, but the extra lap time is
already paid for by scaling the four existing gates in patch_awards.py. Giving
this one a gate as well would hand out a fifth award and blow the margin.

Applies on top of patched_loop/ (run patch_segments.py first).
"""
import os, struct, sys
import patch_track as pt
import routegraph, worldpatch

SRC = sys.argv[1] if len(sys.argv) > 1 else "patched_loop"
OUT = "patched_final"
AT = 0x20000 - 0x200        # the top of the padding, reserved by patch_track.
                            # It used to be pinned at 0x1F800, immediately after
                            # the cell lists - so adding one placement pushed the
                            # lists into it and the build stopped.
MID = 477                    # a segment near the middle of the loop
AFTER = 12                   # chain index of section 313


def load(d):
    half = [open(os.path.join(d, n), "rb").read() for n, _, _ in pt.PARTS]
    b = bytearray(len(half[0]) * 2)
    for i in range(len(half[0])):
        b[2*i], b[2*i+1] = half[0][i], half[1][i]
    return b


def apply(buf):
    nodes = routegraph.read(bytes(buf), 0x001EC)
    secs = [(nd["value"], nd["flags"] & 0xF000, nd["flags"] & 0x0FFF) for nd in nodes]
    print("existing route: %d sections, chain %s" % (len(secs), [s[0] for s in secs]))
    secs.insert(AFTER + 1, (MID, 0, 0x0001))
    print("inserted section value %d after index %d (section 313)" % (MID, AFTER))
    print("new chain: %s" % [s[0] for s in secs])

    n = worldpatch.install_route(buf, 0, secs, at=AT)
    print("wrote %d-section route (%d bytes) at DSK 0x%05X" % (len(secs), n, AT))

    back = routegraph.read(bytes(buf), AT)
    print("read back: %d nodes, ring closes: %s"
          % (len(back), back[-1]["next"] == 0x940000 + AT))
    for off in (0x08, 0x0C):
        p = struct.unpack_from(">I", buf, 0x00 + off)[0]
        print("  track 0 record +0x%02X -> 0x%06X %s" % (off, p, "OK" if p == 0x940000+AT else "FAIL"))
    vals = [nd["value"] for nd in back]
    print("  values in order: %s" % vals)
    print("  loop section present: %s" % (MID in vals))

    return buf


def main():
    import patch_segments
    buf = apply(load(SRC))
    patch_segments.write(buf, OUT)


if __name__ == "__main__":
    main()
