"""Stage a complete loose MAME set: the stock zip's files plus the two compiled DSK halves."""
import os, shutil, zipfile
from . import dsk


def stage(romset, buf, out_dir):
    out = os.path.join(out_dir, "racedriv")
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    if os.path.isdir(romset):
        for n in os.listdir(romset):
            shutil.copy(os.path.join(romset, n), out)
    else:
        with zipfile.ZipFile(romset) as z:
            z.extractall(out)
    dsk.split(buf, out)
    return out
