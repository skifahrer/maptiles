#!/usr/bin/env python3
"""“This degree has no terrain” must not be said by eye or without a stamp.

An empty tile is a lifelong answer: while it's in the store `dem/check.sh` sees
its name and nobody reads it again. Sampled statistics (`-approx_stats`) once
missed every valid pixel in a tile and a region's layers ended in a straight line.

  1. `dem/tiles.py` knows `EMPTY_PX`, `EMPTY_TAG` and `EMPTY_CHECK`;
  2. an empty tile is stamped (`-mo EMPTY_CHECK=…`);
  3. sampling doesn't decide a drop – it goes through `has_elevations(`;
  4. `dem/coverage.py` doesn't define an empty tile a second time;
  5. `check.sh` runs `dem/trust.py`, which judges the stamp with
     `coverage.empty_stamp`.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# folder = job, file = step; sibling jobs are one level up
_WORKERS = os.path.dirname(_HERE)
TILES = os.path.join(_WORKERS, "dem", "tiles.py")
COVERAGE = os.path.join(_WORKERS, "dem", "coverage.py")
CHECK = os.path.join(_WORKERS, "dem", "check.sh")
TRUST = os.path.join(_WORKERS, "dem", "trust.py")


def main():
    bad = []
    tiles = open(TILES, encoding="utf-8").read()
    coverage = open(COVERAGE, encoding="utf-8").read()

    for const in ("EMPTY_PX", "EMPTY_TAG", "EMPTY_CHECK"):
        if not re.search(rf"^{const}\s*=", tiles, re.M):
            bad.append(f"workers/dem/tiles.py lacks the constant {const} – an empty "
                       f"tile can then be neither stamped nor recognised.")

    if not re.search(r"^EMPTY_MAX_BYTES\s*=", tiles, re.M):
        bad.append("workers/dem/tiles.py lacks the EMPTY_MAX_BYTES threshold – "
                   "`workers/dem/trust.py` reads it and the store check "
                   "fails on AttributeError.")

    if 'f"{EMPTY_TAG}={EMPTY_CHECK}"' not in tiles:
        bad.append("workers/dem/tiles.py doesn't stamp an empty tile "
                   "(`gdal_translate -mo EMPTY_CHECK=…`). Unstamped, an old "
                   "check's answer passes for today's and a degree with "
                   "terrain stays empty in the store for good.")

    # banned: the SAMPLED form on a finished tile; `exact=True` is fine
    if re.search(r"elevation_range\(\s*dst\s*\)", tiles):
        bad.append("workers/dem/tiles.py decides on a tile directly through "
                   "`elevation_range(dst)`. Sampled statistics may only say "
                   "“heights exist”; their “none” means dropping a finished "
                   "tile, which must go through `has_elevations()` (an exact pass).")

    if "def has_elevations(" not in tiles:
        bad.append("workers/dem/tiles.py lacks `has_elevations()` – it verifies "
                   "an “empty degree” with an exact pass.")

    for const in ("EMPTY_PX", "EMPTY_TAG", "EMPTY_CHECK"):
        if re.search(rf"^{const}\s*=", coverage, re.M):
            bad.append(f"workers/dem/coverage.py defines its own {const}. "
                       f"What an empty tile looks like is known by its writer "
                       f"(workers/dem/tiles.py) – two ideas of one thing drift.")
    if "tiles.EMPTY_TAG" not in coverage or "tiles.EMPTY_PX" not in coverage:
        bad.append("workers/dem/coverage.py doesn't take the empty-tile stamp "
                   "from workers/dem/tiles.py – a false empty tile then stays "
                   "in the store and the degree is never read again.")

    # the check must ask what the download asks
    try:
        check = open(CHECK, encoding="utf-8").read()
        trust = open(TRUST, encoding="utf-8").read()
    except OSError as exc:
        bad.append(f"{exc} – without `dem/trust.py` the store check falls back "
                   f"to “a name in the store will do”.")
        check = trust = ""

    if check and "trust.py" not in check:
        bad.append("workers/dem/check.sh doesn't run workers/dem/trust.py – "
                   "the check would trust a file name again and an old empty "
                   "tile would pass as a finished model.")
    if trust and "empty_stamp" not in trust:
        bad.append("workers/dem/trust.py doesn't judge the stamp through "
                   "`coverage.empty_stamp` – a third idea of an empty tile "
                   "will drift from the other two.")
    if trust and "EMPTY_MAX_BYTES" not in trust:
        bad.append("workers/dem/trust.py lacks the `tiles.EMPTY_MAX_BYTES` "
                   "threshold – without it it would open real tiles (hundreds "
                   "of MB) and the store check would download the whole store.")

    for m in bad:
        print(f"::error::{m}")
    print(f"Empty tile: {str(len(bad)) + ' errors' if bad else 'fine ✓'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
