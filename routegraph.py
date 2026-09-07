"""Read and write Race Drivin' route graphs.

A route is a doubly-linked circular list of track sections, 26 bytes per node:

    +0x00  u16  section value (length; unit not yet established)
    +0x02  u16  the same value again (occasionally +1 or +5)
    +0x04  u32  0
    +0x08  u16  flags, three fields (decoded from the code at 0x02FF30):

                  bits 15-12  marker  1 = start, 2 = finish,
                              4 / 8 = alternating continuation gates, 0 = none
                  bits 11-8   route type; the game copies this to 0x90173E and
                              compares it against 2 at 0x0223DA
                  bits  7-0   index into the 12-byte section-name table that
                              the track record's +0x10 points at

                The code reads the LOW byte (+0x09), multiplies by 12 and
                indexes the name table; then reads the HIGH byte (+0x08),
                masks it with 0x0F and stores that as the route type.
    +0x0A  u32  next      (68k address, 0x94xxxx)
    +0x0E  u32  0
    +0x12  u32  previous
    +0x16  u32  0
    ---- 26 bytes ----

The track record's +0x08 and +0x0C point at the head of a route each; code at
0x0223C4/0x0223CA picks between them, which is the Speed / Stunt fork.
"""
import struct

NODE = 26
HEADS = {"A": 0x001EC, "B1": 0x006FE, "B2": 0x00884}


def read(dsk, head):
    """Walk a route from its head offset. Returns a list of dicts."""
    out, seen, a = [], set(), head
    while a not in seen:
        seen.add(a)
        v1, v2, fl = (struct.unpack_from(">H", dsk, a + o)[0] for o in (0, 2, 8))
        nxt, prv = (struct.unpack_from(">I", dsk, a + o)[0] for o in (0x0A, 0x12))
        out.append({"at": a, "value": v1, "value2": v2, "flags": fl,
                    "next": nxt, "prev": prv})
        if not (0x940000 <= nxt < 0x960000):
            break
        a = nxt - 0x940000
    return out


def flags(marker=0, route_type=0, name_index=0):
    """Build a section's flags word from its three fields."""
    if marker not in (0, 1, 2, 4, 8):
        raise ValueError("marker must be 0, 1 (start), 2 (finish), or 4/8 (gate)")
    if not 0 <= route_type <= 0x0F:
        raise ValueError("route type is 4 bits")
    if not 0 <= name_index <= 0xFF:
        raise ValueError("name index is 8 bits")
    return (marker << 12) | (route_type << 8) | name_index


def split_flags(f):
    return {"marker": (f >> 12) & 0xF, "route_type": (f >> 8) & 0xF,
            "name_index": f & 0xFF}


def encode(sections, base, background=0x0200):
    """Lay out a circular route at DSK offset `base`.

    `sections` is a list of (value, marker) or (value, marker, extra), where
    marker is 0 or one of 0x1000/0x2000/0x4000/0x8000 and `extra` supplies that
    section's own low bits - route type in 11-8 and name index in 7-0. A
    2-tuple falls back to the shared `background`. Returns bytes for `base`.
    """
    n = len(sections)
    if n < 2:
        raise ValueError("a route needs at least two sections")
    addr = [0x940000 + base + i * NODE for i in range(n)]
    out = bytearray()
    for i, sec in enumerate(sections):
        value, marker = sec[0], sec[1]
        low = sec[2] if len(sec) > 2 else background
        if marker not in (0, 0x1000, 0x2000, 0x4000, 0x8000):
            raise ValueError("marker must be 0 or a single bit of the top nibble")
        rec = bytearray(NODE)
        struct.pack_into(">H", rec, 0x00, value & 0xFFFF)
        struct.pack_into(">H", rec, 0x02, value & 0xFFFF)
        struct.pack_into(">H", rec, 0x08, low | marker)
        struct.pack_into(">I", rec, 0x0A, addr[(i + 1) % n])
        struct.pack_into(">I", rec, 0x12, addr[(i - 1) % n])
        out += rec
    return bytes(out)


def verify(blob, base, background=0x0200):
    """Read back what encode() produced and check the ring closes."""
    fake = bytearray(0x20000)
    fake[base:base + len(blob)] = blob
    nodes = read(bytes(fake), base)
    assert nodes[-1]["next"] == 0x940000 + base, "ring does not close"
    for i, nd in enumerate(nodes):
        assert nd["value"] == nd["value2"]
        assert (nd["flags"] & ~0xF000) == background
    return nodes


if __name__ == "__main__":
    d = open("rd_dskrom.bin", "rb").read()
    for name, head in HEADS.items():
        nodes = read(d, head)
        tot = sum(n["value"] for n in nodes)
        marks = [(i, n["flags"] & 0xF000) for i, n in enumerate(nodes)
                 if n["flags"] & 0xF000]
        print("route %-3s %2d sections, values sum %5d, markers %s"
              % (name, len(nodes), tot,
                 ", ".join("s%d=%04X" % m for m in marks)))
    # round-trip our own encoder against the real thing's shape
    secs = [(n["value"], n["flags"] & 0xF000) for n in read(d, HEADS["B1"])]
    blob = encode(secs, 0x1C044)
    back = verify(blob, 0x1C044)
    print("\nencoder round-trip: %d sections, values %s"
          % (len(back), "match" if [n["value"] for n in back] ==
             [s[0] for s in secs] else "MISMATCH"))
