"""Race Drivin' Panorama side-pod artwork codec.

The pod's 68010 unpacks its bitmaps with the routine at ROM 0x2F12A, writing
16-bit words straight to the GSP host port. The stream is:

    00                  a leading zero byte
    <16 palette bytes>  loaded into a 16-entry colour table
    then control bytes:
        00        load a fresh 16-byte palette
        40        end of stream
        00..3F    n literal pixel bytes follow (stored in byte-swapped pairs)
        40..7F    n bytes follow, each holding two 4-bit palette indices
        80..BF    one byte follows, repeated for n pixels
        C0..FF    one byte follows (two palette indices), its pixel pair
                  repeated n times

Words reach video RAM low byte first, so a literal pair b0,b1 in ROM paints
b1 then b0, and a nibble byte paints the low nibble's colour first.
"""

def unpack(rom, pos, limit=1 << 20):
    out = bytearray()
    pal = [0] * 16

    def load_palette(p):
        for i in range(16):
            pal[i] = rom[p + i]
        return p + 16

    if rom[pos] != 0:
        raise ValueError("stream does not start with 00 at 0x%06X" % pos)
    pos = load_palette(pos + 1)

    pending = None                      # odd literal byte waiting for a partner
    while len(out) < limit:
        c = rom[pos]; pos += 1
        mode, n = c >> 6, c & 0x3F

        if c == 0x00:                   # new palette
            pos = load_palette(pos)
            continue
        if c == 0x40:                   # end
            break

        if mode == 0:                   # literal pixels
            if pending is not None:
                out.append(rom[pos]); out.append(pending); pos += 1
                pending = None
                n -= 1
                if n == 0:
                    continue
            pairs, odd = divmod(n, 2)
            for _ in range(pairs):
                out.append(rom[pos + 1]); out.append(rom[pos]); pos += 2
            if odd:
                pending = rom[pos]; pos += 1

        elif mode == 1:                 # n bytes, two palette indices each
            for _ in range(n):
                b = rom[pos]; pos += 1
                out.append(pal[b & 0xF]); out.append(pal[(b >> 4) & 0xF])

        elif mode == 2:                 # run of one colour, n pixels
            b = rom[pos]; pos += 1
            out += bytes([b]) * n

        else:                           # run of a two-colour pair, n times
            b = rom[pos]; pos += 1
            out += bytes([pal[b & 0xF], pal[(b >> 4) & 0xF]]) * n

    return bytes(out), pos


def pack(pixels, palette16):
    """Encode pixels back into the pod's format.

    Uses three of the four modes: single-colour runs, nibble pairs (two
    palette-indexed pixels per byte) and raw literals for anything off-palette.
    The nibble mode is what makes the original artwork small, so it matters.
    """
    pal = list(palette16[:16])
    pal += [0] * (16 - len(pal))
    index = {c: i for i, c in enumerate(pal)}

    out = bytearray([0x00]) + bytes(pal)
    lit = bytearray()          # raw pixels awaiting a mode 0 chunk
    nib = bytearray()          # packed nibble bytes awaiting a mode 1 chunk

    def flush_lit():
        while len(lit) >= 2:
            n = min(len(lit), 62)
            if n & 1:
                n -= 1
            out.append(n)
            for k in range(0, n, 2):
                out.append(lit[k + 1])      # words reach VRAM low byte first
                out.append(lit[k])
            del lit[:n]
        if lit:
            out.append(0x81)
            out.append(lit[0])
            lit.clear()

    def flush_nib():
        while nib:
            n = min(len(nib), 63)
            out.append(0x40 | n)
            out.extend(nib[:n])
            del nib[:n]

    i, total = 0, len(pixels)
    while i < total:
        j = i
        while j < total and pixels[j] == pixels[i] and j - i < 63:
            j += 1
        run = j - i
        if run >= 3:
            flush_nib(); flush_lit()
            out.append(0x80 | run)
            out.append(pixels[i])
            i = j
            continue
        if i + 1 < total and pixels[i] in index and pixels[i + 1] in index:
            flush_lit()
            nib.append((index[pixels[i + 1]] << 4) | index[pixels[i]])
            i += 2
            continue
        flush_nib()
        lit += pixels[i:i + 1]
        i += 1
    flush_nib(); flush_lit()
    out.append(0x40)
    return bytes(out)
