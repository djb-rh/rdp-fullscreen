# Race Drivin' Panorama side pod - bitmap artwork

## How the screen is divided, main view vs side pod

| | screen | 3D world | furniture | split |
|---|---|---|---|---|
| **main view** (driver board: Hard Drivin', Race Drivin' cockpit, RDP centre) | 508 x 384 | rows 0-255 = **256 lines** | dashboard rows 256-383 = **128 lines** | 2 : 1 |
| **side pod** (multisync board) | 512 x 288 | rows 0-191 = **192 lines** | door card rows 192-287 = **96 lines** | 2 : 1 |

Both boards give exactly two thirds of the screen to the world and one third to
the car. The main view renders 256 lines of 3D, the pod 192.

Measured, not assumed: consecutive frames were captured while driving and the
fraction of each row that changes was counted. On the main view every row up to
255 moves (0.17-0.26 of the row changing frame to frame) and every row from 256
down is exactly 0.000 - a hard boundary at row 256. The pod's split was
established the same way, backed by its video timing table at ROM 0x4DFD0
(VEBLNK 17 to VSBLNK 305 = 288 visible lines) and by the door card occupying
VRAM blocks 96-119.

## Where the artwork lives

The pod's 68010 keeps **70 compressed bitmaps** behind a pointer table of
longwords at **ROM 0x060000**. Each entry points at a stream that the routine at
**0x2F12A** unpacks straight to the GSP host port, one byte per pixel, 512
pixels per row.

### Exact size - match it and no scaling happens

**The door card is exactly 512 x 96 pixels, one byte per pixel.** Author your
replacement at 512 x 96 and `swapart.py` uses it as-is. Anything else is scaled
to fit with ImageMagick's `-resize 512x96!`, which ignores aspect ratio, so a
4:3 source will be squashed. There is no border, bleed or safe area: pixel (0,0)
of your image is the top-left pixel of the panel, and the panel occupies display
rows 192 to 287 of the pod's 288-row screen.

The other assets are all 512 wide too; their heights vary (see `list`), and the
same rule applies - match the listed height exactly.

Colour is indexed, not RGB: each pixel is an index into the pod's hardware
palette. `swapart.py` matches your colours to the nearest available entry. By
default it only uses the colours the original asset used (12 for the door card);
`--full-palette` allows all 256 in the bank, which is what you want for
photographs.

Four of the 70 are 512x96 - the panel across the bottom 96 rows of the pod's
288-row screen:

| entry | ROM | compressed | what it is |
|---|---|---|---|
| 0  | 0x06011E | 2939 | door card, **left-hand pod** |
| 19 | 0x088422 | 2939 | door card, **right-hand pod** |
| 14 | 0x083054 | 6321 | second car's interior, left |
| 69 | 0x09966A | 5147 | second car's interior, right |

**There are two door images, not one mirrored at runtime.** Entry 19 is the
exact horizontal mirror of entry 0 - verified pixel for pixel, 100% match - but
it is stored as its own compressed stream and both are the same size. The second
car's pair is *not* an exact mirror (88.6% against a flipped copy), so that one
was redrawn rather than reflected.

## The compression format

Decoded and re-implemented in `codec.py`; `unpack()` reproduces what the pod
paints **byte for byte** (checked against video RAM dumped from a running pod).

    00                  leading zero byte
    <16 bytes>          palette, loaded into a 16-entry colour table
    then control bytes:
      00                load a fresh 16-byte palette
      40                end of stream
      01..3F  n         n literal pixel bytes follow
      41..7F  n         n bytes follow, each holding two 4-bit palette indices
      80..BF  n         one byte follows, repeated for n pixels
      C0..FF  n         one byte follows (two palette indices), pair repeated n times

Words reach video RAM low byte first, so a literal pair `b0 b1` in ROM paints
`b1` then `b0`, and a nibble byte paints its low nibble's colour first. Get that
backwards and everything comes out mirrored in 2-pixel groups.

`pack()` re-encodes using runs, nibble pairs and literals. It is correct but
about 50% less dense than Atari's encoder (which also uses the two-colour run
mode and presumably searches harder), so a re-encoded image usually no longer
fits its original slot - see relocation below.

## Tools

    # once, against your own ROMs: dump the pod's palette
    mame racedrivpans -rompath <dir> -video none -sound none -str 12 \
         -autoboot_script dumppal.lua

    python3 swapart.py <romdir> list
    python3 swapart.py <romdir> extract 0 door.png --palette palette.bin
    python3 swapart.py <romdir> replace 0 mypic.png --palette palette.bin --apply

`replace` takes PNG, GIF, JPEG or anything else ImageMagick reads, scales it to
the asset's exact size, matches each pixel to the pod's palette, re-encodes and
writes it back.

- By default it uses only the colours the original asset used, which keeps the
  result in keeping with the rest of the screen. `--full-palette` opens it up to
  all 256 entries of the palette bank - much better for photographs.
- If the new stream no longer fits its slot it is **relocated** into unused ROM
  at 0x051000 and the pointer table entry updated.
- Each affected EPROM's 16-bit byte-sum is preserved, using bytes that are never
  read (the abandoned slot, and spare space after the relocated stream). The
  pod's self-test checks those sums, and the low byte of each still matches the
  part-number suffix, as Atari intended.
- Replacing entry 0 changes four EPROMs: **088-2005 / 088-2006** (the relocated
  image) and **088-2007 / 088-2008** (the pointer table). Replacing in place
  would touch only the pair holding the stream.

MAME will report "WRONG CHECKSUMS" for modified ROMs - that is MAME comparing
SHA-1s against its own database, not the pod's self-test.

## Removing the door card entirely

For a pod being used to show something other than a side view - a forward view,
a second centre screen, a bespoke cabinet - the door is simply in the way:

    python3 swapart.py <romdir> blank doors --apply

That replaces both door cards with a flat fill. A solid colour compresses to
1580 bytes against the original 2939, so it always fits in place, no relocation
and no pointer changes: only **088-2007 / 088-2008** (left card) and
**088-2009 / 088-2010** (right card) are rewritten, checksums preserved.
`--colour N` picks the fill index if black is not what you want, and
`blank 14` / `blank 69` do the second car's panels.

Verified: patched ROMs, run in MAME, video RAM blocks 96-119 come up entirely
colour 0 and the card is gone from the screen, with no self-test complaint.

This is worth doing on its own even though the wider-view work did not pan out -
it is the part that a real pod, or a MAME-based pod, actually benefits from.

## Verified end to end

Replaced entry 0 with a test image, ran the patched ROMs in MAME, dumped what
the pod actually painted into video RAM at blocks 96-119, and got the new image
back: `doorcard_replaced_full.png`. Nothing else on the screen changed.

Nothing in these tools contains ROM data. The images come out of your own ROMs
and the palette comes from your own running pod.
