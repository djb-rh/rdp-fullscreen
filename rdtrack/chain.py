"""Chain road parts by their measured entry/exit poses (parts.json).

A pose is (x, z, heading) in world units / degrees, heading = atan2(x, z) so
0 is +z and 90 is +x, matching the placement matrix convention (world =
position + M * model, row-major 1.14).  A part is placed by rotating it so its
entry heading lands on the pose heading and translating its entry point onto
the pose; "rev" drives the part backwards (its exit becomes the entry, 180
degrees turned) - which is how stock builds left-hand curves from right-hand
models, and why it must be a rotation, never a mirror.

close=(x, z, heading) spreads the chain's closing error over the joints, as
stock itself kinks 1-2 degrees per joint (see layout.entry_poses).
"""
import json, math, os

_PARTS = None


def parts():
    global _PARTS
    if _PARTS is None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _PARTS = json.load(open(os.path.join(here, "parts.json")))
    return _PARTS


def ends(name, rev=False):
    """(entry (x, z, h), exit (x, z, h)) in model coordinates, for the driving direction.

    Positions are the measured end cross-sections.  The exit heading is the
    entry heading plus the DESIGN turn where the name decodes one (45 for
    C4572, not its measured 44.24): the models' end edges are skewed up to a
    degree, and chaining by those skews made a 270-degree loop turn 265 and a
    figure-8 miss by 2865 units.  Stock chains by design angles and wears the
    skew as a small wedge at each seam; so do we."""
    p = parts()[name]
    e, x = p["entry"], p["exit"]
    turn = ((x[2] - e[2] + 180) % 360) - 180
    if "design" in p:
        turn = math.copysign(p["design"]["turn"], turn) if abs(turn) > 0.5 else 0.0
    if not rev:
        return (e[0], e[1], e[2]), (x[0], x[1], e[2] + turn)
    return (x[0], x[1], (x[2] + 180) % 360), (e[0], e[1], (x[2] + 180) % 360 - turn)


def place(pose, name, rev=False):
    """-> (placement {name, x, y, z, m, heading, rev, entry, exit}, exit pose)."""
    (ex, ez, eh), (xx, xz, xh) = ends(name, rev)
    px, pz, ph = pose
    rot = ph - eh                                  # world = R(rot) * model
    r = math.radians(rot); s, c = math.sin(r), math.cos(r)
    q = lambda v: int(round(v * 16384))
    M = [q(c), 0, q(s), 0, 16384, 0, q(-s), 0, q(c)]
    # rotate a model point: X = c*x + s*z ; Z = -s*x + c*z
    def W(mx, mz):
        return c*mx + s*mz, -s*mx + c*mz
    rx, rz = W(ex, ez)
    ox, oz = px - rx, pz - rz                      # model origin in the world
    wx, wz = W(xx, xz)
    exit_pose = (ox + wx, oz + wz, (xh + rot) % 360)
    return ({"name": name, "x": round(ox), "y": 0, "z": round(oz), "m": M, "rot": round(rot % 360, 3), "rev": rev,
             "entry": (round(px), round(pz)), "exit": (round(exit_pose[0]), round(exit_pose[1]))},
            exit_pose)


def entry_poses(start, seq, close=None):
    N = len(seq)

    def run(dth):
        pose, poses = tuple(start), []
        for k, (name, rev) in enumerate(seq):
            pose = (pose[0], pose[1], pose[2] + dth/N)
            poses.append(pose)
            _p, pose = place(pose, name, rev)
        return poses, pose
    poses, end = run(0.0)
    if close is None:
        return poses, end
    dth = ((close[2] - end[2] + 180) % 360) - 180
    poses, end = run(dth)
    dx, dz = close[0] - end[0], close[1] - end[1]
    return [(x + dx*(k+0.5)/N, z + dz*(k+0.5)/N, h) for k, (x, z, h) in enumerate(poses)], end


def run(start, seq, close=None):
    """seq = [(part name, rev)] -> (placements, end pose)."""
    poses, _end = entry_poses(start, seq, close)
    out, end = [], None
    for pose, (name, rev) in zip(poses, seq):
        p, end = place(pose, name, rev)
        out.append(p)
    return out, end


def length(seq):
    return sum(parts()[n]["length"] for n, _r in seq)
