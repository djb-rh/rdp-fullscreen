#!/usr/bin/env python3
"""Build linear 68010 program and object-ROM images for the RDP side pod."""
import sys, os
R = os.path.expanduser("~/Developer/rdp-sidepod/roms/racedrivpans")
def interleave(pairs, size, out):
    buf = bytearray(size)
    for even, odd, base in pairs:
        e = open(os.path.join(R, even), "rb").read()
        o = open(os.path.join(R, odd), "rb").read()
        assert len(e) == len(o) == 0x10000, (even, odd)
        for i in range(0x10000):
            buf[base + 2*i]     = e[i]
            buf[base + 2*i + 1] = o[i]
    open(out, "wb").write(buf)
    print("%s  %d bytes" % (out, len(buf)))

interleave([("088-2002.bin","088-2001.bin",0x00000),
            ("088-2004.bin","088-2003.bin",0x20000),
            ("088-2006.bin","088-2005.bin",0x40000),
            ("088-2008.bin","088-2007.bin",0x60000),
            ("088-2010.bin","088-2009.bin",0x80000),
            ("088-2012.bin","088-2011.bin",0xa0000),
            ("088-2014.bin","088-2013.bin",0xc0000),
            ("088-2016.bin","088-2015.bin",0xe0000)], 0x100000, "maincpu.bin")

interleave([("088-1018.bin","088-1017.bin",0x00000),
            ("088-1020.bin","088-1019.bin",0x20000),
            ("088-1022.bin","088-1021.bin",0x40000)], 0x60000, "user1.bin")
