"""Render a decoded side-pod bitmap (512x96, one byte per pixel) as a PNG."""
import zlib, struct

def write_png(name, data, w=512, h=96, palette=None, bank=1):
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        line = data[y * w:(y + 1) * w]
        if palette:
            for px in line:
                o = (bank * 256 + px) * 3
                row += palette[o:o + 3]
        else:
            row += line
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    hdr = struct.pack(">IIBBBBB", w, h, 8, 2 if palette else 0, 0, 0, 0)
    with open(name, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", hdr)
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
