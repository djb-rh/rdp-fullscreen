#!/usr/bin/env python3
"""Apply the east-loop patch to your own Race Drivin' ROM set.

    python3 apply_patch.py /path/to/racedriv.zip [-o OUTDIR] [--warp]

Reads the stock MAME set (racedriv.zip, or a directory holding the same
files), verifies the two DSK ROMs are the stock ones, rebuilds them with the
loop spliced in, and writes a complete loose set to OUTDIR/racedriv that MAME
can run with -rompath OUTDIR.  Nothing from the ROMs is stored in this
repository: the helper images (rd_*.bin) are regenerated from your set on
every run, and the patch itself is code plus the JSON layout files.

--warp starts the car just past the overpass, facing the new section, instead
of on the start line (for testing the loop without driving the whole lap).
"""
import argparse, hashlib, os, shutil, struct, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# MAME's load order for the regions the tools need (even byte, odd byte)
MAIN = [("136077-5002.200r", "136077-5001.210r"), ("136077-5004.200s", "136077-5003.210s"),
        ("136077-5006.200t", "136077-5005.210t"), ("136077-4008.200u", "136077-4007.210u"),
        ("136077-4010.200v", "136077-4009.210v"), ("136077-1012.200w", "136077-1011.210w"),
        ("136077-1014.200x", "136077-1013.210x"), ("136077-1016.200y", "136077-4015.210y")]
OBJ = [("136077-2021.10h", "136077-2023.10k"), ("136077-1022.10j", "136077-1024.10l")]
DSK = [("136077-4030.30e", "136077-4031.10e")]
STOCK_SHA1 = {"136077-4030.30e": "5ec410bd75c281ac57d9856d08ce65431f3af994",
              "136077-4031.10e": "937e27c012c5fb457bee1b43fc8e075b3e9405b4"}
WARP_START = 232          # segment just past the OVERP hump, facing the loop
T0 = 0x049CA              # track 0's segment array; header word +8 = start segment


class RomSet:
    def __init__(self, path):
        self.path = path
        if os.path.isdir(path):
            self.names = set(os.listdir(path))
            self.read = lambda n: open(os.path.join(path, n), "rb").read()
        else:
            self.zip = zipfile.ZipFile(path)
            self.names = set(self.zip.namelist())
            self.read = self.zip.read

    def interleave(self, pairs):
        out = bytearray()
        for even, odd in pairs:
            a, b = self.read(even), self.read(odd)
            buf = bytearray(len(a) * 2)
            buf[0::2], buf[1::2] = a, b
            out += buf
        return bytes(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("romset", help="stock racedriv.zip (or a directory with its contents)")
    ap.add_argument("-o", "--out", default="racedriv_loop", help="output directory (default racedriv_loop/)")
    ap.add_argument("--warp", action="store_true", help="start the car just before the new section")
    args = ap.parse_args(argv)

    rs = RomSet(args.romset)
    need = [n for pairs in (MAIN, OBJ, DSK) for p in pairs for n in p]
    missing = [n for n in need if n not in rs.names]
    if missing:
        sys.exit("not a complete racedriv set, missing: " + ", ".join(missing))
    for n, want in STOCK_SHA1.items():
        got = hashlib.sha1(rs.read(n)).hexdigest()
        if got != want:
            sys.exit("%s is not the stock ROM (sha1 %s, want %s) - is this set already patched?" % (n, got, want))

    # the tools read their data files and the helper images from the repo dir,
    # and the two DSK halves from $RD_ROMS
    os.chdir(HERE)
    for fn, pairs in (("rd_dskrom.bin", DSK), ("rd_maincpu.bin", MAIN), ("rd_objrom.bin", OBJ)):
        open(fn, "wb").write(rs.interleave(pairs))
    work = tempfile.mkdtemp(prefix="rdloop-")
    for n in STOCK_SHA1:
        open(os.path.join(work, n), "wb").write(rs.read(n))
    os.environ["RD_ROMS"] = work

    import patch_track, patch_segments, patch_awards, patch_route, world, worldpatch
    for mod in (patch_track, world, worldpatch):
        mod.ROMDIR = work            # they read $RD_ROMS at import; make repeat calls work too

    print("1. placements (delete 17, add the east loop)")
    patch_track.main()                       # writes patched_track/
    buf = patch_route.load("patched_track")
    print("\n2. road segments (splice the loop in place of the deleted run)")
    buf = patch_segments.apply(buf)
    print("\n3. gate award table")
    patch_awards.patch(buf)
    print("\n4. route section for the loop")
    buf = patch_route.apply(buf)
    if args.warp:
        print("\n5. warp: start segment %d -> %d" % (struct.unpack_from(">H", buf, T0 + 8)[0], WARP_START))
        struct.pack_into(">H", buf, T0 + 8, WARP_START)

    print("\nwriting patched_final/")
    patch_segments.write(buf, "patched_final")

    out = os.path.join(os.path.abspath(os.path.join(os.getcwd() if os.path.isabs(args.out) else HERE, args.out)), "racedriv")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for n in rs.names:
        if not n.endswith("/"):
            open(os.path.join(out, n), "wb").write(rs.read(n))
    for n in STOCK_SHA1:
        shutil.copy(os.path.join("patched_final", n), out)
    shutil.rmtree(work, ignore_errors=True)
    print("\nstaged %s (%d files)%s" % (out, len(os.listdir(out)), " [warp start]" if args.warp else ""))
    print("run:  mame racedriv -rompath %s" % os.path.dirname(out))


if __name__ == "__main__":
    main()
