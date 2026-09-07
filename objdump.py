#!/usr/bin/env python3
"""objdump.py - list and export the 3D models from a Hard Drivin' family object ROM.

The object ROM (MAME region `user1`) holds a table of models at offset 0. Each
table record is 18 bytes: an id, two extent fields, and **two pointers** - a
detailed model and a low-polygon version of the same object, near/far level of
detail. Both are the same dimensions.

    python3 objdump.py rd_objrom.bin list
    python3 objdump.py rd_objrom.bin extract 0x30000 car.obj
    python3 objdump.py rd_objrom.bin extractall out/

Build the object ROM image by interleaving the four EPROMs big-endian:
136077-2021/2023 at 0x00000, 136077-1022/1024 at 0x20000.

OBJ files open in macOS Quick Look - select in Finder and press space.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mesh import read, write_obj


def table(rom, count=26):
    out = []
    for i in range(count):
        off = i * 18
        ident = struct.unpack_from(">H", rom, off)[0]
        e1, e2 = struct.unpack_from(">II", rom, off + 2)
        hi, lo = struct.unpack_from(">II", rom, off + 10)
        out.append((i, ident, e1, e2, hi, lo))
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    rom = open(sys.argv[1], "rb").read()
    cmd = sys.argv[2]

    if cmd == "list":
        seen = {}
        for i, ident, e1, e2, hi, lo in table(rom):
            print("  [%2d] id %5d  extent %7d x %7d   near 0x%05X   far 0x%05X%s"
                  % (i, ident, e1, e2, hi, lo, "   (same)" if hi == lo else ""))
            for p in (hi, lo):
                seen[p] = True
        print("\n  %d distinct models" % len(seen))
        for p in sorted(seen):
            try:
                m = read(rom, p)
                v = m["verts"]
                xs = [q[0] for q in v]; ys = [q[1] for q in v]; zs = [q[2] for q in v]
                print("    0x%05X  %4d verts  %3d/%3d faces   size %5d x %5d x %5d"
                      % (p, len(v), len(m["faces"]), m["nfaces_declared"],
                         max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
            except ValueError as e:
                print("    0x%05X  %s" % (p, e))
        return 0

    if cmd == "extract":
        p = int(sys.argv[3], 0)
        write_obj(sys.argv[4], read(rom, p), "obj_%05X" % p)
        print("wrote %s" % sys.argv[4])
        return 0

    if cmd == "extractall":
        out = sys.argv[3]
        os.makedirs(out, exist_ok=True)
        seen = set()
        for _i, _id, _e1, _e2, hi, lo in table(rom):
            seen.update((hi, lo))
        n = 0
        for p in sorted(seen):
            try:
                m = read(rom, p)
            except ValueError:
                continue
            path = os.path.join(out, "obj_%05X.obj" % p)
            write_obj(path, m, "obj_%05X" % p)
            n += 1
        print("wrote %d models to %s/" % (n, out))
        return 0

    print("unknown command %s" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
