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
import argparse, json, math, os, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import chain, worldgen, scenery

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGNS = os.path.join(HERE, "designs")
CONFIG = {"romset": os.path.expanduser("~/Developer/Race Drivin/racedriv.zip"),
          "mame": os.path.expanduser("~/Developer/mame/hd")}
STATE = {"build": None, "mame": None}       # running subprocesses and their logs


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
    try:
        track = scenery.Track(pl, geoms, bool(design.get("close")))
        for i, s in enumerate(design.get("scenery", [])):
            x, z, hd, y = scenery._pose(s, track)
            out["scenery"].append({"index": i, "name": s.get("name", "?"), "x": round(x), "z": round(z), "heading": round(hd, 1)})
    except Exception as e:                                    # a stale piece index: report, don't fail the layout
        out["scenery_error"] = str(e)
    # exact segment count, as the compiler will make it
    try:
        samples, total = worldgen.sample_chain(pl)
        nseg = len(worldgen.segment_records(samples, closed=bool(design.get("close"))))
    except Exception as e:
        nseg, total = None, sum(g[0][-1][3] for g in geoms)
        out["segments_error"] = str(e)
    out["stats"] = {"pieces": N, "length": round(total), "segments": nseg, "segment_limit": 720,
                    "end": [round(end[0]), round(end[1]), round(end[2] % 360, 2)]}
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


def _run_mame(name):
    outdir = os.path.join(HERE, "roms_" + name)
    if STATE["mame"] and STATE["mame"].poll() is None:
        STATE["mame"].terminate()
    env = dict(os.environ, AUTOSEL="1", AUTOSEL_DELTA="1200", DRIVE="1")
    cmd = [CONFIG["mame"], "racedriv", "-rompath", outdir, "-window", "-autoboot_script", "rd.lua"]
    STATE["mame"] = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": STATE["mame"].pid, "cmd": " ".join(cmd)}


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
            self._json({"parts": chain.parts(), "objects": objs})
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
