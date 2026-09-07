"""Chain Race Drivin' road pieces end to end.

Two things make this fiddly and both are measured, not assumed:
  * a piece's model origin is NOT generally at the midpoint of its chord -
    every curve is offset sideways (D30R917 by 1086 units, C4572 by 2007)
  * the usable chord is the distance between the two end cross-sections,
    which has to be found via the model's principal axis
Both live in piece_ends.json.
"""
import json, math

U = 3.280839895 * 40.0
ENDS = json.load(open("piece_ends.json"))


def piece(name, hand=+1):
    e = ENDS[name]
    return {"name": name, "turn": e["turn"] * hand, "chord": e["chord"],
            "off": e["mid"], "hand": hand}


def place(pose, p):
    """pose = (x, z, heading_deg) at the piece's entry. Returns (placement, exit pose)."""
    x, z, h = pose
    half = p["turn"] / 2.0
    a = math.radians(h + half)                  # the chord bisects the turn
    ca, sa = math.cos(a), math.sin(a)
    cx = x + sa * p["chord"] / 2                # chord midpoint, in world
    cz = z + ca * p["chord"] / 2
    nx = x + sa * p["chord"]
    nz = z + ca * p["chord"]
    q = lambda v: int(round(v * 16384))
    if p["hand"] >= 0:
        M = [q(ca), 0, q(sa), 0, 16384, 0, q(-sa), 0, q(ca)]
        ox, oz = p["off"][0], p["off"][1]
    else:
        # A left-hand curve is the right-hand model driven BACKWARDS: rotate it
        # 180 degrees.  NEVER mirror it.  The renderer back-face culls, and a
        # mirror (determinant -1) flips every face's winding, so the piece
        # draws nothing at all - which is exactly what the two hand=-1 pieces
        # either side of the bridge did, for thirteen theories' worth of
        # looking elsewhere.  Stock has no negative-determinant placement.
        M = [q(-ca), 0, q(-sa), 0, 16384, 0, q(sa), 0, q(-ca)]
        ox, oz = p["off"][0], p["off"][1]
    # the model origin sits where the chord midpoint minus the rotated offset lands
    wx = cx - (M[0]*ox + M[2]*oz) / 16384.0
    wz = cz - (M[6]*ox + M[8]*oz) / 16384.0
    return ({"piece": p["name"], "hand": p["hand"],
             "x": round(wx), "z": round(wz),
             "heading": round(h + half, 2), "matrix": M,
             "entry": (round(x), round(z)), "exit": (round(nx), round(nz))},
            (nx, nz, h + p["turn"]))


def entry_poses(start, seq, close=None):
    """Entry pose of every piece.  With close=(x, z, heading) the residual
    between the chain's end and that target is spread evenly over the joints:
    every joint kinks by 1/N of the heading error and piece k sits at
    (k+0.5)/N of the position error.  Stock joins kink by 1-2
    degrees between neighbouring pieces, so a few hundredths per joint and a
    dozen units of gap are far inside what the game already lives with."""
    N = len(seq)
    def chain(dth):
        pose, poses = start, []
        for k, (name, hand) in enumerate(seq):
            pose = (pose[0], pose[1], pose[2] + dth/N)      # heading carries, so nudge per joint
            poses.append(pose)
            _pl, pose = place(pose, piece(name, hand))
        return poses, pose
    poses, end = chain(0.0)
    if close is None:
        return poses
    dth = ((close[2] - end[2] + 180) % 360) - 180
    poses, end = chain(dth)
    dx, dz = close[0] - end[0], close[1] - end[1]
    return [(x + dx*(k+0.5)/N, z + dz*(k+0.5)/N, h) for k, (x, z, h) in enumerate(poses)]


def run(start, seq, close=None):
    out = []
    for pose, (name, hand) in zip(entry_poses(start, seq, close), seq):
        pl, end = place(pose, piece(name, hand))
        out.append(pl)
    return out, end


def length(seq):
    return sum(ENDS[n]["chord"] for n, _h in seq)


if __name__ == "__main__":
    # every piece's exit must be its successor's entry, exactly
    seq = [("ROAD3", 0), ("D30R917", +1), ("C3060", -1), ("DOTLHALF", 0),
           ("C4572", +1), ("D10R1833", -1), ("ROAD1", 0)]
    pl, end = run((0, 0, 0), seq)
    print("joint check - each piece's exit vs the next piece's entry:")
    worst = 0
    for a, b in zip(pl, pl[1:]):
        d = math.dist(a["exit"], b["entry"])
        worst = max(worst, d)
        print("   %-9s exit (%7d,%8d) -> %-9s entry (%7d,%8d)   gap %.1f units"
              % (a["piece"], a["exit"][0], a["exit"][1],
                 b["piece"], b["entry"][0], b["entry"][1], d))
    print("worst joint gap: %.2f units (%.3f m)" % (worst, worst/U))
