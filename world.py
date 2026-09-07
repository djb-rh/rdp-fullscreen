"""Read the Race Drivin' static world out of the DSK ROM and export it as OBJ.

    python3 world.py list                     the 193 placements, named
    python3 world.py cells                    the two 4x4 spatial grids
    python3 world.py export world.obj         the whole world
    python3 world.py export cell.obj --cell 0x0F1A0
    python3 world.py export near.obj --around 264413,189079 --radius 20000
    python3 world.py move 38 --xyz 263000,1600,189000 --apply

Nothing here contains ROM data; everything is read from your own dumps.
"""
import struct, sys, os, bisect
import mesh

ROMDIR = os.environ.get("RD_ROMS", "/Users/djb/Developer/Race Drivin/racedriv")
DSK, MAIN, OBJ = "rd_dskrom.bin", "rd_maincpu.bin", "rd_objrom.bin"

PLACE_BASE = 0x011D0          # DSK ROM byte offset of the 193-record array
PLACE_N    = 193
PLACE_SZ   = 50
OBJTAB     = 0x435BE          # main CPU ROM, 28 bytes/record
GRIDS      = {"A": 0x037C2, "B": 0x0EFFC}

def _u(b, a): return struct.unpack_from(">H", b, a)[0]
def _s(b, a): return struct.unpack_from(">h", b, a)[0]
def _S(b, a): return struct.unpack_from(">i", b, a)[0]
def _U(b, a): return struct.unpack_from(">I", b, a)[0]

class World:
    def __init__(self):
        self.dsk  = bytearray(open(DSK, "rb").read())
        self.main = open(MAIN, "rb").read()
        self.obj  = open(OBJ, "rb").read()

    def name(self, i):
        p = _U(self.main, OBJTAB + i * 28 + 0x14)
        if not (0 < p < len(self.main)):
            return "obj%d" % i
        e = self.main.index(b"\0", p)
        return self.main[p:e].decode("ascii", "replace") or "obj%d" % i

    def catalogue(self, i):
        """18-byte record at the head of the object ROM."""
        r = i * 18
        return {"radius": _u(self.obj, r),
                "lod":    _U(self.obj, r + 2),
                "cull":   _U(self.obj, r + 6),
                "hi":     _U(self.obj, r + 10),
                "lo":     _U(self.obj, r + 14)}

    def placement(self, n):
        a = PLACE_BASE + n * PLACE_SZ
        d = self.dsk
        return {"n": n, "obj": _u(d, a), "name": self.name(_u(d, a)),
                "m": [_s(d, a + 2 + 2 * i) for i in range(9)],
                "x": _S(d, a + 0x14), "y": _S(d, a + 0x18), "z": _S(d, a + 0x1C)}

    def cell(self, hdr):
        d = self.dsk
        p = _U(d, hdr + 0x18) - 0x940000
        offs = []
        while _u(d, p) != 0xFFFF:
            offs.append(_s(d, p)); p += 2
        return {"hdr": hdr,
                "min": (_S(d, hdr), _S(d, hdr + 4), _S(d, hdr + 8)),
                "max": (_S(d, hdr + 0x0C), _S(d, hdr + 0x10), _S(d, hdr + 0x14)),
                "recs": [o // PLACE_SZ for o in offs]}

    def _hdr_ok(self, a):
        o = self.obj
        if not (0 < a < len(o) - 6):
            return False
        t, nv, nf = _u(o, a), _u(o, a + 2), _u(o, a + 4)
        return t == nv + nf and 3 <= nv <= 4000 and 1 <= nf <= 500 \
            and a + 6 + nv * 6 + nf * 6 < len(o)

    def _starts(self):
        if not hasattr(self, "_st"):
            raw = {p for i in range(390)
                   for p in (self.catalogue(i)["hi"], self.catalogue(i)["lo"])}
            self._st = sorted(a for a in raw if self._hdr_ok(a))
        return self._st

    def _end(self, a):
        """Byte address of the next model. Bounding the parse is required: the
        face count comes from the pair block, which otherwise runs on into the
        following object."""
        s = self._starts()
        i = bisect.bisect_right(s, a)
        e = s[i] if i < len(s) else len(self.obj)
        need = a + 2 * (3 + _u(self.obj, a + 2) * 3 + _u(self.obj, a + 4) * 3)
        if e <= need:
            e = len(self.obj) if i >= len(s) else need + 16
        return e

    def model(self, i, lod="hi"):
        p = self.catalogue(i)[lod]
        if not self._hdr_ok(p):
            return None
        try:
            return mesh.read(self.obj, p, end=self._end(p))
        except Exception:
            return None

def transform(v, m, t):
    """v' = M.v + T, with M row-major 1.14 fixed point."""
    x, y, z = v
    return (t[0] + (m[0]*x + m[1]*y + m[2]*z) / 16384.0,
            t[1] + (m[3]*x + m[4]*y + m[5]*z) / 16384.0,
            t[2] + (m[6]*x + m[7]*y + m[8]*z) / 16384.0)

def export(w, path, recs, scale=1.0/256.0, lod="hi", palette=None, bank=0):
    mtlname = os.path.basename(path).rsplit(".", 1)[0] + ".mtl"
    used, placed, missing = set(), 0, {}
    with open(path, "w") as f:
        f.write("# Race Drivin' static world, from the DSK and object ROMs\n")
        f.write("mtllib %s\n" % mtlname)
        n = 0
        for r in recs:
            p = w.placement(r)
            mo = w.model(p["obj"], lod)
            if mo is None or not mo["faces"]:
                missing[p["name"]] = missing.get(p["name"], 0) + 1
                continue
            f.write("o %03d_%s\n" % (r, p["name"]))
            t = (p["x"], p["y"], p["z"])
            for v in mo["verts"]:
                X, Y, Z = transform(v, p["m"], t)
                f.write("v %.4f %.4f %.4f\n" % (X * scale, Y * scale, -Z * scale))
            last = None
            for idx, colour in mo["faces"]:
                used.add(colour)
                if colour != last:
                    f.write("usemtl colour_%02X\n" % colour); last = colour
                f.write("f " + " ".join(str(n + v + 1) for v in idx) + "\n")
            n += len(mo["verts"]); placed += 1
    with open(os.path.join(os.path.dirname(path) or ".", mtlname), "w") as f:
        for c in sorted(used):
            if palette and (bank * 256 + c) * 3 + 2 < len(palette):
                o = (bank * 256 + c) * 3
                r_, g_, b_ = (palette[o] / 255, palette[o+1] / 255, palette[o+2] / 255)
            else:
                r_, g_, b_ = ((c*37) % 256)/255, ((c*91) % 256)/255, ((c*143) % 256)/255
            f.write("newmtl colour_%02X\nKd %.4f %.4f %.4f\n\n" % (c, r_, g_, b_))
    return placed, n, missing

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    w = World(); cmd = sys.argv[1]
    if cmd == "list":
        for n in range(PLACE_N):
            p = w.placement(n)
            print("%3d %-10s obj%-4d X=%8d Y=%7d Z=%8d" %
                  (n, p["name"], p["obj"], p["x"], p["y"], p["z"]))
    elif cmd == "cells":
        for g, h0 in GRIDS.items():
            print("grid %s @ DSK 0x%05X (68k 0x%06X)" % (g, h0, 0x940000 + h0))
            for i in range(16):
                c = w.cell(h0 + i * 0x1C)
                print("   cell %2d  X[%11d..%11d] Z[%11d..%11d]  %3d objects"
                      % (i, c["min"][0], c["max"][0], c["min"][2], c["max"][2], len(c["recs"])))
    elif cmd == "export":
        path = sys.argv[2]
        recs = list(range(PLACE_N))
        if "--cell" in sys.argv:
            recs = w.cell(int(sys.argv[sys.argv.index("--cell") + 1], 0))["recs"]
        if "--around" in sys.argv:
            cx, cz = (int(v) for v in sys.argv[sys.argv.index("--around") + 1].split(","))
            rad = int(sys.argv[sys.argv.index("--radius") + 1]) if "--radius" in sys.argv else 20000
            recs = [r for r in recs
                    if (w.placement(r)["x"]-cx)**2 + (w.placement(r)["z"]-cz)**2 < rad*rad]
        pal = None
        if "--palette" in sys.argv:
            pal = open(sys.argv[sys.argv.index("--palette") + 1], "rb").read()
        lod = "lo" if "--lo" in sys.argv else "hi"
        placed, nv, missing = export(w, path, recs, lod=lod, palette=pal)
        print("wrote %s: %d/%d placements, %d vertices" % (path, placed, len(recs), nv))
        if missing:
            print("unresolved: " + ", ".join("%s x%d" % kv for kv in
                  sorted(missing.items(), key=lambda kv: -kv[1])))
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
