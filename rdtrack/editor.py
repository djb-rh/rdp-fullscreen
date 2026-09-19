#!/usr/bin/env python3
"""The track editor: a local web page served by Python, editing the design files
that rdtrack.make compiles.

    python3 -m rdtrack.editor [--port 8765] [--romset racedriv.zip] [--mame ~/Developer/mame/hd]

Open http://127.0.0.1:8765/ .  The page chains road parts from parts.json,
shows the plan view with the closure residual per joint, saves designs/*.json,
builds a set with rdtrack.make and launches MAME on it.  Nothing leaves the
machine: the stock zip is read by the compiler only, and the page has no
network dependencies.
"""
import argparse, collections, contextlib, io, json, math, os, re, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import chain, worldgen, scenery, dsk, document
from . import compile as comp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGNS = os.path.join(HERE, "designs")
CONFIG = {"romset": os.path.expanduser("~/Developer/Race Drivin/racedriv.zip"),
          "mame": os.path.expanduser("~/Developer/mame/hd")}
STATE = {"build": None, "mame": None}       # running subprocesses and their logs
_TABLES = None
POOL = 495                                  # the ADSP's polygon pool (NOTES.md 2026-09-08)
SLACK = 300                                 # units between one relief piece's hand-off and the next origin


def tables():
    """The ROM-derived tables rdtrack.make uses, loaded once: catalogue, object index, per-object tails, stock image."""
    global _TABLES
    if _TABLES is None:
        sys.path.insert(0, HERE)
        import world as W
        w = W.World(); cat = {i: w.catalogue(i) for i in range(390)}; obj_index = {w.name(i): i for i in range(156)}
        buf = dsk.load(CONFIG["romset"]); D = dsk.Dsk(buf)
        cnt = collections.defaultdict(collections.Counter)
        for ti in (0, 2, 1):
            for p in D.worlds[D.tracks[ti]["descriptor"]]["placements"]:
                cnt[w.name(p["obj"])][(p["bias"], p["flags"])] += 1
        tails = {nm: c.most_common(1)[0][0] for nm, c in cnt.items()}
        objs = json.load(open(os.path.join(HERE, "objects.json"))) if os.path.exists(os.path.join(HERE, "objects.json")) else {}
        faces = {i: objs.get(w.name(i), {}).get("faces", 0) for i in range(156)}
        _TABLES = {"w": w, "cat": cat, "obj_index": obj_index, "tails": tails, "buf": buf, "faces": faces, "name": {i: w.name(i) for i in range(156)}}
    return _TABLES


def validate(design, lay):
    """Every check a real drive taught us, on the compiler's own output.  -> (checks, extra stats)."""
    checks, extra = [], {}
    def add(level, kind, msg, piece=None):
        checks.append({"level": level, "kind": kind, "msg": msg, "piece": piece})
    n = len(design.get("chain", []))
    if n == 0:
        return checks, extra
    # references into the chain
    for i, r in enumerate(design.get("route", [])):
        if not (0 <= r.get("piece", 0) < n):
            add("error", "route", "route entry %d points at piece %d; the chain has %d pieces" % (i, r.get("piece"), n))
    starts = [r for r in design.get("route", []) if r.get("marker") == 1]
    if len(starts) != 1:
        add("error", "route", "the route needs exactly one start entry (marker 1); it has %d" % len(starts))
    for i, sc in enumerate(design.get("scenery", [])):
        if "piece" in sc and not (0 <= sc["piece"] < n):
            add("error", "scenery", "scenery %d (%s) points at piece %d; the chain has %d pieces" % (i, sc.get("name"), sc["piece"], n))
    if not (0 <= design.get("start_piece", 0) < n):
        add("error", "route", "start_piece %d is outside the chain" % design.get("start_piece", 0))
    # joints: individually when a few are off, one line when the whole chain carries a residual
    bad = [j for j in lay["joints"] if abs(j["kink"]) > 2.0 or j["gap"] > 120]
    if len(bad) > 5:
        add("warn", "joint", "%d of %d joints are strained (up to %.1f degrees and %d units each): the chain does not close on its own" % (
            len(bad), len(lay["joints"]), max(abs(j["kink"]) for j in bad), max(j["gap"] for j in bad)))
    else:
        for j in bad:
            if abs(j["kink"]) > 2.0:
                add("warn", "joint", "joint after piece %d kinks %.1f degrees (stock wears 1-2)" % (j["after"], j["kink"]), j["after"])
            if j["gap"] > 120:
                add("warn", "joint", "joint after piece %d has a %d-unit gap (the parts overlap by 40 when they meet)" % (j["after"], j["gap"]), j["after"])
    c = lay.get("closure")
    if c and (math.hypot(c["dx"], c["dz"]) > 3000 or abs(c["dth"]) > 6):
        add("warn", "closure", "the chain misses its start by %d, %d units and %.1f degrees before spreading" % (c["dx"], c["dz"], c["dth"]))
    if not design.get("close"):
        add("info", "closure", "open chain: the route will not lap")
    # the compiler's own pass
    T = tables()
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            recs, cells, segs, nodes, pl, samples, entities = worldgen.expand(design, T["cat"], T["obj_index"], T["tails"])
    except SystemExit as e:
        add("error", "compile", "the compiler stopped: %s" % e); return checks, extra
    except Exception as e:
        add("error", "compile", "the compiler failed: %s: %s" % (type(e).__name__, e)); return checks, extra
    for line in out.getvalue().splitlines():
        line = line.strip()
        if line.startswith("WARNING:"):
            add("warn", "compiler", line[8:].strip())
        elif line.startswith("crossing:"):
            add("info", "crossing", line[9:].strip())
    nseg = len(segs["segs"])
    extra.update({"segments": nseg, "placements": len(recs), "route_nodes": len(nodes), "cells": [len(cl["recs"]) for cl in cells]})
    if nseg > 720:
        add("error", "budget", "%d segments; the DSP32C table holds 727 and the compiler caps at 720" % nseg)
    elif nseg > 650:
        add("warn", "budget", "%d segments of 720" % nseg)
    # same-level crossings: any centreline crossing that is not an UNDERP under a road
    geoms = [worldgen.piece_geometry(p) for p in pl]
    under = {(k, j) for k, j, *_r in worldgen.crossings(pl, geoms)}
    for k in range(len(pl)):
        for j in range(k + 2, len(pl)):
            if k == 0 and j == len(pl) - 1:
                continue
            if (k, j) in under or (j, k) in under:
                continue
            a_poly, b_poly = geoms[k][0], geoms[j][0]
            hit = None
            for a, b in zip(a_poly, a_poly[1:]):
                for cc, d in zip(b_poly, b_poly[1:]):
                    h = worldgen._seg_cross(a, b, cc, d)
                    if h:
                        hit = (a[0] + (b[0]-a[0])*h[0], a[1] + (b[1]-a[1])*h[0]); break
                if hit: break
            if hit:
                add("error", "overlap", "pieces %d (%s) and %d (%s) cross at %d, %d with no underpass" % (k, pl[k]["name"], j, pl[j]["name"], hit[0], hit[1]), k)
    # relief hand-offs: forced ownership windows must not overlap (sample_chain's rule)
    total, windows = 0.0, []
    for k, (poly, prof) in enumerate(geoms):
        if prof:
            for (s0, e0), (s1, e1) in zip(prof, prof[1:]):
                windows.append((total + s0, total + s1, k))
        total += poly[-1][3]
    windows.sort()
    for (a0, a1, k0), (b0, b1, k1) in zip(windows, windows[1:]):
        if k0 != k1 and b0 < a1 + SLACK:
            add("error", "handoff", "relief pieces %d (%s) and %d (%s) hand off %d units apart; leave at least %d" % (k0, pl[k0]["name"], k1, pl[k1]["name"], b0 - a1, SLACK), k1)
    # polygon load along the track: faces of every placement within its cull of the car
    worst = (0, None)
    for s in samples[::4]:
        load = 0
        for r in recs:
            if math.hypot(r["x"] - s["x"], r["z"] - s["z"]) <= T["cat"][r["obj"]]["cull"]:
                load += T["faces"].get(r["obj"], 0)
        if load > worst[0]:
            worst = (load, s)
    extra["poly_worst"] = worst[0]
    if worst[1] is not None:
        # a single driven-on road piece is already ~450 of the pool and the ADSP drops the rest by depth, so this
        # is a density estimate, not a limit: it says where the scene is busiest
        add("info", "polygons", "busiest view: about %d polygons within cull range at piece %d, %d units in (pool %d, sorted by depth)" % (
            worst[0], worst[1]["piece"], worst[1]["arc"], POOL), worst[1]["piece"])
    # the image itself
    try:
        doc = document.decompile(T["buf"])
        doc["worlds"]["A"] = {"desc_words": [28, 112, 112], "cells": cells,
                              "placements": [{k: (v.hex() if isinstance(v, bytes) else v) for k, v in p.items()} for p in recs]}
        doc["segments"]["A"] = segs; doc["routes"]["R0"] = {"nodes": nodes}
        for t in doc["tracks"]:
            t["world"] = "A"; t["segments"] = "A"; t["routes"] = ["R0", "R0"]; t["names"] = doc["tracks"][0]["names"]
            t["awards"] = doc["tracks"][0]["awards"]; t["entities"] = [entities, entities]; t["entities_at"] = [None, None]
        for k in [k for k in doc["worlds"] if k != "A"]: del doc["worlds"][k]
        for k in [k for k in doc["segments"] if k != "A"]: del doc["segments"][k]
        for k in [k for k in doc["routes"] if k != "R0"]: del doc["routes"][k]
        for k in [k for k in doc["names"] if k != doc["tracks"][0]["names"]]: del doc["names"][k]
        with contextlib.redirect_stdout(io.StringIO()):
            img, L = comp.compile_doc(doc, fixed=False)
        top = max(b for a, b in L.used)
        extra["image_free"] = comp.LIMIT - top
        if comp.LIMIT - top < 4096:
            add("warn", "budget", "only %d bytes free below the DSK checksum" % (comp.LIMIT - top))
    except SystemExit as e:
        add("error", "budget", "does not fit the DSK: %s" % e)
    except Exception as e:
        add("error", "compile", "compile failed: %s: %s" % (type(e).__name__, e))
    return checks, extra


def layout(design):
    """Plan-view geometry and the closure diagnostics for a design."""
    seq = [(n, bool(r)) for n, r in design.get("chain", [])]
    start = tuple(design.get("start", [150000, 150000, 90.0]))
    out = {"pieces": [], "joints": [], "closure": None, "scenery": [], "stats": {}}
    if not seq:
        return out
    parts = chain.parts()
    close = start if design.get("close") else None
    # the open run gives the raw closure error; the closed run is what compiles
    _open_poses, open_end = chain.entry_poses(start, seq, None)
    pl, end = chain.run(start, seq, close)
    geoms = [worldgen.piece_geometry(p) for p in pl]
    for k, (p, (poly, prof)) in enumerate(zip(pl, geoms)):
        P = parts[p["name"]]
        half = P["width"] / 2.0
        left, right = [], []
        for i, (x, z, e, a) in enumerate(poly):
            j = i + 1 if i + 1 < len(poly) else i
            i0 = i if i + 1 < len(poly) else i - 1
            dx, dz = poly[j][0] - poly[i0][0], poly[j][1] - poly[i0][1]
            L = math.hypot(dx, dz) or 1.0
            nx, nz = dz / L, -dx / L                    # right-hand normal (heading = atan2(x, z))
            right.append([round(x + nx * half), round(z + nz * half)])
            left.append([round(x - nx * half), round(z - nz * half)])
        out["pieces"].append({"index": k, "name": p["name"], "rev": p["rev"], "class": P["class"],
                              "x": p["x"], "z": p["z"], "rot": p["rot"], "entry": list(p["entry"]), "exit": list(p["exit"]),
                              "centre": [[round(x), round(z), round(e)] for x, z, e, a in poly],
                              "outline": right + left[::-1], "length": round(poly[-1][3]), "turn": P.get("turn", 0)})
    # joints: the gap and heading kink between piece k's exit pose and piece k+1's entry pose
    poses, _e = chain.entry_poses(start, seq, close)
    N = len(seq)
    for k in range(N if close else N - 1):
        _p, exit_pose = chain.place(poses[k], *seq[k])
        nxt = poses[(k + 1) % N] if k + 1 < N else start
        gap = math.hypot(nxt[0] - exit_pose[0], nxt[1] - exit_pose[1])
        kink = ((nxt[2] - exit_pose[2] + 180) % 360) - 180
        out["joints"].append({"after": k, "gap": round(gap), "kink": round(kink, 2)})
    if close:
        out["closure"] = {"dx": round(start[0] - open_end[0]), "dz": round(start[1] - open_end[1]),
                          "dth": round(((start[2] - open_end[2] + 180) % 360) - 180, 2)}
    # scenery, resolved the way the compiler resolves it
    objs = {}
    try:
        objs = json.load(open(os.path.join(HERE, "objects.json")))
    except Exception:
        pass
    try:
        track = scenery.Track(pl, geoms, bool(design.get("close")))
        for i, s in enumerate(design.get("scenery", [])):
            if "kit" in s:
                # composites resolve inside scenery.expand; show them at their anchor
                x, z, hd, y = scenery._pose({"piece": s.get("piece", 0), "arc": -1400, "side": 1200}, track)
                out["scenery"].append({"index": i, "name": "kit:" + s["kit"], "x": round(x), "z": round(z), "heading": round(hd, 1), "bbox": None})
                continue
            x, z, hd, y = scenery._pose(s, track)
            bb = objs.get(s.get("name", ""), {}).get("bbox")
            out["scenery"].append({"index": i, "name": s.get("name", "?"), "x": round(x), "z": round(z), "heading": round(hd, 1), "y": round(y),
                                   "bbox": [bb["x"][0], bb["z"][0], bb["x"][1], bb["z"][1]] if bb else None})
    except Exception as e:                                    # a stale piece index: report, don't fail the layout
        out["scenery_error"] = str(e)
    # exact segment count, as the compiler will make it; and where the start post lands (worldgen's rule)
    try:
        samples, total = worldgen.sample_chain(pl)
        sp, so = design.get("start_piece", 0), design.get("start_offset", 0)
        first = {}
        for i, sm in enumerate(samples):
            first.setdefault(sm["piece"], i)
        if sp in first:
            post = first[sp]
            for i, sm in enumerate(samples):
                if sm["piece"] == sp and sm["arc"] - samples[first[sp]]["arc"] <= so:
                    post = i
            out["startpost"] = [round(samples[post]["x"]), round(samples[post]["z"])]
        nseg = len(worldgen.segment_records(samples, closed=bool(design.get("close"))))
    except Exception as e:
        nseg, total = None, sum(g[0][-1][3] for g in geoms)
        out["segments_error"] = str(e)
    out["stats"] = {"pieces": N, "length": round(total), "segments": nseg, "segment_limit": 720,
                    "end": [round(end[0]), round(end[1]), round(end[2] % 360, 2)]}
    try:
        checks, extra = validate(design, out)
    except Exception as e:
        checks, extra = [{"level": "error", "kind": "validator", "msg": "%s: %s" % (type(e).__name__, e), "piece": None}], {}
    out["checks"] = checks; out["stats"].update(extra)
    return out


def _run_build(name):
    design = os.path.join(DESIGNS, name + ".json")
    outdir = os.path.join(HERE, "roms_" + name)
    cmd = [sys.executable, "-m", "rdtrack.make", design, CONFIG["romset"], "-o", outdir]
    log = {"cmd": " ".join(cmd), "lines": [], "done": False, "ok": None, "out": outdir}
    STATE["build"] = log
    def go():
        p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            log["lines"].append(line.rstrip())
        p.wait()
        log["done"], log["ok"] = True, p.returncode == 0
    threading.Thread(target=go, daemon=True).start()
    return log


def _run_mame(name, rec=None):
    outdir = os.path.join(HERE, "roms_" + name)
    if STATE["mame"] and STATE["mame"].poll() is None:
        STATE["mame"].terminate()
    env = dict(os.environ, AUTOSEL="1", AUTOSEL_DELTA="1200", DRIVE="1")
    if rec:
        env["REC"] = rec                        # rd.lua dumps the game's own lap recording there every 2 s and at exit
    cmd = [CONFIG["mame"], "racedriv", "-rompath", outdir, "-window", "-autoboot_script", "rd.lua"]
    STATE["mame"] = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": STATE["mame"].pid, "cmd": " ".join(cmd), "rec": rec}


def recordings():
    """The lap recordings on disk, with how many keyframes each holds (12 bytes per 0.2 s)."""
    from . import drones
    out = []
    d = os.path.join(HERE, "recordings")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith(".rec"):
            continue
        path = os.path.join(d, fn); n = None
        try:
            dump = open(path, "rb").read()
            import struct
            ptr = struct.unpack_from(">I", dump, drones.SLOT)[0] if len(dump) >= drones.SLOT + 4 else None
            n = (ptr - 0x90A838) // 12 if ptr else struct.unpack_from(">H", dump, 0x1C)[0]
        except Exception:
            pass
        out.append({"file": "recordings/" + fn, "keyframes": n, "seconds": round(n * drones.KF_S, 1) if n else None, "mtime": int(os.path.getmtime(path))})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/":
            page = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(page)))
            self.end_headers(); self.wfile.write(page)
        elif u.path == "/api/parts":
            objs = json.load(open(os.path.join(HERE, "objects.json"))) if os.path.exists(os.path.join(HERE, "objects.json")) else {}
            names = []
            try:
                doc = document.decompile(tables()["buf"]); t0 = doc["tracks"][0]
                names = [e["name"] for e in doc["names"][t0["names"]]["entries"]]
            except Exception as e:
                names = ["START", "SPEED", "STUNT", "DROPOFF", "BRIDGE", "LOOP", "JUMP", "BANKED"]
            self._json({"parts": chain.parts(), "objects": objs, "names": names})
        elif u.path == "/api/designs":
            self._json(sorted(f[:-5] for f in os.listdir(DESIGNS) if f.endswith(".json")))
        elif u.path == "/api/design":
            name = q.get("name", [""])[0]
            path = os.path.join(DESIGNS, os.path.basename(name) + ".json")
            if not os.path.exists(path):
                return self._json({"error": "no such design"}, 404)
            self._json(json.load(open(path)))
        elif u.path == "/api/build":
            self._json(STATE["build"] or {"lines": [], "done": True, "ok": None})
        elif u.path == "/api/recordings":
            self._json(recordings())
        elif u.path == "/api/status":
            m = STATE["mame"]
            self._json({"mame_running": bool(m and m.poll() is None), "romset": CONFIG["romset"], "mame": CONFIG["mame"]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/layout":
            try:
                self._json(layout(self._body()))
            except Exception as e:
                self._json({"error": "%s: %s" % (type(e).__name__, e)}, 400)
        elif u.path == "/api/design":
            name = os.path.basename(q.get("name", [""])[0])
            if not name:
                return self._json({"error": "name?"}, 400)
            design = self._body()
            path = os.path.join(DESIGNS, name + ".json")
            json.dump(design, open(path, "w"), indent=1)
            self._json({"saved": path})
        elif u.path == "/api/build":
            name = os.path.basename(q.get("name", [""])[0])
            if STATE["build"] and not STATE["build"]["done"]:
                return self._json({"error": "a build is running"}, 409)
            self._json(_run_build(name))
        elif u.path == "/api/drive":
            name = os.path.basename(q.get("name", [""])[0])
            if not os.path.isdir(os.path.join(HERE, "roms_" + name)):
                return self._json({"error": "build it first"}, 400)
            self._json(_run_mame(name))
        elif u.path == "/api/record":
            name = os.path.basename(q.get("name", [""])[0])
            if not os.path.isdir(os.path.join(HERE, "roms_" + name)):
                return self._json({"error": "build it first"}, 400)
            rec = "recordings/%s_%s.rec" % (name, time.strftime("%Y%m%d_%H%M%S"))
            self._json(_run_mame(name, rec))
        elif u.path == "/api/stop":
            m = STATE["mame"]
            if m and m.poll() is None:
                m.terminate()
            self._json({"stopped": True})
        else:
            self._json({"error": "not found"}, 404)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--romset", default=CONFIG["romset"])
    ap.add_argument("--mame", default=CONFIG["mame"])
    a = ap.parse_args(argv)
    CONFIG["romset"], CONFIG["mame"] = a.romset, a.mame
    os.chdir(HERE)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("track editor at http://127.0.0.1:%d/  (romset %s)" % (a.port, a.romset), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
