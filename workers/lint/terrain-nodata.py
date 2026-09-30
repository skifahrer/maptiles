#!/usr/bin/env python3
"""Where the elevation model has no data, no sea level may be made."""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
TILES = os.path.join(_WORKERS, "terrain", "tiles.py")
# the sentinel and the fill are in `height.py`; `-dstnodata` and the skip in `tiles.py`
HEIGHT = os.path.join(_WORKERS, "terrain", "height.py")
PACK = os.path.join(_WORKERS, "terrain", "pack.py")
BUILD = os.path.join(_WORKERS, "terrain", "build.sh")


def code(path):
    """The file without whole comment lines, so a comment can't satisfy the check."""
    with open(path, encoding="utf-8") as f:
        return "\n".join(r for r in f.read().splitlines()
                         if not r.lstrip().startswith("#"))


bad = []
tiles, height, pack, build = code(TILES), code(HEIGHT), code(PACK), code(BUILD)

# 1. a sentinel outside real heights
m = re.search(r"^NODATA\s*=\s*(-?[\d.]+)", height, re.M)
if not m:
    bad.append(
        f"{HEIGHT}: constant `NODATA` is missing. The value marking \"no "
        f"model here\" must be named in one place – the warp writes it and "
        f"the loop spots an empty tile by it.")
else:
    v = float(m.group(1))
    # the Earth spans −430 m (Dead Sea) to 8849 m
    if -430 <= v <= 8849:
        bad.append(
            f"{HEIGHT}: `NODATA = {v}` is a VALID elevation, so \"no model "
            f"here\" can't be told from a measured value. Zero did exactly "
            f"that: a wall at the data's edge (668 m at 407 m/px = 59°) and "
            f"an unshaded plane behind it.")

if not re.search(r'"-dstnodata",\s*str\(NODATA\)', tiles):
    bad.append(
        f"{TILES}: `gdalwarp` doesn't get `-dstnodata str(NODATA)`. When the "
        f"sentinel and what is really written drift, the fill finds nothing "
        f"and an unexpected value stays in the tile.")

# 2. and 3. the warped grid is filled and an empty tile isn't written
if "def fill_nodata" not in height:
    bad.append(
        f"{HEIGHT}: `fill_nodata` is missing – filling holes in the model. "
        f"A constant would make a wall at their edge, so the surroundings fill.")
if "fill_nodata(" not in tiles:
    bad.append(
        f"{TILES}: `fill_nodata` isn't used anywhere. Without it the sentinel "
        f"({m.group(1) if m else '−9999'} m) goes straight into the tile.")

if not (re.search(r"missing\[[^\]]*\][^\n]*\.all\(\)", tiles)
        and "no_model += 1" in tiles):
    bad.append(
        f"{TILES}: a tile with NOT ONE valid pixel isn't checked. It must not "
        f"be written – it isn't a plane, the model says nothing about it.")

# 4. the header is clipped to the run's bbox
if "--clip-bbox" not in pack:
    bad.append(
        f"{PACK}: `--clip-bbox` is missing. Without it the header is the union "
        f"of WHOLE tiles, 11.25° at z5 – one region promises half of Europe.")
if "--clip-bbox" not in build:
    bad.append(
        f"{BUILD}: `pack.py` is called without `--clip-bbox`. An option not "
        f"passed is an option that doesn't exist.")

for b in bad:
    print(f"::error::{b}")
print(f"hillshading makes no terrain where the model has none: {len(bad)} errors")
sys.exit(1 if bad else 0)
