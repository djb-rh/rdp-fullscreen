"""Scenery: placing the non-road objects of a design.

Design entries (the "scenery" list of a design.json):

    {"name": "HOUSE", "piece": 4, "arc": 3000, "side": -2600, "heading": 0}
        track-relative: `arc` units along piece 4 from its entry (negative =
        before the entry, may run into the neighbours), `side` right (+) or
        left (-) of the centreline, `heading` relative to the direction of
        travel (default: buildings face the road, everything else faces along
        it); y = the road's elevation there (+ optional "dy").
    {"name": "BARN", "x": 120000, "z": 150000, "heading": 30, "y": 0}
        absolute world pose; y defaults to 0.
    {"kit": "curve_sign", "piece": 3, "speed": 90}
        a composite: LCURV/RCURV + floating speed number, 1400 before piece
        3's entry on the right, hand and default speed from the piece.
    "auto_signs": true   (design top level)
        a curve_sign before every run of curves, as stock does.

Any entry may override "bias" and "flags".  Stock's conventions, measured
from world A (NOTES.md 2026-09-09): curve signs on the right at +1000..1400,
facing travel; hills 3000-5600 off the road with bias +200/400; ground
patches wherever, some pushed to the back with bias ~24000.
"""
import json, math, os
from . import chain

CLASSES = {
    "ground":   "BROWN LBROWN LGREEN DGREEN BPAVE GRASS",
    "hill":     "HILL1 HILL2 HILL3 HILL_A HILL_B1 HILL_B2 HILL_B3 HILL_C1 HILL_C2 HILL_D1 HILL_D2 HILL_D3 HILL_D4 HILL_D5",
    "building": "HOUSE STORE BARN DINER RESTSTOP HUT LOFT SKIDPAD",
    "structure": "BRIDGE TUBE",
    "sign":     "LCURV RCURV TURNOFF GRDARROW DIP NEW60M NEW90M NEW150M FLOAT40 FLOAT60 FLOAT65 FLOAT90 FLOAT150 SIGNPOST SORS FINISH STRTPOST CHKPT WWAY",
    "prop":     "COW BALE CONEB CONER CONEW CONEY BARRIER PTABLE PBENCH TREEBLIT BROCK WEED WEED1 WEED2 FLOWER FLOWER1 FLOWER2 FLOWER3 CRSHSQ",
    "vehicle":  "TRAIN RRCAR VAN VANL CAR1 CAR2 CAR2A POR FER VET VET3 PIC JAG YEL TRUK3 WTRUK3 WPIC WWL WL WCAR1 WCAR2 WCAR2A WVAN WPOR WFER WVET WVET3 WJAG WYEL",
    "internal": "TESTOBJ STREET GRHORIZ FIREA FIREB FIREC FIRED EXPLO FBALL LITERED LITEYEL LITEGRN SWHL CAR1STOP CAR2STOP VANSTOP PORSTOP FERSTOP VETSTOP VET3STOP TRUK3STOP PICSTOP JAGSTOP YELSTOP WLSTOP CAR2ASTOP",
}
CLASS_OF = {n: c for c, names in CLASSES.items() for n in names.split()}
FLAGS_DEFAULT = {"sign": 0x9000, "prop": 0x9000}        # stock: signs, cones, cows carry bit 15 as well as draw-enable
BIAS_DEFAULT = {"hill": 400}
FLOAT_BIAS = -125                                        # the number sorts in front of its post (stock -113..-156)
SIGN_SIDE, SIGN_BEFORE = 1160, 1400                      # stock medians: lateral +1160, ~1400 before the curve
ROAD_HALF = 800
OVERHEAD = {"SORS", "FINISH", "STRTPOST", "CHKPT", "WWAY"}     # gantries and banners span the road by design


def speed_for(name):
    """Curve-sign number from the piece's radius (stock: 90 on D30R917/C4572)."""
    P = chain.parts()[name]
    turn, length = abs(P.get("turn") or 0), P.get("length") or 0
    if not turn:
        return None
    r = length / math.radians(turn)
    return 90 if r >= 25000 else 60 if r >= 15000 else 40


def kit(name, hand, speed):
    """-> [(object, d_along, d_side, d_heading, dy, bias)] in the anchor's frame."""
    if name == "curve_sign":
        return [("RCURV" if hand > 0 else "LCURV", 0, 0, 0, 0, None), ("FLOAT%d" % speed, 0, 0, 0, 0, FLOAT_BIAS)]
    if name == "speed_sign":
        return [("FLOAT%d" % speed, 0, 0, 0, 0, FLOAT_BIAS), ("SIGNPOST", 0, 0, 180, 0, None)]
    raise KeyError("unknown kit %r" % name)


class Track:
    """The chain's concatenated centreline: global arc -> pose and elevation."""
    def __init__(self, pl, geoms, closed):
        self.pl, self.closed = pl, closed
        self.poly, self.base = [], []
        total = 0.0
        for poly, _prof in geoms:
            self.base.append(total)
            self.poly += [(x, z, e, total + a) for x, z, e, a in poly]
            total += poly[-1][3]
        self.total = total

    def at(self, arc):
        """-> (x, z, heading, elev) at global arc (wrapped when closed)."""
        if self.closed:
            arc %= self.total
        arc = max(0.0, min(self.total, arc))
        P = self.poly
        for k in range(len(P) - 1):
            (x0, z0, e0, a0), (x1, z1, e1, a1) = P[k], P[k + 1]
            if a0 <= arc <= a1 and a1 > a0:
                t = (arc - a0) / (a1 - a0)
                hd = math.degrees(math.atan2(x1 - x0, z1 - z0)) % 360
                return x0 + (x1 - x0) * t, z0 + (z1 - z0) * t, hd, e0 + (e1 - e0) * t
        x0, z0, e0, _ = P[-2]; x1, z1, e1, _ = P[-1]
        return x1, z1, math.degrees(math.atan2(x1 - x0, z1 - z0)) % 360, e1

    def nearest(self, x, z):
        """-> (lateral distance, elev) of the closest centreline point."""
        best = None
        for k in range(len(self.poly) - 1):
            (x0, z0, e0, _), (x1, z1, e1, _) = self.poly[k], self.poly[k + 1]
            dx, dz = x1 - x0, z1 - z0
            L2 = dx * dx + dz * dz
            t = 0.0 if not L2 else max(0.0, min(1.0, ((x - x0) * dx + (z - z0) * dz) / L2))
            d = math.hypot(x - (x0 + dx * t), z - (z0 + dz * t))
            if best is None or d < best[0]:
                best = (d, e0 + (e1 - e0) * t)
        return best


def _pose(entry, track):
    """Resolve a design entry to (x, z, heading, y) in the world."""
    if "piece" in entry:
        arc = track.base[entry["piece"]] + entry.get("arc", 0)
        x, z, hd, elev = track.at(arc)
        side = entry.get("side", 0)
        fx, fz = math.sin(math.radians(hd)), math.cos(math.radians(hd))
        x, z = x + fz * side, z - fx * side                       # +side = right of travel
        y = entry["y"] if "y" in entry else -elev + entry.get("dy", 0)
        rel = entry.get("heading")
        if rel is None:
            # stock buildings face -x in model space and sit on the right with the
            # road's heading, so a left-side building turns round to face the road
            # (seen from behind, STORE is an open shell with a sign pole)
            rel = 180 if (side < 0 and CLASS_OF.get(entry.get("name"), "") in ("building", "structure", "vehicle")) else 0
        return x, z, (hd + rel) % 360, y
    return entry["x"], entry["z"], entry.get("heading", 0) % 360, entry.get("y", 0)


def _hand(pl_entry):
    P = chain.parts()[pl_entry["name"]]
    t = P.get("turn") or 0
    return -t if pl_entry["rev"] else t


def expand(design, pl, geoms, obj_index, tails, bbox, place):
    """-> (records, warnings).  `place(obj, heading, x, y, z, bias, flags)` makes a record."""
    track = Track(pl, geoms, bool(design.get("close")))
    entries = list(design.get("scenery", []))
    if design.get("auto_signs"):
        prev = _hand(pl[-1]) if track.closed else 0
        for i, p in enumerate(pl):
            h = _hand(p)
            if h and (prev == 0 or (prev > 0) != (h > 0)):
                entries.append({"kit": "curve_sign", "piece": i})
            prev = h
    records, warnings = [], []
    for e in entries:
        items = [(e.get("name"), 0, 0, 0, 0, None)]
        if "kit" in e:
            hand = _hand(pl[e["piece"]]) if "piece" in e else e.get("hand", 1)
            speed = e.get("speed") or (speed_for(pl[e["piece"]]["name"]) if "piece" in e else 60)
            items = kit(e["kit"], hand, speed)
            e = dict(e); e.setdefault("arc", -SIGN_BEFORE); e.setdefault("side", SIGN_SIDE)
        x, z, hd, y = _pose(e, track)
        fx, fz = math.sin(math.radians(hd)), math.cos(math.radians(hd))
        for name, da, ds, dh, dy, kb in items:
            if name not in obj_index:
                warnings.append("unknown object %s" % name); continue
            cls = CLASS_OF.get(name, "other")
            b, f = tails.get(name, (BIAS_DEFAULT.get(cls, 0), FLAGS_DEFAULT.get(cls, 0x1000)))
            if kb is not None: b = kb
            b = e.get("bias", b); f = e.get("flags", f)
            px, pz = x + fx * da + fz * ds, z + fz * da - fx * ds
            records.append(place(obj_index[name], (hd + dh) % 360, px, y + dy, pz, b, f))
            if cls in ("building", "structure", "prop", "vehicle", "sign") and name not in OVERHEAD:
                w = _road_overlap(name, px, pz, (hd + dh) % 360, y + dy, bbox, track)
                if w: warnings.append(w)
    return records, warnings


def _road_overlap(name, x, z, hd, y, bbox, track):
    """Warn when an object's ground footprint reaches into the road strip at road level."""
    bb = bbox.get(name)
    if not bb:
        return None
    (x0, x1), (z0, z1) = bb["x"], bb["z"]
    r = math.radians(hd); s, c = math.sin(r), math.cos(r)
    worst = None
    for mx, mz in ((x0, z0), (x1, z0), (x0, z1), (x1, z1), (0, 0), ((x0+x1)/2, z0), ((x0+x1)/2, z1), (x0, (z0+z1)/2), (x1, (z0+z1)/2)):
        wx, wz = x + c * mx + s * mz, z - s * mx + c * mz
        d, elev = track.nearest(wx, wz)
        if d < ROAD_HALF and abs(-elev - y) < 400 and (worst is None or d < worst):
            worst = d
    if worst is not None:
        return "%s at (%d, %d) reaches %d from the road centreline (road half-width %d)" % (name, x, z, worst, ROAD_HALF)
    return None


def catalogue(w, worlds, out="objects.json"):
    """Write the editor's object palette: every object with class, bbox, size and stock use."""
    import collections
    use = collections.defaultdict(lambda: collections.defaultdict(int))
    for label, W in worlds.items():
        for p in W["placements"]:
            use[p["obj"]][label] += 1
    parts = chain.parts()
    objs = {}
    for i in range(156):
        nm = w.name(i)
        m = w.model(i)
        if m is None:
            continue
        vs = m["verts"]
        bb = {a: (min(v[k] for v in vs), max(v[k] for v in vs)) for k, a in enumerate("xyz")}
        cls = "road" if nm in parts else CLASS_OF.get(nm, "other")
        objs[nm] = {"index": i, "class": cls, "radius": w.catalogue(i)["radius"], "cull": w.catalogue(i)["cull"],
                    "verts": len(vs), "faces": len(m["faces"]), "bbox": bb, "stock_use": dict(use[i])}
    json.dump(objs, open(out, "w"), indent=1, sort_keys=True)
    return objs


def bboxes(path="objects.json"):
    if not os.path.exists(path):
        return {}
    return {n: o["bbox"] for n, o in json.load(open(path)).items()}
