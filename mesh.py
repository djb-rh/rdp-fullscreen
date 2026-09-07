"""Read and write Hard Drivin' / Race Drivin' object-ROM models.

Layout, with every word accounted for (verified against the whole catalogue):

    u16  total = nverts + nnormals
    u16  nverts
    u16  nnormals
         vertices   3 x s16 per vertex, x y z
         normals    3 x s16 per normal, 1.14 fixed point (16384 = 1.0)
    u16  pointer to the pair block
         pairs      two words per face:
                      u16 pointer to that face's index list
                      u16 attribute: low byte is the colour index, high byte
                         is a draw mode - 0xF0 for flat shaded, 0x10 on the
                         billboard-like objects (TREEBLIT, BROCK). Kept
                         verbatim so a round trip is exact.
    u16  0x0000, u16 0x0000        terminates the pair block
         index lists  per face: face id, 1-based vertex indices, 0xFFFF

Both pointers are the **low 16 bits of the absolute word address**, so they
resolve against the model's own high bits and depend on where the model is
placed. Face ids live in a combined space: 1..nverts are vertices, nverts+1..
are faces, which is what the header's `total` counts.

The third header word is the number of **normals**, not faces - a flat road
piece such as D30R917 declares one normal and carries 34 coplanar polygons.
The face count comes only from the zero terminator.
"""
import struct


def _s(rom, base, i): return struct.unpack_from(">h", rom, base + 2 * i)[0]
def _u(rom, base, i): return struct.unpack_from(">H", rom, base + 2 * i)[0]


def read(rom, base, limit=40000, end=None):
    """Decode one model. `end` is accepted for compatibility but no longer
    needed - the zero terminator bounds the pair block exactly."""
    total, nverts, nnorm = (_u(rom, base, i) for i in range(3))
    if total != nverts + nnorm or not (3 <= nverts <= 4000) or not (1 <= nnorm <= 500):
        raise ValueError("bad header at 0x%05X: %d %d %d" % (base, total, nverts, nnorm))

    verts = [(_s(rom, base, 3 + i*3), _s(rom, base, 4 + i*3), _s(rom, base, 5 + i*3))
             for i in range(nverts)]
    n0 = 3 + nverts * 3
    normals = [(_s(rom, base, n0 + i*3), _s(rom, base, n0 + 1 + i*3),
                _s(rom, base, n0 + 2 + i*3)) for i in range(nnorm)]

    hi = (base // 2) & 0xFFFF0000
    pblock = _u(rom, base, n0 + nnorm * 3)          # -> the pair block
    j = (hi | pblock) - base // 2
    if j != n0 + nnorm * 3 + 1:
        raise ValueError("pair-block pointer at 0x%05X does not self-locate" % base)

    faces = []
    while True:
        ptr, attr = _u(rom, base, j), _u(rom, base, j + 1)
        if ptr == 0:
            break                                    # zero pair terminates
        off = (hi | ptr) - base // 2
        fid = _u(rom, base, off)
        idx, k = [], off + 1
        while True:
            v = _u(rom, base, k); k += 1
            if v == 0xFFFF:
                break
            idx.append(v - 1)
        faces.append({"id": fid, "idx": idx, "attr": attr, "colour": attr & 0xFF})
        j += 2

    return {"base": base, "verts": verts, "normals": normals,
            "faces": [(f["idx"], f["colour"]) for f in faces],
            "records": faces, "nfaces_declared": nnorm}


def encode(model, base):
    """Assemble a model for placement at byte address `base`.

    Returns bytes. Both pointer kinds are absolute word addresses truncated to
    16 bits, so `base` must be the address the model will actually live at.
    """
    verts, normals = model["verts"], model["normals"]
    recs = model.get("records")
    if recs is None:
        recs = [{"id": len(verts) + 1 + i, "idx": idx, "colour": c,
                 "attr": 0xF000 | (c & 0xFF)}
                for i, (idx, c) in enumerate(model["faces"])]
    V, N, F = len(verts), len(normals), len(recs)
    if base & 1:
        raise ValueError("model base must be word aligned")
    bw = base // 2

    n0 = 3 + V * 3
    pblock = n0 + N * 3 + 1                    # first word of the pair block
    lists = pblock + F * 2 + 2                 # first index list, past the zeros

    offs, at = [], lists
    for r in recs:
        offs.append(at)
        at += 1 + len(r["idx"]) + 1            # id + indices + 0xFFFF

    w = [V + N, V, N]
    for v in verts:
        w += [x & 0xFFFF for x in v]
    for n in normals:
        w += [x & 0xFFFF for x in n]
    w.append((bw + pblock) & 0xFFFF)
    for r, off in zip(recs, offs):
        w += [(bw + off) & 0xFFFF,
              r.get("attr", 0xF000 | (r["colour"] & 0xFF))]
    w += [0x0000, 0x0000]
    for r in recs:
        w.append(r["id"])
        w += [i + 1 for i in r["idx"]]
        w.append(0xFFFF)
    # Pointers carry only the low 16 bits of a word address, so a model that
    # straddles a 0x10000-word (128 KB) boundary would resolve its own index
    # lists into the wrong half.
    if (bw & 0xFFFF0000) != ((bw + len(w) - 1) & 0xFFFF0000):
        raise ValueError(
            "model at 0x%05X (%d words) straddles a 128 KB boundary; "
            "its pointers cannot resolve" % (base, len(w)))
    return struct.pack(">%dH" % len(w), *w)


def write_obj(path, model, name="model", scale=1.0 / 256.0):
    mtl = path.rsplit(".", 1)[0] + ".mtl"
    with open(path, "w") as f:
        f.write("# extracted from a Hard Drivin' family object ROM\n")
        f.write("mtllib %s\no %s\n" % (mtl.split("/")[-1], name))
        for x, y, z in model["verts"]:
            f.write("v %.4f %.4f %.4f\n" % (x * scale, y * scale, -z * scale))
        last = None
        for idx, colour in model["faces"]:
            if colour != last:
                f.write("usemtl colour_%02X\n" % colour); last = colour
            f.write("f " + " ".join(str(v + 1) for v in idx) + "\n")


def write_mtl(path, model, palette=None, bank=0):
    colours = sorted({c for _i, c in model["faces"]})
    with open(path, "w") as f:
        for c in colours:
            if palette and (bank * 256 + c) * 3 + 2 < len(palette):
                o = (bank * 256 + c) * 3
                r, g, b = (palette[o] / 255, palette[o+1] / 255, palette[o+2] / 255)
            else:
                r, g, b = ((c*37) % 256)/255, ((c*91) % 256)/255, ((c*143) % 256)/255
            f.write("newmtl colour_%02X\nKd %.4f %.4f %.4f\n\n" % (c, r, g, b))
