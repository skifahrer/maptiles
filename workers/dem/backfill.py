#!/usr/bin/env python3
"""A cut-out over a coarser model: the cut where it has heights, the fill under it, as one VRT.

    python3 workers/dem/backfill.py --cut=dem/ugkk-vysoke_tatry.tif --fill=dem/fill/all.vrt \
        --out=dem/all.vrt
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lib"))
from cell import dem_cell_metres, resampling  # noqa: E402


def band(path):
    """(data type, nodata) of the first band."""
    info = json.loads(subprocess.run(["gdalinfo", "-json", path], check=True,
                                     capture_output=True, text=True).stdout)
    first = info["bands"][0]
    return first["type"], first.get("noDataValue")


def commands(cut, fill, out, kind, nodata, kernel):
    """A VRT of the fill in the cut's type (gdalbuildvrt skips a mixed one), then both."""
    typed = out[:-len(".vrt")] + "-fill.vrt"
    translate = ["gdal_translate", "-q", "-of", "VRT", "-ot", kind]
    if nodata is not None:
        translate += ["-a_nodata", str(nodata)]
    # the later source wins where it has heights: the cut over the fill
    build = ["gdalbuildvrt", "-q", "-overwrite", "-resolution", "highest", "-r", kernel, out, typed, cut]
    return [translate + [fill, typed], build]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", required=True)
    ap.add_argument("--fill", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    kind, nodata = band(args.cut)
    px_m, _ = dem_cell_metres(args.cut)
    cell_m, _ = dem_cell_metres(args.fill)
    kernel = resampling(px_m, cell_m)
    for cmd in commands(args.cut, args.fill, args.out, kind, nodata, kernel):
        subprocess.run(cmd, check=True)
    print(f"{args.cut} over {args.fill} ({cell_m or 0:.0f} m, {kernel}) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
