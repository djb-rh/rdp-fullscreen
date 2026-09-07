#!/usr/bin/env python3
"""swapart.py - list, extract and replace Race Drivin' Panorama side-pod artwork.

The pod keeps 70 compressed bitmaps behind a pointer table at ROM 0x060000.
Among them are the two door cards - the panel across the bottom 96 rows of the
screen - one drawn for a left-hand pod and one for a right-hand pod. They are
separate images, not one mirrored at runtime.

    python3 swapart.py <romdir> list
    python3 swapart.py <romdir> blank doors --apply
    python3 swapart.py <romdir> extract 0 door.png --palette palette.bin
    python3 swapart.py <romdir> replace 0 mypic.png --palette palette.bin --apply

Nothing here contains ROM data: the images are read out of your own ROMs, and
the palette comes from dumppal.lua run against your own ROMs.

Replacement needs ImageMagick (`convert`) to read PNG/GIF/JPEG. The new image
is scaled to the asset's exact size, matched to the pod's palette, re-encoded,
and written back. If it no longer fits where it was, it is relocated into unused
ROM and the pointer updated. Each affected EPROM's 16-bit byte-sum is preserved,
so the pod's self-test still passes.
"""
import os, struct, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codec import unpack, pack
from topng import write_png

TABLE   = 0x060000
COUNT   = 70
SPARE   = (0x051000, 0x05F000)     # unused ROM used when an image no longer fits
ROMSIZE = 0x100000

# the 68010 set: eight pairs of 64K EPROMs, even bytes / odd bytes
def pair_for(offset):
    b = offset >> 17
    return "088-20%02d.bin" % (2 * b + 2), "088-20%02d.bin" % (2 * b + 1), b << 17


def load(romdir):
    lin = bytearray(ROMSIZE)
    files = {}
    for b in range(8):
        even, odd, base = pair_for(b << 17)
        for name in (even, odd):
            p = os.path.join(romdir, name)
            if not os.path.exists(p):
                sys.exit("missing %s" % p)
            files[name] = bytearray(open(p, "rb").read())
        lin[base + 0:base + 0x20000:2] = files[even]
        lin[base + 1:base + 0x20000:2] = files[odd]
    return lin, files


def store(lin, files, romdir, before):
    for b in range(8):
        even, odd, base = pair_for(b << 17)
        files[even][:] = lin[base + 0:base + 0x20000:2]
        files[odd][:]  = lin[base + 1:base + 0x20000:2]
    changed = 0
    for name, data in sorted(files.items()):
        after = sum(data) & 0xFFFF
        if after != before[name]:
            sys.exit("%s checksum %04X != %04X - compensation failed" % (name, after, before[name]))
        path = os.path.join(romdir, name)
        if bytes(data) == open(path, "rb").read():
            continue
        open(path, "wb").write(bytes(data))
        changed += 1
        print("  wrote %s (checksum %04X preserved)" % (name, after))
    if not changed:
        print("  nothing changed")


def assets(lin):
    out = []
    for i in range(COUNT):
        p = struct.unpack_from(">I", lin, TABLE + i * 4)[0]
        try:
            px, end = unpack(lin, p, limit=200000)
        except Exception:
            px, end = b"", p
        out.append((i, p, end, px))
    return out


def read_image(path, w, h):
    ppm = subprocess.run(["convert", path, "-resize", "%dx%d!" % (w, h),
                          "-depth", "8", "ppm:-"], capture_output=True).stdout
    if not ppm.startswith(b"P6"):
        sys.exit("could not read %s (is ImageMagick installed?)" % path)
    parts = ppm.split(b"\n", 3)
    return parts[3]


def quantise(rgb, palette, bank, allowed):
    table = [(palette[(bank * 256 + i) * 3], palette[(bank * 256 + i) * 3 + 1],
              palette[(bank * 256 + i) * 3 + 2], i) for i in allowed]
    cache, out = {}, bytearray()
    for k in range(0, len(rgb), 3):
        key = rgb[k:k + 3]
        v = cache.get(key)
        if v is None:
            r, g, b = key[0], key[1], key[2]
            v = min(table, key=lambda t: (t[0] - r) ** 2 + (t[1] - g) ** 2 + (t[2] - b) ** 2)[3]
            cache[key] = v
        out.append(v)
    return bytes(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    romdir, cmd = sys.argv[1], sys.argv[2]
    lin, files = load(romdir)
    before = {n: sum(d) & 0xFFFF for n, d in files.items()}
    pal = None
    if "--palette" in sys.argv:
        pal = open(sys.argv[sys.argv.index("--palette") + 1], "rb").read()
    bank = int(sys.argv[sys.argv.index("--bank") + 1]) if "--bank" in sys.argv else 1

    if cmd == "blank":
        # Paint the door cards as flat black instead of a door. For a pod being
        # used to show something other than a side view, the door is in the way;
        # a solid fill compresses to almost nothing, so it always fits in place
        # and only the EPROM pair holding that stream changes.
        which = sys.argv[3] if len(sys.argv) > 3 else "doors"
        colour = int(sys.argv[sys.argv.index("--colour") + 1], 0) if "--colour" in sys.argv else 0
        targets = [0, 19] if which == "doors" else [int(which)]
        spans = {}
        for t in targets:
            i, p, end, px = assets(lin)[t]
            rows = len(px) // 512
            spans[t] = [p, end, 0]
            blob = pack(bytes([colour]) * (512 * rows), [colour] * 16)
            span = end - p
            if len(blob) > span:
                sys.exit("asset %d: blank stream (%d) does not fit %d" % (t, len(blob), span))
            lin[p:p + len(blob)] = blob
            spans[t][2] = len(blob)
            for k in range(p + len(blob), end):
                lin[k] = 0
            print("  asset %2d (0x%06X, 512x%d) -> flat colour %d, %d of %d bytes used"
                  % (t, p, rows, colour, len(blob), span))
        for b in range(8):
            even, odd, base = pair_for(b << 17)
            for name, parity in ((even, 0), (odd, 1)):
                data = lin[base + parity:base + 0x20000:2]
                delta = (before[name] - (sum(data) & 0xFFFF)) & 0xFFFF
                if not delta:
                    continue
                slots = []
                for t in targets:
                    p2, end2, used = spans[t]      # only the tail is free
                    slots += [k for k in range(p2 + used, end2)
                              if (k >> 17) == b and (k & 1) == parity and lin[k] == 0]
                if (delta + 254) // 255 > len(slots):
                    sys.exit("%s: not enough spare bytes to restore the checksum" % name)
                for k in slots:
                    if not delta:
                        break
                    step = min(delta, 255)
                    lin[k] = step
                    delta -= step
        if "--apply" not in sys.argv:
            print("check only - pass --apply to write the images")
            return 0
        store(lin, files, romdir, before)
        return 0

    if cmd == "list":
        for i, p, end, px in assets(lin):
            rows = len(px) // 512
            print("  [%2d] 0x%06X  %5d bytes -> 512x%-3d  %2d colours%s"
                  % (i, p, end - p, rows, len(set(px)),
                     "   <- door card" if rows == 96 else ""))
        return 0

    idx = int(sys.argv[3])
    i, p, end, px = assets(lin)[idx]
    rows = len(px) // 512
    if not px:
        sys.exit("asset %d did not decode" % idx)

    if cmd == "extract":
        write_png(sys.argv[4], px, 512, rows, palette=pal, bank=bank)
        print("asset %d (0x%06X, 512x%d) -> %s" % (idx, p, rows, sys.argv[4]))
        return 0

    if cmd != "replace":
        sys.exit("unknown command %s" % cmd)
    if pal is None:
        sys.exit("replace needs --palette (run dumppal.lua against your own ROMs)")

    allowed = sorted(set(px)) if "--full-palette" not in sys.argv else list(range(256))
    rgb = read_image(sys.argv[4], 512, rows)
    pixels = quantise(rgb, pal, bank, allowed)
    from collections import Counter
    pal16 = [c for c, _ in Counter(pixels).most_common(16)]
    blob = pack(pixels, pal16)
    check, _ = unpack(blob, 0, limit=200000)
    if check != pixels:
        sys.exit("internal error: encoded stream does not decode back")

    span = end - p
    print("asset %d: 512x%d, %d colours used, encoded %d bytes (space here: %d)"
          % (idx, rows, len(set(pixels)), len(blob), span))

    if len(blob) + 8 <= span:
        dest, pad_at, pad_len = p, p + len(blob), span - len(blob)
        print("  fits in place at 0x%06X" % dest)
    else:
        dest = SPARE[0]
        if any(lin[dest:dest + len(blob)]):
            sys.exit("spare ROM at 0x%06X is not free" % dest)
        pad_at, pad_len = p, span            # the old stream becomes the padding
        struct.pack_into(">I", lin, TABLE + idx * 4, dest)
        print("  too big for its slot - relocated to 0x%06X, pointer updated" % dest)

    lin[dest:dest + len(blob)] = blob
    for k in range(pad_at, pad_at + pad_len):
        lin[k] = 0

    # restore each EPROM's byte-sum using bytes that are never read: the old
    # stream's slot, plus whatever is left of the spare region after the blob
    free = list(range(pad_at, pad_at + pad_len))
    if dest != p:
        free += list(range(dest + len(blob), min(dest + len(blob) + 4096, SPARE[1])))
    for b in range(8):
        even, odd, base = pair_for(b << 17)
        for name, parity in ((even, 0), (odd, 1)):
            data = lin[base + parity:base + 0x20000:2]
            delta = (before[name] - (sum(data) & 0xFFFF)) & 0xFFFF
            if not delta:
                continue
            slots = [k for k in free
                     if (k >> 17) == b and (k & 1) == parity and lin[k] == 0]
            if (delta + 254) // 255 > len(slots):
                sys.exit("%s: not enough spare bytes to restore the checksum" % name)
            for k in slots:
                if not delta:
                    break
                step = min(delta, 255)
                lin[k] = step
                delta -= step

    if "--apply" not in sys.argv:
        print("check only - pass --apply to write the images")
        return 0
    store(lin, files, romdir, before)
    print("\nBurn the EPROMs listed above; the rest are unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
