"""Drone paths: the recorded laps the traffic and the attract demo replay.

Format (main ROM, NOTES.md R4 + 2026-09-09): a track's paths sit in an array
of 0x2598-byte slots (56-byte header + up to 797 12-byte keyframes, one per
50 clock units = 0.2 s).  Track record +0x8C -> slot 0; the +0x9C table
(18 B) holds the slot count, slot 0 again, the drone-list count and pointer;
each 14-byte drone-list entry is (kind, name ptr, slot, param, flags, w).
Kind 1 lines up on the grid and follows its own slot; kind 3 is already on
the path `param` keyframes in when the race starts; kind 2 starts parked and
is released later; kind 4 is the champion ghost.  Attract mode replays slot 0.

    header +0x00 type (1)   +0x02 label[8]   +0x0A 3x3 initial matrix (1.14)
           +0x1C total keyframes   +0x1E run-in (played once, the loop starts
           there)   +0x20 start xyz (where the loop starts)   +0x2C parked xyz
    keyframe: dx dy dz (s16, per 0.2 s)  pitch roll (s16)  heading (u16 turns)

The game records the player's own lap in the same form at RAM 0x90A800
(write pointer 0x9051FE): rd.lua REC=file dumps it and `from_recording`
turns it into a path.  `from_centreline` synthesises a lap without driving.
"""
import math, struct

SLOT = 0x2598
HDR = 56
MAXKF = (SLOT - HDR) // 12            # 797
PATHS_AT = 0x0A0000                   # slot 0 of track 0 in the main ROM (pair 1012/1011)
NSLOTS = 16                           # 0x0A0000 .. 0x0C5980 as stock lays them out
UNITS_PER_M = 131.0
KF_S = 0.2
LANE_RACE, LANE_ONCOMING = 300, -420  # right-hand traffic: the lap in the right half, oncoming in the left
GRID = ((3000, 583), (3000, 183), (0, 583), (6000, 583), (6000, 183))   # stock's grid: pairs ahead and one alongside (player lane ~200); nothing behind the line


def mph(v):
    return v * 0.44704 * UNITS_PER_M


class Path:
    def __init__(self, label=b"", matrix=None, runin=0, start=(0, 0, 0), parked=(0, 0, 0), kf=None, type_=1):
        self.label, self.matrix, self.runin, self.start, self.parked, self.kf, self.type = label, matrix, runin, start, parked, kf or [], type_

    @classmethod
    def decode(cls, buf, off):
        h = buf[off:off + HDR]
        total = struct.unpack_from(">H", h, 0x1C)[0]
        kf = [struct.unpack_from(">hhhhhH", buf, off + HDR + 12 * k) for k in range(total)]
        return cls(bytes(h[2:10]), list(struct.unpack_from(">9h", h, 0x0A)), struct.unpack_from(">H", h, 0x1E)[0],
                   struct.unpack_from(">iii", h, 0x20), struct.unpack_from(">iii", h, 0x2C), kf, struct.unpack_from(">H", h, 0)[0])

    def encode(self):
        if len(self.kf) > MAXKF:
            raise ValueError("path has %d keyframes, a slot holds %d" % (len(self.kf), MAXKF))
        out = bytearray(HDR)
        struct.pack_into(">H", out, 0, self.type); out[2:10] = (self.label + bytes(8))[:8]
        struct.pack_into(">9h", out, 0x0A, *self.matrix)
        struct.pack_into(">HH", out, 0x1C, len(self.kf), self.runin)
        struct.pack_into(">iii", out, 0x20, *[int(v) for v in self.start]); struct.pack_into(">iii", out, 0x2C, *[int(v) for v in self.parked])
        for k in self.kf:
            out += struct.pack(">hhhhhH", *[int(v) for v in k[:5]], int(k[5]) & 0xFFFF)
        return bytes(out)

    def positions(self):
        """Accumulate the loop's deltas from `start`; -> [(x, y, z)] (run-in from parked first)."""
        pts, p = [], list(self.parked)
        for k, d in enumerate(self.kf):
            if k == self.runin:
                p = list(self.start)
            p = [p[0] + d[0], p[1] + d[1], p[2] + d[2]]
            pts.append(tuple(p))
        return pts


def heading_matrix(h_turns):
    r = h_turns / 65536.0 * 2 * math.pi; s, c = math.sin(r), math.cos(r)
    q = lambda v: int(round(v * 16384))
    return [q(c), 0, q(s), 0, 16384, 0, q(-s), 0, q(c)]


def _keyframes(pts):
    """World points 0.2 s apart -> keyframes; the last delta closes back to pts[0]."""
    kf = []
    n = len(pts)
    for k in range(n):
        x0, y0, z0 = pts[k]; x1, y1, z1 = pts[(k + 1) % n]
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        hd = int(round(math.atan2(dx, dz) / (2 * math.pi) * 65536)) & 0xFFFF
        run = math.hypot(dx, dz)
        pitch = int(round(math.atan2(dy, run) / (2 * math.pi) * 65536)) if run else 0
        kf.append([int(round(dx)), int(round(dy)), int(round(dz)), pitch, 0, hd])
    return kf


def _close(kf, lo, hi, target):
    """Make sum(kf[lo:hi]) == target by nudging deltas (rounding residue)."""
    for axis in range(3):
        res = int(round(target[axis])) - sum(k[axis] for k in kf[lo:hi])
        i, step = lo, 1 if res > 0 else -1
        while res:
            kf[i][axis] += step; res -= step; i = lo + ((i - lo + 1) % (hi - lo))


def _section_bits(kf, arcs, bits_at):
    """The game reads a 6-bit route-node counter from each keyframe (pitch bits 0-2 <<3 | heading
    bits 0-2, loader 0x0360E8) and compares it with the player's (0x9016BE) for the rubber band."""
    for k, a in zip(kf, arcs):
        b = bits_at(a) & 63
        k[3] = (k[3] & ~7) | (b >> 3); k[5] = (k[5] & ~7) | (b & 7)


def from_centreline(track, speed_mph, lane=LANE_RACE, start_arc=0.0, grid=None, label=b"CAR", reverse=False, preroll=0, bits_at=None):
    """A lap at constant speed along `track` (scenery.Track: .at(arc) -> x, z, heading, elev, .total).
    grid: (arc, lane) of the parked spot; the run-in accelerates from there to the loop start.
    preroll: instead, a run-in made of the `preroll` keyframes of lap that precede the start
    (the game rewinds every drone through its run-in at the green light and a kind-3 drone
    is placed by walking the path from the run-in, so the run-in must exist)."""
    v = mph(speed_mph) * KF_S
    n = max(2, int(round(track.total / v)))
    v = track.total / n
    sgn = -1 if reverse else 1
    def at(arc, ln):
        x, z, hd, elev = track.at(arc)
        fx, fz = math.sin(math.radians(hd)), math.cos(math.radians(hd))
        return x + fz * ln, -elev, z - fx * ln
    loop_arcs = [start_arc + sgn * k * v for k in range(n)]
    loop = [at(a, lane) for a in loop_arcs]
    runin, runin_arcs = [], []
    if grid is not None:
        garc, glane = grid
        D = (start_arc - garc) * sgn
        if D <= 0:
            D += track.total
        T = 2 * D / (v / KF_S)                          # constant acceleration 0 -> v
        nr = max(1, int(math.ceil(T / KF_S)))
        for k in range(nr):
            f = (k / nr) ** 2
            runin_arcs.append(garc + sgn * D * f)
            runin.append(at(runin_arcs[-1], glane + (lane - glane) * min(1.0, k / max(1, nr - 1))))
    if preroll:
        runin, runin_arcs = loop[-preroll:], loop_arcs[-preroll:]
    kf = _keyframes(loop)                                   # closes loop[-1] -> loop[0]
    if runin:
        kf = _keyframes(runin + [loop[0]])[:-1] + kf        # run-in ends on the loop's first point
        _close(kf, 0, len(runin), [loop[0][a] - runin[0][a] for a in range(3)])
    _close(kf, len(runin), len(kf), [0, 0, 0])
    if bits_at:
        _section_bits(kf, runin_arcs + loop_arcs, bits_at)
    if len(kf) > MAXKF:
        raise ValueError("lap needs %d keyframes at %d mph (slot holds %d): raise the speed or shorten the lap" % (len(kf), speed_mph, MAXKF))
    p = Path(label, heading_matrix(kf[0][5]), len(runin), loop[0], runin[0] if runin else loop[0], kf)
    return p


def from_recording(dump, start_xz=None):
    """The game's RAM recording (0x90A800.., 9624 bytes, plus the 4-byte write pointer appended)
    -> a drone path: the loop is one lap from the keyframe nearest `start_xz`."""
    ptr = struct.unpack_from(">I", dump, SLOT)[0] if len(dump) >= SLOT + 4 else None
    n = (ptr - 0x90A838) // 12 if ptr else struct.unpack_from(">H", dump, 0x1C)[0]
    if n <= 0:
        raise ValueError("empty recording")
    h = bytearray(dump[:HDR]); struct.pack_into(">H", h, 0x1C, n)
    p = Path.decode(bytes(h) + dump[HDR:HDR + 12 * n], 0)
    p.kf = [list(k) for k in p.kf]; p.runin = 0; p.start = p.parked
    pts = p.positions()
    if start_xz is None:
        return p
    d = [math.hypot(x - start_xz[0], z - start_xz[1]) for x, y, z in pts]
    i0 = min(range(len(pts)), key=lambda i: d[i])
    # the next pass of the line after a decent run: the lap
    i1 = None
    for i in range(i0 + 50, len(pts)):
        if d[i] < 2500 and all(d[j] >= d[i] for j in range(max(i0 + 50, i - 10), min(len(pts), i + 10))):
            i1 = i; break
    if i1 is None:
        raise ValueError("no full lap in the recording (%d keyframes, nearest the line at %d)" % (len(pts), i0))
    lap = [list(k) for k in p.kf[i0:i1]]
    _close(lap, 0, len(lap), [0, 0, 0])
    runin = [list(k) for k in p.kf[:i0]]
    q = Path(p.label, heading_matrix(lap[0][5]), len(runin), pts[i0 - 1] if i0 else p.parked, p.parked, runin + lap)
    if runin:
        _close(q.kf, 0, len(runin), [q.start[a] - q.parked[a] for a in range(3)])
    return q


# ------------------------------------------------------------- installing ---
NAMES = {"CAR2": 0x0E54, "POR": 0x0E5A, "VET3": 0x0E5E, "CAR2A": 0x0E64, "VAN": 0x0E6A, "TRUK3": 0x0E6E, "CAR1": 0x0E74, "PIC": 0x0E84}
LIST_AT, LIST_MAX = 0x0CB0, 20        # stock track 0's list; with one world the three tracks' areas are ours
T9C = (0x0C7A, 0x0C8C, 0x0C9E)        # the +0x9C tables
TA0 = (0x0BFC, 0x0C26, 0x0C50)        # the 42-byte tables
TRACK_REC = 0xA4


def install(main, dskbuf, paths, entries, ghost=None):
    """Write `paths` into slots 0.. of the main ROM image and point every track at them.
    entries: [(kind, name, slot, param)].  Returns the number of slots used."""
    if len(paths) + (1 if ghost else 0) > NSLOTS:
        raise ValueError("too many paths")
    for k, p in enumerate(paths):
        data = p.encode()
        main[PATHS_AT + k * SLOT:PATHS_AT + k * SLOT + len(data)] = data
    nslots = len(paths)
    if ghost:
        data = ghost.encode()
        main[PATHS_AT + nslots * SLOT:PATHS_AT + nslots * SLOT + len(data)] = data
    if len(entries) > LIST_MAX:
        raise ValueError("too many drones")
    for i, (kind, name, slot, param) in enumerate(entries):
        a = LIST_AT + 14 * i
        struct.pack_into(">HIHHHH", dskbuf, a, kind, 0x940000 + NAMES[name], slot, param, 0, 0x0307)
    for t in range(3):
        rec = t * TRACK_REC
        struct.pack_into(">I", dskbuf, rec + 0x8C, PATHS_AT)
        struct.pack_into(">HIHI", dskbuf, T9C[t], nslots + (1 if ghost else 0), PATHS_AT, len(entries), 0x940000 + LIST_AT)
        struct.pack_into(">I", dskbuf, TA0[t] + 2, PATHS_AT)
        if ghost:
            struct.pack_into(">I", dskbuf, TA0[t] + 0x20, PATHS_AT + nslots * SLOT)
    return nslots + (1 if ghost else 0)


def node_counter(samples, nodes, start, total, bias=70):
    """-> bits_at(arc): route nodes entered since the lap's start line, as the game counts them
    (0x02EF3C: +1 per node entered, the finish node rounds up to the next lap = 0 mod 64)."""
    n = len(samples)
    post = start - 1                                   # the finish node's segment
    def seg_of(arc):
        arc %= total
        i = max(k for k in range(n) if samples[k]["arc"] <= arc + 1e-6)
        return i + 1
    order = []
    for nd in nodes:
        seg = nd["value"] - bias + 1
        if (nd["flags"] >> 12) & 0xF in (1, 2):        # the start node is where the count begins (the
            continue                                   # player sits in it at 0); the finish is the rollover
        order.append((seg - start) % n)
    def bits_at(arc):
        k = (seg_of(arc) - start) % n
        return sum(1 for o in order if o <= k)
    return bits_at


def plan(design, track, player_arc, bits_at=None):
    """Design "drones" -> (paths, entries).  Defaults: three cars on the grid with the
    player, two oncoming cars in the left lane (kind 1 all round; the game's kind 3
    placed cars off the path in tests, so oncoming cars get their own slots)."""
    d = design.get("drones", {})
    n_race, n_on = d.get("count", 3), d.get("oncoming", 2)
    speeds = d.get("speeds") or [d.get("speed", 70) - 4 * k for k in range(n_race)]
    cars = d.get("cars") or ["CAR2", "POR", "VET3", "CAR2A", "CAR1"]
    paths, entries = [], []
    # recorded laps first: "recordings": ["my_lap.rec"] (rd.lua REC=my_lap.rec while driving a
    # clean lap of this very design); the lap is cut at the start line and gets its own slot
    for k, fn in enumerate(d.get("recordings", [])):
        sx, _y, sz = track.at(player_arc)[0], 0, track.at(player_arc)[1]
        p = from_recording(open(fn, "rb").read(), (sx, sz))
        if bits_at:
            _section_bits(p.kf[p.runin:], [player_arc + i * (track.total / max(1, len(p.kf) - p.runin)) for i in range(len(p.kf) - p.runin)], bits_at)
        p.label = cars[k % len(cars)].encode()
        paths.append(p); entries.append((1, cars[k % len(cars)], len(paths) - 1, 1))
    grid = [(player_arc + GRID[k % len(GRID)][0], GRID[k % len(GRID)][1]) for k in range(n_race)]
    for k in range(n_race):
        paths.append(from_centreline(track, speeds[k], LANE_RACE, player_arc + 20000, grid[k], cars[k % len(cars)].encode(), bits_at=bits_at))
        entries.append((1, cars[k % len(cars)], len(paths) - 1, 1))
    v_on = max(d.get("oncoming_speed", 45), math.ceil(track.total / ((MAXKF - 40) * KF_S) / mph(1)))
    for k in range(n_on):
        phase = player_arc + track.total * (k + 1) / (n_on + 1)      # spread round the lap, away from the grid
        on = from_centreline(track, v_on, LANE_ONCOMING, phase, None, ["VAN", "TRUK3", "PIC"][k % 3].encode(), reverse=True, preroll=40, bits_at=bits_at)
        paths.append(on)
        entries.append((1, ["VAN", "TRUK3", "PIC"][k % 3], len(paths) - 1, 1))
    return paths, entries
