"""Build a patched Race Drivin' object ROM with VIR's geometry in place of
Super Stunt's scenery.

Reads your own ROMs; writes new EPROM images with Atari's byte-sum convention
preserved. Contains no ROM data.
"""
import json, os, struct, sys
import world, mesh, vir_build as B

ROMDIR = os.environ.get("RD_ROMS", "/Users/djb/Developer/Race Drivin/racedriv")
OBJ = [("136077-2021.10h", 0x21, 0, 0x00000), ("136077-2023.10k", 0x23, 1, 0x00000),
       ("136077-1022.10j", 0x22, 0, 0x20000), ("136077-1024.10l", 0x24, 1, 0x20000)]
VEH = ("CAR", "VAN", "TRUK", "FER", "POR", "VET", "JAG", "PIC", "YEL",
       "RRCAR", "TRAIN", "WL", "WWL")


def _path(n):
    for c in (n, n + ".bin"):
        p = os.path.join(ROMDIR, c)
        if os.path.exists(p):
            return p
    raise SystemExit("missing " + n)


def vir_models():
    d, C, segs = B.build()
    out = [{"name": "VIRROAD%02d" % i, "verts": s["verts"],
            "faces": [(list(f), 8) for f in s["faces"]]} for i, s in enumerate(segs)]
    out += [{"name": m["name"], "verts": m["verts"],
             "faces": [(list(f), 8) for f in m["faces"]], "origin": m["origin"],
             "matrix": m["matrix"]} for m in B.extras(d, C) + B.structures(d, C)]
    for i, s in enumerate(segs):
        out[i]["origin"] = s["origin"]
        out[i]["matrix"] = [16384,0,0, 0,16384,0, 0,0,16384]
    for m in out:
        m["normals"] = [(0, 16384, 0)]          # one shared normal, as the ROM does
        # geometry comes out of the transform as floats; the format is s16
        m["verts"] = [(int(round(x)), int(round(y)), int(round(z)))
                      for x, y, z in m["verts"]]
        bad = [v for v in m["verts"] if max(abs(c) for c in v) > 32767]
        if bad:
            raise SystemExit("%s has %d vertices outside s16" % (m["name"], len(bad)))
    return out


def free_spans(w):
    """Object-ROM space reachable only from Super Stunt-exclusive scenery."""
    d = open("rd_dskrom.bin", "rb").read()
    u  = lambda a: struct.unpack_from(">H", d, a)[0]
    s16 = lambda a: struct.unpack_from(">h", d, a)[0]
    S  = lambda a: struct.unpack_from(">i", d, a)[0]
    def lst(p):
        t = p - 0x940000; r = []
        while u(t) != 0xFFFF:
            r.append(s16(t)); t += 2
        return r
    TR = {0: (0x037C2, 0x011D0), 1: (0x0BFF2, 0x0B58A), 2: (0x0EFFC, 0x0CCF8)}
    used = {}
    for t, (g, b) in TR.items():
        cells = [g + i*0x1C for i in range(16) if 0x940000 <= S(g + i*0x1C + 0x18) < 0x960000]
        used[t] = {u(b + x) for h in cells for x in lst(S(h + 0x18))}
    veh = lambda n: any(v in n for v in VEH)
    def mo(ii):
        out = set()
        for i in ii:
            c = w.catalogue(i)
            for k in ("hi", "lo"):
                if w._hdr_ok(c[k]):
                    out.add(c[k])
        return out
    onlyB = used[2] - used[0] - used[1]
    keep = mo(used[0] | used[1] | {i for i in onlyB if veh(w.name(i))})
    freeable = sorted(mo(onlyB) - keep)
    sz = lambda a: len(mesh.encode(mesh.read(w.obj, a), a))
    spans = []
    for a in freeable:
        n = sz(a)
        if spans and spans[-1][0] + spans[-1][1] == a:
            spans[-1][1] += n
        else:
            spans.append([a, n])
    return spans, used, mo, veh


def allocate(models, spans):
    """Best-fit decreasing, honouring the 0x20000 pointer boundary."""
    free = [list(x) for x in spans]
    order = sorted(range(len(models)),
                   key=lambda i: -len(mesh.encode(models[i], 0x1000)))
    placed, dropped = {}, []
    for i in order:
        size = len(mesh.encode(models[i], 0x1000))
        best = None
        for f in free:
            if f[1] >= size and (f[0] & 0xFFFE0000) == ((f[0] + size - 1) & 0xFFFE0000):
                if best is None or f[1] < best[1]:
                    best = f
        if best is None:
            dropped.append(models[i]["name"]); continue
        placed[i] = best[0]; best[0] += size; best[1] -= size
    return placed, dropped, free


def main():
    w = world.World()
    models = vir_models()
    spans, used, mo, veh = free_spans(w)
    placed, dropped, free = allocate(models, spans)
    print("VIR models: %d, placed %d, dropped %d (%s)"
          % (len(models), len(placed), len(dropped), ", ".join(dropped) or "none"))

    obj = bytearray(w.obj)
    for i, base in placed.items():
        blob = mesh.encode(models[i], base)
        obj[base:base + len(blob)] = blob

    # read every one back out of the patched image
    ok = 0
    for i, base in placed.items():
        m2 = mesh.read(bytes(obj), base)
        if (len(m2["verts"]) == len(models[i]["verts"]) and
                len(m2["faces"]) == len(models[i]["faces"])):
            ok += 1
    print("re-read from the patched image: %d/%d models decode correctly" % (ok, len(placed)))

    # ---- catalogue entries -------------------------------------------------
    # 18 bytes each at the head of the object ROM:
    #   u16 bounding radius | u32 LOD distance | u32 cull distance
    #   u32 hi-detail model | u32 lo-detail model
    free_idx = [i for i in range(390)
                if i not in (used[0] | used[1] | used[2]) and not veh(w.name(i))]
    if len(free_idx) < len(placed):
        raise SystemExit("not enough free catalogue slots")
    assign = {}
    for slot, i in zip(free_idx, sorted(placed)):
        base = placed[i]
        vs = models[i]["verts"]
        radius = int(max(max(abs(c) for c in v) for v in vs)) if vs else 100
        rec = struct.pack(">HIIII", min(radius, 0xFFFF), 38400, 288000, base, base)
        obj[slot*18: slot*18 + 18] = rec
        assign[models[i]["name"]] = {"index": slot, "addr": base, "radius": radius}
    print("catalogue: wrote %d entries into free slots %d..%d"
          % (len(assign), min(a["index"] for a in assign.values()),
             max(a["index"] for a in assign.values())))
    # verify by reading them back through the normal path
    w2 = world.World(); w2.obj = bytes(obj)
    if hasattr(w2, "_st"): del w2._st
    good = sum(1 for a in assign.values()
               if w2._hdr_ok(w2.catalogue(a["index"])["hi"]))
    print("catalogue entries whose hi model has a valid header: %d/%d"
          % (good, len(assign)))

    os.makedirs("patched", exist_ok=True)
    for name, suffix, phase, base in OBJ:
        half = bytearray(obj[base + phase: base + 0x20000: 2])
        pad = len(half) - 1
        while pad > 0 and half[pad] == 0:
            pad -= 1
        pad += 1
        if pad >= len(half):
            print("  %s: no padding for a checksum byte - left unbalanced" % name)
        else:
            half[pad] = 0
            half[pad] = (suffix - (sum(half) & 0xFF)) & 0xFF
        open(os.path.join("patched", name), "wb").write(bytes(half))
        print("  %-18s sum 0x%04X low 0x%02X (want 0x%02X) %s"
              % (name, sum(half) & 0xFFFF, sum(half) & 0xFF, suffix,
                 "OK" if (sum(half) & 0xFF) == suffix else "MISMATCH"))
    json.dump(assign, open("vir_layout.json", "w"), indent=1)
    print("wrote patched/ and vir_layout.json")


if __name__ == "__main__":
    main()
