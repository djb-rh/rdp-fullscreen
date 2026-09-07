"""Build VIR's route graph: sections at the named corners, start/finish where
the user placed it (2/3 down pit lane), and gates in the ROM's own scheme.

Marker scheme, as read off all three stock routes:
    0x1000  once, on the first section          - start
    0x2000  once, on the LAST section           - finish
    0x4000 / 0x8000  strictly alternating       - continuation gates

The section VALUE's unit is not yet established, so `unit_per_metre` is left as
the one open parameter. Everything else is fixed.
"""
import json, math, sys
import routegraph as R

START_SAMPLE = 481          # 2/3 down pit lane, per the user
STEP_M = 10.0


def sections(unit_per_metre=1.0, target=None):
    """Section boundaries are the real OSM way boundaries of the Full Course,
    recovered by re-walking the loop, not an even division."""
    import vir_fetch as F
    d = json.load(open("vir_centreline.json"))
    n = len(d["xy"])
    raw = json.load(open(F.CACHE))
    lat0, lon0 = d["lat0"], d["lon0"]
    ways = F.build_ways(raw, lat0, lon0)
    _dv, _L, path = F.find_loop(ways)

    # cumulative metres at each way boundary, in lap order
    bounds, acc = [], 0.0
    for i, rev in path:
        bounds.append((acc, ways[i]["name"]))
        acc += ways[i]["len"]
    lap = acc

    # rotate so the lap starts at START_SAMPLE, and convert to metres
    start_m = START_SAMPLE * STEP_M
    rot = sorted(((b - start_m) % lap, nm) for b, nm in bounds)
    if rot[0][0] > 1.0:                     # the start itself opens a section
        rot.insert(0, (0.0, "start/finish straight"))

    out = []
    for k, (at, nm) in enumerate(rot):
        nxt = rot[k + 1][0] if k + 1 < len(rot) else lap
        metres = nxt - at
        if metres < 40:                     # fold away slivers
            continue
        out.append({"name": nm, "at_m": at, "metres": metres,
                    "value": int(round(metres * unit_per_metre))})

    alt = 0x8000
    for i, sec in enumerate(out):
        if i == 0: sec["marker"] = 0x1000
        elif i == len(out) - 1: sec["marker"] = 0x2000
        else:
            sec["marker"] = alt
            alt = 0x4000 if alt == 0x8000 else 0x8000
    if target:
        tot = sum(x["value"] for x in out) or 1
        for x in out:
            x["value"] = max(1, int(round(x["value"] * target / tot)))
    return out


if __name__ == "__main__":
    tgt = int(sys.argv[1]) if len(sys.argv) > 1 else None
    secs = sections(unit_per_metre=1.0, target=tgt)
    print("VIR route: %d sections, start/finish at centreline sample %d"
          % (len(secs), START_SAMPLE))
    for i, s in enumerate(secs):
        print("  %2d %-30s %6.0f m   value %5d   marker %04X"
              % (i, s["name"][:30], s["metres"], s["value"], s["marker"]))
    print("  lap %.0f m, values sum %d" % (sum(s["metres"] for s in secs),
                                           sum(s["value"] for s in secs)))
    blob = R.encode([(s["value"], s["marker"]) for s in secs], 0x1C044)
    R.verify(blob, 0x1C044)
    print("\nencoded %d bytes at DSK 0x1C044; ring closes, markers legal" % len(blob))
