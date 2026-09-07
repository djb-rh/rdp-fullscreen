#!/usr/bin/env python3
"""Developer convenience: build both local sets from the stock zip.

    roms_loop/racedriv   the patch as shipped
    roms_warp/racedriv   the same, starting just before the new section

apply_patch.py is the real entry point (and the one to hand to anyone else);
this just runs it twice with the paths used on this machine.
"""
import apply_patch

STOCK_ZIP = "/Users/djb/Developer/Race Drivin/racedriv.zip"

if __name__ == "__main__":
    apply_patch.main([STOCK_ZIP, "-o", "roms_loop"])
    print("\n" + "=" * 70 + "\n")
    apply_patch.main([STOCK_ZIP, "-o", "roms_warp", "--warp"])
