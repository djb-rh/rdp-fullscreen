"""roms_fig8 variant: start on segment SEG shifted D units along its forward axis; optional bias overrides."""
import sys, struct, json, shutil, math
sys.path.insert(0, "/Users/djb/Developer/rdp-fullscreen")
from rdtrack import dsk, build
import world as W
w = W.World(); names = {i: w.name(i) for i in range(156)}
tag, seg, shift = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); over = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
import os
src = os.environ.get("SRC_IMAGE")
buf = bytearray(open(src, "rb").read()) if src else dsk.load("/Users/djb/Developer/Race Drivin/racedriv.zip")
D = dsk.Dsk(buf); t = D.tracks[0]; S = D.segs[t["segments"]]
a = t["segments"] + 64*seg; s = S["segs"][seg-1]
fx, fz = s["m"][0]/16384, s["m"][3]/16384
buf[a:a+4] = dsk.psw32(int(round(s["x"] + fx*shift))); buf[a+4:a+8] = dsk.psw32(int(round(s["z"] + fz*shift)))
buf[t["segments"] + 8:t["segments"] + 12] = dsk.psw32(seg)
d = D.worlds[t["descriptor"]]["descriptor"]
for k, p in enumerate(D.worlds[t["descriptor"]]["placements"]):
    nm = names.get(p["obj"])
    if nm in over: struct.pack_into(">h", buf, d["placements"] + 50*k + 0x20, over[nm])
    if ("hide:" + str(nm)) in over: struct.pack_into(">H", buf, d["placements"] + 50*k + 0x22, 0)
    if ("hide_rec:%d" % k) in over: struct.pack_into(">H", buf, d["placements"] + 50*k + 0x22, 0); print("hid record", k, nm)
out = "/tmp/abx2/" + tag; shutil.rmtree(out, ignore_errors=True); build.stage("/Users/djb/Developer/Race Drivin/racedriv.zip", buf, out)
