"""Render the edited speed track: kept placements + the new stock-piece loop."""
import json, math, world, layout
from PIL import Image, ImageDraw

w = world.World()
U = layout.U
dele = set(json.load(open("delete_list.json")))
S = json.load(open("loop_final.json"))
seq = [(n, h) for n, h in S["seq"]]
pl, _end = layout.run(tuple(S["start"]), seq, S.get("close"))
ci, cj, cpt = S["cross"]

IDX = {w.name(i): i for i in range(390)}

def new_objects():
    """Each placed piece, as (name, transformed verts, faces)."""
    out = []
    for k, ((nm, hand), p) in enumerate(zip(seq, pl)):
        i = IDX[nm]; mo = w.model(i)
        if not mo:
            continue
        M = p["matrix"]
        t = (p["x"], 0, p["z"])
        V = [world.transform(v, M, t) for v in mo["verts"]]
        out.append(("NEW%02d_%s" % (k, nm), V, [f for f, _c in mo["faces"]], k))
    return out

def plan(path="plan_loop.png"):
    W = H = 1400; PAD = 30
    MNX, MXX, MNZ, MXZ = 73748, 344272, 96006, 330000
    SC = min((W-2*PAD)/(MXX-MNX), (H-2*PAD)/(MXZ-MNZ))
    T = lambda x, z: (PAD+(x-MNX)*SC, H-PAD-(z-MNZ)*SC)
    im = Image.new("RGB", (W, H), (12, 14, 18)); d = ImageDraw.Draw(im)
    for r in range(193):
        p = w.placement(r); mo = w.model(p["obj"])
        if not mo or not mo["faces"]:
            continue
        t = (p["x"], p["y"], p["z"])
        V = [world.transform(v, p["m"], t) for v in mo["verts"]]
        col = (110, 34, 34) if r in dele else (60, 62, 70)
        for idx, _c in mo["faces"]:
            d.polygon([T(V[i][0], V[i][2]) for i in idx], fill=col)
    under = S["under"]
    for nm, V, F, k in new_objects():
        col = (70, 200, 110)
        if k == under: col = (90, 170, 255)          # the UNDERP itself
        elif k in (ci, cj): col = (255, 170, 60)     # the leg passing over it
        for f in F:
            d.polygon([T(V[i][0], V[i][2]) for i in f], fill=col)
    x, y = T(*cpt); d.ellipse([x-16, y-16, x+16, y+16], outline=(255, 255, 255), width=3)
    d.text((16, 14), "EDITED SPEED TRACK - new loop from stock road pieces", fill=(240, 240, 240))
    d.text((16, 34), "dark red = 17 deleted    green = %d new stock pieces" % len(seq),
           fill=(200, 200, 200))
    d.text((16, 52), "blue = UNDERP (dips 5.5 m)    orange = the leg crossing over it",
           fill=(150, 190, 255))
    im.save(path)
    return path

def obj(path="newloop_world.obj"):
    objs = []
    for r in range(193):
        if r in dele: continue
        p = w.placement(r); mo = w.model(p["obj"])
        if not mo or not mo["faces"]: continue
        t = (p["x"], p["y"], p["z"])
        objs.append(("%03d_%s" % (r, p["name"]),
                     [world.transform(v, p["m"], t) for v in mo["verts"]],
                     [f for f, _c in mo["faces"]], "existing"))
    for nm, V, F, k in new_objects():
        mat = "under" if k == S["under"] else ("over" if k in (ci, cj) else "newroad")
        objs.append((nm, V, F, mat))
    MAT = {"existing": (0.26,0.27,0.30), "newroad": (0.22,0.50,0.28),
           "over": (0.35,0.55,0.85), "under": (0.85,0.60,0.22)}
    sc = 1.0/256.0
    with open(path, "w") as f:
        f.write("mtllib %s\n" % path.replace(".obj", ".mtl"))
        base = 0
        for nm, V, F, mat in objs:
            f.write("o %s\n" % nm)
            for x, y, z in V:
                f.write("v %.4f %.4f %.4f\n" % (x*sc, y*sc, -z*sc))
            f.write("usemtl %s\n" % mat)
            for fc in F:
                f.write("f " + " ".join(str(base+i+1) for i in fc) + "\n")
            base += len(V)
    with open(path.replace(".obj", ".mtl"), "w") as f:
        for k, (r, g, b) in MAT.items():
            f.write("newmtl %s\nKd %.3f %.3f %.3f\n\n" % (k, r, g, b))
    return len(objs)

if __name__ == "__main__":
    print("plan ->", plan())
    print("obj  -> newloop_world.obj (%d objects)" % obj())
